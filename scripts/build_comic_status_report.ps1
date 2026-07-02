param(
    [string]$EpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json",
    [string]$OutputJson = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_status.json",
    [string]$OutputMarkdown = "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP01_status.md"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($EpisodePlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json") { $EpisodePlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_pages.json" }
if ($OutputJson -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_status.json") { $OutputJson = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_status.json" }
if ($OutputMarkdown -eq "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP01_status.md") {
    $OutputMarkdown = Join-Path $comicConfig.OutputRoot "review_packages\SSJ_COMIC_EP01_status.md"
}

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& $python (Join-Path $PSScriptRoot "build_comic_status_report.py") $EpisodePlanPath $OutputJson $OutputMarkdown
exit $LASTEXITCODE
