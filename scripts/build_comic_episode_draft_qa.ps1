param(
    [string]$DraftReviewPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_review.json",
    [string]$EpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_pages.json",
    [string]$OutputJson = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_qa.json",
    [string]$OutputMarkdown = "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP02_draft_qa.md"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($DraftReviewPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_review.json") { $DraftReviewPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_draft_review.json" }
if ($EpisodePlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_pages.json") { $EpisodePlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_pages.json" }
if ($OutputJson -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_qa.json") { $OutputJson = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode02_draft_qa.json" }
if ($OutputMarkdown -eq "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP02_draft_qa.md") { $OutputMarkdown = Join-Path $comicConfig.OutputRoot "review_packages\SSJ_COMIC_EP02_draft_qa.md" }

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& $python (Join-Path $PSScriptRoot "build_comic_episode_draft_qa.py") `
    --draft-review $DraftReviewPath `
    --episode-plan $EpisodePlanPath `
    --output-json $OutputJson `
    --output-md $OutputMarkdown
exit $LASTEXITCODE
