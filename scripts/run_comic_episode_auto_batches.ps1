param(
    [int]$EpisodeNumber = 3,
    [string]$EpisodePlanPath = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [int]$MaxPanelsPerBatch = 1,
    [int]$MaxBatches = 3,
    [int]$PollSeconds = 30,
    [int]$MaxPolls = 120,
    [int]$RequiredIdlePolls = 2,
    [int]$LongRunningQueueSeconds = 300,
    [int]$IdleTimeoutRetries = 0,
    [int]$IdleRetrySeconds = 60,
    [int]$RateLimitRetries = 0,
    [int]$RateLimitRetrySeconds = 300,
    [int]$UpstreamErrorRetries = 0,
    [int]$UpstreamErrorRetrySeconds = 300,
    [int]$RetryCount = 0,
    [int]$CooldownSeconds = 240,
    [string]$RunLabel = "auto_batch",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\comic_episode_auto_batches.json"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) { $ComfyUrl = $comicConfig.ComfyUrl }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\comic_episode_auto_batches.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\comic_episode_auto_batches.json" }

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-StatusSummary {
    param([string]$Path)
    $status = Read-JsonFile -Path $Path
    if (-not $status) {
        return $null
    }
    return $status.summary
}

function Refresh-EpisodeStatus {
    param(
        [string]$PlanPath,
        [string]$StatusPath,
        [string]$StatusMarkdownPath
    )

    $argsList = @(
        (Join-Path $PSScriptRoot "build_comic_status_report.ps1"),
        "-EpisodePlanPath", $PlanPath,
        "-OutputJson", $StatusPath,
        "-OutputMarkdown", $StatusMarkdownPath
    )
    $output = & powershell -ExecutionPolicy Bypass -File @argsList
    $exitCode = $LASTEXITCODE
    return [ordered]@{
        exit_code = $exitCode
        output_line_count = @($output).Count
        summary = Get-StatusSummary -Path $StatusPath
    }
}

function Copy-Summary {
    param($Summary)
    if (-not $Summary) {
        return $null
    }
    return [ordered]@{
        total_pages = [int]$Summary.total_pages
        complete_pages = [int]$Summary.complete_pages
        incomplete_pages = [int]$Summary.incomplete_pages
        total_panels = [int]$Summary.total_panels
        generated_panels = [int]$Summary.generated_panels
        missing_panels = [int]$Summary.missing_panels
    }
}

if ($EpisodeNumber -le 0 -and -not $EpisodePlanPath) {
    throw "EpisodeNumber or EpisodePlanPath is required."
}
if ($RequiredIdlePolls -lt 1) {
    $RequiredIdlePolls = 1
}
if ($MaxBatches -lt 0) {
    $MaxBatches = 0
}
if ($RateLimitRetries -lt 0) {
    $RateLimitRetries = 0
}
if ($RateLimitRetrySeconds -lt 0) {
    $RateLimitRetrySeconds = 0
}
if ($UpstreamErrorRetries -lt 0) {
    $UpstreamErrorRetries = 0
}
if ($UpstreamErrorRetrySeconds -lt 0) {
    $UpstreamErrorRetrySeconds = 0
}

$episodeToken = if ($EpisodeNumber -gt 0) { "episode$($EpisodeNumber.ToString("00"))" } else { "custom" }
$episodeId = if ($EpisodeNumber -gt 0) { "SSJ_COMIC_EP$($EpisodeNumber.ToString("00"))" } else { "COMIC_EPISODE_CUSTOM" }
$planPath = if ($EpisodePlanPath) { $EpisodePlanPath } else { Join-Path $comicConfig.Workspace "manifests\ssj_comic_$($episodeToken)_pages.json" }
$statusPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_$($episodeToken)_status.json"
$statusMarkdownPath = Join-Path $comicConfig.OutputRoot "review_packages\$($episodeId)_status.md"
$runToken = (Get-Date).ToString("yyyyMMdd_HHmmss")
$runStem = "ssj_comic_$($episodeToken)_$($RunLabel)_$runToken"

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    episode_number = $EpisodeNumber
    episode_plan_path = $planPath
    comfy_url = $ComfyUrl
    max_panels_per_batch = $MaxPanelsPerBatch
    max_batches = $MaxBatches
    required_idle_polls = $RequiredIdlePolls
    long_running_queue_seconds = $LongRunningQueueSeconds
    idle_timeout_retries = $IdleTimeoutRetries
    idle_retry_seconds = $IdleRetrySeconds
    idle_timeouts_seen = 0
    rate_limit_retries = $RateLimitRetries
    rate_limit_retry_seconds = $RateLimitRetrySeconds
    rate_limit_retries_seen = 0
    upstream_error_retries = $UpstreamErrorRetries
    upstream_error_retry_seconds = $UpstreamErrorRetrySeconds
    upstream_error_retries_seen = 0
    attempts = 0
    completed_batches = 0
    status = "running"
    completed = $false
    partial = $false
    waiting = $false
    waiting_reason = ""
    waiting_detail = $null
    blocked = $false
    failed = $false
    resumable = $true
    next_action = "run_next_batch"
    initial_status = $null
    final_status = $null
    batches = @()
    error = $null
}

try {
    $initialRefresh = Refresh-EpisodeStatus -PlanPath $planPath -StatusPath $statusPath -StatusMarkdownPath $statusMarkdownPath
    $currentSummary = $initialRefresh.summary
    $result.initial_status = [ordered]@{
        refresh = $initialRefresh
        summary = Copy-Summary -Summary $currentSummary
    }

    if (-not $currentSummary) {
        throw "Could not read episode status after refresh: $statusPath"
    }

    if ([int]$currentSummary.missing_panels -le 0) {
        $result.status = "success"
        $result.completed = $true
        $result.resumable = $false
        $result.next_action = "none"
    }

    $batch = 1
    while ($batch -le $MaxBatches -and -not $result.completed -and -not $result.waiting -and -not $result.blocked -and -not $result.failed) {
        $result.attempts += 1
        $attemptIndex = [int]$result.attempts
        $beforeSummary = Copy-Summary -Summary $currentSummary
        $wrapperPath = Join-Path $comicConfig.Workspace "manifests\$($runStem)_batch$($batch.ToString("00"))_attempt$($attemptIndex.ToString("00"))_wrapper.json"
        $pipelinePath = Join-Path $comicConfig.Workspace "manifests\$($runStem)_batch$($batch.ToString("00"))_attempt$($attemptIndex.ToString("00"))_pipeline.json"
        $argsList = @(
            (Join-Path $PSScriptRoot "run_comic_episode_when_idle.ps1"),
            "-ComfyUrl", $ComfyUrl,
            "-MaxPanels", $MaxPanelsPerBatch,
            "-PollSeconds", $PollSeconds,
            "-MaxPolls", $MaxPolls,
            "-RequiredIdlePolls", $RequiredIdlePolls,
            "-LongRunningQueueSeconds", $LongRunningQueueSeconds,
            "-RetryCount", $RetryCount,
            "-CooldownSeconds", $CooldownSeconds,
            "-ResultPath", $wrapperPath,
            "-PipelineResultPath", $pipelinePath
        )
        if ($EpisodeNumber -gt 0) {
            $argsList += @("-EpisodeNumber", $EpisodeNumber)
        }
        if ($EpisodePlanPath) {
            $argsList += @("-EpisodePlanPath", $EpisodePlanPath)
        }

        $output = & powershell -ExecutionPolicy Bypass -File @argsList
        $wrapperExitCode = $LASTEXITCODE
        $wrapper = Read-JsonFile -Path $wrapperPath
        $statusRefresh = Refresh-EpisodeStatus -PlanPath $planPath -StatusPath $statusPath -StatusMarkdownPath $statusMarkdownPath
        $currentSummary = $statusRefresh.summary
        $afterSummary = Copy-Summary -Summary $currentSummary
        $generatedDelta = 0
        $missingDelta = 0
        if ($beforeSummary -and $afterSummary) {
            $generatedDelta = [int]$afterSummary.generated_panels - [int]$beforeSummary.generated_panels
            $missingDelta = [int]$afterSummary.missing_panels - [int]$beforeSummary.missing_panels
        }

        $batchRecord = [ordered]@{
            batch = $batch
            attempt = $attemptIndex
            wrapper_path = $wrapperPath
            pipeline_path = $pipelinePath
            wrapper_exit_code = $wrapperExitCode
            wrapper_status = if ($wrapper) { $wrapper.status } else { "missing_wrapper_result" }
            wrapper_next_action = if ($wrapper) { $wrapper.next_action } else { "inspect_wrapper_invocation" }
            wrapper_waiting_reason = if ($wrapper) { $wrapper.waiting_reason } else { "" }
            wrapper_waiting_detail = if ($wrapper) { $wrapper.waiting_detail } else { $null }
            wrapper_summary = if ($wrapper) { $wrapper.pipeline_summary } else { $null }
            output_line_count = @($output).Count
            before_summary = $beforeSummary
            after_summary = $afterSummary
            status_refresh = $statusRefresh
            generated_delta = $generatedDelta
            missing_delta = $missingDelta
        }
        $result.batches += $batchRecord

        if (-not $wrapper) {
            $result.status = "wrapper_missing_result"
            $result.failed = $true
            $result.resumable = $false
            $result.next_action = "inspect_wrapper_invocation"
            break
        }

        if ($wrapper.status -eq "success") {
            $result.status = "success"
            $result.completed = $true
            $result.resumable = $false
            $result.next_action = "none"
            break
        }

        if ($wrapper.status -eq "partial_after_pipeline") {
            if ($generatedDelta -le 0 -and [int]$currentSummary.missing_panels -gt 0) {
                $result.status = "stalled_after_partial"
                $result.partial = $true
                $result.resumable = $true
                $result.next_action = "inspect_latest_batch_then_rerun"
                break
            }
            if ([int]$currentSummary.missing_panels -le 0) {
                $result.status = "success"
                $result.completed = $true
                $result.resumable = $false
                $result.next_action = "none"
                break
            }
            $result.status = "partial"
            $result.partial = $true
            $result.completed_batches = $batch
            $result.next_action = "run_next_batch"
            $batch += 1
            continue
        }

        if ($wrapper.status -eq "waiting_after_pipeline" -or $wrapper.status -eq "timeout_waiting_for_idle") {
            if ($wrapper.status -eq "timeout_waiting_for_idle" -and $result.idle_timeouts_seen -lt $IdleTimeoutRetries) {
                $result.idle_timeouts_seen += 1
                $batchRecord.retry_class = "idle_timeout"
                $batchRecord.retry_number = $result.idle_timeouts_seen
                $batchRecord.retry_wait_seconds = $IdleRetrySeconds
                if ($IdleRetrySeconds -gt 0) {
                    Start-Sleep -Seconds $IdleRetrySeconds
                }
                continue
            }

            $waitingReason = [string]$wrapper.waiting_reason
            if ($wrapper.status -eq "waiting_after_pipeline" -and $waitingReason -eq "rate_limit" -and $result.rate_limit_retries_seen -lt $RateLimitRetries) {
                $result.rate_limit_retries_seen += 1
                $batchRecord.retry_class = "rate_limit"
                $batchRecord.retry_number = $result.rate_limit_retries_seen
                $batchRecord.retry_wait_seconds = $RateLimitRetrySeconds
                if ($RateLimitRetrySeconds -gt 0) {
                    Start-Sleep -Seconds $RateLimitRetrySeconds
                }
                continue
            }

            if ($wrapper.status -eq "waiting_after_pipeline" -and $waitingReason -eq "upstream_error" -and $result.upstream_error_retries_seen -lt $UpstreamErrorRetries) {
                $result.upstream_error_retries_seen += 1
                $batchRecord.retry_class = "upstream_error"
                $batchRecord.retry_number = $result.upstream_error_retries_seen
                $batchRecord.retry_wait_seconds = $UpstreamErrorRetrySeconds
                if ($UpstreamErrorRetrySeconds -gt 0) {
                    Start-Sleep -Seconds $UpstreamErrorRetrySeconds
                }
                continue
            }

            $result.status = $wrapper.status
            $result.waiting = $true
            $result.waiting_reason = $waitingReason
            $result.waiting_detail = $wrapper.waiting_detail
            $result.resumable = $true
            $result.next_action = $wrapper.next_action
            break
        }

        if ($wrapper.status -eq "blocked_after_pipeline") {
            $result.status = $wrapper.status
            $result.blocked = $true
            $result.resumable = $false
            $result.next_action = $wrapper.next_action
            break
        }

        $result.status = $wrapper.status
        $result.failed = $true
        $result.resumable = $false
        $result.next_action = $wrapper.next_action
        break
    }

    if ($result.status -eq "running") {
        $result.status = "max_batches_reached"
        $result.partial = $true
        $result.resumable = $true
        $result.next_action = "rerun_auto_batches"
    } elseif ($result.status -eq "partial" -and @($result.batches).Count -ge $MaxBatches) {
        $result.status = "max_batches_reached"
        $result.resumable = $true
        $result.next_action = "rerun_auto_batches"
    }

    $result.final_status = [ordered]@{
        summary = Copy-Summary -Summary $currentSummary
    }
} catch {
    $result.status = "exception"
    $result.failed = $true
    $result.resumable = $false
    $result.next_action = "inspect_auto_batch_error"
    $result.error = $_.Exception.Message
} finally {
    $result.updated = (Get-Date).ToString("s")
    New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
    $result | ConvertTo-Json -Depth 40 | Set-Content -Path $ResultPath -Encoding UTF8
    $result | ConvertTo-Json -Depth 40
}

if ($result.failed -or $result.blocked -or $result.status -eq "timeout_waiting_for_idle") {
    exit 1
}
