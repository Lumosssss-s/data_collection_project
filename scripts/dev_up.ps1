#requires -Version 5.1
<#
 dev_up.ps1 - 一条命令全起：后端容器组 -> PC 前端容器 -> 手机 H5 预览
 幂等：已在运行的服务识别并跳过；3100 被他人占用时跳过而不抢占。
 失败语义：后端 healthcheck 超时则报错退出，不静默继续。
 注意：本文件必须以 UTF-8 with BOM 保存（PS 5.1 对无 BOM UTF-8 按 GBK 解析，中文会乱码）。
#>
param(
    [int]$BackendHealthTimeoutSec = 330
)
$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $PSScriptRoot
$logsDir   = Join-Path $root 'logs'
$statePath = Join-Path $logsDir 'dev_up.state.json'
$compose   = Join-Path $root 'docker-compose.yml'

$EXIT_OK = 0; $EXIT_BACKEND = 1; $EXIT_FRONTEND = 2; $EXIT_H5 = 3; $EXIT_PRE = 4

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

function Test-PortListen([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}
function Get-ListenerPid([int]$port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess } else { return $null }
}
function Get-ContainerField([string]$name, [string]$fmt) {
    $v = docker inspect -f $fmt $name 2>$null
    if ($LASTEXITCODE -ne 0) { return '' }
    return ($v | Out-String).Trim()
}
function Get-LanIPv4 {
    try {
        $r = Find-NetRoute -RemoteIPAddress '8.8.8.8' -ErrorAction Stop | Select-Object -First 1
        if ($r.IPAddress -and $r.IPAddress -notlike '127.*') { return $r.IPAddress }
    } catch {}
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' -and $_.InterfaceAlias -notmatch 'WSL|VMware|Loopback|Teredo|Hyper-V|VPN|Radmin' } |
        Select-Object -First 1
    if ($ip) { return $ip.IPAddress }
    return $null
}
function Test-HttpOk([string]$url, [int]$timeoutSec = 5) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
        return $r.StatusCode
    } catch {
        $resp = $_.Exception.Response
        if ($resp) { return [int]$resp.StatusCode }
        return -1
    }
}

# ---------- 状态文件 ----------
$state = [ordered]@{
    started_at       = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    backend_started  = $false
    frontend_started = $false
    h5_wrapper_pid   = $null
    h5_pid           = $null
    log_followers    = @{}
    lan_ip           = $null
}
if (Test-Path $statePath) {
    try {
        $old = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($old.log_followers) {
            $old.log_followers.PSObject.Properties | ForEach-Object { $state.log_followers[$_.Name] = $_.Value }
        }
    } catch {}
}
function Save-State {
    ($state | ConvertTo-Json) | Set-Content -Path $statePath -Encoding UTF8
}

# ---------- 前置检查 ----------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Output 'FATAL: 未找到 docker CLI'; exit $EXIT_PRE }
if (-not (Test-Path $compose)) { Write-Output "FATAL: 未找到 $compose"; exit $EXIT_PRE }
foreach ($img in 'medical-rag-backend:latest', 'medical-rag-es:8.11.0') {
    docker image inspect $img *> $null
    if ($LASTEXITCODE -ne 0) { Write-Output "FATAL: 镜像缺失 $img（先执行 docker compose build，本脚本不触发构建）"; exit $EXIT_PRE }
}

Push-Location $root
try {

# ==================== [1/3] 后端容器组 ====================
Write-Output '[1/3] 后端容器组 (docker compose: elasticsearch + redis + backend)'
$bHealth = Get-ContainerField 'medical-backend' '{{.State.Health.Status}}'
if ($bHealth -eq 'healthy') {
    Write-Output "  backend     port=8002 bind=0.0.0.0 health=healthy 动作=skip(已在运行且健康)"
} else {
    Write-Output "  backend     当前状态='$bHealth'，执行 docker compose up -d backend 并等待 healthcheck ..."
    docker compose up -d backend 2>&1 | ForEach-Object { Write-Output "    $_" }
    if ($LASTEXITCODE -ne 0) { Write-Output 'FATAL: docker compose up -d backend 失败'; exit $EXIT_BACKEND }
    $state.backend_started = $true
    $deadline = (Get-Date).AddSeconds($BackendHealthTimeoutSec)
    $ok = $false
    while ((Get-Date) -lt $deadline) {
        $h = Get-ContainerField 'medical-backend' '{{.State.Health.Status}}'
        $r = Get-ContainerField 'medical-backend' '{{.State.Status}}'
        if ($h -eq 'healthy') { $ok = $true; break }
        if ($r -eq 'exited' -or $r -eq 'dead') {
            Write-Output "FATAL: medical-backend 容器已退出($r)。排查: docker logs --tail 50 medical-backend"
            exit $EXIT_BACKEND
        }
        Start-Sleep -Seconds 5
    }
    if (-not $ok) {
        Write-Output "FATAL: 等待 ${BackendHealthTimeoutSec}s 后 backend 仍未 healthy（health=$(Get-ContainerField 'medical-backend' '{{.State.Health.Status}}')）。排查: docker logs --tail 50 medical-backend ; logs\backend.log"
        exit $EXIT_BACKEND
    }
    Write-Output "  backend     port=8002 bind=0.0.0.0 health=healthy 动作=started"
}
$readyCode = Test-HttpOk 'http://127.0.0.1:8002/health/ready'
Write-Output "  backend     /health/ready => HTTP $readyCode"
Write-Output ("  elasticsearch port=9201 bind=0.0.0.0 health=" + (Get-ContainerField 'medical-es' '{{.State.Health.Status}}'))
Write-Output ("  redis       port=6380 bind=0.0.0.0 health=" + (Get-ContainerField 'medical-redis' '{{.State.Health.Status}}'))

# ==================== [2/3] 前端容器（PC 3001 + H5 3100）====================
# H5 移动端自 2026-11-03 起并入 medical-frontend 容器（容器内 8080，对外 3100），
# 不再使用 python h5_preview 进程；计划任务 H5Preview3100 已禁用。
Write-Output '[2/3] 前端容器 medical-frontend（PC=3001，H5=3100）'
$fRunning = Get-ContainerField 'medical-frontend' '{{.State.Running}}'
if ($fRunning -eq 'true' -and (Test-PortListen 3001) -and (Test-PortListen 3100)) {
    Write-Output "  frontend    port=3001+3100 bind=0.0.0.0 动作=skip(已在运行)"
} else {
    # --no-deps：backend 健康已在 [1/3] 确保，避免 compose 顺带重启 backend
    docker compose up -d --no-deps frontend 2>&1 | ForEach-Object { Write-Output "    $_" }
    if ($LASTEXITCODE -ne 0) { Write-Output 'FATAL: docker compose up -d frontend 失败'; exit $EXIT_FRONTEND }
    $state.frontend_started = $true
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline -and -not ((Test-PortListen 3001) -and (Test-PortListen 3100))) { Start-Sleep -Milliseconds 800 }
    if (-not ((Test-PortListen 3001) -and (Test-PortListen 3100))) { Write-Output 'FATAL: frontend 容器启动后 3001/3100 未全部监听。排查: docker logs medical-frontend'; exit $EXIT_FRONTEND }
    Write-Output '  frontend    port=3001+3100 bind=0.0.0.0 动作=started'
}
$fCode = Test-HttpOk 'http://127.0.0.1:3001/'
Write-Output "  frontend    PC HTTP / => $fCode $(if ($fCode -ne 200) { '(非200，请排查 logs\frontend.log)' })"
if ($fCode -ne 200) { exit $EXIT_FRONTEND }

# ==================== [3/3] H5 移动端预览（随容器已起，此处仅验证）====================
Write-Output '[3/3] 手机 H5 预览（frontend 容器内 8080，对外 3100）'
$h5Code = Test-HttpOk 'http://127.0.0.1:3100/index.html'
if ($h5Code -eq 401) {
    Write-Output '  h5          port=3100 bind=0.0.0.0 健康=HTTP 401(鉴权在线，预期) 动作=verified'
} else {
    Write-Output "FATAL: H5 预览异常，HTTP /index.html => $h5Code（预期 401 鉴权在线）。排查: docker logs medical-frontend"
    exit $EXIT_H5
}

# ==================== 日志跟随器 ====================
Write-Output '[logs] docker 日志跟随 -> logs\'
$followMap = [ordered]@{ 'medical-es' = 'es'; 'medical-redis' = 'redis'; 'medical-backend' = 'backend'; 'medical-frontend' = 'frontend' }
foreach ($c in $followMap.Keys) {
    $short = $followMap[$c]
    $existing = $state.log_followers[$c]
    if ($existing) {
        $alive = Get-CimInstance Win32_Process -Filter "ProcessId=$existing" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -like '*docker logs*' }
        if ($alive) { Write-Output "  $short.log 跟随器已在运行(PID $existing)，skip"; continue }
    }
    $f = Join-Path $logsDir ($short + '.log')
    $arg = '/c "docker logs -f --tail 100 ' + $c + ' >> "' + $f + '" 2>&1"'
    $fp = Start-Process -FilePath 'cmd.exe' -ArgumentList $arg -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $state.log_followers[$c] = $fp.Id
    Write-Output "  logs\$short.log  <= docker logs -f $c (PID $($fp.Id))"
}

# ==================== 访问地址表 ====================
$lan = Get-LanIPv4
$state.lan_ip = $lan
Save-State
Write-Output ''
Write-Output '==================== 访问地址表 ===================='
Write-Output "  PC 前端      http://localhost:3001/"
if ($lan) { Write-Output "               http://${lan}:3001/  (局域网)" }
Write-Output "  手机 H5      http://${lan}:3100/index.html  (需 Basic Auth，凭据见 .env 的 MEDICAL_H5_AUTH_*)"
Write-Output "  后端 API     http://localhost:8002/api/v1"
Write-Output "  日志目录     $logsDir"
Write-Output "  停止本脚本起的服务: scripts\dev_down.ps1"
Write-Output '==================================================='
exit $EXIT_OK

} finally {
    Pop-Location
}
