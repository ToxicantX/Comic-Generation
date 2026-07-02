param(
    [string]$EpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json",
    [string]$OutputDir = "E:\workspace\ComfyUIProjects\manifests",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_page_plan_create_result.json",
    [switch]$OverwriteExisting
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($EpisodePlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json") { $EpisodePlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_pages.json" }
if ($OutputDir -eq "E:\workspace\ComfyUIProjects\manifests") { $OutputDir = Join-Path $comicConfig.Workspace "manifests" }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_page_plan_create_result.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_page_plan_create_result.json" }

if (-not (Test-Path -LiteralPath $EpisodePlanPath)) {
    throw "Episode plan file not found: $EpisodePlanPath"
}

$episode = Get-Content -Path $EpisodePlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$created = @()

function Get-ComicPageLayoutPreset {
    param(
        [int]$PageNumber
    )

    $presets = @(
        [ordered]@{
            name = "splash_opening"
            reading_flow = "top establishing panel, mid action beat, bottom page-turn splash"
            visual_priority = "top establishing panel and bottom hook panel"
            panels = @(
                [ordered]@{ x = 0; y = 0; w = 1600; h = 690; role = "opening_splash"; shot_type = "wide_splash"; shape = "rect"; border = 0; render_order = 1 },
                [ordered]@{ x = 12; y = 722; w = 764; h = 700; role = "action_advance"; shot_type = "medium_action"; shape = "rect"; border = 0; render_order = 2 },
                [ordered]@{ x = 812; y = 722; w = 764; h = 700; role = "emotional_reaction"; shot_type = "reaction"; shape = "rect"; border = 0; render_order = 3 },
                [ordered]@{ x = 0; y = 1446; w = 1600; h = 954; role = "page_turn_hook"; shot_type = "bottom_splash"; shape = "rect"; border = 0; render_order = 4 }
            )
        },
        [ordered]@{
            name = "diagonal_action"
            reading_flow = "upper setup, diagonal action cut, lower consequence panel"
            visual_priority = "diagonal action panel"
            panels = @(
                [ordered]@{ x = 12; y = 16; w = 764; h = 636; role = "scene_setup"; shot_type = "establishing"; shape = "rect"; border = 0; render_order = 1 },
                [ordered]@{ x = 812; y = 16; w = 764; h = 636; role = "close_reaction"; shot_type = "close_reaction"; shape = "rect"; border = 0; render_order = 2 },
                [ordered]@{ x = 0; y = 688; w = 1600; h = 800; role = "action_splash"; shot_type = "action_splash"; shape = "slant_right"; slant = 88; border = 0; render_order = 3 },
                [ordered]@{ x = 0; y = 1512; w = 1600; h = 888; role = "consequence_hook"; shot_type = "reveal"; shape = "rect"; border = 0; render_order = 4 }
            )
        },
        [ordered]@{
            name = "bottom_reveal"
            reading_flow = "small setup beats, then a dominant bottom reveal"
            visual_priority = "bottom reveal splash"
            panels = @(
                [ordered]@{ x = 12; y = 16; w = 504; h = 552; role = "detail_setup"; shot_type = "detail"; shape = "rect"; border = 0; render_order = 1 },
                [ordered]@{ x = 548; y = 16; w = 504; h = 552; role = "character_reaction"; shot_type = "reaction"; shape = "rect"; border = 0; render_order = 2 },
                [ordered]@{ x = 1072; y = 16; w = 504; h = 552; role = "action_trigger"; shot_type = "action"; shape = "rect"; border = 0; render_order = 3 },
                [ordered]@{ x = 0; y = 604; w = 1600; h = 1796; role = "reveal_splash"; shot_type = "reveal_splash"; shape = "rect"; border = 0; render_order = 4 }
            )
        },
        [ordered]@{
            name = "bleed_tension"
            reading_flow = "near-bleed opening pressure, two reaction beats, final narrow silence"
            visual_priority = "large near-bleed pressure panel"
            panels = @(
                [ordered]@{ x = 0; y = 20; w = 1600; h = 1002; role = "bleed_pressure"; shot_type = "bleed_splash"; shape = "rect"; border = 0; render_order = 1 },
                [ordered]@{ x = 12; y = 1042; w = 760; h = 650; role = "counter_action"; shot_type = "medium_action"; shape = "slant_left"; slant = 56; border = 0; render_order = 2 },
                [ordered]@{ x = 816; y = 1042; w = 760; h = 650; role = "reaction_cut"; shot_type = "reaction"; shape = "slant_right"; slant = 56; border = 0; render_order = 3 },
                [ordered]@{ x = 0; y = 1716; w = 1600; h = 684; role = "silent_hook"; shot_type = "quiet_transition"; shape = "rect"; border = 0; render_order = 4 }
            )
        },
        [ordered]@{
            name = "inset_reaction"
            reading_flow = "main scene panel with an inset reaction, then a lower transition"
            visual_priority = "main scene with upper-right inset reaction"
            panels = @(
                [ordered]@{ x = 0; y = 0; w = 1600; h = 636; role = "wide_opening"; shot_type = "wide_establishing"; shape = "rect"; border = 0; render_order = 1 },
                [ordered]@{ x = 0; y = 648; w = 1600; h = 1056; role = "main_scene_action"; shot_type = "scene_splash"; shape = "rect"; border = 0; render_order = 2 },
                [ordered]@{ x = 1074; y = 696; w = 460; h = 420; role = "inset_reaction"; shot_type = "inset_reaction"; shape = "rect"; border = 0; render_order = 3; drop_shadow = $true; shadow_offset = 8 },
                [ordered]@{ x = 0; y = 1716; w = 1600; h = 684; role = "page_transition"; shot_type = "transition"; shape = "rect"; border = 0; render_order = 4 }
            )
        }
    )

    return $presets[($PageNumber - 1) % $presets.Count]
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

foreach ($page in $episode.pages) {
    if ($page.plan -and (Test-Path -LiteralPath ([string]$page.plan)) -and -not $OverwriteExisting) {
        $created += [ordered]@{
            page_id = $page.page_id
            status = "existing_plan_kept"
            plan_path = [string]$page.plan
        }
        continue
    }

    if (-not $page.panels) {
        $created += [ordered]@{
            page_id = $page.page_id
            status = "skipped_no_panels"
            plan_path = $null
        }
        continue
    }

    $pageNumber = [int]([regex]::Match([string]$page.page_id, 'P(\d+)$').Groups[1].Value)
    $layoutPreset = Get-ComicPageLayoutPreset -PageNumber $pageNumber
    $layoutSet = @($layoutPreset.panels)
    $panelPlans = @()
    $panelIndex = 0
    foreach ($panel in $page.panels) {
        $layout = $layoutSet[[Math]::Min($panelIndex, $layoutSet.Count - 1)]
        $panelNumber = "{0:D2}" -f ($panelIndex + 1)
        $panelId = "$($page.page_id)_PANEL$panelNumber"
        $referenceImage = ""
        if ($panel.reference_alias -and $episode.asset_aliases.PSObject.Properties.Name -contains ([string]$panel.reference_alias)) {
            $referenceImage = [string]$episode.asset_aliases.$($panel.reference_alias)
        }

        $panelPlans += [ordered]@{
            panel_id = $panelId
            order = $panelIndex + 1
            title = $panel.title
            layout = $layout
            panel_role = $layout.role
            shot_type = $layout.shot_type
            filename_prefix = "ComicPipeline/panels/$($page.page_id)_PANEL$($panelNumber)_v001"
            fallback_filename_prefix = "ComicPipeline/panels/$($page.page_id)_PANEL$($panelNumber)_v001"
            reference_image = $referenceImage
            fallback_reference_image = ""
            prompt = $panel.prompt
            fallback_prompt = $panel.prompt
            caption = if ($panel.caption) { $panel.caption } else { "" }
            dialogue = @($panel.dialogue)
        }
        $panelIndex += 1
    }

    $plan = [ordered]@{
        updated = (Get-Date).ToString("yyyy-MM-dd")
        project = $episode.project
        source = $episode.source
        episode_id = $episode.episode_id
        page_id = $page.page_id
        title = $page.title
        reading_order = $episode.page_defaults.reading_order
        layout_style = $layoutPreset.name
        reading_flow = $layoutPreset.reading_flow
        visual_priority = $layoutPreset.visual_priority
        page = [ordered]@{
            width = $episode.page_defaults.width
            height = $episode.page_defaults.height
            background = "#050403"
            gutter = $episode.page_defaults.gutter
            border = 0
            safe_margin = 48
            paper_border = 0
        }
        assets = [ordered]@{
            style_bible = $episode.style_bible
            character_cards = $episode.character_cards
        }
        beat_ids = @($page.beat_ids)
        summary = $page.summary
        source_excerpt = if ($page.source_excerpt) { [string]$page.source_excerpt } else { "" }
        panel_intent = @($page.panel_intent)
        close_reading_required = if ($page.PSObject.Properties.Name -contains "close_reading_required") { [bool]$page.close_reading_required } else { $false }
        global_prompt_block = $episode.global_prompt_block
        negative_prompt = $episode.negative_prompt
        panels = $panelPlans
    }

    $fileStem = ([string]$page.page_id).ToLowerInvariant()
    $planPath = Join-Path $OutputDir "$($fileStem)_plan.json"
    $plan | ConvertTo-Json -Depth 20 | Set-Content -Path $planPath -Encoding UTF8
    $created += [ordered]@{
        page_id = $page.page_id
        status = "created"
        plan_path = $planPath
        panels = $panelPlans.Count
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    episode_plan_path = $EpisodePlanPath
    output_dir = $OutputDir
    created = $created
}

$result | ConvertTo-Json -Depth 12 | Set-Content -Path $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 12
