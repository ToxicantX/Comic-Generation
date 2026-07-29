param(
    [switch]$SkipComfyHttp,
    [switch]$RequireImageApiKey
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\scripts\comic_pipeline_config.ps1"
$config = Get-ComicPipelineConfig -Root $PSScriptRoot
Set-ComicPipelineProcessEnv -Config $config

$checks = @()
function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $script:checks += [ordered]@{ name = $Name; ok = $Ok; detail = $Detail }
}

Add-Check "workspace_exists" (Test-Path -LiteralPath $config.Workspace) $config.Workspace
Add-Check "scripts_exists" (Test-Path -LiteralPath (Join-Path $config.Workspace "scripts")) (Join-Path $config.Workspace "scripts")
Add-Check "manifests_exists" (Test-Path -LiteralPath (Join-Path $config.Workspace "manifests")) (Join-Path $config.Workspace "manifests")
Add-Check "workflows_exists" (Test-Path -LiteralPath (Join-Path $config.Workspace "workflows\comic")) (Join-Path $config.Workspace "workflows\comic")
Add-Check "image_backend_valid" ($config.ImageBackend -in @("direct_api", "comfyui")) $config.ImageBackend
if ($config.ImageBackend -eq "comfyui") {
    Add-Check "comfy_root_exists" (Test-Path -LiteralPath $config.ComfyRoot) $config.ComfyRoot
    Add-Check "custom_nodes_exists" (Test-Path -LiteralPath $config.CustomNodesRoot) $config.CustomNodesRoot
}
if ($config.ImageBackend -eq "direct_api" -or $RequireImageApiKey) {
    Add-Check "image_env_exists" (Test-Path -LiteralPath $config.ImageEnvPath) $config.ImageEnvPath
}
Add-Check "novel_path_exists" ([string]::IsNullOrWhiteSpace($config.NovelPath) -or (Test-Path -LiteralPath $config.NovelPath)) $config.NovelPath

if (($config.ImageBackend -eq "direct_api" -or $RequireImageApiKey) -and (Test-Path -LiteralPath $config.ImageEnvPath)) {
    $imageEnv = Read-ComicEnvFile -Path $config.ImageEnvPath
    $hasKey = -not [string]::IsNullOrWhiteSpace($imageEnv.OPENAI_API_KEY) -or -not [string]::IsNullOrWhiteSpace($imageEnv.API_KEY) -or -not [string]::IsNullOrWhiteSpace($imageEnv.API_KEYS)
    Add-Check "image_api_key_configured" ($hasKey -or -not $RequireImageApiKey) $config.ImageEnvPath
}

if ($config.ImageBackend -eq "comfyui" -and -not $SkipComfyHttp) {
    try {
        $queue = Invoke-RestMethod -Uri "$($config.ComfyUrl.TrimEnd('/'))/queue" -TimeoutSec 10
        Add-Check "comfy_http_reachable" $true $config.ComfyUrl
        Add-Check "comfy_queue_readable" ($null -ne $queue) $config.ComfyUrl
    } catch {
        Add-Check "comfy_http_reachable" $false $_.Exception.Message
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    config = $config
    checks = $checks
    ok = (($checks | Where-Object { -not $_.ok }).Count -eq 0)
}

$result | ConvertTo-Json -Depth 8
if (-not $result.ok) {
    exit 1
}
