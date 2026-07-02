param(
    [string]$ComfyRoot = "",
    [switch]$Force,
    [switch]$DisableLegacySingleFileNode
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\scripts\comic_pipeline_config.ps1"
$config = Get-ComicPipelineConfig -Root $PSScriptRoot
if ($ComfyRoot) {
    $config.ComfyRoot = $ComfyRoot
    $config.CustomNodesRoot = Join-Path $ComfyRoot "custom_nodes"
}

if (-not (Test-Path -LiteralPath $config.CustomNodesRoot)) {
    throw "ComfyUI custom_nodes directory not found: $($config.CustomNodesRoot)"
}

$targetDir = Join-Path $config.CustomNodesRoot "comic_episode_pipeline"
if ((Test-Path -LiteralPath $targetDir) -and -not $Force) {
    throw "Target already exists: $targetDir. Use -Force to overwrite."
}

$legacyNode = Join-Path $config.CustomNodesRoot "comic_episode_pipeline_node.py"
if ((Test-Path -LiteralPath $legacyNode) -and -not $DisableLegacySingleFileNode) {
    throw "Legacy single-file node exists: $legacyNode. Re-run with -DisableLegacySingleFileNode to avoid duplicate node registration."
}
if (Test-Path -LiteralPath $legacyNode) {
    $backup = "$legacyNode.disabled"
    Move-Item -LiteralPath $legacyNode -Destination $backup -Force
    Write-Output "Disabled legacy node: $backup"
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "custom_nodes\comic_episode_pipeline_node.py") -Destination (Join-Path $targetDir "__init__.py") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "custom_nodes\comic_episode_pipeline_web.disabled") -Destination (Join-Path $targetDir "comic_episode_pipeline_web.disabled") -Recurse -Force
Set-Content -LiteralPath (Join-Path $targetDir "comic_pipeline_root.txt") -Value $PSScriptRoot -Encoding UTF8

$imageNodeSource = Join-Path $PSScriptRoot "custom_nodes\openai_compatible_image_node.py"
$imageNodeTarget = Join-Path $config.CustomNodesRoot "openai_compatible_image_node.py"
Copy-Item -LiteralPath $imageNodeSource -Destination $imageNodeTarget -Force

Write-Output "Installed comic pipeline node to $targetDir"
Write-Output "Installed OpenAI compatible image node to $imageNodeTarget"
Write-Output "Restart ComfyUI, then verify /object_info contains ComicNovelSource and /extensions contains comic_episode_pipeline_node."
