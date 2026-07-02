import argparse
import json
import re
from datetime import datetime
from pathlib import Path


DEFAULT_STATUS = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode03_status.json")
DEFAULT_RESULT = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode03_missing_workflow_size_refresh.json")


def main() -> int:
    args = parse_args()
    status_path = Path(args.status_path)
    result_path = Path(args.result_path)
    status = read_json(status_path)

    plan_cache = {}
    workflow_result_cache = {}
    updated = []
    skipped_generated = []
    skipped_missing_workflow = []

    for page in status.get("pages", []):
        plan_path = Path(page.get("plan_path") or "")
        plan = read_cached_json(plan_path, plan_cache)
        layout_by_panel = {
            panel.get("panel_id"): panel.get("layout", {})
            for panel in plan.get("panels", [])
            if panel.get("panel_id")
        }
        workflow_result_path = find_workflow_result_path(page)
        workflow_result = read_cached_json(workflow_result_path, workflow_result_cache)
        workflow_result_changed = False

        for panel in page.get("panels", []):
            panel_id = panel.get("panel_id", "")
            current_workflow = panel.get("workflow") or ""
            if panel.get("exists"):
                skipped_generated.append(panel_id)
                continue
            if not current_workflow or not Path(current_workflow).is_file():
                skipped_missing_workflow.append(panel_id)
                continue
            layout = layout_by_panel.get(panel_id, {})
            target_size = size_for_layout(layout)
            if not target_size:
                continue
            old_size, changed = update_workflow_size(Path(current_workflow), target_size, dry_run=args.dry_run)
            workflow_item = workflow_item_by_panel(workflow_result, panel_id)
            if workflow_item is not None and workflow_item.get("image_size") != target_size:
                if not args.dry_run:
                    workflow_item["image_size"] = target_size
                workflow_result_changed = True
            updated.append(
                {
                    "panel_id": panel_id,
                    "workflow": current_workflow,
                    "layout": layout,
                    "old_size": old_size,
                    "new_size": target_size,
                    "changed": changed,
                }
            )

        if workflow_result_changed and workflow_result_path.is_file() and not args.dry_run:
            workflow_result["updated"] = datetime.now().isoformat(timespec="seconds")
            workflow_result["auto_image_size"] = True
            workflow_result_path.write_text(json.dumps(workflow_result, ensure_ascii=False, indent=4), encoding="utf-8")

    result = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "status_path": str(status_path),
        "dry_run": args.dry_run,
        "updated_workflows": updated,
        "skipped_generated": skipped_generated,
        "skipped_missing_workflow": skipped_missing_workflow,
        "summary": {
            "updated_workflows": len(updated),
            "changed_workflows": len([item for item in updated if item.get("changed")]),
            "skipped_generated": len(skipped_generated),
            "skipped_missing_workflow": len(skipped_missing_workflow),
        },
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh image sizes only for missing comic panel workflows.")
    parser.add_argument("status_path", nargs="?", default=str(DEFAULT_STATUS))
    parser.add_argument("result_path", nargs="?", default=str(DEFAULT_RESULT))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def find_workflow_result_path(page: dict) -> Path:
    candidates = [
        page.get("workflow_path"),
        page.get("fallback_workflow_path"),
        page.get("micro_fallback_workflow_path"),
    ]
    for candidate in candidates:
        path = Path(candidate or "")
        if path.is_file():
            return path
    return Path("")


def workflow_item_by_panel(workflow_result: dict, panel_id: str) -> dict | None:
    for item in workflow_result.get("created", []):
        if item.get("panel_id") == panel_id:
            return item
    return None


def update_workflow_size(path: Path, target_size: str, dry_run: bool = False) -> tuple[str, bool]:
    workflow = read_json(path)
    old_size = ""
    changed = False
    prompt = workflow.get("prompt", {})
    for node in prompt.values() if isinstance(prompt, dict) else []:
        if not isinstance(node, dict) or node.get("class_type") != "OpenAICompatibleImageGenerate":
            continue
        inputs = node.setdefault("inputs", {})
        old_size = str(inputs.get("size", ""))
        if old_size != target_size:
            inputs["size"] = target_size
            changed = True
    if changed and not dry_run:
        path.write_text(json.dumps(workflow, ensure_ascii=False, indent=4), encoding="utf-8")
    return old_size, changed


def size_for_layout(layout: dict) -> str:
    width = float(layout.get("w", 0) or 0)
    height = float(layout.get("h", 0) or 0)
    if width <= 0 or height <= 0:
        return ""
    ratio = width / height
    if ratio >= 1.25:
        return "1536x1024"
    if ratio <= 0.80:
        return "1024x1536"
    return "1024x1024"


def read_cached_json(path: Path, cache: dict[str, dict]) -> dict:
    if not path or not path.is_file():
        return {}
    key = str(path.resolve())
    if key not in cache:
        cache[key] = read_json(path)
    return cache[key]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
