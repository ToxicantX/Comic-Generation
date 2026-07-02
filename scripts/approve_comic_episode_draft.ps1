param(
    [string]$QaJson = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_qa.json",
    [string]$PageIds = "SSJ_COMIC_EP02_P001",
    [string]$OutputJson = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_draft_approval.json",
    [string]$Reviewer = "codex_auto_review",
    [string]$Note = "Approved after QA showed no blocking issues or memory-character continuity warnings."
)

$python = "python"
& $python "E:\workspace\ComfyUIProjects\scripts\approve_comic_episode_draft.py" `
    --qa-json $QaJson `
    --page-ids $PageIds `
    --output-json $OutputJson `
    --reviewer $Reviewer `
    --note $Note
exit $LASTEXITCODE
