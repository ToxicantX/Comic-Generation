param(
    [string]$SeriesPlanPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json",
    [string]$TemplateEpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json",
    [string]$OutputDir = "E:\workspace\ComfyUIProjects\manifests",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_skeleton_create_result.json",
    [int]$StartEpisodeNumber = 2,
    [int]$EpisodeCount = 1,
    [int]$PagesPerEpisode = 8,
    [switch]$OverwriteExisting
)

if (-not (Test-Path -LiteralPath $SeriesPlanPath)) {
    throw "Series plan not found: $SeriesPlanPath"
}
if (-not (Test-Path -LiteralPath $TemplateEpisodePlanPath)) {
    throw "Template episode plan not found: $TemplateEpisodePlanPath"
}

$series = Get-Content -LiteralPath $SeriesPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$template = Get-Content -LiteralPath $TemplateEpisodePlanPath -Raw -Encoding UTF8 | ConvertFrom-Json

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$created = @()

$episodes = @($series.episodes | Where-Object {
    $episodeNumber = [int]([regex]::Match([string]$_.episode_id, 'EP0*(\d+)$').Groups[1].Value)
    $episodeNumber -ge $StartEpisodeNumber
} | Select-Object -First $EpisodeCount)

foreach ($episode in $episodes) {
    $episodeNumber = [int]([regex]::Match([string]$episode.episode_id, 'EP0*(\d+)$').Groups[1].Value)
    $episodeId = "SSJ_COMIC_EP{0:D2}" -f $episodeNumber
    $episodeSlug = "ssj_comic_episode{0:D2}" -f $episodeNumber
    $outputPath = Join-Path $OutputDir "$($episodeSlug)_pages.json"

    if ((Test-Path -LiteralPath $outputPath) -and -not $OverwriteExisting) {
        $created += [ordered]@{
            episode_id = $episodeId
            status = "existing_kept"
            path = $outputPath
        }
        continue
    }

    $pages = @()
    for ($pageIndex = 1; $pageIndex -le $PagesPerEpisode; $pageIndex++) {
        $pageId = "$episodeId`_P{0:D3}" -f $pageIndex
        $panels = @()
        for ($panelIndex = 1; $panelIndex -le 4; $panelIndex++) {
            $panels += [ordered]@{
                title = "待细读分镜 $panelIndex"
                reference_alias = ""
                caption = ""
                dialogue = @()
                prompt = "Placeholder comic panel for $($episode.source_volume) $($episode.chapter_title), page $pageIndex panel $panelIndex. Replace after close reading; ancient Chinese mythic fantasy, no text."
            }
        }

        $pages += [ordered]@{
            page_id = $pageId
            status = "skeleton_needs_close_reading"
            beat_ids = @()
            title = "$($episode.chapter_title) P{0:D2}" -f $pageIndex
            summary = "Skeleton page for $($episode.source_volume) $($episode.chapter_title). Requires chapter close reading before production."
            panels = $panels
        }
    }

    $episodePlan = [ordered]@{
        updated = (Get-Date).ToString("yyyy-MM-dd")
        project = $template.project
        source = "搜神记 $($episode.source_volume) $($episode.chapter_title)"
        source_volume = $episode.source_volume
        source_chapter_title = $episode.chapter_title
        source_chapter_line = $episode.chapter_line
        episode_id = $episodeId
        episode_title = $episode.chapter_title
        skeleton = $true
        close_reading_required = $true
        style_bible = $template.style_bible
        character_cards = $template.character_cards
        page_defaults = $template.page_defaults
        asset_aliases = $template.asset_aliases
        global_prompt_block = $template.global_prompt_block
        negative_prompt = $template.negative_prompt
        pages = $pages
    }

    $episodePlan | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $outputPath -Encoding UTF8
    $created += [ordered]@{
        episode_id = $episodeId
        status = "created"
        path = $outputPath
        pages = $pages.Count
        panels = $pages.Count * 4
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    series_plan_path = $SeriesPlanPath
    template_episode_plan_path = $TemplateEpisodePlanPath
    output_dir = $OutputDir
    start_episode_number = $StartEpisodeNumber
    episode_count = $EpisodeCount
    pages_per_episode = $PagesPerEpisode
    created = $created
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 12
