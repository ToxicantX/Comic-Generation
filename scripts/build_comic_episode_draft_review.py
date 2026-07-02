import argparse
import json
import os
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or SCRIPT_DIR.parent)
COMFY_OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or r"G:\ComfyUI\output")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-plan", required=True)
    parser.add_argument("--page-plan-result", required=True)
    parser.add_argument("--workflow-create-result", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    episode_plan_path = Path(args.episode_plan)
    page_plan_result_path = Path(args.page_plan_result)
    workflow_create_result_path = Path(args.workflow_create_result) if args.workflow_create_result else None

    episode = read_json(episode_plan_path)
    page_plan_result = read_json(page_plan_result_path)
    workflow_create_result = read_json(workflow_create_result_path) if workflow_create_result_path and workflow_create_result_path.is_file() else {}

    workflow_by_page = workflow_result_by_page(workflow_create_result)
    pages = []
    for item in page_plan_result.get("created", []):
        plan_path = Path(item.get("plan_path", ""))
        if not plan_path.is_file():
            continue
        page_plan = read_json(plan_path)
        workflow_result_path = workflow_by_page.get(page_plan.get("page_id")) or default_workflow_result_path(page_plan.get("page_id", ""))
        workflow_result = read_json(workflow_result_path) if workflow_result_path.is_file() else {"created": []}
        pages.append(build_page_review(page_plan, plan_path, workflow_result_path, workflow_result))

    review = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_plan": str(episode_plan_path),
        "episode_id": episode.get("episode_id"),
        "episode_title": episode.get("episode_title"),
        "adaptation_status": episode.get("adaptation_status"),
        "chapter_brief": episode.get("chapter_brief"),
        "summary": {
            "pages": len(pages),
            "panels": sum(len(page["panels"]) for page in pages),
            "workflow_panels": sum(page["workflow_panel_count"] for page in pages),
            "pages_needing_human_review": len([page for page in pages if page.get("needs_human_review")]),
        },
        "pages": pages,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(build_markdown(review), encoding="utf-8")
    print(json.dumps(review["summary"], ensure_ascii=False, indent=2))
    return 0


def build_page_review(page_plan: dict, plan_path: Path, workflow_result_path: Path, workflow_result: dict) -> dict:
    workflow_by_panel = {item.get("panel_id"): item for item in workflow_result.get("created", [])}
    global_prompt = page_plan.get("global_prompt_block", "")
    panels = []
    for panel in page_plan.get("panels", []):
        workflow = workflow_by_panel.get(panel.get("panel_id"), {})
        panel_prompt = panel.get("prompt", "")
        full_prompt = "\n\n".join(item for item in [global_prompt, panel_prompt] if item)
        panels.append(
            {
                "panel_id": panel.get("panel_id"),
                "order": panel.get("order"),
                "title": panel.get("title"),
                "reference_alias": panel.get("reference_alias", ""),
                "reference_image": workflow.get("reference_image") or panel.get("reference_image", ""),
                "caption": panel.get("caption", ""),
                "dialogue": panel.get("dialogue", []),
                "prompt": panel_prompt,
                "full_prompt": full_prompt,
                "workflow": workflow.get("workflow"),
                "expected_panel_path": workflow.get("expected_panel_path") or expected_panel_path(panel),
            }
        )

    return {
        "page_id": page_plan.get("page_id"),
        "title": page_plan.get("title"),
        "adaptation_status": page_plan.get("adaptation_status"),
        "needs_human_review": bool(page_plan.get("close_reading_required") or page_plan.get("draft_refined_from_source_excerpt")),
        "plan_path": str(plan_path),
        "workflow_result_path": str(workflow_result_path),
        "workflow_panel_count": len(workflow_result.get("created", [])),
        "detected_characters": page_plan.get("detected_characters", []),
        "detected_locations": page_plan.get("detected_locations", []),
        "summary": page_plan.get("summary", ""),
        "source_excerpt": page_plan.get("source_excerpt", ""),
        "panels": panels,
    }


def workflow_result_by_page(workflow_create_result: dict) -> dict[str, Path]:
    result = {}
    for run in workflow_create_result.get("runs", []):
        page_id = run.get("page_id")
        path = run.get("workflow_result_path")
        if page_id and path:
            result[page_id] = Path(path)
    return result


def default_workflow_result_path(page_id: str) -> Path:
    return WORKSPACE / "manifests" / f"{page_id.lower()}_fallback_workflows.json"


def expected_panel_path(panel: dict) -> str:
    prefix = panel.get("filename_prefix", "")
    return str(COMFY_OUTPUT_ROOT / f"{prefix}_00001_.png") if prefix else ""


def build_markdown(review: dict) -> str:
    lines = [
        f"# {review.get('episode_id')} Draft Review",
        "",
        f"- Updated: {review.get('updated')}",
        f"- Title: {review.get('episode_title', '')}",
        f"- Adaptation status: `{review.get('adaptation_status', '')}`",
        f"- Chapter brief: `{review.get('chapter_brief', '')}`",
        f"- Pages: {review['summary']['pages']}",
        f"- Panels: {review['summary']['panels']}",
        f"- Workflow panels: {review['summary']['workflow_panels']}",
        "",
        "## Review Checklist",
        "",
        "- [ ] Page beats match source excerpt",
        "- [ ] Character presence is correct in every panel",
        "- [ ] Locations and props match continuity",
        "- [ ] Captions/dialogue are concise and not baked into art",
        "- [ ] Prompt is safe to submit to image workflow",
        "",
    ]
    for page in review.get("pages", []):
        lines.extend(
            [
                f"## {page['page_id']} - {page.get('title', '')}",
                "",
                f"- Status: `{page.get('adaptation_status', '')}`",
                f"- Plan: `{page.get('plan_path', '')}`",
                f"- Workflows: `{page.get('workflow_result_path', '')}`",
                f"- Detected characters: {', '.join(page.get('detected_characters') or []) or 'none'}",
                f"- Detected locations: {', '.join(page.get('detected_locations') or []) or 'none'}",
                "",
                "### Source Summary",
                "",
                page.get("summary", ""),
                "",
                "### Source Excerpt",
                "",
                blockquote(trim_text(page.get("source_excerpt", ""), 900)),
                "",
                "### Panels",
                "",
            ]
        )
        for panel in page.get("panels", []):
            dialogue = "; ".join(
                f"{item.get('speaker', '')}: {item.get('text', '')}".strip(": ")
                for item in panel.get("dialogue", [])
            )
            lines.extend(
                [
                    f"#### {panel.get('panel_id')} - {panel.get('title', '')}",
                    "",
                    f"- Reference alias: `{panel.get('reference_alias', '')}`",
                    f"- Reference image: `{panel.get('reference_image', '')}`",
                    f"- Caption: {panel.get('caption', '') or 'none'}",
                    f"- Dialogue: {dialogue or 'none'}",
                    f"- Expected image: `{panel.get('expected_panel_path', '')}`",
                    f"- Workflow: `{panel.get('workflow', '')}`",
                    "",
                    "Prompt:",
                    "",
                    f"> {panel.get('prompt', '')}",
                    "",
                    "- [ ] approve panel",
                    "- [ ] revise prompt",
                    "",
                ]
            )
    return "\n".join(lines)


def trim_text(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."


def blockquote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
