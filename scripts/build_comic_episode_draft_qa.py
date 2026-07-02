import argparse
import json
import os
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or SCRIPT_DIR.parent)
OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or r"G:\ComfyUI\output")
RISK_TERMS = ["神农生死之别", "回忆", "昨日", "半日至交", "想起神农", "神农赠送之物"]
PROHIBITED_PROMPT_TERMS = ["text in image", "speech bubble", "caption in image"]
PROHIBITED_NEGATED_TERMS = ["watermark", "logo"]
KEY_CHARACTER_ALIASES = {
    "拓拔野": "tuobaye_turnaround",
    "白龙鹿": "bailonglu_reference",
    "神农": "shennong_turnaround",
    "黑衣少年": "shisilang_turnaround",
    "朝阳谷十四郎": "shisilang_turnaround",
    "十四郎": "shisilang_turnaround",
    "黑衣老者": "green_eyed_elder_turnaround",
    "枯瘦老者": "green_eyed_elder_turnaround",
    "科沙度": "green_eyed_elder_turnaround",
    "段聿铠": "duanyukai_turnaround",
    "段狂": "duanyukai_turnaround",
    "青衣大汉": "duanyukai_turnaround",
    "幻电玄蛇": "huandian_xuanshe_reference",
    "玄蛇": "huandian_xuanshe_reference",
    "白衣女子": "white_clothed_woman_reference",
    "仙女姐姐": "white_clothed_woman_reference",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-review", required=True)
    parser.add_argument("--episode-plan", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    review_path = Path(args.draft_review)
    review = read_json(review_path)
    episode_plan = read_json(Path(args.episode_plan)) if args.episode_plan and Path(args.episode_plan).is_file() else {}
    asset_aliases = episode_plan.get("asset_aliases", {})

    pages = []
    approved_panels = []
    blocked_panels = []
    warning_panels = []
    for page in review.get("pages", []):
        page_result = {"page_id": page.get("page_id"), "panels": []}
        for panel in page.get("panels", []):
            result = check_panel(page, panel, asset_aliases)
            page_result["panels"].append(result)
            if result["approval_status"] == "approved_to_submit":
                approved_panels.append(result["panel_id"])
            elif result["approval_status"] == "blocked":
                blocked_panels.append(result["panel_id"])
            else:
                warning_panels.append(result["panel_id"])
        pages.append(page_result)

    qa = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "draft_review": str(review_path),
        "episode_id": review.get("episode_id"),
        "episode_title": review.get("episode_title"),
        "summary": {
            "pages": len(pages),
            "panels": sum(len(page["panels"]) for page in pages),
            "approved_to_submit": len(approved_panels),
            "warnings": len(warning_panels),
            "blocked": len(blocked_panels),
        },
        "approved_panel_ids": approved_panels,
        "warning_panel_ids": warning_panels,
        "blocked_panel_ids": blocked_panels,
        "pages": pages,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(build_markdown(qa), encoding="utf-8")
    print(json.dumps(qa["summary"], ensure_ascii=False, indent=2))
    return 0


def check_panel(page: dict, panel: dict, asset_aliases: dict) -> dict:
    issues = []
    warnings = []
    prompt = panel.get("full_prompt") or panel.get("prompt", "")
    workflow = Path(panel.get("workflow") or "")
    expected = Path(panel.get("expected_panel_path") or "")
    reference_alias = panel.get("reference_alias") or ""
    reference_image = panel.get("reference_image") or ""

    if not prompt.strip():
        issues.append("missing_prompt")
    if len(prompt) < 80:
        warnings.append("short_prompt")
    if len(prompt) > 900:
        warnings.append("long_prompt")
    lowered = prompt.lower()
    for term in PROHIBITED_PROMPT_TERMS:
        if term in lowered:
            issues.append(f"prohibited_prompt_term:{term}")
    for term in PROHIBITED_NEGATED_TERMS:
        if term in lowered and f"no {term}" not in lowered:
            issues.append(f"prohibited_prompt_term:{term}")
    if "no baked-in text" not in lowered and "no text" not in lowered:
        warnings.append("missing_no_text_instruction")

    if not workflow.is_file():
        issues.append("missing_workflow_file")
    if not str(expected):
        issues.append("missing_expected_panel_path")
    elif expected.is_file():
        warnings.append("output_already_exists")

    if reference_alias and reference_alias not in asset_aliases:
        issues.append(f"unknown_reference_alias:{reference_alias}")
    if reference_alias and reference_alias in asset_aliases and not reference_image:
        issues.append(f"reference_alias_not_resolved:{reference_alias}")
    if reference_image and not Path(reference_image).is_file():
        issues.append(f"missing_reference_file:{reference_alias or reference_image}")
    for character, required_alias in KEY_CHARACTER_ALIASES.items():
        if character in prompt and not reference_alias:
            warnings.append(f"missing_key_character_reference:{character}")
        if character in prompt and reference_alias == required_alias and not reference_image:
            warnings.append(f"missing_key_character_reference:{character}")

    risk = memory_character_risk(page, panel)
    if risk:
        warnings.append(risk)

    if page.get("needs_human_review"):
        warnings.append("page_marked_needs_human_review")

    if issues:
        approval_status = "blocked"
    elif warnings:
        approval_status = "needs_review"
    else:
        approval_status = "approved_to_submit"

    return {
        "panel_id": panel.get("panel_id"),
        "page_id": page.get("page_id"),
        "approval_status": approval_status,
        "issues": issues,
        "warnings": warnings,
        "workflow": str(workflow) if str(workflow) else "",
        "expected_panel_path": str(expected) if str(expected) else "",
        "reference_alias": reference_alias,
        "reference_image": reference_image,
        "prompt_chars": len(prompt),
    }


def memory_character_risk(page: dict, panel: dict) -> str:
    excerpt = page.get("source_excerpt", "")
    prompt = panel.get("prompt", "")
    title = panel.get("title", "")
    current_scene_markers = ["赠送之物", "想起神农", "生死之别", "昨日", "回忆"]
    prompt_mentions_memory = any(marker in prompt for marker in current_scene_markers)
    if "神农" in prompt and any(term in excerpt for term in RISK_TERMS) and "神农" not in title:
        return "possible_memory_character_in_prompt:神农"
    if prompt_mentions_memory and "神农" in prompt and "神农" not in title:
        return "possible_memory_character_in_prompt:神农"
    return ""


def build_markdown(qa: dict) -> str:
    lines = [
        f"# {qa.get('episode_id')} Draft QA",
        "",
        f"- Updated: {qa.get('updated')}",
        f"- Title: {qa.get('episode_title', '')}",
        f"- Approved: {qa['summary']['approved_to_submit']}",
        f"- Needs review: {qa['summary']['warnings']}",
        f"- Blocked: {qa['summary']['blocked']}",
        "",
    ]
    for page in qa.get("pages", []):
        lines.extend([f"## {page.get('page_id')}", ""])
        for panel in page.get("panels", []):
            lines.extend(
                [
                    f"### {panel['panel_id']}",
                    "",
                    f"- Status: `{panel['approval_status']}`",
                    f"- Issues: `{', '.join(panel['issues']) if panel['issues'] else 'none'}`",
                    f"- Warnings: `{', '.join(panel['warnings']) if panel['warnings'] else 'none'}`",
                    f"- Prompt chars: {panel['prompt_chars']}",
                    f"- Workflow: `{panel.get('workflow', '')}`",
                    f"- Expected: `{panel.get('expected_panel_path', '')}`",
                    f"- Reference alias: `{panel.get('reference_alias', '')}`",
                    f"- Reference image: `{panel.get('reference_image', '')}`",
                    "",
                ]
            )
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
