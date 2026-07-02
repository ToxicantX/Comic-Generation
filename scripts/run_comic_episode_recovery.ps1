param(
    [string]$EpisodePlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json",
    [string]$StatusPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_status.json",
    [string]$StatusMarkdownPath = "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP01_status.md",
    [string]$StatusScript = "E:\workspace\ComfyUIProjects\scripts\build_comic_status_report.ps1",
    [string]$RunMissingScript = "E:\workspace\ComfyUIProjects\scripts\run_missing_comic_panels.ps1",
    [string]$AssembleScript = "E:\workspace\ComfyUIProjects\scripts\build_comic_page_from_panels.ps1",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_recovery_run.json",
    [int]$MaxPanels = 1,
    [int]$RetryCount = 0,
    [int]$CooldownSeconds = 240,
    [int]$PollSeconds = 30,
    [int]$MaxIdlePolls = 120,
    [int]$MaxPromptPolls = 240,
    [string]$GenerationContextPath = "",
    [string[]]$SkipPanelIds = @(),
    [switch]$DryRun,
    [switch]$SkipAssembly
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($EpisodePlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_pages.json") { $EpisodePlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_pages.json" }
if ($StatusPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode01_status.json") { $StatusPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode01_status.json" }
if ($StatusMarkdownPath -eq "G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP01_status.md") { $StatusMarkdownPath = Join-Path $comicConfig.OutputRoot "review_packages\SSJ_COMIC_EP01_status.md" }
if ($StatusScript -eq "E:\workspace\ComfyUIProjects\scripts\build_comic_status_report.ps1") { $StatusScript = Join-Path $comicConfig.Workspace "scripts\build_comic_status_report.ps1" }
if ($RunMissingScript -eq "E:\workspace\ComfyUIProjects\scripts\run_missing_comic_panels.ps1") { $RunMissingScript = Join-Path $comicConfig.Workspace "scripts\run_missing_comic_panels.ps1" }
if ($AssembleScript -eq "E:\workspace\ComfyUIProjects\scripts\build_comic_page_from_panels.ps1") { $AssembleScript = Join-Path $comicConfig.Workspace "scripts\build_comic_page_from_panels.ps1" }
if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) { $ComfyUrl = $comicConfig.ComfyUrl }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_episode_recovery_run.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_episode_recovery_run.json" }

function Wait-ComfyIdle {
    param(
        [string]$Url,
        [int]$PollSeconds,
        [int]$MaxPolls
    )

    $polls = @()
    for ($i = 1; $i -le $MaxPolls; $i++) {
        $queue = Invoke-RestMethod -Uri "$Url/queue" -TimeoutSec 10
        $runningCount = @($queue.queue_running).Count
        $pendingCount = @($queue.queue_pending).Count
        $polls += [ordered]@{
            poll = $i
            time = (Get-Date).ToString("s")
            running = $runningCount
            pending = $pendingCount
        }
        if ($runningCount -eq 0 -and $pendingCount -eq 0) {
            return [ordered]@{
                idle = $true
                polls = $polls
                error = $null
            }
        }
        Start-Sleep -Seconds $PollSeconds
    }

    return [ordered]@{
        idle = $false
        polls = $polls
        error = "ComfyUI did not become idle within $MaxPolls polls."
    }
}

function Get-MissingPanelJobs {
    param([object]$Status)

    $jobs = @()
    foreach ($page in $Status.pages) {
        $workflowPath = if ($page.fallback_workflow_path) {
            [string]$page.fallback_workflow_path
        } else {
            [string]$page.workflow_path
        }

        foreach ($panelId in @($page.missing_panels)) {
            $panelIdText = [string]$panelId
            if ($SkipPanelIds.Count -gt 0 -and $SkipPanelIds -contains $panelIdText) {
                continue
            }
            $jobs += [ordered]@{
                page_id = [string]$page.page_id
                panel_id = $panelIdText
                plan_path = [string]$page.plan_path
                workflow_result_path = $workflowPath
                page_image = [string]$page.page_image
            }
        }
    }
    return $jobs
}

function ConvertTo-SafeStem {
    param([string]$Value)

    $stem = if ($Value) { $Value } else { "item" }
    $stem = $stem -replace '[^A-Za-z0-9_]+', '_'
    $stem = $stem.Trim("_").ToLowerInvariant()
    if (-not $stem) { return "item" }
    return $stem
}

function New-ContextWorkflowResult {
    param(
        [string]$WorkflowResultPath,
        [string]$PanelId,
        [object]$GenerationContext,
        [string]$RunRoot
    )

    if (-not $GenerationContext -or -not $GenerationContext.prompt_block) {
        return $WorkflowResultPath
    }
    if (-not (Test-Path -LiteralPath $WorkflowResultPath)) {
        return $WorkflowResultPath
    }

    $workflowResult = Get-Content -LiteralPath $WorkflowResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $selected = @($workflowResult.created | Where-Object { [string]$_.panel_id -eq $PanelId })
    if ($selected.Count -eq 0) {
        return $WorkflowResultPath
    }

    $panel = $selected[0]
    $sourceWorkflowPath = [string]$panel.workflow
    if (-not (Test-Path -LiteralPath $sourceWorkflowPath)) {
        return $WorkflowResultPath
    }

    $workflow = Get-Content -LiteralPath $sourceWorkflowPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $changed = $false
    foreach ($nodeProp in $workflow.prompt.PSObject.Properties) {
        $node = $nodeProp.Value
        if ($node.class_type -ne "OpenAICompatibleImageGenerate") {
            continue
        }
        $currentPrompt = [string]$node.inputs.prompt
        if ($currentPrompt -match "\[生成上下文\]") {
            continue
        }
        $node.inputs.prompt = $currentPrompt.TrimEnd() + [string]$GenerationContext.prompt_block
        $changed = $true
    }
    if (-not $changed) {
        return $WorkflowResultPath
    }

    $contextDir = Join-Path $RunRoot "context_workflows"
    New-Item -ItemType Directory -Path $contextDir -Force | Out-Null
    $panelStem = ConvertTo-SafeStem $PanelId
    $workflowPath = Join-Path $contextDir "$($panelStem)_context_workflow.json"
    $resultPath = Join-Path $contextDir "$($panelStem)_context_workflow_result.json"
    $workflow | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $workflowPath -Encoding UTF8

    $panel.workflow = $workflowPath
    $workflowResult | Add-Member -NotePropertyName context_injected -NotePropertyValue $true -Force
    $workflowResult | Add-Member -NotePropertyName generation_context_path -NotePropertyValue $GenerationContextPath -Force
    $workflowResult | Add-Member -NotePropertyName runtime_source_workflow_result_path -NotePropertyValue $WorkflowResultPath -Force
    $workflowResult | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    return $resultPath
}

function Get-AssemblyManifestPath {
    param([string]$PlanPath)

    if (Test-Path -LiteralPath $PlanPath) {
        try {
            $plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($plan.page_id) {
                $pageId = ([string]$plan.page_id).ToLowerInvariant()
                return (Join-Path $comicConfig.Workspace "manifests\$($pageId)_assembly.json")
            }
        } catch {
        }
    }

    $stem = [IO.Path]::GetFileNameWithoutExtension($PlanPath)
    $stem = $stem -replace "_plan$", ""
    return (Join-Path $comicConfig.Workspace "manifests\$($stem)_assembly.json")
}

function Get-AssemblySummary {
    param(
        [string]$ManifestPath,
        [int]$ExitCode
    )

    $summary = [ordered]@{
        assembly_manifest = $ManifestPath
        exit_code = $ExitCode
        status = "failed"
        assembly_ok = $null
        lettering_items = 0
        missing_panels = @()
        exists = (Test-Path -LiteralPath $ManifestPath)
    }

    if (-not $summary.exists) {
        return $summary
    }

    $assembly = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $missing = @()
    $letteringCount = 0
    foreach ($panel in @($assembly.panels)) {
        if (-not [bool]$panel.exists) {
            $missing += [string]$panel.panel_id
        }
        $letteringCount += @($panel.lettering).Count
    }

    $summary.assembly_ok = [bool]$assembly.ok
    $summary.lettering_items = $letteringCount
    $summary.missing_panels = $missing
    if ([bool]$assembly.ok) {
        $summary.status = "passed"
    } elseif ($missing.Count -gt 0) {
        $summary.status = "waiting_missing_panels"
    }
    return $summary
}

function Get-PanelRunSummary {
    param([object[]]$Output)

    $text = ($Output -join "`n")
    $summary = [ordered]@{
        output_line_count = @($Output).Count
        completed = $false
        runs = @()
    }
    if (-not $text.Trim()) {
        return $summary
    }
    try {
        $runResult = $text | ConvertFrom-Json
        $summary.completed = [bool]$runResult.completed
        foreach ($run in @($runResult.runs)) {
            $lastAttempt = @($run.attempts | Select-Object -Last 1)
            $summary.runs += [ordered]@{
                panel_id = [string]$run.panel_id
                completed = [bool]$run.completed
                skipped_existing = [bool]$run.skipped_existing
                attempts = @($run.attempts).Count
                last_status = if ($lastAttempt.Count -gt 0) { [string]$lastAttempt[0].status } else { $null }
                last_error = if ($lastAttempt.Count -gt 0) { $lastAttempt[0].error } else { $null }
            }
        }
    } catch {
        $summary.parse_error = $_.Exception.Message
    }
    return $summary
}

function Get-WaitingReasonFromErrors {
    param([string[]]$Errors)

    $text = ($Errors -join "`n")
    if (-not $text.Trim()) {
        return $null
    }
    if ($text -match "429|rate_limit|requests-per-minute") {
        return "rate_limit"
    }
    if ($text -match "502|503|504|upstream_error|Upstream authentication failed|upstream authentication|Bad Gateway|Gateway Timeout|RemoteDisconnected|Connection aborted|Remote end closed connection|closed connection without response|Connection reset|connection reset|temporarily unavailable") {
        return "upstream_error"
    }
    return $null
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    episode_plan_path = $EpisodePlanPath
    status_path = $StatusPath
    status_markdown_path = $StatusMarkdownPath
    comfy_url = $ComfyUrl
    dry_run = [bool]$DryRun
    max_panels = $MaxPanels
    skipped_panel_ids = $SkipPanelIds
    generation_context_path = $GenerationContextPath
    completed = $false
    waiting = $false
    jobs_discovered = 0
    jobs_attempted = @()
    pages_assembled = @()
    status_refresh = $null
    waiting_rate_limit = 0
    error = $null
}

try {
    if (-not (Test-Path -LiteralPath $StatusScript)) {
        throw "Status script not found: $StatusScript"
    }
    if (-not (Test-Path -LiteralPath $RunMissingScript)) {
        throw "Run missing script not found: $RunMissingScript"
    }
    if (-not (Test-Path -LiteralPath $AssembleScript)) {
        throw "Assemble script not found: $AssembleScript"
    }
    $generationContext = $null
    if ($GenerationContextPath) {
        if (-not (Test-Path -LiteralPath $GenerationContextPath)) {
            throw "Generation context file not found: $GenerationContextPath"
        }
        $generationContext = Get-Content -LiteralPath $GenerationContextPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }

    $statusOutput = & powershell -ExecutionPolicy Bypass -File $StatusScript `
        -EpisodePlanPath $EpisodePlanPath `
        -OutputJson $StatusPath `
        -OutputMarkdown $StatusMarkdownPath
    $result.status_refresh = @{
        before_run_exit_code = $LASTEXITCODE
        output_line_count = @($statusOutput).Count
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Status refresh failed before recovery."
    }
    if (-not (Test-Path -LiteralPath $StatusPath)) {
        throw "Status file not found after refresh: $StatusPath"
    }

    $status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $result.status_refresh.before_summary = $status.summary
    $jobs = @(Get-MissingPanelJobs -Status $status)
    $result.jobs_discovered = $jobs.Count

    if ($MaxPanels -gt 0) {
        $jobs = @($jobs | Select-Object -First $MaxPanels)
    }

    $touchedPages = @{}
    $jobIndex = 0
    foreach ($job in $jobs) {
        $jobIndex += 1
        $attempt = [ordered]@{
            page_id = $job.page_id
            panel_id = $job.panel_id
            workflow_result_path = $job.workflow_result_path
            plan_path = $job.plan_path
            skipped = $false
            idle_wait = $null
            exit_code = $null
            run_summary = $null
            output_line_count = 0
            completed = $false
            error = $null
        }

        if (-not (Test-Path -LiteralPath $job.workflow_result_path)) {
            $attempt.skipped = $true
            $attempt.error = "Workflow result file not found."
            $result.jobs_attempted += $attempt
            continue
        }
        $runtimeWorkflowResultPath = New-ContextWorkflowResult `
            -WorkflowResultPath $job.workflow_result_path `
            -PanelId $job.panel_id `
            -GenerationContext $generationContext `
            -RunRoot (Split-Path $ResultPath)
        if ($runtimeWorkflowResultPath -ne $job.workflow_result_path) {
            $attempt.runtime_workflow_result_path = $runtimeWorkflowResultPath
            $attempt.original_workflow_result_path = $job.workflow_result_path
        }

        if ($DryRun) {
            $attempt.skipped = $true
            $attempt.completed = $false
            $attempt.error = "Dry run; no workflow submitted."
            $result.jobs_attempted += $attempt
            continue
        }

        $attempt.idle_wait = Wait-ComfyIdle -Url $ComfyUrl -PollSeconds $PollSeconds -MaxPolls $MaxIdlePolls
        if (-not $attempt.idle_wait.idle) {
            $attempt.exit_code = 1
            $attempt.error = $attempt.idle_wait.error
            $result.jobs_attempted += $attempt
            break
        }

        $runOutput = & powershell -ExecutionPolicy Bypass -File $RunMissingScript `
            -WorkflowResultPath $runtimeWorkflowResultPath `
            -PanelIds $job.panel_id `
            -RetryCount $RetryCount `
            -CooldownSeconds $CooldownSeconds `
            -MaxPolls $MaxPromptPolls

        $attempt.exit_code = $LASTEXITCODE
        $attempt.run_summary = Get-PanelRunSummary -Output @($runOutput)
        $attempt.output_line_count = @($runOutput).Count
        $attempt.completed = ($LASTEXITCODE -eq 0)
        if (-not $attempt.completed) {
            $attempt.error = "Panel run failed. Inspect output and manifests\comic_runs for details."
            $lastErrors = @()
            foreach ($run in @($attempt.run_summary.runs)) {
                if ($run.last_error) {
                    $lastErrors += [string]$run.last_error
                }
            }
            $waitingReason = Get-WaitingReasonFromErrors -Errors $lastErrors
            if ($waitingReason) {
                $attempt.waiting_reason = $waitingReason
                $attempt.error = "Panel run is waiting on image API $waitingReason."
            }
        }
        $result.jobs_attempted += $attempt
        $touchedPages[$job.page_id] = $job

        if (-not $attempt.completed -and $CooldownSeconds -gt 0 -and $jobIndex -lt $jobs.Count) {
            Start-Sleep -Seconds $CooldownSeconds
        }
    }

    if (-not $DryRun -and -not $SkipAssembly) {
        foreach ($pageId in $touchedPages.Keys) {
            $job = $touchedPages[$pageId]
            $assemblyManifest = Get-AssemblyManifestPath -PlanPath $job.plan_path
            $assemblyOutput = & powershell -ExecutionPolicy Bypass -File $AssembleScript `
                -PlanPath $job.plan_path `
                -WorkflowResultPath $job.workflow_result_path `
                -ManifestPath $assemblyManifest

            $assemblySummary = Get-AssemblySummary -ManifestPath $assemblyManifest -ExitCode $LASTEXITCODE
            $result.pages_assembled += [ordered]@{
                page_id = $pageId
                assembly_manifest = $assemblySummary.assembly_manifest
                exit_code = $assemblySummary.exit_code
                status = $assemblySummary.status
                assembly_ok = $assemblySummary.assembly_ok
                lettering_items = $assemblySummary.lettering_items
                missing_panels = $assemblySummary.missing_panels
                output_line_count = @($assemblyOutput).Count
            }
        }

        $statusOutputAfter = & powershell -ExecutionPolicy Bypass -File $StatusScript `
            -EpisodePlanPath $EpisodePlanPath `
            -OutputJson $StatusPath `
            -OutputMarkdown $StatusMarkdownPath
        $result.status_refresh.after_run_exit_code = $LASTEXITCODE
        $result.status_refresh.after_run_output_line_count = @($statusOutputAfter).Count
        if (Test-Path -LiteralPath $StatusPath) {
            $statusAfter = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $result.status_refresh.after_summary = $statusAfter.summary
        }
    }

    $failedRuns = @($result.jobs_attempted | Where-Object { -not $_.skipped -and -not $_.completed })
    $rateLimitRuns = @($failedRuns | Where-Object { $_.waiting_reason -eq "rate_limit" })
    $upstreamErrorRuns = @($failedRuns | Where-Object { $_.waiting_reason -eq "upstream_error" })
    $hardFailedRuns = @($failedRuns | Where-Object { $_.waiting_reason -ne "rate_limit" -and $_.waiting_reason -ne "upstream_error" })
    $assemblyFailures = @($result.pages_assembled | Where-Object { $_.status -eq "failed" })
    $result.waiting_for_panels = @($result.pages_assembled | Where-Object { $_.status -eq "waiting_missing_panels" }).Count
    $result.waiting_rate_limit = $rateLimitRuns.Count
    $result.waiting_upstream_error = $upstreamErrorRuns.Count
    $result.waiting = ($result.waiting_rate_limit -gt 0 -or $result.waiting_upstream_error -gt 0)
    $result.completed = ($hardFailedRuns.Count -eq 0 -and $assemblyFailures.Count -eq 0 -and -not $result.waiting)
} catch {
    $result.error = $_.Exception.Message
} finally {
    New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
    $result | ConvertTo-Json -Depth 30 | Set-Content -Path $ResultPath -Encoding UTF8
    $result | ConvertTo-Json -Depth 30
}

if (-not $result.completed -and -not $result.waiting -and -not $DryRun) {
    exit 1
}
