param(
    [string]$PagePlanCreateResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json",
    [string]$EpisodePlanPath = "",
    [string]$WorkflowScript = "E:\workspace\ComfyUIProjects\scripts\create_comic_panel_workflows.ps1",
    [string]$WorkflowDir = "E:\workspace\ComfyUIProjects\workflows\comic",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_workflow_create_result.json",
    [int]$MaxPages = 0,
    [switch]$AutoImageSize,
    [switch]$UseFallbackPrompts
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($PagePlanCreateResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json") { $PagePlanCreateResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_page_plan_create_result.json" }
if ($WorkflowScript -eq "E:\workspace\ComfyUIProjects\scripts\create_comic_panel_workflows.ps1") { $WorkflowScript = Join-Path $comicConfig.Workspace "scripts\create_comic_panel_workflows.ps1" }
if ($WorkflowDir -eq "E:\workspace\ComfyUIProjects\workflows\comic") { $WorkflowDir = Join-Path $comicConfig.Workspace "workflows\comic" }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_episode_workflow_create_result.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_episode_workflow_create_result.json" }

if (-not (Test-Path -LiteralPath $PagePlanCreateResultPath)) {
    throw "Page plan create result not found: $PagePlanCreateResultPath"
}
if (-not (Test-Path -LiteralPath $WorkflowScript)) {
    throw "Workflow script not found: $WorkflowScript"
}

$pagePlanResult = Get-Content -LiteralPath $PagePlanCreateResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
$items = @($pagePlanResult.created | Where-Object { $_.plan_path })
if ($MaxPages -gt 0) {
    $items = @($items | Select-Object -First $MaxPages)
}

$runs = @()
foreach ($item in $items) {
    $pageId = [string]$item.page_id
    $workflowResultPath = Join-Path (Split-Path $PagePlanCreateResultPath) "$(($pageId -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant())_fallback_workflows.json"
    $args = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $WorkflowScript,
        "-PlanPath", ([string]$item.plan_path),
        "-WorkflowDir", $WorkflowDir,
        "-ResultPath", $workflowResultPath
    )
    if ($EpisodePlanPath) {
        $args += @("-EpisodePlanPath", $EpisodePlanPath)
    }
    if ($AutoImageSize) {
        $args += "-AutoImageSize"
    }
    if ($UseFallbackPrompts) {
        $args += "-UseFallbackPrompts"
    }

    $output = & powershell @args
    $runs += [ordered]@{
        page_id = $pageId
        plan_path = [string]$item.plan_path
        workflow_result_path = $workflowResultPath
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
