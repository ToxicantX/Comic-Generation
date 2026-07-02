param(
    [string]$EpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_pages.json",
    [string]$PagePlanCreateResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json",
    [string]$WorkflowCreateResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_workflow_create_result.json",
    [string]$OutputJson = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_review.json",
    [string]$OutputMarkdown = "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP02_draft_review.md"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($EpisodePlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_pages.json") { $EpisodePlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_pages.json" }
if ($PagePlanCreateResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_page_plan_create_result.json") { $PagePlanCreateResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_page_plan_create_result.json" }
if ($WorkflowCreateResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_workflow_create_result.json") { $WorkflowCreateResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_workflow_create_result.json" }
if ($OutputJson -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_review.json") { $OutputJson = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_draft_review.json" }
if ($OutputMarkdown -eq "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP02_draft_review.md") { $OutputMarkdown = Join-Path $comicConfig.OutputRoot "review_packages\SSJ_COMIC_EP02_draft_review.md" }

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& $python (Join-Path $PSScriptRoot "build_comic_episode_draft_review.py") `
    --episode-plan $EpisodePlanPath `
    --page-plan-result $PagePlanCreateResultPath `
    --workflow-create-result $WorkflowCreateResultPath `
    --output-json $OutputJson `
    --output-md $OutputMarkdown
exit $LASTEXITCODE
