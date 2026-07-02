param(
    [Parameter(Mandatory = $true)]
    [string]$EpisodePlanPath,
    [Parameter(Mandatory = $true)]
    [string]$BriefPath,
    [string]$OutputPath = "",
    [switch]$ExpandPages
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$args = @(
    (Join-Path $PSScriptRoot "apply_comic_chapter_brief_to_episode.py"),
    "--episode-plan", $EpisodePlanPath,
    "--brief", $BriefPath
)
if ($OutputPath) {
    $args += @("--output", $OutputPath)
}
if ($ExpandPages) {
    $args += "--expand-pages"
}

& $python @args
exit $LASTEXITCODE
