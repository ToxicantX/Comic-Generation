param(
    [string]$ChapterIndexPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_chapter_index.json",
    [string]$OutputPath = "E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json",
    [int]$PagesPerChapter = 8,
    [int]$PanelsPerPage = 4
)

if (-not (Test-Path -LiteralPath $ChapterIndexPath)) {
    throw "Chapter index not found: $ChapterIndexPath"
}

$index = Get-Content -Path $ChapterIndexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$chapters = @($index | Where-Object { $_.type -eq "chapter" })
$volumes = @($index | Where-Object { $_.type -eq "volume" })
$episodes = @()
$volumeStats = @{}

for ($i = 0; $i -lt $chapters.Count; $i++) {
    $chapter = $chapters[$i]
    $volume = [string]$chapter.volume
    if (-not $volumeStats.ContainsKey($volume)) {
        $volumeStats[$volume] = [ordered]@{
            volume = $volume
            chapters = 0
            planned_pages = 0
            planned_panels = 0
        }
    }
    $chapterNumberInVolume = $volumeStats[$volume].chapters + 1
    $volumeStats[$volume].chapters += 1
    $volumeStats[$volume].planned_pages += $PagesPerChapter
    $volumeStats[$volume].planned_panels += ($PagesPerChapter * $PanelsPerPage)

    $episodeNumber = "{0:D3}" -f ($i + 1)
    $episodes += [ordered]@{
        episode_id = "SSJ_COMIC_EP$episodeNumber"
        source_volume = $volume
        chapter_title = $chapter.title
        chapter_line = $chapter.line
        chapter_number_in_volume = $chapterNumberInVolume
        priority = if ($i -lt 6) { "P0_volume01" } elseif ($i -lt 20) { "P1_early_series" } else { "P2_backlog" }
        planned_pages = $PagesPerChapter
        planned_panels = $PagesPerChapter * $PanelsPerPage
        page_plan_pattern = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep$episodeNumber`_p###_plan.json"
        status = if ($i -eq 0) {
            "production_started"
        } else {
            "needs_close_reading"
        }
        next_required_inputs = @(
            "chapter close reading",
            "episode page index",
            "new characters and locations",
            "page plans",
            "panel workflows"
        )
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    project = "Longform Comic Generation Pipeline"
    source = "Sou Shen Ji"
    source_chapter_index = $ChapterIndexPath
    assumptions = [ordered]@{
        pages_per_chapter = $PagesPerChapter
        panels_per_page = $PanelsPerPage
        note = "This is a production budgeting plan. Individual chapters should be rebalanced after close reading."
    }
    totals = [ordered]@{
        volumes = $volumes.Count
        chapters = $chapters.Count
        planned_pages = $chapters.Count * $PagesPerChapter
        planned_panels = $chapters.Count * $PagesPerChapter * $PanelsPerPage
    }
    volumes = @($volumeStats.Values)
    episodes = $episodes
}

New-Item -ItemType Directory -Path (Split-Path $OutputPath) -Force | Out-Null
$result | ConvertTo-Json -Depth 20 | Set-Content -Path $OutputPath -Encoding UTF8
$result | ConvertTo-Json -Depth 20
