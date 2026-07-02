param(
    [int]$EpisodeNumber = 0,
    [string]$EpisodePlanPath = "",
    [string]$NovelPath = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [int]$Pages = 8,
    [int]$ExcerptChars = 3600,
    [string]$Encoding = "gb18030",
    [switch]$DryRun,
    [switch]$Force,
    [switch]$GenerateImages,
    [switch]$SkipImageGeneration,
    [switch]$CreateChapterBrief,
    [switch]$ApplyChapterBrief,
    [switch]$ExpandPages,
    [switch]$RefinePagePlans,
    [switch]$OverwritePagePlans,
    [switch]$AssemblePages,
    [switch]$RunLetteringQa,
    [switch]$RunConsistencyQa,
    [switch]$RunImageHealthQa,
    [switch]$CheckComfyHealth,
    [switch]$AllowAnchorMissing,
    [switch]$AllowDraftWarnings,
    [string]$OnlyStage = "",
    [string]$FromStage = "",
    [string]$UntilStage = "",
    [int]$MaxPages = 0,
    [int]$MaxPanels = 0,
    [int]$RetryCount = 0,
    [int]$CooldownSeconds = 240,
    [int]$PollSeconds = 30,
    [int]$MaxIdlePolls = 120,
    [int]$MaxPromptPolls = 240,
    [string]$GenerationContextPath = "",
    [string]$RunLabel = "pipeline",
    [string]$ResultPath = ""
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
$python = Get-ComicPipelinePython -Config $comicConfig

if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) { $ComfyUrl = $comicConfig.ComfyUrl }
if ($Pages -eq 8 -and $comicConfig.DefaultPages) { $Pages = [int]$comicConfig.DefaultPages }
if ($Encoding -eq "gb18030" -and $comicConfig.Encoding) { $Encoding = [string]$comicConfig.Encoding }
if (-not $NovelPath -and $comicConfig.NovelPath) { $NovelPath = [string]$comicConfig.NovelPath }

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$argsList = @(
    (Join-Path $PSScriptRoot "run_comic_episode_pipeline.py"),
    "--comfy-url", $ComfyUrl,
    "--pages", $Pages,
    "--excerpt-chars", $ExcerptChars,
    "--encoding", $Encoding,
    "--max-pages", $MaxPages,
    "--max-panels", $MaxPanels,
    "--retry-count", $RetryCount,
    "--cooldown-seconds", $CooldownSeconds,
    "--poll-seconds", $PollSeconds,
    "--max-idle-polls", $MaxIdlePolls,
    "--max-prompt-polls", $MaxPromptPolls,
    "--run-label", $RunLabel
)

if ($EpisodeNumber -gt 0) {
    $argsList += @("--episode-number", $EpisodeNumber)
}
if ($EpisodePlanPath) {
    $argsList += @("--episode-plan", $EpisodePlanPath)
}
if ($NovelPath) {
    $argsList += @("--novel", $NovelPath)
}
if ($DryRun) { $argsList += "--dry-run" }
if ($Force) { $argsList += "--force" }
if ($GenerateImages) { $argsList += "--generate-images" }
if ($SkipImageGeneration) { $argsList += "--skip-image-generation" }
if ($CreateChapterBrief) { $argsList += "--create-chapter-brief" }
if ($ApplyChapterBrief) { $argsList += "--apply-chapter-brief" }
if ($ExpandPages) { $argsList += "--expand-pages" }
if ($RefinePagePlans) { $argsList += "--refine-page-plans" }
if ($OverwritePagePlans) { $argsList += "--overwrite-page-plans" }
if ($AssemblePages) { $argsList += "--assemble-pages" }
if ($RunLetteringQa) { $argsList += "--run-lettering-qa" }
if ($RunConsistencyQa) { $argsList += "--run-consistency-qa" }
if ($RunImageHealthQa) { $argsList += "--run-image-health-qa" }
if ($CheckComfyHealth) { $argsList += "--check-comfy-health" }
if ($AllowAnchorMissing) { $argsList += "--allow-anchor-missing" }
if ($AllowDraftWarnings) { $argsList += "--allow-draft-warnings" }
if ($OnlyStage) { $argsList += @("--only-stage", $OnlyStage) }
if ($FromStage) { $argsList += @("--from-stage", $FromStage) }
if ($UntilStage) { $argsList += @("--until-stage", $UntilStage) }
if ($GenerationContextPath) { $argsList += @("--generation-context", $GenerationContextPath) }
if ($ResultPath) { $argsList += @("--result-path", $ResultPath) }

& $python @argsList
exit $LASTEXITCODE
