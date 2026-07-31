import argparse
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - dependency availability is checked at runtime.
    Image = None
    ImageDraw = None
    ImageFont = None


KEY_CHARACTER_ALIASES = {
    "拓拔野": "tuobaye_turnaround",
    "白龙鹿": "bailonglu_reference",
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
    parser = argparse.ArgumentParser(description="Validate comic panel reference-anchor consistency.")
    parser.add_argument("status_json")
    parser.add_argument("output_json")
    parser.add_argument("output_md")
    parser.add_argument("--episode-plan", default="")
    parser.add_argument("--contact-sheet", default="")
    args = parser.parse_args()

    status_path = Path(args.status_json)
    status = read_json(status_path)
    episode_path = Path(args.episode_plan or status.get("episode_plan", ""))
    episode = read_json(episode_path) if episode_path.is_file() else {}
    asset_aliases = episode.get("asset_aliases", {})

    pages = []
    flat_panels = []
    for page_status in status.get("pages", []):
        page_result = check_page(page_status, asset_aliases)
        pages.append(page_result)
        flat_panels.extend(page_result["panels"])

    blocked = [panel for panel in flat_panels if panel["technical_status"] == "blocked"]
    pending = [panel for panel in flat_panels if panel["technical_status"] == "pending_generation"]
    needs_review = [panel for panel in flat_panels if panel["technical_status"] == "needs_visual_review"]
    passed = [panel for panel in flat_panels if panel["technical_status"] == "technical_passed"]
    generated = [panel for panel in flat_panels if panel["generated"]]
    issues = [issue for panel in flat_panels for issue in panel["issues"]]
    warnings = [warning for panel in flat_panels for warning in panel["warnings"]]

    qa = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "status_json": str(status_path),
        "episode_plan": str(episode_path) if str(episode_path) else "",
        "episode_id": status.get("episode_id"),
        "episode_title": status.get("episode_title"),
        "summary": {
            "pages": len(pages),
            "panels": len(flat_panels),
            "generated_panels": len(generated),
            "missing_panels": len(pending),
            "technical_passed": len(passed),
            "needs_visual_review": len(needs_review),
            "pending_generation": len(pending),
            "blocked": len(blocked),
            "issues": len(issues),
            "warnings": len(warnings),
            "visual_review_pending": len(generated),
            "passed": len(blocked) == 0,
            "complete_episode": status.get("summary", {}).get("missing_panels", 0) == 0,
        },
        "blocked_panel_ids": [panel["panel_id"] for panel in blocked],
        "needs_visual_review_panel_ids": [panel["panel_id"] for panel in needs_review],
        "pending_generation_panel_ids": [panel["panel_id"] for panel in pending],
        "contact_sheet": "",
        "contact_sheet_error": "",
        "pages": pages,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    contact_sheet = Path(args.contact_sheet) if args.contact_sheet else output_md.with_name(f"{output_md.stem}_contact_sheet.jpg")
    if generated:
        try:
            write_contact_sheet(generated, contact_sheet)
            qa["contact_sheet"] = str(contact_sheet)
        except Exception as exc:
            qa["contact_sheet_error"] = str(exc)
            qa["summary"]["warnings"] += 1

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(build_markdown(qa), encoding="utf-8")
    print(json.dumps(qa["summary"], ensure_ascii=False, indent=2))
    return 0 if qa["summary"]["passed"] else 1


def check_page(page_status: dict, asset_aliases: dict) -> dict:
    plan_path = Path(page_status.get("plan_path") or "")
    plan = read_json(plan_path) if plan_path.is_file() else {}
    plan_by_panel = {panel.get("panel_id"): panel for panel in plan.get("panels", [])}
    workflow_by_panel = load_workflow_entries(page_status)

    panels = []
    for status_panel in page_status.get("panels", []):
        panel_id = status_panel.get("panel_id")
        panels.append(
            check_panel(
                page_id=page_status.get("page_id", ""),
                status_panel=status_panel,
                plan_panel=plan_by_panel.get(panel_id, {}),
                workflow_panel=workflow_by_panel.get(panel_id, {}),
                asset_aliases=asset_aliases,
                plan_exists=plan_path.is_file(),
            )
        )

    return {
        "page_id": page_status.get("page_id"),
        "status": page_status.get("status"),
        "plan_path": str(plan_path),
        "panels": panels,
    }


def load_workflow_entries(page_status: dict) -> dict:
    paths = []
    for key in ("workflow_path", "fallback_workflow_path", "micro_fallback_workflow_path"):
        value = page_status.get(key)
        if value:
            paths.append(Path(value))
    entries = {}
    for path in unique_existing(paths):
        manifest = read_json(path)
        for item in manifest.get("created", []):
            panel_id = item.get("panel_id")
            if panel_id and panel_id not in entries:
                entries[panel_id] = item
    return entries


def check_panel(
    page_id: str,
    status_panel: dict,
    plan_panel: dict,
    workflow_panel: dict,
    asset_aliases: dict,
    plan_exists: bool,
) -> dict:
    issues = []
    warnings = []
    panel_id = status_panel.get("panel_id")
    plan_alias = plan_panel.get("reference_alias", "")
    workflow_alias = workflow_panel.get("reference_alias", "")
    asset_image = asset_aliases.get(plan_alias, "") if plan_alias else ""
    plan_reference = plan_panel.get("reference_image", "")
    workflow_reference = workflow_panel.get("reference_image", "")
    status_reference = status_panel.get("reference_image", "")
    used_panel_path = status_panel.get("used_panel_path") or status_panel.get("expected_panel_path", "")
    generated = bool(status_panel.get("exists")) and path_exists(used_panel_path)
    workflow_json = inspect_workflow_json(workflow_panel)
    issues.extend(workflow_json["issues"])
    warnings.extend(workflow_json["warnings"])

    if not plan_exists:
        issues.append("missing_page_plan")
    if not plan_panel:
        issues.append("missing_panel_in_plan")
    if not plan_alias:
        issues.append("missing_plan_reference_alias")
    elif plan_alias not in asset_aliases:
        issues.append(f"unknown_plan_reference_alias:{plan_alias}")
    elif not path_exists(asset_image):
        issues.append(f"missing_asset_reference_file:{plan_alias}")

    if plan_reference and asset_image and not same_path(plan_reference, asset_image):
        issues.append("plan_reference_image_mismatch_asset_alias")
    if not workflow_panel:
        issues.append("missing_panel_workflow_entry")
    if workflow_alias and plan_alias and workflow_alias != plan_alias:
        issues.append("workflow_reference_alias_mismatch_plan")
    if workflow_reference and plan_reference and not same_path(workflow_reference, plan_reference):
        issues.append("workflow_reference_image_mismatch_plan")
    if plan_reference and workflow_json["reference_image_paths"]:
        if not any(same_path(reference, plan_reference) for reference in workflow_json["reference_image_paths"]):
            issues.append("workflow_json_reference_image_mismatch_plan")
    if workflow_panel.get("filename_prefix") and workflow_json["save_filename_prefixes"]:
        if workflow_panel["filename_prefix"] not in workflow_json["save_filename_prefixes"]:
            issues.append("workflow_json_save_prefix_mismatch_manifest")
    workflow_prefix = first_or_empty(workflow_json["save_filename_prefixes"])
    if workflow_prefix and status_panel.get("expected_panel_path"):
        if not output_matches_prefix(status_panel.get("expected_panel_path", ""), workflow_prefix):
            issues.append("workflow_json_expected_output_mismatch_status")
    if status_reference and plan_reference and not same_path(status_reference, plan_reference):
        issues.append("status_reference_image_mismatch_plan")
    if status_panel.get("exists") and not path_exists(used_panel_path):
        issues.append("status_generated_panel_missing_on_disk")

    if not generated:
        warnings.append("pending_generation")
    else:
        warnings.append("visual_consistency_pending_human_or_model_review")

    prompt = plan_panel.get("prompt", "")
    for character, required_alias in KEY_CHARACTER_ALIASES.items():
        if character in prompt and plan_alias and required_alias != plan_alias:
            warnings.append(f"secondary_character_without_matching_primary_anchor:{character}->{required_alias}")

    if issues:
        technical_status = "blocked"
    elif not generated:
        technical_status = "pending_generation"
    elif len(warnings) > 1:
        technical_status = "needs_visual_review"
    else:
        technical_status = "technical_passed"

    return {
        "page_id": page_id,
        "panel_id": panel_id,
        "title": status_panel.get("title", ""),
        "generated": generated,
        "technical_status": technical_status,
        "issues": issues,
        "warnings": warnings,
        "plan_reference_alias": plan_alias,
        "workflow_reference_alias": workflow_alias,
        "asset_reference_image": asset_image,
        "plan_reference_image": plan_reference,
        "workflow_reference_image": workflow_reference,
        "status_reference_image": status_reference,
        "panel_image": used_panel_path,
        "workflow_json": workflow_json["summary"],
    }


def inspect_workflow_json(workflow_panel: dict) -> dict:
    workflow_path = workflow_panel.get("workflow", "") if workflow_panel else ""
    issues = []
    warnings = []
    summary = {
        "workflow_path": workflow_path,
        "exists": False,
        "image_generate_nodes": 0,
        "save_image_nodes": 0,
        "reference_image_paths": [],
        "save_filename_prefixes": [],
        "has_no_text_prompt_instruction": False,
        "has_negative_text_ban": False,
    }

    if not workflow_panel:
        return {"issues": issues, "warnings": warnings, "summary": summary, "reference_image_paths": [], "save_filename_prefixes": []}
    if not workflow_path:
        issues.append("missing_workflow_json_path")
        return {"issues": issues, "warnings": warnings, "summary": summary, "reference_image_paths": [], "save_filename_prefixes": []}

    path = Path(workflow_path)
    if not path.is_file():
        issues.append("workflow_json_missing_on_disk")
        return {"issues": issues, "warnings": warnings, "summary": summary, "reference_image_paths": [], "save_filename_prefixes": []}

    summary["exists"] = True
    workflow = read_json(path)
    prompt_graph = workflow.get("prompt", {})
    if not isinstance(prompt_graph, dict) or not prompt_graph:
        issues.append("workflow_json_missing_prompt_graph")
        return {"issues": issues, "warnings": warnings, "summary": summary, "reference_image_paths": [], "save_filename_prefixes": []}

    direct_nodes = nodes_by_class(prompt_graph, "OpenAICompatibleImageGenerate")
    local_nodes = nodes_by_class(prompt_graph, "KSampler")
    image_nodes = direct_nodes + local_nodes
    save_nodes = nodes_by_class(prompt_graph, "SaveImage")
    summary["image_generate_nodes"] = len(image_nodes)
    summary["save_image_nodes"] = len(save_nodes)
    if not image_nodes:
        issues.append("workflow_json_missing_image_generate_node")
    if not save_nodes:
        issues.append("workflow_json_missing_save_image_node")
    if len(image_nodes) > 1:
        warnings.append("workflow_json_multiple_image_generate_nodes")
    if len(save_nodes) > 1:
        warnings.append("workflow_json_multiple_save_image_nodes")

    reference_paths = []
    prompt_texts = []
    negative_prompt_texts = []
    for node in direct_nodes:
        inputs = node.get("inputs", {})
        reference_paths.extend(normalize_reference_paths(inputs.get("reference_image_paths", "")))
        prompt_texts.append(str(inputs.get("prompt", "")))
        negative_prompt_texts.append(str(inputs.get("negative_prompt", "")))
    for node in nodes_by_class(prompt_graph, "LoadImage"):
        inputs = node.get("inputs", {})
        meta = node.get("_meta") or {}
        reference_paths.extend(normalize_reference_paths(meta.get("comic_pipeline_reference_path", "")))
        if not meta.get("comic_pipeline_reference_path"):
            reference_paths.extend(normalize_reference_paths(inputs.get("image", "")))
    for node in prompt_graph.values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        role = (node.get("_meta") or {}).get("comic_pipeline_role")
        text = str((node.get("inputs") or {}).get("text", ""))
        if role == "positive_prompt":
            prompt_texts.append(text)
        elif role == "negative_prompt":
            negative_prompt_texts.append(text)

    save_prefixes = []
    for node in save_nodes:
        inputs = node.get("inputs", {})
        prefix = inputs.get("filename_prefix", "")
        if prefix:
            save_prefixes.append(str(prefix))

    summary["reference_image_paths"] = reference_paths
    summary["save_filename_prefixes"] = save_prefixes
    summary["has_no_text_prompt_instruction"] = any(has_no_text_instruction(text) for text in prompt_texts)
    summary["has_negative_text_ban"] = any(has_negative_text_ban(text) for text in negative_prompt_texts)

    reference_required = bool(direct_nodes or nodes_by_class(prompt_graph, "LoadImage"))
    if reference_required and not reference_paths:
        issues.append("workflow_json_missing_reference_image_paths")
    for reference_path in reference_paths:
        if not reference_path_exists(reference_path):
            issues.append("workflow_json_reference_file_missing")
            break
    if not save_prefixes:
        issues.append("workflow_json_missing_save_filename_prefix")
    if not summary["has_no_text_prompt_instruction"]:
        issues.append("workflow_prompt_missing_no_text_instruction")
    if not summary["has_negative_text_ban"]:
        issues.append("workflow_negative_prompt_missing_text_ban")

    return {
        "issues": issues,
        "warnings": warnings,
        "summary": summary,
        "reference_image_paths": reference_paths,
        "save_filename_prefixes": save_prefixes,
    }


def nodes_by_class(prompt_graph: dict, class_type: str) -> list[dict]:
    return [
        node
        for node in prompt_graph.values()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]


def normalize_reference_paths(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(normalize_reference_paths(item))
        return result
    text = str(value)
    separators = ["\n", ";", "|"]
    for separator in separators:
        text = text.replace(separator, ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def has_no_text_instruction(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in (
            "no baked-in text",
            "no text",
            "text-free",
            "without text",
            "avoid text",
            "do not render text",
            "无画面内文字",
        )
    )


def has_negative_text_ban(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ("text", "watermark", "logo"))


def expected_output_from_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return str(Path(r"G:\ComfyUI\output") / f"{prefix}_00001_.png")


def output_matches_prefix(output_path: str, prefix: str) -> bool:
    if not output_path or not prefix:
        return False
    normalized_output = str(output_path).replace("\\", "/").lower()
    normalized_prefix = str(prefix).replace("\\", "/").strip("/").lower()
    return normalized_output.endswith(f"/{normalized_prefix}_00001_.png")


def first_or_empty(values: list[str]) -> str:
    return values[0] if values else ""


def build_markdown(qa: dict) -> str:
    summary = qa["summary"]
    lines = [
        f"# {qa.get('episode_id')} Consistency QA",
        "",
        f"- Updated: {qa.get('updated')}",
        f"- Title: {qa.get('episode_title', '')}",
        f"- Generated panels: {summary['generated_panels']} / {summary['panels']}",
        f"- Blocked technical consistency issues: {summary['blocked']}",
        f"- Visual review pending: {summary['visual_review_pending']}",
        f"- Passed technical gate: `{summary['passed']}`",
        "",
        "This report verifies reference-anchor continuity in the pipeline metadata. Visual likeness still needs human or model review for generated panels.",
        "",
    ]
    if qa.get("contact_sheet"):
        lines.extend(
            [
                "## Contact Sheet",
                "",
                f"![consistency contact sheet]({markdown_image_path(qa['contact_sheet'])})",
                "",
            ]
        )
    if qa.get("contact_sheet_error"):
        lines.extend([f"- Contact sheet error: `{qa['contact_sheet_error']}`", ""])
    for page in qa.get("pages", []):
        lines.extend([f"## {page.get('page_id')}", ""])
        for panel in page.get("panels", []):
            lines.extend(
                [
                    f"### {panel.get('panel_id')} - {panel.get('title', '')}",
                    "",
                    f"- Status: `{panel.get('technical_status')}`",
                    f"- Generated: `{panel.get('generated')}`",
                    f"- Issues: `{', '.join(panel.get('issues', [])) if panel.get('issues') else 'none'}`",
                    f"- Warnings: `{', '.join(panel.get('warnings', [])) if panel.get('warnings') else 'none'}`",
                    f"- Plan alias: `{panel.get('plan_reference_alias', '')}`",
                    f"- Workflow alias: `{panel.get('workflow_reference_alias', '')}`",
                    f"- Reference image: `{panel.get('plan_reference_image', '')}`",
                    f"- Panel image: `{panel.get('panel_image', '')}`",
                    "",
                ]
            )
            if panel.get("generated"):
                reference = markdown_image_path(panel.get("plan_reference_image", ""))
                panel_image = markdown_image_path(panel.get("panel_image", ""))
                if reference:
                    lines.append(f"![reference]({reference})")
                if panel_image:
                    lines.append(f"![panel]({panel_image})")
                lines.append("")
    return "\n".join(lines)


def write_contact_sheet(generated_panels: list[dict], output_path: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow is not available; cannot build consistency contact sheet.")

    rows = []
    for panel in generated_panels:
        reference_path = panel.get("plan_reference_image", "")
        panel_path = panel.get("panel_image", "")
        if not path_exists(reference_path) or not path_exists(panel_path):
            continue
        reference = open_image(reference_path)
        panel_image = open_image(panel_path)
        rows.append(build_contact_row(reference, panel_image, panel))

    if not rows:
        raise RuntimeError("No generated panels with readable reference and panel images.")

    gutter = 18
    width = max(row.width for row in rows)
    height = sum(row.height for row in rows) + gutter * (len(rows) + 1)
    sheet = Image.new("RGB", (width + gutter * 2, height), "#f7f4ec")
    y = gutter
    for row in rows:
        sheet.paste(row, (gutter, y))
        y += row.height + gutter
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def build_contact_row(reference: "Image.Image", panel_image: "Image.Image", panel: dict) -> "Image.Image":
    target_h = 320
    label_w = 440
    gutter = 16
    reference = resize_to_height(reference, target_h)
    panel_image = resize_to_height(panel_image, target_h)
    width = label_w + reference.width + panel_image.width + gutter * 4
    row = Image.new("RGB", (width, target_h + gutter * 2), "white")
    draw = ImageDraw.Draw(row)
    font = load_font(22)
    small_font = load_font(18)
    text_x = gutter
    text_y = gutter
    draw.text((text_x, text_y), panel.get("panel_id", ""), fill="#151515", font=font)
    draw.text((text_x, text_y + 34), panel.get("plan_reference_alias", ""), fill="#444444", font=small_font)
    draw.text((text_x, text_y + 66), panel.get("technical_status", ""), fill="#6b3d00", font=small_font)
    title = panel.get("title", "")
    for index, line in enumerate(wrap_text(title, 24)[:4]):
        draw.text((text_x, text_y + 104 + index * 26), line, fill="#333333", font=small_font)

    ref_x = label_w + gutter * 2
    panel_x = ref_x + reference.width + gutter
    row.paste(reference, (ref_x, gutter))
    row.paste(panel_image, (panel_x, gutter))
    draw.rectangle((ref_x, gutter, ref_x + reference.width - 1, gutter + reference.height - 1), outline="#222222", width=2)
    draw.rectangle((panel_x, gutter, panel_x + panel_image.width - 1, gutter + panel_image.height - 1), outline="#222222", width=2)
    draw.text((ref_x, target_h + 2), "reference", fill="#555555", font=small_font)
    draw.text((panel_x, target_h + 2), "panel", fill="#555555", font=small_font)
    return row


def open_image(path: str) -> "Image.Image":
    return Image.open(path).convert("RGB")


def resize_to_height(image: "Image.Image", height: int) -> "Image.Image":
    width = max(1, int(image.width * (height / image.height)))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def load_font(size: int):
    if ImageFont is None:
        return None
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def wrap_text(text: str, limit: int) -> list[str]:
    if not text:
        return []
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def unique_existing(paths: list[Path]) -> list[Path]:
    seen = set()
    unique = []
    for path in paths:
        if not path.is_file():
            continue
        key = normalized_path(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def same_path(left: str, right: str) -> bool:
    return normalized_path(left) == normalized_path(right)


def normalized_path(value: str | Path) -> str:
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(str(value).replace("/", os.sep)))


def path_exists(value: str) -> bool:
    return bool(value) and Path(value).is_file()


def reference_path_exists(value: str) -> bool:
    if path_exists(value):
        return True
    candidate = Path(value or "")
    if candidate.is_absolute():
        return False
    comfy_root = Path(os.environ.get("COMIC_PIPELINE_COMFY_ROOT") or "")
    return bool(comfy_root and (comfy_root / "input" / candidate).is_file())


def markdown_image_path(value: str) -> str:
    if not value:
        return ""
    return str(value).replace("\\", "/").replace(" ", "%20")


if __name__ == "__main__":
    raise SystemExit(main())
