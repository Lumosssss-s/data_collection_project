# cloudflared quick tunnel 启动器（把 3100 预览服务暴露到公网）。
# 本文件必须以 UTF-8 with BOM 保存：PowerShell 5.1 对无 BOM 的 UTF-8 源码按 GBK 解析，中文路径会乱码。
$port = 3100
$log = Join-Path $env:TEMP 'cloudflared_3100.log'

# 单实例：本脚本已有实例在跑时直接退出，避免计划任务重复触发堆积多条隧道
$self = $MyInvocation.MyCommand.Path
$others = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*$self*" })
if ($others.Count -gt 0) { Write-Output "已有实例 PID=$($others[0].ProcessId)，不重复启动"; exit 8 }

# 3100 未监听说明预览服务没起来，隧道没有回源目标，拒绝启动
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $busy) { Write-Output "3100 未监听，未启动隧道"; exit 3 }

# cloudflared 路径探测：PATH 优先，回退默认安装位置
$exe = $null
$found = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($found) { $exe = $found.Source }
elseif (Test-Path 'C:\Program Files (x86)\cloudflared\cloudflared.exe') { $exe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe' }
if (-not $exe) { Write-Output '未找到 cloudflared.exe'; exit 2 }

# quick tunnel 每次启动 URL 都不同；逐行透传到日志，首行 URL 打到 stdout
$url = $null
& $exe tunnel --url "http://localhost:$port" --no-autoupdate --protocol http2 2>&1 | ForEach-Object {
    $line = "$_"
    Add-Content -Path $log -Value $line -Encoding utf8
    if (-not $url -and $line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        $url = $Matches[0]
        Write-Output "URL=$url"
    }
}