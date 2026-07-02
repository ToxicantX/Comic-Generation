param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [string]$OutputPath = ""
)

$python = "python"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$args = @(
    "E:\workspace\ComfyUIProjects\scripts\refine_comic_page_plan_from_excerpt.py",
    "--plan", $PlanPath
)
if ($OutputPath) {
    $args += @("--output", $OutputPath)
}

& $python @args
exit $LASTEXITCODE
