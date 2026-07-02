param(
    [string]$PagePlanCreateResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json",
    [string]$RefineScript = "E:\workspace\ComfyUIProjects\scripts\refine_comic_page_plan_from_excerpt.ps1",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_page_plan_refine_result.json",
    [int]$MaxPages = 0
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($PagePlanCreateResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json") { $PagePlanCreateResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_page_plan_create_result.json" }
if ($RefineScript -eq "E:\workspace\ComfyUIProjects\scripts\refine_comic_page_plan_from_excerpt.ps1") { $RefineScript = Join-Path $comicConfig.Workspace "scripts\refine_comic_page_plan_from_excerpt.ps1" }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_episode_page_plan_refine_result.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_episode_page_plan_refine_result.json" }

if (-not (Test-Path -LiteralPath $PagePlanCreateResultPath)) {
    throw "Page plan create result not found: $PagePlanCreateResultPath"
}
if (-not (Test-Path -LiteralPath $RefineScript)) {
    throw "Refine script not found: $RefineScript"
}

$pagePlanResult = Get-Content -LiteralPath $PagePlanCreateResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
$items = @($pagePlanResult.created | Where-Object { $_.plan_path })
if ($MaxPages -gt 0) {
    $items = @($items | Select-Object -First $MaxPages)
}

$runs = @()
foreach ($item in $items) {
    $output = & powershell -ExecutionPolicy Bypass -File $RefineScript -PlanPath ([string]$item.plan_path)
    $runs += [ordered]@{
        page_id = [string]$item.page_id
        plan_path = [string]$item.plan_path
        exit_code = $LASTEXITCODE
        output = @($output)
    }
    if ($LASTEXITCODE -ne 0) {
        break
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    page_plan_create_result_path = $PagePlanCreateResultPath
    pages_requested = $items.Count
    completed = (($runs | Where-Object { $_.exit_code -ne 0 }).Count -eq 0)
    runs = $runs
}

$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 20

if (-not $result.completed) {
    exit 1
}
