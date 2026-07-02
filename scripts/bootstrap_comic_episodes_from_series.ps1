param(
    [string]$SeriesPlanPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json",
    [string]$TemplateEpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json",
    [string]$OutputDir = "E:\workspace\ComfyUIProjects\manifests",
    [string]$WorkflowDir = "E:\workspace\ComfyUIProjects\workflows\comic",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_bootstrap_result.json",
    [int]$StartEpisodeNumber = 2,
    [int]$EpisodeCount = 1,
    [int]$PagesPerEpisode = 8,
    [int]$WorkflowPagesPerEpisode = 1,
    [switch]$OverwriteExisting
)

$skeletonScript = "E:\workspace\ComfyUIProjects\scripts\create_comic_episode_skeletons_from_series.ps1"
$pagePlanScript = "E:\workspace\ComfyUIProjects\scripts\create_comic_page_plans.ps1"
$workflowScript = "E:\workspace\ComfyUIProjects\scripts\create_comic_panel_workflows.ps1"

foreach ($script in @($skeletonScript, $pagePlanScript, $workflowScript)) {
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Required script not found: $script"
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    start_episode_number = $StartEpisodeNumber
    episode_count = $EpisodeCount
    pages_per_episode = $PagesPerEpisode
    workflow_pages_per_episode = $WorkflowPagesPerEpisode
    skeleton_result = $null
    page_plan_results = @()
    workflow_results = @()
    completed = $false
    error = $null
}

try {
    $skeletonResultPath = Join-Path $OutputDir "comic_episode_bootstrap_skeletons.json"
    $skeletonArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $skeletonScript,
        "-SeriesPlanPath", $SeriesPlanPath,
        "-TemplateEpisodePlanPath", $TemplateEpisodePlanPath,
        "-OutputDir", $OutputDir,
        "-ResultPath", $skeletonResultPath,
        "-StartEpisodeNumber", $StartEpisodeNumber,
        "-EpisodeCount", $EpisodeCount,
        "-PagesPerEpisode", $PagesPerEpisode
    )
    if ($OverwriteExisting) {
        $skeletonArgs += "-OverwriteExisting"
    }
    & powershell @skeletonArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Skeleton creation failed."
    }
    $result.skeleton_result = Get-Content -LiteralPath $skeletonResultPath -Raw -Encoding UTF8 | ConvertFrom-Json

    foreach ($episodeItem in @($result.skeleton_result.created)) {
        $episodeId = [string]$episodeItem.episode_id
        $episodePlanPath = [string]$episodeItem.path
        if (-not (Test-Path -LiteralPath $episodePlanPath)) {
            continue
        }

        $pagePlanResultPath = Join-Path $OutputDir "$(($episodeId -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant())_page_plan_create_result.json"
        $pagePlanArgs = @(
            "-ExecutionPolicy", "Bypass",
            "-File", $pagePlanScript,
            "-EpisodePlanPath", $episodePlanPath,
            "-OutputDir", $OutputDir,
            "-ResultPath", $pagePlanResultPath
        )
        if ($OverwriteExisting) {
            $pagePlanArgs += "-OverwriteExisting"
        }
        & powershell @pagePlanArgs | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Page plan creation failed for $episodeId."
        }

        $pagePlanResult = Get-Content -LiteralPath $pagePlanResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $result.page_plan_results += $pagePlanResult

        $workflowPageItems = @($pagePlanResult.created | Where-Object { $_.plan_path } | Select-Object -First $WorkflowPagesPerEpisode)
        foreach ($pageItem in $workflowPageItems) {
            $pageId = [string]$pageItem.page_id
            $workflowResultPath = Join-Path $OutputDir "$(($pageId -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant())_fallback_workflows.json"
            & powershell -ExecutionPolicy Bypass -File $workflowScript `
                -PlanPath ([string]$pageItem.plan_path) `
                -WorkflowDir $WorkflowDir `
                -ResultPath $workflowResultPath `
                -UseFallbackPrompts | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Workflow creation failed for $pageId."
            }
            $result.workflow_results += Get-Content -LiteralPath $workflowResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
    }

    $result.completed = $true
} catch {
    $result.error = $_.Exception.Message
} finally {
    New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
    $result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    $result | ConvertTo-Json -Depth 20
}

if (-not $result.completed) {
    exit 1
}
