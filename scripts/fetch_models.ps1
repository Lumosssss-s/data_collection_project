#Requires -Version 5.1
<#
.SYNOPSIS
    Download the two local models required by the backend.

.DESCRIPTION
    Fetches BAAI/bge-m3 and BAAI/bge-reranker-v2-m3 into .\models,
    removes the unused onnx folder (2.18 GB) and verifies required files.

.PARAMETER ModelsDir
    Target directory. Defaults to <repo>\models.

.PARAMETER Mirror
    Use https://hf-mirror.com instead of huggingface.co (for networks
    where the official endpoint is slow or blocked).

.PARAMETER KeepOnnx
    Keep models\bge-m3\onnx. The backend never reads it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\fetch_models.ps1 -Mirror
#>
param(
    [string]$ModelsDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'models'),
    [switch]$Mirror,
    [switch]$KeepOnnx
)

$ErrorActionPreference = 'Stop'

if ($Mirror) {
    $env:HF_ENDPOINT = 'https://hf-mirror.com'
    Write-Host "[info] HF_ENDPOINT=$env:HF_ENDPOINT"
}

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$cli = Get-Command 'huggingface-cli' -ErrorAction SilentlyContinue
if (-not $cli) {
    Write-Host '[error] huggingface-cli not found. Install it first:' -ForegroundColor Red
    Write-Host '        pip install -U huggingface_hub'
    exit 1
}

$repos = @(
    @{ Id = 'BAAI/bge-m3';             Dir = 'bge-m3' },
    @{ Id = 'BAAI/bge-reranker-v2-m3'; Dir = 'bge-reranker-v2-m3' }
)

foreach ($r in $repos) {
    $target = Join-Path $ModelsDir $r.Dir
    Write-Host ("[info] downloading {0} -> {1}" -f $r.Id, $target)
    & huggingface-cli download $r.Id --local-dir $target --local-dir-use-symlinks False
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("[error] download failed: {0}" -f $r.Id) -ForegroundColor Red
        exit 1
    }
}

$onnx = Join-Path $ModelsDir 'bge-m3\onnx'
if ((-not $KeepOnnx) -and (Test-Path -LiteralPath $onnx)) {
    Remove-Item -LiteralPath $onnx -Recurse -Force
    Write-Host '[info] removed models\bge-m3\onnx (unused by this project)'
}

$required = @{
    'bge-m3'             = @('pytorch_model.bin', 'tokenizer.json', 'sentencepiece.bpe.model', 'config.json', 'config_sentence_transformers.json')
    'bge-reranker-v2-m3' = @('model.safetensors', 'tokenizer.json', 'sentencepiece.bpe.model', 'config.json')
}

$missing = @()
foreach ($k in $required.Keys) {
    foreach ($f in $required[$k]) {
        $p = Join-Path (Join-Path $ModelsDir $k) $f
        if (-not (Test-Path -LiteralPath $p)) { $missing += $p }
    }
}

if ($missing.Count -gt 0) {
    Write-Host '[error] missing files:' -ForegroundColor Red
    $missing | ForEach-Object { Write-Host ("        {0}" -f $_) }
    exit 1
}

$total = 0
Get-ChildItem -LiteralPath $ModelsDir -Recurse -File | ForEach-Object { $total += $_.Length }
Write-Host ("[ok] models ready: {0:N2} GB in {1}" -f ($total / 1GB), $ModelsDir) -ForegroundColor Green
Write-Host '[next] copy .env.example to .env, then: docker compose up -d'
