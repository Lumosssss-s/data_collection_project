#requires -Version 5.1
<#
 dev_down.ps1 - 只停 dev_up.ps1 启动的进程/容器，不误杀其他东西。
 依据 logs\dev_up.state.json：停 H5 预览进程树、docker 日志跟随器，
 以及(仅当确由本脚本启动的) frontend / backend 容器组（compose stop，不 down、不动数据卷）。
 杀进程前一律校验目标进程的命令行匹配预期，防 PID 复用误杀。
 注意：本文件必须以 UTF-8 with BOM 保存。
#>
$ErrorActionPreference = 'Stop'
$root      = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $root 'logs\dev_up.state.json'

if (-not (Test-Path $statePath)) {
    Write-Output '无状态文件 logs\dev_up.state.json：没有 dev_up.ps1 启动记录，不做任何操作。'
    exit 0
}
$state = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json

function Stop-ProcessTreeIfMatch([int]$pid_, [string]$cmdPattern, [string]$label) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pid_" -ErrorAction SilentlyContinue
    if (-not $p) { Write-Output "  $label PID $pid_ 已不存在，skip"; return }
    if ($p.CommandLine -notlike $cmdPattern) {
        Write-Output "  $label PID $pid_ 命令行不匹配预期($cmdPattern)，跳过不杀: $($p.CommandLine)"
        return
    }
    & taskkill /PID $pid_ /T /F | Out-Null
    Write-Output "  $label PID $pid_ 已停止(进程树)"
}

# 1) H5 预览
if ($state.h5_wrapper_pid) { Stop-ProcessTreeIfMatch $state.h5_wrapper_pid '*h5_preview.py*' 'h5_preview(wrapper)' }
if ($state.h5_pid -and ($state.h5_pid -ne $state.h5_wrapper_pid)) {
    Stop-ProcessTreeIfMatch $state.h5_pid '*h5_preview.py*' 'h5_preview(python)'
}

# 2) docker 日志跟随器
if ($state.log_followers) {
    foreach ($prop in $state.log_followers.PSObject.Properties) {
        Stop-ProcessTreeIfMatch ([int]$prop.Value) ("*docker logs*" + $prop.Name + "*") ("follower:" + $prop.Name)
    }
}

# 3) 容器：仅停本脚本启动过的
Push-Location $root
try {
    if ($state.frontend_started -eq $true) {
        docker compose stop frontend | Out-Null
        Write-Output '  容器 medical-frontend 已 stop（由 dev_up 启动）'
    } else {
        Write-Output '  容器 medical-frontend 非本脚本启动或本就运行中，保持不动'
    }
    if ($state.backend_started -eq $true) {
        docker compose stop backend redis elasticsearch | Out-Null
        Write-Output '  容器 backend/redis/elasticsearch 已 stop（由 dev_up 启动，compose stop 不删数据卷）'
    } else {
        Write-Output '  容器 backend/redis/elasticsearch 非本脚本启动或本就运行中，保持不动'
    }
} finally {
    Pop-Location
}

Remove-Item $statePath -Force
Write-Output '完成。状态文件已清除。'
exit 0
