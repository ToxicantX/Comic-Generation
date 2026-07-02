import argparse
import json
from datetime import datetime
from pathlib import Path


ALLOWED_WARNINGS = {"page_marked_needs_human_review", "output_already_exists"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-json", required=True)
    parser.add_argument("--page-ids", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--reviewer", default="codex_auto_review")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    qa_path = Path(args.qa_json)
    qa = read_json(qa_path)
    selected_page_ids = [item.strip() for item in args.page_ids.split(",") if item.strip()]
    selected = set(selected_page_ids)

    pages = []
    approved_panels = []
    blocked_panels = []
    for page in qa.get("pages", []):
        page_id = page.get("page_id", "")
        if selected and page_id not in selected:
            continue
        page_result = {"page_id": page_id, "panels": []}
        for panel in page.get("panels", []):
            result = approve_panel(panel)
            page_result["panels"].append(result)
            if result["approval_status"] == "approved_to_submit":
                approved_panels.append(result["panel_id"])
            else:
                blocked_panels.append(result["panel_id"])
        pages.append(page_result)

    approval = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "qa_json": str(qa_path),
        "episode_id": qa.get("episode_id"),
        "episode_title": qa.get("episode_title"),
        "reviewer": args.reviewer,
        "note": args.note,
        "selected_page_ids": selected_page_ids,
        "summary": {
            "pages": len(pages),
            "panels": sum(len(page["panels"]) for page in pages),
            "approved_to_submit": len(approved_panels),
            "blocked": len(blocked_panels),
        },
        "approved_panel_ids": approved_panels,
        "blocked_panel_ids": blocked_panels,
        "pages": pages,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(approval["summary"], ensure_ascii=False, indent=2))
    return 0 if not blocked_panels else 1


def approve_panel(panel: dict) -> dict:
    warnings = list(panel.get("warnings", []))
    issues = list(panel.get("issues", []))
    unexpected_warnings = [warning for warning in warnings if warning not in ALLOWED_WARNINGS]
    if issues or unexpected_warnings:
        status = "blocked"
    else:
        status = "approved_to_submit"
    return {
        "panel_id": panel.get("panel_id"),
        "page_id": panel.get("page_id"),
        "approval_status": status,
        "issues": issues,
        "warnings": warnings,
        "unexpected_warnings": unexpected_warnings,
        "workflow": panel.get("workflow", ""),
        "expected_panel_path": panel.get("expected_panel_path", ""),
    }


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
