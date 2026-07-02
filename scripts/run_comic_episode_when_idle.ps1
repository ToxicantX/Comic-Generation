param(
    [int]$EpisodeNumber = 3,
    [string]$EpisodePlanPath = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [int]$MaxPanels = 1,
    [int]$PollSeconds = 30,
    [int]$MaxPolls = 120,
    [int]$RequiredIdlePolls = 2,
    [int]$LongRunningQueueSeconds = 300,
    [int]$RetryCount = 0,
    [int]$CooldownSeconds = 240,
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_when_idle_run.json",
    [string]$PipelineResultPath = ""
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) { $ComfyUrl = $comicConfig.ComfyUrl }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_episode_when_idle_run.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_episode_when_idle_run.json" }

function Get-QueueSnapshot {
    param([string]$Url)

    $queue = Invoke-RestMethod -Uri "$Url/queue" -TimeoutSec 10
    $jobs = @()
    foreach ($stateName in @("queue_running", "queue_pending")) {
        foreach ($item in @($queue.$stateName)) {
            $extra = if (@($item).Count -gt 3) { $item[3] } else { $null }
            $ageSeconds = $null
            if ($extra -and $extra.create_time) {
                $ageSeconds = [Math]::Max(0, [int](([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - [int64]$extra.create_time) / 1000))
            }
            $jobs += [ordered]@{
                queue_state = $stateName
                prompt_id = if (@($item).Count -gt 1) { [string]$item[1] } else { $null }
                client_id = if ($extra) { [string]$extra.client_id } else { "" }
                create_time = if ($extra) { $extra.create_time } else { $null }
                age_seconds = $ageSeconds
            }
        }
    }

    return [ordered]@{
        running = @($queue.queue_running).Count
        pending = @($queue.queue_pending).Count
        jobs = $jobs
    }
}

if (-not $PipelineResultPath) {
    $PipelineResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_episode$($EpisodeNumber.ToString("00"))_when_idle_pipeline_run.json"
}
if ($RequiredIdlePolls -lt 1) {
    $RequiredIdlePolls = 1
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    episode_number = $EpisodeNumber
    episode_plan_path = $EpisodePlanPath
    comfy_url = $ComfyUrl
    max_panels = $MaxPanels
    required_idle_polls = $RequiredIdlePolls
    long_running_queue_seconds = $LongRunningQueueSeconds
    consecutive_idle_polls = 0
    long_running_queue_items = @()
    status = "waiting"
    polls = @()
    pipeline_result_path = $PipelineResultPath
    pipeline_exit_code = $null
    pipeline_summary = $null
    waiting_reason = ""
    waiting_detail = $null
    resumable = $true
    next_action = "wait_for_idle"
    error = $null
}

try {
    $consecutiveIdlePolls = 0
    for ($i = 1; $i -le $MaxPolls; $i++) {
        $snapshot = Get-QueueSnapshot -Url $ComfyUrl
        $longRunningItems = @($snapshot.jobs | Where-Object { $_.age_seconds -ne $null -and $_.age_seconds -ge $LongRunningQueueSeconds })
        if ($longRunningItems.Count -gt 0) {
            $result.long_running_queue_items = $longRunningItems
        }
        $isIdle = $snapshot.running -eq 0 -and $snapshot.pending -eq 0
        if ($isIdle) {
            $consecutiveIdlePolls += 1
        } else {
            $consecutiveIdlePolls = 0
        }
        $result.consecutive_idle_polls = $consecutiveIdlePolls
        $result.polls += [ordered]@{
            poll = $i
            time = (Get-Date).ToString("s")
            running = $snapshot.running
            pending = $snapshot.pending
            idle = $isIdle
            consecutive_idle_polls = $consecutiveIdlePolls
            long_running_queue_items = $longRunningItems
            jobs = $snapshot.jobs
        }

        if ($consecutiveIdlePolls -ge $RequiredIdlePolls) {
            $argsList = @(
                (Join-Path $PSScriptRoot "run_comic_episode_pipeline.ps1"),
                "-ComfyUrl", $ComfyUrl,
                "-GenerateImages",
                "-OnlyStage", "comfy_health,anchor_assets,anchor_gate,draft_qa,generate_panels,assemble_pages,status_report,lettering_qa,consistency_qa",
                "-MaxPanels", $MaxPanels,
                "-RunLetteringQa",
                "-RunConsistencyQa",
                "-ResultPath", $PipelineResultPath,
                "-RetryCount", $RetryCount,
                "-CooldownSeconds", $CooldownSeconds
            )
            if ($EpisodeNumber -gt 0) {
                $argsList += @("-EpisodeNumber", $EpisodeNumber)
            }
            if ($EpisodePlanPath) {
                $argsList += @("-EpisodePlanPath", $EpisodePlanPath)
            }

            $result.status = "running_pipeline"
            $pipelineOutput = & powershell -ExecutionPolicy Bypass -File @argsList
            $result.pipeline_exit_code = $LASTEXITCODE
            $result.pipeline_output_line_count = @($pipelineOutput).Count
            if (Test-Path -LiteralPath $PipelineResultPath) {
                $pipeline = Get-Content -LiteralPath $PipelineResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $result.pipeline_summary = [ordered]@{
                    completed = [bool]$pipeline.completed
                    blocked = [bool]$pipeline.blocked
                    waiting = [bool]$pipeline.waiting
                    partial = [bool]$pipeline.partial
                    waiting_reason = [string]$pipeline.waiting_reason
                    waiting_detail = $pipeline.waiting_detail
                    summary = $pipeline.summary
                }
                $result.waiting_reason = [string]$pipeline.waiting_reason
                $result.waiting_detail = $pipeline.waiting_detail
                if ($pipeline.completed) {
                    $result.status = "success"
                    $result.resumable = $false
                    $result.next_action = "none"
                } elseif ($pipeline.partial) {
                    $result.status = "partial_after_pipeline"
                    $result.resumable = $true
                    $result.next_action = "rerun_to_generate_next_batch"
                } elseif ($pipeline.waiting) {
                    $result.status = "waiting_after_pipeline"
                    $result.resumable = $true
                    if ($pipeline.waiting_reason -eq "queue_busy" -or $pipeline.waiting_reason -eq "idle_timeout") {
                        $result.next_action = "rerun_after_queue_clears"
                    } elseif ($pipeline.waiting_reason -eq "rate_limit") {
                        $result.next_action = "rerun_after_rate_limit_clears"
                    } elseif ($pipeline.waiting_reason -eq "upstream_error") {
                        $result.next_action = "rerun_after_upstream_recovers"
                    } else {
                        $result.next_action = "rerun_after_queue_or_rate_limit_clears"
                    }
                } elseif ($pipeline.blocked) {
                    $result.status = "blocked_after_pipeline"
                    $result.resumable = $false
                    $result.next_action = "inspect_pipeline_result"
                } else {
                    $result.status = "pipeline_failed"
                    $result.resumable = $false
                    $result.next_action = "inspect_pipeline_result"
                }
            } else {
                $result.status = "pipeline_missing_result"
                $result.resumable = $false
                $result.next_action = "inspect_pipeline_invocation"
                $result.error = "Pipeline result was not created."
            }
            break
        }

        if ($i -lt $MaxPolls) {
            Start-Sleep -Seconds $PollSeconds
        }
    }

    if ($result.status -eq "waiting") {
        $result.status = "timeout_waiting_for_idle"
        $result.resumable = $true
        $result.waiting_reason = "idle_timeout"
        $result.waiting_detail = [ordered]@{
            required_idle_polls = $RequiredIdlePolls
            max_polls = $MaxPolls
            consecutive_idle_polls = $result.consecutive_idle_polls
            last_poll = if (@($result.polls).Count -gt 0) { @($result.polls)[-1] } else { $null }
            long_running_queue_items = $result.long_running_queue_items
        }
        $result.next_action = "rerun_after_queue_clears"
        $result.error = "ComfyUI did not stay idle for $RequiredIdlePolls consecutive poll(s) within $MaxPolls poll(s)."
    }
} catch {
    $result.status = "exception"
    $result.resumable = $false
    $result.next_action = "inspect_wrapper_error"
    $result.error = $_.Exception.Message
} finally {
    New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
    $result | ConvertTo-Json -Depth 30 | Set-Content -Path $ResultPath -Encoding UTF8
    $result | ConvertTo-Json -Depth 30
}

if ($result.status -in @("pipeline_failed", "pipeline_missing_result", "blocked_after_pipeline", "timeout_waiting_for_idle", "exception")) {
    exit 1
}
