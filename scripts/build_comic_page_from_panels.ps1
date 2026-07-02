param(
    [string]$PlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_plan.json",
    [string]$WorkflowResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_workflows.json",
    [string]$OutputDir = "G:\ComfyUI\output\ComicPipeline\pages",
    [string]$ReviewDir = "",
    [string]$ManifestPath = ""
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($OutputDir -eq "G:\ComfyUI\output\ComicPipeline\pages") { $OutputDir = Join-Path $comicConfig.OutputRoot "pages" }

if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Plan file not found: $PlanPath"
}

$plan = Get-Content -Path $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pageId = if ($plan.page_id) { [string]$plan.page_id } else { "comic_page" }
if (-not $ReviewDir) {
    $ReviewDir = Join-Path $comicConfig.OutputRoot "review_packages\$pageId"
}
if (-not $ManifestPath) {
    $safePageId = $pageId.ToLowerInvariant()
    $ManifestPath = Join-Path $comicConfig.Workspace "manifests\$($safePageId)_assembly.json"
}

$python = Get-ComicPipelinePython -Config $comicConfig
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& $python (Join-Path $PSScriptRoot "build_comic_page_from_panels.py") $PlanPath $WorkflowResultPath $OutputDir $ReviewDir $ManifestPath
exit $LASTEXITCODE
