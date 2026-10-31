# H5 预览服务启动器。
# 本文件必须以 UTF-8 with BOM 保存：PowerShell 5.1 对无 BOM 的 UTF-8 源码按 GBK 解析，
# 中文路径会乱码，导致 python 收到空参数而起成交互 REPL。
$port = 3100
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $PSScriptRoot 'h5_preview.py'
$outLog = Join-Path $env:TEMP 'h5_preview.out.log'
$errLog = Join-Path $env:TEMP 'h5_preview.err.log'

# python 解释器探测：优先 PATH，回退固定安装路径
$py = $null
$found = Get-Command python -ErrorAction SilentlyContinue
if ($found) { $py = $found.Source }
elseif (Test-Path 'D:\Program Files\Python310\python.exe') { $py = 'D:\Program Files\Python310\python.exe' }
if (-not $py) { Write-Output '未找到可用 python：PATH 中无 python，且 D:\Program Files\Python310\python.exe 不存在'; exit 3 }

# 端口已被占用时不抢端口，直接退出
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) { Write-Output "3100 已被 PID $($busy.OwningProcess) 占用，未启动"; exit 4 }

# fail-closed：缺任一凭据即拒绝启动，避免退化成无鉴权服务；凭据只进子进程环境，不进命令行
$envPath = Join-Path $root '.env'
if (-not (Test-Path $envPath)) { Write-Output ".env 不存在：$envPath"; exit 5 }
$lines = @([System.IO.File]::ReadAllText($envPath, [System.Text.UTF8Encoding]::new($false)) -split "`r?`n")
$userLine = $lines | Where-Object { $_ -like 'MEDICAL_H5_AUTH_USER=*' } | Select-Object -First 1
$passLine = $lines | Where-Object { $_ -like 'MEDICAL_H5_AUTH_PASS=*' } | Select-Object -First 1
$user = if ($userLine) { (($userLine -split '=', 2)[1]).Trim() } else { '' }
$pass = if ($passLine) { (($passLine -split '=', 2)[1]).Trim() } else { '' }
if (-not $user -or -not $pass) { Write-Output '拒绝启动：.env 缺少 MEDICAL_H5_AUTH_USER 或 MEDICAL_H5_AUTH_PASS'; exit 6 }
$env:MEDICAL_H5_AUTH_USER = $user
$env:MEDICAL_H5_AUTH_PASS = $pass

$proc = Start-Process -FilePath $py -ArgumentList "`"$target`"" -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 750
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { break }
}
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "已启动 PID=$($proc.Id)，监听 0.0.0.0:$port；日志 $outLog / $errLog"
    exit 0
}
Write-Output "启动失败：$port 端口未进入监听，详见 $errLog"
exit 7
