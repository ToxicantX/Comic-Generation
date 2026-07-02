param(
    [Parameter(Mandatory = $true)]
    [int]$EpisodeNumber,
    [string]$NovelPath = "",
    [string]$ChapterIndexPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_chapter_index.json",
    [string]$SeriesPlanPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json",
    [string]$OutputPath = "",
    [string]$Encoding = "gb18030",
    [int]$ExcerptChars = 3600,
    [int]$Pages = 8
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if (-not $NovelPath) { $NovelPath = $comicConfig.NovelPath }
$manifestDir = if ($env:COMIC_PIPELINE_MANIFEST_DIR) { $env:COMIC_PIPELINE_MANIFEST_DIR } else { Join-Path $comicConfig.Workspace "manifests" }
$activeProject = if ($comicConfig.ActiveProject) { [string]$comicConfig.ActiveProject } else { "sou_shen_ji" }
if ($ChapterIndexPath -eq "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_chapter_index.json") {
    $candidate = Join-Path $manifestDir "$activeProject`_chapter_index.json"
    if (Test-Path -LiteralPath $candidate) { $ChapterIndexPath = $candidate } else { $ChapterIndexPath = Join-Path $comicConfig.Workspace "manifests\sou_shen_ji_chapter_index.json" }
}
if ($SeriesPlanPath -eq "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json") {
    $candidate = Join-Path $manifestDir "$activeProject`_comic_series_plan.json"
    if (Test-Path -LiteralPath $candidate) { $SeriesPlanPath = $candidate } else { $SeriesPlanPath = Join-Path $comicConfig.Workspace "manifests\sou_shen_ji_comic_series_plan.json" }
}

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$args = @(
    (Join-Path $PSScriptRoot "create_comic_chapter_brief.py"),
    "--episode-number", $EpisodeNumber,
    "--chapter-index", $ChapterIndexPath,
    "--series-plan", $SeriesPlanPath,
    "--encoding", $Encoding,
    "--excerpt-chars", $ExcerptChars,
    "--pages", $Pages
)
$args += @("--novel", $NovelPath)
if ($OutputPath) {
    $args += @("--output", $OutputPath)
}

& $python @args
exit $LASTEXITCODE
