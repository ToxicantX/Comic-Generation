param(
    [string]$ContainerName = "comic-pipeline-postgres",
    [string]$Database = "comic_pipeline",
    [string]$User = "comic_pipeline",
    [string]$Password = "comic_pipeline",
    [int]$Port = 54329,
    [string]$VolumeName = "comic-pipeline-postgres-data"
)

$ErrorActionPreference = "Stop"

function Test-Docker {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw "Docker is not installed or not in PATH. Install Docker Desktop, or configure COMIC_PIPELINE_DATABASE_URL manually."
    }
}

function Test-ContainerRunning {
    param([string]$Name)
    $names = docker ps --format "{{.Names}}"
    return @($names | Where-Object { $_ -eq $Name }).Count -gt 0
}

function Test-ContainerExists {
    param([string]$Name)
    $names = docker ps -a --format "{{.Names}}"
    return @($names | Where-Object { $_ -eq $Name }).Count -gt 0
}

Test-Docker

if (Test-ContainerRunning -Name $ContainerName) {
    Write-Host "PostgreSQL already running: $ContainerName"
} elseif (Test-ContainerExists -Name $ContainerName) {
    Write-Host "Starting PostgreSQL container: $ContainerName"
    docker start $ContainerName | Out-Null
} else {
    Write-Host "Creating PostgreSQL container: $ContainerName"
    docker volume create $VolumeName | Out-Null
    docker run -d `
        --name $ContainerName `
        -e POSTGRES_DB=$Database `
        -e POSTGRES_USER=$User `
        -e POSTGRES_PASSWORD=$Password `
        -p "${Port}:5432" `
        -v "${VolumeName}:/var/lib/postgresql/data" `
        postgres:16 | Out-Null
}

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    try {
        $ready = docker exec $ContainerName pg_isready -U $User -d $Database
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL ready: postgresql://${User}:***@127.0.0.1:${Port}/${Database}"
            exit 0
        }
    } catch {
    }
    Start-Sleep -Seconds 1
}

throw "PostgreSQL container started but was not ready within 45 seconds."
