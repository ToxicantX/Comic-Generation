param(
    [switch]$Build,
    [switch]$SkipHealthCheck,
    [switch]$SkipGenerationBackend,
    [ValidateSet("direct_api", "comfyui")]
    [string]$ImageBackend = "direct_api",
    [string]$ComfyRoot = "G:\ComfyUI",
    [string]$ComfyUrl = "http://127.0.0.1:8188"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Docker {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw "Docker is not installed or not in PATH. Install Docker Desktop first."
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running."
    }
}

function Copy-ExampleIfMissing {
    param(
        [string]$ExamplePath,
        [string]$TargetPath,
        [string]$Label
    )
    if (Test-Path -LiteralPath $TargetPath) {
        Write-Host "$Label exists: $TargetPath"
        return
    }
    if (-not (Test-Path -LiteralPath $ExamplePath)) {
        throw "$Label example not found: $ExamplePath"
    }
    Copy-Item -LiteralPath $ExamplePath -Destination $TargetPath
    Write-Host "$Label created from example: $TargetPath"
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )
    $lines = if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path) } else { @() }
    $prefix = "$Key="
    $found = $false
    $updated = @($lines | ForEach-Object {
        if ($_.StartsWith($prefix)) {
            $found = $true
            "$prefix$Value"
        } else {
            $_
        }
    })
    if (-not $found) {
        $updated += "$prefix$Value"
    }
    $updated | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-PortListening {
    param([int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return @($connections).Count -gt 0
}

function Test-HttpReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Start-GenerationBackend {
    if ($ImageBackend -ne "comfyui") {
        Write-Host "Direct image API selected; ComfyUI autostart is not required."
        return
    }
    if ($SkipGenerationBackend) {
        Write-Host "Generation backend autostart skipped."
        return
    }
    if (Test-HttpReady -Url $ComfyUrl) {
        Write-Host "Generation backend already running: $ComfyUrl"
        return
    }

    $mainPy = Join-Path $ComfyRoot "main.py"
    if (-not (Test-Path -LiteralPath $mainPy)) {
        Write-Warning "Generation backend entry not found: $mainPy"
        return
    }
    $pythonExe = Join-Path $ComfyRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = "python"
    }

    $logDir = Join-Path $root "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdout = Join-Path $logDir "generation-backend.out.log"
    $stderr = Join-Path $logDir "generation-backend.err.log"
    $backendPort = ([Uri]$ComfyUrl).Port

    Write-Host "Starting generation backend: $ComfyUrl"
    Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($mainPy, "--listen", "0.0.0.0", "--port", [string]$backendPort) `
        -WorkingDirectory $ComfyRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-HttpReady -Url $ComfyUrl) {
            Write-Host "Generation backend ready: $ComfyUrl"
            return
        }
    }
    Write-Warning "Generation backend did not respond within 90 seconds. Logs: $stdout / $stderr"
}

Set-Location $root
Test-Docker

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\.env.docker.example") `
    -TargetPath (Join-Path $root "config\.env.docker") `
    -Label "Docker config"

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\text.env.example") `
    -TargetPath (Join-Path $root "config\text.env") `
    -Label "Text API config"

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\image.env.example") `
    -TargetPath (Join-Path $root "config\image.env") `
    -Label "Image API config"

$dockerConfigPath = Join-Path $root "config\.env.docker"
$containerOutputRoot = if ($ImageBackend -eq "comfyui") { "/comfyui/output" } else { "/app/output" }
Set-EnvValue -Path $dockerConfigPath -Key "COMIC_PIPELINE_IMAGE_BACKEND" -Value $ImageBackend
Set-EnvValue -Path $dockerConfigPath -Key "COMIC_PIPELINE_COMFY_ROOT" -Value "/comfyui"
Set-EnvValue -Path $dockerConfigPath -Key "COMIC_PIPELINE_COMFY_URL" -Value "http://host.docker.internal:$(([Uri]$ComfyUrl).Port)"
Set-EnvValue -Path $dockerConfigPath -Key "COMIC_PIPELINE_COMFY_OUTPUT_ROOT" -Value $containerOutputRoot
Set-EnvValue -Path $dockerConfigPath -Key "COMIC_PIPELINE_OUTPUT_ROOT" -Value "$containerOutputRoot/ComicPipeline"

Start-GenerationBackend

$existingConsole = docker ps --format "{{.Names}}" | Where-Object { $_ -eq "comic-pipeline-console" }
if (-not $existingConsole -and (Test-PortListening -Port 8199)) {
    throw "Port 8199 is already in use. Stop the existing local console first, then run this script again."
}

$composeArgs = @("compose", "-f", (Join-Path $root "docker-compose.yml"))
if ($ImageBackend -eq "comfyui") {
    $env:COMIC_PIPELINE_HOST_COMFY_ROOT = $ComfyRoot.Replace("\", "/")
    $composeArgs += @("-f", (Join-Path $root "docker-compose.comfyui.yml"))
}
$composeArgs += @("up", "-d")
if ($Build) {
    $composeArgs += "--build"
}

docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

Write-Host ""
Write-Host "Console URL: http://127.0.0.1:8199"
Write-Host "PostgreSQL URL from host: postgresql://comic_pipeline:comic_pipeline@127.0.0.1:55432/comic_pipeline"
Write-Host "Image backend: $ImageBackend"
if ($ImageBackend -eq "comfyui") {
    Write-Host "ComfyUI backend expected at: $ComfyUrl"
}
Write-Host ""

if (-not $SkipHealthCheck) {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8199/" -UseBasicParsing -TimeoutSec 2
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500) {
                Write-Host "Console health check passed."
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Warning "Console did not respond within 45 seconds. Check logs with: docker compose logs --tail=100 comic-console"
}
