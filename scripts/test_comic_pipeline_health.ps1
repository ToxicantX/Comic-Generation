param(
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_pipeline_health.json"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) { $ComfyUrl = $comicConfig.ComfyUrl }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_pipeline_health.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_pipeline_health.json" }

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    comfy_url = $ComfyUrl
    reachable = $false
    queue = $null
    system_stats = $null
    python_processes = @()
    error = $null
}

try {
    $result.system_stats = Invoke-RestMethod -Uri "$ComfyUrl/system_stats" -TimeoutSec 10
    $result.queue = Invoke-RestMethod -Uri "$ComfyUrl/queue" -TimeoutSec 10
    $result.reachable = $true
} catch {
    $result.error = $_.Exception.Message
}

$result.python_processes = @(
    Get-Process |
        Where-Object { $_.ProcessName -like "*python*" -or $_.ProcessName -like "*Comfy*" } |
        Select-Object Id, ProcessName, Path, StartTime
)

New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -Path $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 12

if (-not $result.reachable) {
    exit 1
}
