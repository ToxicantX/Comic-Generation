import json
import os
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or SCRIPT_DIR.parent)
COMFY_OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or r"G:\ComfyUI\output")
OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_OUTPUT_ROOT") or (COMFY_OUTPUT_ROOT / "ComicPipeline"))
DEFAULT_EPISODE = WORKSPACE / "manifests" / "ssj_comic_episode01_pages.json"
DEFAULT_OUTPUT_JSON = WORKSPACE / "manifests" / "ssj_comic_episode01_status.json"
DEFAULT_OUTPUT_MD = OUTPUT_ROOT / "review_packages" / "SSJ_COMIC_EP01_status.md"


def main() -> int:
    episode_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EPISODE
    output_json = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_JSON
    output_md = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT_MD

    episode = read_json(episode_path)
    pages = []
    for page in episode.get("pages", []):
        pages.append(build_page_status(page))

    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_plan": str(episode_path),
        "episode_id": episode.get("episode_id"),
        "episode_title": episode.get("episode_title"),
        "summary": summarize_pages(pages),
        "pages": pages,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(build_markdown(status), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def build_page_status(page: dict) -> dict:
    page_id = page.get("page_id", "")
    plan_path = Path(page.get("plan") or WORKSPACE / "manifests" / f"{page_id.lower()}_plan.json")
    workflow_path = first_existing(
        WORKSPACE / "manifests" / f"{page_id.lower()}_workflows.json",
        WORKSPACE / "manifests" / f"{page_id.lower().replace('_p001', '_page01')}_workflows.json",
    )
    fallback_workflow_path = first_existing(
        WORKSPACE / "manifests" / f"{page_id.lower()}_fallback_workflows.json",
        WORKSPACE / "manifests" / f"{page_id.lower().replace('_p001', '_page01')}_fallback_workflows.json",
    )
    micro_fallback_workflow_path = first_existing(
        WORKSPACE / "manifests" / f"{page_id.lower()}_micro_fallback_workflows.json",
        WORKSPACE / "manifests" / f"{page_id.lower().replace('_p001', '_page01')}_micro_fallback_workflows.json",
    )
    assembly_path = first_existing(
        WORKSPACE / "manifests" / f"{page_id.lower()}_assembly.json",
        WORKSPACE / "manifests" / f"{page_id.lower().replace('_p001', '_page01')}_assembly.json",
    )
    page_image = OUTPUT_ROOT / "pages" / f"{page_id}.png"
    review_markdown = OUTPUT_ROOT / "review_packages" / page_id / "human_review.md"

    plan = read_json(plan_path) if plan_path.is_file() else {}
    assembly = read_json(assembly_path) if assembly_path.is_file() else {"panels": []}
    workflow_candidates = []
    if assembly.get("workflow_result_path"):
        workflow_candidates.append(Path(assembly["workflow_result_path"]))
    workflow_candidates.extend([workflow_path, micro_fallback_workflow_path, fallback_workflow_path])
    active_workflow_path = first_existing(*workflow_candidates)
    workflow_manifests = [
        read_json(path)
        for path in unique_existing_paths(
            workflow_path,
            fallback_workflow_path,
            Path(assembly["workflow_result_path"]) if assembly.get("workflow_result_path") else None,
            micro_fallback_workflow_path,
        )
    ]
    workflows = workflow_manifests[0] if workflow_manifests else {"created": []}

    workflow_by_panel = {}
    for manifest in workflow_manifests:
        for item in manifest.get("created", []):
            workflow_by_panel[item.get("panel_id")] = item
    assembly_by_panel = {item.get("panel_id"): item for item in assembly.get("panels", [])}

    panels = []
    for panel in plan.get("panels", []):
        panel_id = panel.get("panel_id")
        workflow = workflow_by_panel.get(panel_id, {})
        assembly_panel = assembly_by_panel.get(panel_id, {})
        expected_path = Path(
            assembly_panel.get("expected_panel_path")
            or workflow.get("expected_panel_path")
            or panel_expected_path(panel)
        )
        used_path = Path(assembly_panel.get("used_panel_path") or expected_path)
        exists = bool(assembly_panel.get("exists")) or used_path.is_file()
        panels.append(
            {
                "panel_id": panel_id,
                "order": panel.get("order"),
                "title": panel.get("title", ""),
                "exists": exists,
                "expected_panel_path": str(expected_path),
                "used_panel_path": str(used_path),
                "workflow": workflow.get("workflow"),
                "reference_image": workflow.get("reference_image") or panel.get("reference_image", ""),
            }
        )

    missing = [panel["panel_id"] for panel in panels if not panel["exists"]]
    page_status = "complete" if panels and not missing and page_image.is_file() else "incomplete"
    if not plan:
        page_status = "missing_plan"
    elif not workflows.get("created"):
        page_status = "missing_workflows"
    elif not page_image.is_file():
        page_status = "missing_assembly"

    return {
        "page_id": page_id,
        "title": page.get("title", ""),
        "declared_status": page.get("status", ""),
        "status": page_status,
        "plan_path": str(plan_path),
        "workflow_path": str(active_workflow_path),
        "fallback_workflow_path": str(fallback_workflow_path) if fallback_workflow_path.is_file() else None,
        "micro_fallback_workflow_path": str(micro_fallback_workflow_path) if micro_fallback_workflow_path.is_file() else None,
        "assembly_path": str(assembly_path),
        "page_image": str(page_image),
        "review_markdown": str(review_markdown),
        "panel_count": len(panels),
        "generated_panels": len([panel for panel in panels if panel["exists"]]),
        "missing_panels": missing,
        "panels": panels,
    }


def panel_expected_path(panel: dict) -> str:
    prefix = panel.get("filename_prefix", "")
    return str(COMFY_OUTPUT_ROOT / f"{prefix}_00001_.png") if prefix else ""


def first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def unique_existing_paths(*paths: Path | None) -> list[Path]:
    unique = []
    seen = set()
    for path in paths:
        if not path or not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def summarize_pages(pages: list[dict]) -> dict:
    return {
        "total_pages": len(pages),
        "complete_pages": len([page for page in pages if page["status"] == "complete"]),
        "incomplete_pages": len([page for page in pages if page["status"] != "complete"]),
        "total_panels": sum(page["panel_count"] for page in pages),
        "generated_panels": sum(page["generated_panels"] for page in pages),
        "missing_panels": sum(len(page["missing_panels"]) for page in pages),
    }


def build_markdown(status: dict) -> str:
    lines = [
        f"# {status.get('episode_id')} Comic Status",
        "",
        f"- Updated: {status.get('updated')}",
        f"- Title: {status.get('episode_title', '')}",
        f"- Complete pages: {status['summary']['complete_pages']} / {status['summary']['total_pages']}",
        f"- Generated panels: {status['summary']['generated_panels']} / {status['summary']['total_panels']}",
        "",
    ]
    for page in status.get("pages", []):
        lines.extend(
            [
                f"## {page['page_id']} - {page.get('title', '')}",
                "",
                f"- Status: `{page['status']}`",
                f"- Page: `{page['page_image']}`",
                f"- Review: `{page['review_markdown']}`",
                f"- Panels: {page['generated_panels']} / {page['panel_count']}",
                f"- Missing: `{', '.join(page['missing_panels']) if page['missing_panels'] else 'none'}`",
                "",
            ]
        )
        for panel in page.get("panels", []):
            mark = "ok" if panel["exists"] else "missing"
            lines.append(f"- `{mark}` {panel['panel_id']} {panel.get('title', '')}")
        lines.append("")
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
