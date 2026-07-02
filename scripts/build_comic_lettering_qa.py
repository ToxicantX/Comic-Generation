import argparse
import json
from datetime import datetime
from pathlib import Path


DEFAULT_STATUS = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_status.json")
DEFAULT_OUTPUT_JSON = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode02_lettering_qa.json")
DEFAULT_OUTPUT_MD = Path(r"G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP02_lettering_qa.md")


def main() -> int:
    args = parse_args()
    status_path = Path(args.status_path)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)

    status = read_json(status_path)
    page_results = []
    issues = []
    warnings = []
    skipped_pages = []

    for page in status.get("pages", []):
        page_result = check_page(page, allow_missing_assemblies=args.allow_missing_assemblies)
        page_results.append(page_result)
        issues.extend(page_result["issues"])
        warnings.extend(page_result["warnings"])
        if page_result.get("skipped"):
            skipped_pages.append(page_result)

    qa = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "status_path": str(status_path),
        "allow_missing_assemblies": bool(args.allow_missing_assemblies),
        "episode_id": status.get("episode_id"),
        "episode_title": status.get("episode_title"),
        "summary": {
            "pages": len(page_results),
            "checked_pages": len([page for page in page_results if not page.get("skipped")]),
            "skipped_pages": len(skipped_pages),
            "lettering_items": sum(page["lettering_items"] for page in page_results),
            "issues": len(issues),
            "warnings": len(warnings),
            "missing_assemblies": len(skipped_pages),
            "passed": not issues,
        },
        "issues": issues,
        "warnings": warnings,
        "skipped_pages": [
            {
                "page_id": page.get("page_id", ""),
                "assembly_path": page.get("assembly_path", ""),
                "reason": page.get("skip_reason", ""),
            }
            for page in skipped_pages
        ],
        "pages": page_results,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(build_markdown(qa), encoding="utf-8")
    print(json.dumps(qa["summary"], ensure_ascii=False, indent=2))
    return 0 if not issues else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate assembled comic page lettering metadata.")
    parser.add_argument("status_path", nargs="?", default=str(DEFAULT_STATUS))
    parser.add_argument("output_json", nargs="?", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("output_md", nargs="?", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument(
        "--allow-missing-assemblies",
        action="store_true",
        help="Skip missing page assemblies so incremental episode runs can QA the pages that already exist.",
    )
    return parser.parse_args()


def check_page(page: dict, allow_missing_assemblies: bool = False) -> dict:
    page_id = page.get("page_id", "")
    assembly_path = Path(page.get("assembly_path") or "")
    issues = []
    warnings = []
    panel_results = []

    if not assembly_path.is_file():
        missing = issue(page_id, "", "missing_assembly", str(assembly_path))
        if allow_missing_assemblies:
            return {
                "page_id": page_id,
                "assembly_path": str(assembly_path),
                "lettering_items": 0,
                "issues": issues,
                "warnings": warnings,
                "panels": panel_results,
                "skipped": True,
                "skip_reason": "missing_assembly",
                "missing_assembly": missing,
            }
        issues.append(missing)
        return {
            "page_id": page_id,
            "assembly_path": str(assembly_path),
            "lettering_items": 0,
            "issues": issues,
            "warnings": warnings,
            "panels": panel_results,
        }

    assembly = read_json(assembly_path)
    for panel in assembly.get("panels", []):
        panel_id = panel.get("panel_id", "")
        lettering = panel.get("lettering")
        if lettering is None:
            warnings.append(issue(page_id, panel_id, "missing_lettering_metadata", str(assembly_path)))
            lettering = []

        panel_issues = []
        panel_warnings = []
        for item in lettering:
            kind = item.get("kind", "")
            style = item.get("style", "")
            if kind == "dialogue" and style != "speech_bubble":
                panel_issues.append(issue(page_id, panel_id, "dialogue_not_speech_bubble", item.get("text", "")))
            if kind == "caption" and style != "box":
                panel_issues.append(issue(page_id, panel_id, "caption_not_box", item.get("text", "")))
            if kind == "caption" and has_dialogue_marker(item.get("text", "")):
                panel_issues.append(issue(page_id, panel_id, "dialogue_left_in_caption", item.get("text", "")))
            if not item.get("within_panel", False):
                panel_issues.append(issue(page_id, panel_id, "lettering_out_of_panel", item.get("text", "")))
            if not item.get("text_box_within_panel", False):
                panel_issues.append(issue(page_id, panel_id, "text_box_out_of_panel", item.get("text", "")))
            if item.get("text_bounds") and not item.get("text_bounds_within_text_box", False):
                panel_issues.append(issue(page_id, panel_id, "text_pixels_out_of_box", item.get("text", "")))
            if item.get("rendered_text_was_truncated", False):
                panel_warnings.append(issue(page_id, panel_id, "lettering_text_truncated", item.get("text", "")))

        issues.extend(panel_issues)
        warnings.extend(panel_warnings)
        panel_results.append(
            {
                "panel_id": panel_id,
                "lettering_items": len(lettering),
                "issues": panel_issues,
                "warnings": panel_warnings,
            }
        )

    return {
        "page_id": page_id,
        "assembly_path": str(assembly_path),
        "lettering_items": sum(panel["lettering_items"] for panel in panel_results),
        "issues": issues,
        "warnings": warnings,
        "panels": panel_results,
        "skipped": False,
    }


def issue(page_id: str, panel_id: str, code: str, detail: str) -> dict:
    return {
        "page_id": page_id,
        "panel_id": panel_id,
        "code": code,
        "detail": detail,
    }


def has_dialogue_marker(text: str) -> bool:
    if "“" in text or "”" in text:
        return True
    dialogue_cues = (
        "道：",
        "说道：",
        "喊道：",
        "叫道：",
        "问道：",
        "答道：",
        "喝道：",
        "怒道：",
        "笑道：",
        "呼喊：",
        "朗声道：",
        "厉声道：",
        "大声说道：",
        "冷冷道：",
    )
    if any(cue in text for cue in dialogue_cues):
        return True
    return bool(__import__("re").search(r"(?:道|说|喊|叫|问|答|喝|怒|笑|叹)\s*[：:]", text))


def build_markdown(qa: dict) -> str:
    lines = [
        f"# {qa.get('episode_id')} Lettering QA",
        "",
        f"- Updated: {qa.get('updated')}",
        f"- Title: {qa.get('episode_title', '')}",
        f"- Passed: `{qa['summary']['passed']}`",
        f"- Pages: {qa['summary']['pages']}",
        f"- Lettering items: {qa['summary']['lettering_items']}",
        f"- Issues: {qa['summary']['issues']}",
        f"- Warnings: {qa['summary']['warnings']}",
        "",
    ]
    if qa.get("issues"):
        lines.extend(["## Issues", ""])
        for item in qa["issues"]:
            lines.append(f"- `{item['code']}` {item.get('page_id', '')} {item.get('panel_id', '')}: {item.get('detail', '')}")
        lines.append("")
    if qa.get("warnings"):
        lines.extend(["## Warnings", ""])
        for item in qa["warnings"]:
            lines.append(f"- `{item['code']}` {item.get('page_id', '')} {item.get('panel_id', '')}: {item.get('detail', '')}")
        lines.append("")
    if qa.get("skipped_pages"):
        lines.extend(["## Skipped Pages", ""])
        for item in qa["skipped_pages"]:
            lines.append(f"- `{item.get('reason', '')}` {item.get('page_id', '')}: {item.get('assembly_path', '')}")
        lines.append("")
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
