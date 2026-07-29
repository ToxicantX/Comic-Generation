import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or SCRIPT_DIR.parent)
COMFY_OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or r"G:\ComfyUI\output")
OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_OUTPUT_ROOT") or (COMFY_OUTPUT_ROOT / "ComicPipeline"))
DEFAULT_PLAN = WORKSPACE / "manifests" / "ssj_comic_ep01_page01_plan.json"
DEFAULT_WORKFLOWS = WORKSPACE / "manifests" / "ssj_comic_ep01_page01_workflows.json"
DEFAULT_OUTPUT_DIR = OUTPUT_ROOT / "pages"
DEFAULT_REVIEW_DIR = OUTPUT_ROOT / "review_packages" / "SSJ_COMIC_EP01_P001"
DEFAULT_MANIFEST = WORKSPACE / "manifests" / "ssj_comic_ep01_page01_assembly.json"
MIN_LETTERING_FONT_SIZE = 16
BUBBLE_TAIL_LENGTH = 16


def main() -> int:
    plan_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PLAN
    workflow_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_WORKFLOWS
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT_DIR
    review_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_REVIEW_DIR
    manifest_path = Path(sys.argv[5]) if len(sys.argv) > 5 else DEFAULT_MANIFEST

    plan = read_json(plan_path)
    workflows = read_json(workflow_path) if workflow_path.is_file() else {"created": []}
    workflow_by_panel = {item.get("panel_id"): item for item in workflows.get("created", [])}

    page_cfg = plan.get("page", {})
    width = int(page_cfg.get("width", 1600))
    height = int(page_cfg.get("height", 2400))
    background = page_cfg.get("background", "#050403")
    border = int(page_cfg.get("border", 0) or 0)

    output_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    page = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(page)
    draw_page_surface(draw, page_cfg, width, height)
    body_font = load_font(32)
    small_font = load_font(24)

    panels = []
    ordered_panels = sorted(plan.get("panels", []), key=lambda item: item.get("order", 0))
    for panel in panel_render_order(ordered_panels):
        panel_id = panel.get("panel_id", "UNKNOWN_PANEL")
        layout = normalize_panel_layout(panel.get("layout", {}))
        x, y = int(layout.get("x", 0)), int(layout.get("y", 0))
        w, h = int(layout.get("w", 100)), int(layout.get("h", 100))
        expected_path = expected_panel_path(panel, workflow_by_panel.get(panel_id, {}))
        panel_path = resolve_panel_path(expected_path)
        exists = panel_path.is_file()

        panel_image = load_panel_image(panel_path, w, h, panel, small_font)
        paste_panel(page, panel_image, layout)
        draw_panel_border(draw, layout, border)

        lettering = add_lettering(draw, panel, (x, y, w, h), body_font)
        panels.append(
            {
                "panel_id": panel_id,
                "title": panel.get("title", ""),
                "expected_panel_path": str(expected_path) if expected_path else "",
                "used_panel_path": str(panel_path) if panel_path else "",
                "exists": exists,
                "layout": layout,
                "lettering": lettering,
            }
        )
    panels.sort(key=lambda item: int(item.get("layout", {}).get("render_order", item.get("layout", {}).get("order", 0)) or 0))

    page_name = f"{plan.get('page_id', 'comic_page')}.png"
    page_path = output_dir / page_name
    page.save(page_path, quality=95)

    layout_quality = assess_layout_quality(plan, panels)

    markdown_path = review_dir / "human_review.md"
    markdown_path.write_text(build_markdown(plan, page_path, panels, layout_quality), encoding="utf-8")

    manifest = {
        "ok": all(panel["exists"] for panel in panels),
        "updated": datetime.now().isoformat(timespec="seconds"),
        "plan_path": str(plan_path),
        "workflow_result_path": str(workflow_path),
        "page_path": str(page_path),
        "review_markdown": str(markdown_path),
        "layout_quality": layout_quality,
        "panels": panels,
        "note": "ok=false means the page was assembled with one or more placeholders so layout and lettering can still be reviewed.",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["ok"] else 1


def load_panel_image(path: Path, width: int, height: int, panel: dict, font: ImageFont.ImageFont) -> Image.Image:
    if path and path.is_file():
        image = Image.open(path).convert("RGB")
        image = trim_flat_image_border(image)
        return cover_resize(image, width, height)

    placeholder = Image.new("RGB", (width, height), "#ded7c8")
    draw = ImageDraw.Draw(placeholder)
    draw.rectangle([0, 0, width - 1, height - 1], outline="#8d8170", width=4)
    title = panel.get("title") or panel.get("panel_id") or "missing panel"
    lines = wrap_text(f"待生成: {title}", font, width - 60)
    y = max(30, height // 2 - len(lines) * 18)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, y), line, fill="#4b4338", font=font)
        y += 34
    return placeholder


def draw_page_surface(draw: ImageDraw.ImageDraw, page_cfg: dict, width: int, height: int) -> None:
    paper_border = int(page_cfg.get("paper_border", 0) or 0)
    if paper_border > 0:
        draw.rectangle([paper_border, paper_border, width - paper_border, height - paper_border], outline="#17130f", width=2)

    safe_margin = int(page_cfg.get("safe_margin", 48) or 48)
    if truthy(page_cfg.get("show_safe_area")):
        draw.rectangle([safe_margin, safe_margin, width - safe_margin, height - safe_margin], outline="#eadfca", width=1)


def panel_render_order(panels: list[dict]) -> list[dict]:
    def sort_key(panel: dict) -> tuple[int, int]:
        layout = panel.get("layout", {}) if isinstance(panel.get("layout", {}), dict) else {}
        render_order = int(layout.get("render_order", panel.get("render_order", panel.get("order", 0))) or 0)
        return render_order, int(panel.get("order", 0) or 0)

    return sorted(panels, key=sort_key)


def normalize_panel_layout(layout: dict) -> dict:
    normalized = dict(layout or {})
    normalized["x"] = int(normalized.get("x", 0) or 0)
    normalized["y"] = int(normalized.get("y", 0) or 0)
    normalized["w"] = int(normalized.get("w", 100) or 100)
    normalized["h"] = int(normalized.get("h", 100) or 100)
    normalized["shape"] = str(normalized.get("shape", "rect") or "rect").lower()
    return normalized


def paste_panel(page: Image.Image, panel_image: Image.Image, layout: dict) -> None:
    x, y, w, h = int(layout["x"]), int(layout["y"]), int(layout["w"]), int(layout["h"])
    shape = str(layout.get("shape", "rect")).lower()
    if truthy(layout.get("drop_shadow")):
        shadow_offset = int(layout.get("shadow_offset", 12) or 12)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 42))
        if shape in {"slant_left", "slant_right", "polygon"}:
            shadow_mask = panel_mask(layout)
            shadow.putalpha(shadow_mask)
        page.paste(shadow.convert("RGB"), (x + shadow_offset, y + shadow_offset), shadow.split()[-1])

    if shape in {"slant_left", "slant_right", "polygon"}:
        mask = panel_mask(layout)
        page.paste(panel_image, (x, y), mask)
        return

    paste_rect_panel(page, panel_image, x, y, w, h, int(layout.get("bleed_overlap", 2) or 2))


def paste_rect_panel(page: Image.Image, panel_image: Image.Image, x: int, y: int, width: int, height: int, overlap: int) -> None:
    left = max(0, x - overlap)
    top = max(0, y - overlap)
    right = min(page.width, x + width + overlap)
    bottom = min(page.height, y + height + overlap)
    target_w = max(1, right - left)
    target_h = max(1, bottom - top)
    expanded = cover_resize(panel_image, target_w, target_h)
    page.paste(expanded, (left, top))


def draw_panel_border(draw: ImageDraw.ImageDraw, layout: dict, border: int) -> None:
    x, y, w, h = int(layout["x"]), int(layout["y"]), int(layout["w"]), int(layout["h"])
    width = int(layout.get("border", border) or border)
    if width <= 0:
        return
    color = layout.get("border_color", "#17130f")
    shape = str(layout.get("shape", "rect")).lower()
    if shape in {"slant_left", "slant_right", "polygon"}:
        points = [(x + px, y + py) for px, py in polygon_points(layout, w, h)]
        draw.line(points + [points[0]], fill=color, width=width, joint="curve")
        return
    draw.rectangle([x, y, x + w, y + h], outline=color, width=width)


def panel_mask(layout: dict) -> Image.Image:
    w, h = int(layout["w"]), int(layout["h"])
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(polygon_points(layout, w, h), fill=255)
    return mask


def polygon_points(layout: dict, width: int, height: int) -> list[tuple[int, int]]:
    shape = str(layout.get("shape", "rect")).lower()
    slant = int(layout.get("slant", min(90, max(36, width // 10))) or min(90, max(36, width // 10)))
    if shape == "slant_left":
        return [(slant, 0), (width, 0), (width - slant, height), (0, height)]
    if shape == "slant_right":
        return [(0, 0), (width - slant, 0), (width, height), (slant, height)]
    raw_points = layout.get("points")
    if isinstance(raw_points, list) and len(raw_points) >= 3:
        points = []
        for item in raw_points:
            if isinstance(item, dict):
                points.append((int(item.get("x", 0)), int(item.get("y", 0))))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append((int(item[0]), int(item[1])))
        if len(points) >= 3:
            return points
    return [(0, 0), (width, 0), (width, height), (0, height)]


def expected_panel_path(panel: dict, workflow_item: dict) -> Path:
    workflow_path = workflow_item.get("expected_panel_path") if workflow_item else ""
    if workflow_path:
        return Path(workflow_path)

    filename_prefix = panel.get("fallback_filename_prefix") or panel.get("filename_prefix") or ""
    if filename_prefix:
        return COMFY_OUTPUT_ROOT / f"{filename_prefix}_00001_.png"

    return Path("")


def resolve_panel_path(expected_path: Path) -> Path:
    if expected_path and expected_path.is_file():
        newer = find_latest_sibling_output(expected_path)
        return newer or expected_path
    return find_latest_sibling_output(expected_path) or expected_path


def find_latest_sibling_output(expected_path: Path) -> Path | None:
    if not expected_path or not expected_path.parent:
        return None
    if not expected_path.parent.is_dir():
        return None
    stem = expected_path.stem
    marker = "_00001_"
    prefix = stem.split(marker)[0] if marker in stem else stem
    candidates = sorted(
        expected_path.parent.glob(f"{prefix}_*.png"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height) * 1.04
    resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def trim_flat_image_border(image: Image.Image) -> Image.Image:
    width, height = image.size
    max_trim_x = max(0, int(width * 0.18))
    max_trim_y = max(0, int(height * 0.18))
    left = count_flat_edge_columns(image, "left", max_trim_x)
    right = count_flat_edge_columns(image, "right", max_trim_x)
    top = count_flat_edge_rows(image, "top", max_trim_y)
    bottom = count_flat_edge_rows(image, "bottom", max_trim_y)
    if left + right >= width * 0.4 or top + bottom >= height * 0.4:
        return image
    if max(left, right, top, bottom) < 4:
        return image
    return image.crop((left, top, width - right, height - bottom))


def count_flat_edge_columns(image: Image.Image, side: str, max_trim: int) -> int:
    width, height = image.size
    trim = 0
    for offset in range(max_trim):
        x = offset if side == "left" else width - 1 - offset
        if not edge_line_is_flat([image.getpixel((x, y)) for y in range(0, height, max(1, height // 80))]):
            break
        trim += 1
    return trim


def count_flat_edge_rows(image: Image.Image, side: str, max_trim: int) -> int:
    width, height = image.size
    trim = 0
    for offset in range(max_trim):
        y = offset if side == "top" else height - 1 - offset
        if not edge_line_is_flat([image.getpixel((x, y)) for x in range(0, width, max(1, width // 80))]):
            break
        trim += 1
    return trim


def edge_line_is_flat(pixels: list[tuple[int, int, int]]) -> bool:
    if not pixels:
        return False
    avg = tuple(sum(pixel[channel] for pixel in pixels) / len(pixels) for channel in range(3))
    variance = sum(sum(abs(pixel[channel] - avg[channel]) for channel in range(3)) for pixel in pixels) / len(pixels)
    brightness = sum(avg) / 3
    dark_or_light = brightness < 48 or brightness > 216
    near_monochrome = max(avg) - min(avg) < 18
    return variance < 34 and dark_or_light and near_monochrome


def add_lettering(draw: ImageDraw.ImageDraw, panel: dict, box: tuple[int, int, int, int], font: ImageFont.ImageFont) -> list[dict]:
    x, y, w, h = box
    margin = lettering_margin(w, h)
    gap = max(10, min(22, h // 36))
    top_cursor = y + margin
    bottom_cursor = y + h - margin
    records = []

    caption, dialogues = normalize_lettering_content(panel)
    if caption:
        caption_w = caption_box_width(caption, font, w, margin)
        caption_h = measure_text_box_height(caption, font, caption_w, min_height=72, max_height=max_text_block_height(h))
        bottom_cursor -= caption_h
        caption_x = caption_box_x(panel, box, caption_w, margin)
        caption_box = fit_box_inside_panel((caption_x, bottom_cursor, caption_w, caption_h), box, margin)
        text_result = draw_caption_box(draw, caption, caption_box, font)
        records.append(lettering_record("caption", caption, caption_box, box, "box", tail_points=None, text_result=text_result))
        bottom_cursor = caption_box[1] - gap

    for dialogue in dialogues:
        text = dialogue.get("text") or ""
        speaker = dialogue.get("speaker") or ""
        if not text:
            continue
        content = f"{speaker}: {text}" if speaker else text
        placement = resolve_dialogue_placement(panel, dialogue, len(records), len(dialogues))
        max_bubble_w = max(80, w - margin * 2)
        bubble_w = speech_bubble_width(content, font, w, margin)
        bubble_w = min(max_bubble_w, bubble_w)
        bubble_h = measure_text_box_height(
            content,
            font,
            bubble_w,
            min_height=72,
            max_height=max_text_block_height(h),
            padding=18,
        )
        bubble_x, bubble_y, tail, cursor_region = speech_bubble_position(
            (x, y, w, h),
            bubble_w,
            bubble_h,
            margin,
            top_cursor,
            bottom_cursor,
            placement,
        )
        if cursor_region == "top":
            top_cursor = bubble_y + bubble_h + gap + (BUBBLE_TAIL_LENGTH if tail == "bottom" else 0)
        elif cursor_region == "bottom":
            bottom_cursor = bubble_y - gap - (BUBBLE_TAIL_LENGTH if tail == "top" else 0)
        bubble_box = fit_speech_bubble_inside_panel((bubble_x, bubble_y, bubble_w, bubble_h), box, margin, tail)
        tail_points, text_result = draw_speech_bubble(draw, content, bubble_box, font, tail=tail)
        records.append(
            lettering_record(
                "dialogue",
                content,
                bubble_box,
                box,
                "speech_bubble",
                tail_points=tail_points,
                text_result=text_result,
                placement=placement,
            )
        )
    return records


def lettering_margin(width: int, height: int) -> int:
    return max(14, min(28, width // 28, height // 24))


def caption_box_width(text: str, font: ImageFont.ImageFont, panel_width: int, margin: int) -> int:
    max_w = max(96, panel_width - margin * 2)
    text_w = text_width(text, font) + 42
    if len(text) <= 20:
        preferred = max(220, text_w)
    elif len(text) <= 36:
        preferred = max(320, min(text_w, int(panel_width * 0.72)))
    else:
        preferred = max(420, min(text_w, int(panel_width * 0.86)))
    return min(max_w, preferred)


def caption_box_x(panel: dict, panel_box: tuple[int, int, int, int], caption_width: int, margin: int) -> int:
    x, _, w, _ = panel_box
    caption_position = str(panel.get("caption_position", "")).lower()
    if caption_position == "right":
        return x + w - margin - caption_width
    if caption_position == "center":
        return x + (w - caption_width) // 2
    return x + margin


def speech_bubble_width(text: str, font: ImageFont.ImageFont, panel_width: int, margin: int) -> int:
    max_w = max(120, panel_width - margin * 2)
    text_w = text_width(text, font) + 56
    if len(text) <= 6:
        preferred = max(180, text_w)
    elif len(text) <= 16:
        preferred = max(260, text_w)
    elif len(text) <= 28:
        preferred = max(320, min(text_w, int(panel_width * 0.72)))
    else:
        preferred = max(420, min(text_w, int(panel_width * 0.86)))
    return min(max_w, preferred)


def resolve_dialogue_placement(panel: dict, dialogue: dict, index: int, total_dialogues: int) -> dict:
    requested = str(dialogue.get("position") or "").strip().lower()
    locked = truthy(dialogue.get("lock_position")) or truthy(dialogue.get("fixed_position")) or truthy(panel.get("lock_dialogue_position"))
    speaker_anchor = infer_speaker_anchor(panel, dialogue)
    side = ""
    vertical = ""
    mode = "explicit" if requested and locked else "auto"
    reason = []

    if requested and requested != "bottom":
        side, vertical = parse_requested_position(requested)
        if side or vertical:
            mode = "explicit"
            reason.append(f"requested:{requested}")
    elif requested == "bottom" and locked:
        side, vertical = "left", "lower"
        reason.append("locked_bottom")

    if not side:
        side = infer_dialogue_side(panel, dialogue, index, speaker_anchor)
        reason.append(f"inferred_side:{side}")
    if not vertical:
        vertical = infer_dialogue_vertical(panel, dialogue, side, speaker_anchor)
        reason.append(f"inferred_vertical:{vertical}")

    if total_dialogues > 1 and mode == "auto":
        side = stagger_dialogue_side(side, index)
        reason.append(f"stagger:{index}")

    tail = tail_for_placement(side, vertical, mode, requested)
    return {
        "mode": mode,
        "requested_position": requested or "",
        "side": side,
        "vertical": vertical,
        "tail": tail,
        "speaker_anchor": speaker_anchor,
        "reason": ", ".join(reason),
    }


def parse_requested_position(position: str) -> tuple[str, str]:
    normalized = position.replace("-", "_").replace(" ", "_")
    side = ""
    vertical = ""
    if "left" in normalized:
        side = "left"
    elif "right" in normalized:
        side = "right"
    elif "center" in normalized or "middle" in normalized:
        side = "center"

    if "top" in normalized or "upper" in normalized:
        vertical = "upper"
    elif "bottom" in normalized or "lower" in normalized:
        vertical = "lower"
    elif "middle" in normalized or "center" in normalized:
        vertical = "middle"

    if normalized == "left":
        side, vertical = "left", "middle"
    elif normalized == "right":
        side, vertical = "right", "middle"
    elif normalized == "top":
        side, vertical = "left", "upper"
    return side, vertical


def infer_speaker_anchor(panel: dict, dialogue: dict) -> str:
    explicit = str(dialogue.get("speaker") or dialogue.get("speaker_anchor") or dialogue.get("anchor") or "").strip()
    if explicit:
        return explicit

    text = compact_text(dialogue.get("text") or "")
    reference_alias = str(panel.get("reference_alias") or "").lower()
    prompt = compact_text(" ".join(str(panel.get(key) or "") for key in ("title", "prompt", "fallback_prompt"))).lower()
    short_reaction = len(text) <= 4 or any(cue in text for cue in ("啊", "咦", "呀", "哎", "呃", "住手"))

    if short_reaction:
        for name, cues in (
            ("duanyukai", ("duan yukai", "段聿铠", "段狂")),
            ("tuobaye", ("tuobaye", "拓拔野")),
            ("shisilang", ("shisilang", "十四郎")),
            ("white_clothed_woman", ("white clothed woman", "白衣女子")),
            ("green_eyed_elder", ("green eyed elder", "青帝", "灵感仰")),
        ):
            if any(cue in prompt for cue in cues):
                return name

    if reference_alias:
        return reference_alias
    return "panel_subject"


def infer_dialogue_side(panel: dict, dialogue: dict, index: int, speaker_anchor: str) -> str:
    text = compact_text(dialogue.get("text") or "")
    speaker = compact_text(dialogue.get("speaker") or "")
    reference_alias = str(panel.get("reference_alias") or "").lower()
    prompt = compact_text(" ".join(str(panel.get(key) or "") for key in ("title", "prompt", "fallback_prompt")))
    combined = f"{speaker_anchor} {speaker} {text} {reference_alias} {prompt}".lower()

    if any(cue in combined for cue in ("right side", "stage right", "右侧", "右边", "右手", "右方")):
        return "right"
    if any(cue in combined for cue in ("left side", "stage left", "左侧", "左边", "左手", "左方")):
        return "left"

    right_leaning = ("shisilang", "white_clothed_woman", "huandian_xuanshe", "xuanshe", "十四郎", "白衣女子", "玄蛇")
    left_leaning = ("duanyukai", "tuobaye", "green_eyed_elder", "dragonhorse", "段聿铠", "拓拔野", "科沙度")
    anchor = speaker_anchor.lower()
    if any(cue in anchor for cue in left_leaning):
        return "left"
    if any(cue in anchor for cue in right_leaning):
        return "right"
    if any(cue in combined for cue in right_leaning):
        return "right"
    if any(cue in combined for cue in left_leaning):
        return "left"

    layout = panel.get("layout", {})
    width = int(layout.get("w", 0) or 0)
    height = int(layout.get("h", 0) or 0)
    if width and height and width > height * 1.5:
        return "left"
    return "left" if index % 2 == 0 else "right"


def infer_dialogue_vertical(panel: dict, dialogue: dict, side: str, speaker_anchor: str) -> str:
    prompt = compact_text(" ".join(str(panel.get(key) or "") for key in ("title", "prompt", "fallback_prompt")))
    text = compact_text(dialogue.get("text") or "")
    short_reaction = len(text) <= 4 or any(cue in text for cue in ("啊", "咦", "呀", "哎", "呃"))
    if short_reaction:
        return "lower" if panel_has_lower_character_anchor(panel, speaker_anchor) else "middle"
    if any(cue in prompt for cue in ("松枝", "树梢", "上方", "空中", "above", "branch")):
        return "upper"
    if any(cue in prompt for cue in ("落地", "地上", "庭院", "ground")) and len(text) > 12:
        return "middle"
    layout = panel.get("layout", {})
    height = int(layout.get("h", 0) or 0)
    if height >= 720 and len(text) <= 8:
        return "upper"
    if side == "center":
        return "upper"
    return "upper"


def panel_has_lower_character_anchor(panel: dict, speaker_anchor: str) -> bool:
    prompt = compact_text(" ".join(str(panel.get(key) or "") for key in ("title", "prompt", "fallback_prompt"))).lower()
    anchor = speaker_anchor.lower()
    if any(cue in prompt for cue in ("behind bamboo", "竹", "下方", "底部", "behind", "react")):
        return True
    return any(cue in anchor for cue in ("duanyukai", "tuobaye", "段聿铠", "拓拔野"))


def stagger_dialogue_side(side: str, index: int) -> str:
    if index == 0:
        return side
    if side == "left":
        return "right" if index % 2 else "left"
    if side == "right":
        return "left" if index % 2 else "right"
    return "left" if index % 2 else "right"


def tail_for_placement(side: str, vertical: str, mode: str, requested: str) -> str:
    if mode == "explicit" and requested in {"left", "right"}:
        return requested
    if vertical == "lower":
        return "top"
    return "bottom"


def speech_bubble_position(
    panel_box: tuple[int, int, int, int],
    bubble_w: int,
    bubble_h: int,
    margin: int,
    top_cursor: int,
    bottom_cursor: int,
    placement: dict,
) -> tuple[int, int, str, str]:
    x, y, w, h = panel_box
    side = placement.get("side", "left")
    vertical = placement.get("vertical", "upper")
    tail = placement.get("tail", "bottom")

    if side == "right":
        bubble_x = x + w - bubble_w - margin
    elif side == "center":
        bubble_x = x + (w - bubble_w) // 2
    else:
        bubble_x = x + margin

    if vertical == "lower":
        bubble_y = bottom_cursor - bubble_h - (BUBBLE_TAIL_LENGTH if tail == "top" else 0)
        cursor_region = "bottom"
    elif vertical == "middle":
        bubble_y = y + (h - bubble_h) // 2
        cursor_region = "middle"
    else:
        bubble_y = max(y + margin + (BUBBLE_TAIL_LENGTH if tail == "bottom" else 0), top_cursor)
        cursor_region = "top"

    return bubble_x, bubble_y, tail, cursor_region


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "locked", "fixed"}


def fit_box_inside_panel(
    text_box: tuple[int, int, int, int],
    panel_box: tuple[int, int, int, int],
    margin: int,
) -> tuple[int, int, int, int]:
    x, y, w, h = text_box
    px, py, pw, ph = panel_box
    max_w = max(48, pw - margin * 2)
    max_h = max(48, ph - margin * 2)
    w = min(max_w, max(48, w))
    h = min(max_h, max(56, h))
    x = clamp(x, px + margin, px + pw - margin - w)
    y = clamp(y, py + margin, py + ph - margin - h)
    return (x, y, w, h)


def fit_speech_bubble_inside_panel(
    text_box: tuple[int, int, int, int],
    panel_box: tuple[int, int, int, int],
    margin: int,
    tail: str,
) -> tuple[int, int, int, int]:
    x, y, w, h = fit_box_inside_panel(text_box, panel_box, margin)
    px, py, pw, ph = panel_box
    if tail == "bottom":
        y = min(y, py + ph - margin - BUBBLE_TAIL_LENGTH - h)
    elif tail == "top":
        y = max(y, py + margin + BUBBLE_TAIL_LENGTH)
    elif tail == "right":
        x = min(x, px + pw - margin - BUBBLE_TAIL_LENGTH - w)
    return fit_box_inside_panel((x, y, w, h), panel_box, margin)


def clamp(value: int, low: int, high: int) -> int:
    if high < low:
        return low
    return max(low, min(high, value))


def normalize_lettering_content(panel: dict) -> tuple[str, list[dict]]:
    caption = panel.get("caption") or ""
    dialogues = normalize_dialogue_items(panel.get("dialogue", []))
    if is_skeleton_lettering(caption):
        caption = ""
    dialogues = [item for item in dialogues if not is_skeleton_lettering(item.get("text") or "")]
    extracted_dialogues, caption = extract_dialogue_from_caption(caption, dialogues)
    dialogues.extend(extracted_dialogues)
    if caption and not dialogues and caption_should_be_dialogue(caption):
        dialogues.append({"speaker": "", "text": cleanup_dialogue_text(caption), "position": "bottom"})
        caption = ""
    caption = cleanup_caption_text(caption)
    return caption, dedupe_dialogues(dialogues)


def is_skeleton_lettering(text: str) -> bool:
    compacted = compact_text(text)
    if not compacted:
        return False
    return any(marker in compacted for marker in ("待细读", "初始页面骨架", "需要AI细读拆解", "人工审核后再生成"))


def normalize_dialogue_items(raw_dialogues) -> list[dict]:
    if not raw_dialogues:
        return []
    if isinstance(raw_dialogues, str):
        raw_dialogues = [{"text": raw_dialogues}]
    dialogues = []
    for item in raw_dialogues:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict) or not item.get("text"):
            continue
        dialogues.append(dict(item))
    return dialogues


def caption_should_be_dialogue(caption: str) -> bool:
    cleaned = cleanup_dialogue_text(caption)
    if not cleaned:
        return False
    if has_dialogue_quote_or_cue(cleaned):
        return True
    return len(cleaned) <= 28 and looks_like_dialogue(cleaned)


def has_dialogue_quote_or_cue(text: str) -> bool:
    if "“" in text or "”" in text:
        return True
    return bool(re.search(r"(?:道|说|喊|叫|问|答|喝|怒|笑|叹)\s*[：:]", text))


def extract_dialogue_from_caption(caption: str, existing_dialogues: list[dict]) -> tuple[list[dict], str]:
    extracted: list[dict] = []
    cleaned = caption

    for match in list(re.finditer(r"“([^”]+)”", cleaned)):
        quote = cleanup_dialogue_text(match.group(1))
        if quote and should_extract_dialogue(cleaned, match.start(), quote, existing_dialogues):
            extracted.append({"speaker": "", "text": quote, "position": "bottom"})
            cleaned = cleaned.replace(match.group(0), "", 1)

    cued_dialogues, cleaned = extract_cued_dialogues(cleaned, existing_dialogues + extracted)
    extracted.extend(cued_dialogues)

    if "“" in cleaned:
        before, _mark, _after = cleaned.partition("“")
        cleaned = trim_unclosed_dialogue_intro(before)

    leading_close = re.match(r"^\s*([^”]{2,80})”", cleaned)
    if leading_close:
        quote = cleanup_dialogue_text(leading_close.group(1))
        if quote and looks_like_dialogue(quote):
            extracted.append({"speaker": "", "text": quote, "position": "bottom"})
            cleaned = cleaned[leading_close.end() :]

    for dialogue in existing_dialogues + extracted:
        text = cleanup_dialogue_text(dialogue.get("text") or "")
        if text:
            cleaned = remove_dialogue_text(cleaned, text)

    return dedupe_dialogues(extracted), cleaned


def extract_cued_dialogues(caption: str, existing_dialogues: list[dict]) -> tuple[list[dict], str]:
    extracted: list[dict] = []
    cleaned = caption
    cue = r"(?:冷冷道|朗声道|厉声道|大声说道|笑道|喝道|怒道|叫道|问道|答道|说道|呼喊|道|说|喊|叫|问|答|喝|怒|叹)"
    pattern = re.compile(rf"([^。！？!?；;\n]{{0,24}}?{cue})\s*[：:]\s*([^。！？!?；;\n]{{1,90}}[。！？!?]?)")
    for match in list(pattern.finditer(caption)):
        quote = cleanup_dialogue_text(match.group(2))
        if not quote or dialogue_already_present(quote, existing_dialogues + extracted):
            cleaned = cleaned.replace(match.group(0), "", 1)
            continue
        speaker = speaker_from_dialogue_intro(match.group(1))
        extracted.append({"speaker": speaker, "text": quote, "position": "bottom"})
        cleaned = cleaned.replace(match.group(0), "", 1)
    return dedupe_dialogues(extracted), cleaned


def speaker_from_dialogue_intro(text: str) -> str:
    cleaned = re.sub(r"(?:冷冷道|朗声道|厉声道|大声说道|笑道|喝道|怒道|叫道|问道|答道|说道|呼喊|道|说|喊|叫|问|答|喝|怒|叹)$", "", text)
    cleaned = cleaned.strip(" ，,。；;：:")
    return cleaned[-8:]


def should_extract_dialogue(caption: str, quote_start: int, quote: str, existing_dialogues: list[dict]) -> bool:
    if dialogue_already_present(quote, existing_dialogues):
        return True
    prefix = caption[max(0, quote_start - 12) : quote_start]
    return bool(re.search(r"(道|说|喊|呼|叫|问|答|冷冷|朗声|大声|笑道|皱眉)\s*[：:]?$", prefix)) or looks_like_dialogue(quote)


def dialogue_already_present(quote: str, dialogues: list[dict]) -> bool:
    normalized_quote = compact_text(quote)
    for dialogue in dialogues:
        text = compact_text(dialogue.get("text") or "")
        if normalized_quote and (normalized_quote in text or text in normalized_quote):
            return True
    return False


def looks_like_dialogue(text: str) -> bool:
    cues = ("我", "你", "咱", "公子", "鹿兄", "大伙儿", "十四郎", "奉家父", "拜见", "别", "默许", "小乞丐")
    return any(cue in text for cue in cues) or "！" in text or "？" in text


def remove_dialogue_text(caption: str, dialogue_text: str) -> str:
    cleaned = caption
    variants = {
        dialogue_text,
        dialogue_text.rstrip("。！？!?"),
        f"“{dialogue_text}”",
        f"“{dialogue_text.rstrip('。！？!?')}”",
    }
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            cleaned = cleaned.replace(variant, "")
    cleaned = re.sub(r"(道|说|喊|呼|叫|问|答|冷冷道|朗声道|大声说道|笑道)\s*[：:]?\s*(?=。|，|,|\.{3}|…|$)", "", cleaned)
    return cleaned


def cleanup_dialogue_text(text: str) -> str:
    cleaned = text.strip(" \t\r\n“”\"'")
    cleaned = cleaned.lstrip("：:，,；;")
    cleaned = cleaned.rstrip("：:，,；;")
    return cleaned


def cleanup_caption_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.replace("“", "").replace("”", "")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"([：:，,。；;]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"[^。！？!?，,；;]{0,24}(?:冷冷道|朗声道|大声说道|笑道|呼喊|道|说|喊|叫|问|答)\s*[：:]", "", cleaned)
    cleaned = cleaned.strip(" ：:，,。；;")
    return cleaned


def trim_unclosed_dialogue_intro(text: str) -> str:
    cleaned = text.rstrip("：:，,。 ")
    parts = re.split(r"([。！？!?])", cleaned)
    if len(parts) >= 3:
        sentence_tail = parts[-1]
        prefix = "".join(parts[:-1])
        if re.search(r"(冷冷道|朗声道|大声说道|笑道|呼喊|道|说|喊|叫|问|答)$", sentence_tail):
            return prefix
    return re.sub(r"[^。！？!?]{0,24}(?:冷冷道|朗声道|大声说道|笑道|呼喊|道|说|喊|叫|问|答)$", "", cleaned)


def dedupe_dialogues(dialogues: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for dialogue in dialogues:
        text = cleanup_dialogue_text(dialogue.get("text") or "")
        if not text:
            continue
        key = compact_text(text)
        if key in seen:
            continue
        seen.add(key)
        item = dict(dialogue)
        item["text"] = text
        if not item.get("position"):
            item["position"] = "bottom"
        deduped.append(item)
    return deduped


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", cleanup_dialogue_text(text))


def lettering_record(
    kind: str,
    text: str,
    text_box: tuple[int, int, int, int],
    panel_box: tuple[int, int, int, int],
    style: str,
    tail_points: list[tuple[int, int]] | None,
    require_tail_inside: bool = True,
    text_result: dict | None = None,
    placement: dict | None = None,
) -> dict:
    x, y, w, h = text_box
    px, py, pw, ph = panel_box
    box_bounds = [x, y, x + w, y + h]
    tail_bounds = None
    if tail_points:
        xs = [point[0] for point in tail_points]
        ys = [point[1] for point in tail_points]
        tail_bounds = [min(xs), min(ys), max(xs), max(ys)]
    bounds = combine_bounds(box_bounds, tail_bounds)
    panel_bounds = [px, py, px + pw, py + ph]
    text_box_within_panel = bounds_within(box_bounds, panel_bounds)
    full_bounds_within_panel = bounds_within(bounds, panel_bounds)
    text_bounds = text_result.get("text_bounds") if text_result else None
    text_bounds_within_text_box = bounds_within(text_bounds, box_bounds) if text_bounds else True
    text_bounds_within_panel = bounds_within(text_bounds, panel_bounds) if text_bounds else True
    return {
        "kind": kind,
        "style": style,
        "text": text,
        "text_box": box_bounds,
        "tail_bounds": tail_bounds,
        "bounds": bounds,
        "text_bounds": text_bounds,
        "font_size": text_result.get("font_size") if text_result else None,
        "line_count": text_result.get("line_count") if text_result else None,
        "rendered_text": text_result.get("rendered_text") if text_result else text,
        "rendered_text_was_truncated": text_result.get("truncated") if text_result else False,
        "text_box_within_panel": text_box_within_panel,
        "text_bounds_within_text_box": text_bounds_within_text_box,
        "text_bounds_within_panel": text_bounds_within_panel,
        "full_bounds_within_panel": full_bounds_within_panel,
        "within_panel": (full_bounds_within_panel if require_tail_inside else text_box_within_panel) and text_bounds_within_panel,
        "placement": placement,
    }


def combine_bounds(first: list[int], second: list[int] | None) -> list[int]:
    if not second:
        return first
    return [min(first[0], second[0]), min(first[1], second[1]), max(first[2], second[2]), max(first[3], second[3])]


def bounds_within(bounds: list[int], container: list[int]) -> bool:
    return bounds[0] >= container[0] and bounds[1] >= container[1] and bounds[2] <= container[2] and bounds[3] <= container[3]


def measure_text_box_height(
    text: str,
    font: ImageFont.ImageFont,
    width: int,
    min_height: int = 76,
    max_height: int = 172,
    padding: int = 14,
) -> int:
    inner_width = max(24, width - padding * 2)
    base_size = font.size if hasattr(font, "size") else 32
    for size in range(base_size, MIN_LETTERING_FONT_SIZE - 1, -2):
        candidate = resized_font(font, size)
        lines = wrap_text(text, candidate, inner_width)
        line_h = line_height(candidate)
        needed = padding * 2 + line_h * max(1, len(lines))
        if needed <= max_height and lines_fit_width(lines, candidate, inner_width):
            return max(min_height, needed)

    fallback = resized_font(font, MIN_LETTERING_FONT_SIZE)
    line_h = line_height(fallback)
    lines = wrap_text(text, fallback, inner_width)
    max_lines = max(1, (max_height - padding * 2) // line_h)
    needed = padding * 2 + line_h * min(max(1, len(lines)), max_lines)
    return max(min_height, min(max_height, needed))


def max_text_block_height(panel_height: int) -> int:
    return min(max(128, panel_height // 2), 360)


def draw_caption_box(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], font: ImageFont.ImageFont) -> dict:
    return draw_text_box(draw, text, box, font, fill="#fbf7ed", outline="#25211c", radius=10, padding=14)


def draw_speech_bubble(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    tail: str = "bottom",
) -> tuple[list[tuple[int, int]], dict]:
    x, y, w, h = box
    radius = 24
    fill = "#fffdf8"
    outline = "#171717"
    tail_len = BUBBLE_TAIL_LENGTH
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline, width=4)

    if tail == "bottom":
        points = [(x + min(72, w - 42), y + h - 2), (x + min(112, w - 20), y + h - 2), (x + min(82, w - 24), y + h + tail_len)]
    elif tail == "right":
        points = [(x + w - 2, y + min(34, h - 30)), (x + w - 2, y + min(72, h - 16)), (x + w + tail_len, y + min(52, h - 18))]
    else:
        points = [(x + min(72, w - 42), y + 2), (x + min(112, w - 20), y + 2), (x + min(82, w - 24), y - tail_len)]

    draw.polygon(points, fill=fill, outline=outline)
    draw.line([points[0], points[2], points[1]], fill=outline, width=4)
    text_result = draw_fitted_text(draw, text, box, font, padding=18)
    return points, text_result


def draw_text_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    fill: str,
    outline: str,
    radius: int = 12,
    padding: int = 14,
) -> dict:
    x, y, w, h = box
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline, width=4)
    return draw_fitted_text(draw, text, box, font, padding=padding)


def draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    padding: int = 14,
) -> dict:
    x, y, w, h = box
    fitted_font, lines, line_h = fit_text_layout(text, font, w - padding * 2, h - padding * 2)
    text_y = y + max(padding, (h - line_h * len(lines)) // 2)
    text_bounds = None
    for line in lines:
        text_x = x + padding
        draw.text((text_x, text_y), line, fill="#1f1b17", font=fitted_font)
        bbox = draw.textbbox((text_x, text_y), line, font=fitted_font)
        text_bounds = combine_bounds(list(bbox), text_bounds) if text_bounds else list(bbox)
        text_y += line_h
    return {
        "text_bounds": text_bounds,
        "font_size": fitted_font.size if hasattr(fitted_font, "size") else None,
        "line_count": len(lines),
        "rendered_text": "\n".join(lines),
        "truncated": any(line.endswith("...") for line in lines) and compact_text(text) != compact_text("".join(lines)),
    }


def fit_text_layout(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_height: int,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    base_size = font.size if hasattr(font, "size") else 32
    for size in range(base_size, MIN_LETTERING_FONT_SIZE - 1, -2):
        candidate = resized_font(font, size)
        line_h = line_height(candidate)
        max_lines = max(1, max_height // line_h)
        lines = wrap_text(text, candidate, max_width)
        if len(lines) <= max_lines and lines_fit_width(lines, candidate, max_width):
            return candidate, lines, line_h

    fallback = resized_font(font, MIN_LETTERING_FONT_SIZE)
    line_h = line_height(fallback)
    max_lines = max(1, max_height // line_h)
    lines = fit_lines_to_box(wrap_text(text, fallback, max_width), fallback, max_width, max_lines)
    return fallback, lines, line_h


def line_height(font: ImageFont.ImageFont) -> int:
    return max(22, font.size + 8 if hasattr(font, "size") else 34)


def fit_lines_to_box(lines: list[str], font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    width_safe = [line if text_width(line, font) <= max_width else fit_ellipsis(line, font, max_width) for line in lines]
    if len(width_safe) <= max_lines:
        return width_safe
    fitted = width_safe[:max_lines]
    overflow = "".join(width_safe[max_lines - 1 :])
    fitted[-1] = fit_ellipsis(overflow, font, max_width)
    return fitted


def lines_fit_width(lines: list[str], font: ImageFont.ImageFont, max_width: int) -> bool:
    for line in lines:
        if text_width(line, font) > max_width:
            return False
    return True


def text_width(text: str, font: ImageFont.ImageFont) -> int:
    canvas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = canvas.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def fit_ellipsis(line: str, font: ImageFont.ImageFont, max_width: int) -> str:
    ellipsis = "..."
    canvas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while line:
        trial = line + ellipsis
        bbox = canvas.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return trial
        line = line[:-1]
    return ellipsis


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return []
    leading_punctuation = set("，。！？、；：,.!?;:)）】》」』”’…")
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), trial, font=font)
        if current and bbox[2] - bbox[0] > max_width:
            if char in leading_punctuation:
                lines.append(trial)
                current = ""
            else:
                lines.append(current)
                current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def resized_font(font: ImageFont.ImageFont, size: int) -> ImageFont.ImageFont:
    font_path = getattr(font, "path", None)
    if isinstance(font_path, (str, Path)):
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except OSError:
            pass
    return font


def assess_layout_quality(plan: dict, panels: list[dict]) -> dict:
    panel_count = len(panels)
    page_cfg = plan.get("page", {})
    page_area = max(1, int(page_cfg.get("width", 1600) or 1600) * int(page_cfg.get("height", 2400) or 2400))
    areas = []
    shapes = []
    warnings = []
    strengths = []

    for panel in panels:
        layout = panel.get("layout", {})
        area = int(layout.get("w", 0) or 0) * int(layout.get("h", 0) or 0)
        areas.append(area)
        shapes.append(str(layout.get("shape", "rect") or "rect").lower())

    max_area = max(areas) if areas else 0
    min_area = min(areas) if areas else 0
    dominant_ratio = round(max_area / page_area, 3) if page_area else 0
    size_ratio = round(max_area / max(1, min_area), 2) if min_area else 0
    has_dominant_panel = dominant_ratio >= 0.24 or size_ratio >= 2.2
    has_dynamic_shape = any(shape in {"slant_left", "slant_right", "polygon"} for shape in shapes)
    has_inset = any(truthy(panel.get("layout", {}).get("drop_shadow")) for panel in panels)
    has_skeleton_prompt = plan_is_skeleton(plan)

    if has_dominant_panel:
        strengths.append("页面存在明确主视觉格")
    else:
        warnings.append("缺少明确主视觉格，页面容易像平均拼贴")

    if panel_count >= 4 and size_ratio <= 1.35:
        warnings.append("面板尺寸过于接近，节奏偏机械")
    elif panel_count:
        strengths.append("面板尺寸有层级变化")

    if has_dynamic_shape:
        strengths.append("包含斜切或非矩形面板")
    if has_inset:
        strengths.append("包含嵌入反应格")
    if not has_dynamic_shape and not has_inset:
        warnings.append("缺少斜切、嵌入、出血等漫画页变化")

    if has_skeleton_prompt:
        warnings.append("当前仍是待细读骨架分镜，故事节奏和角色调度不足")

    if has_dominant_panel and (has_dynamic_shape or has_inset) and not has_skeleton_prompt:
        level = "production_candidate"
    elif has_dominant_panel or has_dynamic_shape or has_inset:
        level = "layout_prototype"
    else:
        level = "basic_collage"

    return {
        "level": level,
        "layout_style": plan.get("layout_style", ""),
        "reading_flow": plan.get("reading_flow", ""),
        "director": plan.get("director", {}),
        "panel_count": panel_count,
        "dominant_panel_ratio": dominant_ratio,
        "panel_size_ratio": size_ratio,
        "has_dynamic_shape": has_dynamic_shape,
        "has_inset": has_inset,
        "has_skeleton_prompt": has_skeleton_prompt,
        "strengths": strengths,
        "warnings": warnings,
    }


def plan_is_skeleton(plan: dict) -> bool:
    candidates = [plan.get("summary", ""), plan.get("source_excerpt", "")]
    for panel in plan.get("panels", []):
        candidates.extend([panel.get("title", ""), panel.get("prompt", ""), panel.get("fallback_prompt", "")])
    combined = "\n".join(str(item or "") for item in candidates)
    return any(marker in combined for marker in ("待细读", "初始页面骨架", "需要 AI 细读"))


def build_markdown(plan: dict, page_path: Path, panels: list[dict], layout_quality: dict | None = None) -> str:
    lines = [
        f"# {plan.get('page_id', 'Comic Page')} Review",
        "",
        f"- Updated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Source: {plan.get('source', '')}",
        f"- Title: {plan.get('title', '')}",
        f"- Page: `{page_path}`",
        "",
        f"![comic page]({page_path.as_posix()})",
        "",
        "## Layout Quality",
        "",
    ]
    if layout_quality:
        lines.extend(
            [
                f"- Level: `{layout_quality.get('level', '')}`",
                f"- Layout style: `{layout_quality.get('layout_style', '')}`",
                f"- Reading flow: {layout_quality.get('reading_flow', '')}",
                f"- Dominant panel ratio: `{layout_quality.get('dominant_panel_ratio', '')}`",
                f"- Panel size ratio: `{layout_quality.get('panel_size_ratio', '')}`",
                f"- Dynamic shape: `{layout_quality.get('has_dynamic_shape', False)}`",
                f"- Inset panel: `{layout_quality.get('has_inset', False)}`",
                f"- Skeleton prompt: `{layout_quality.get('has_skeleton_prompt', False)}`",
                "",
            ]
        )
        for warning in layout_quality.get("warnings", []):
            lines.append(f"- Warning: {warning}")
        for strength in layout_quality.get("strengths", []):
            lines.append(f"- Strength: {strength}")
        director = layout_quality.get("director") or {}
        if director:
            lines.extend(
                [
                    "",
                    f"- Director rhythm: {director.get('page_rhythm', '')}",
                    f"- Emotional arc: {director.get('emotional_arc', '')}",
                    f"- Lettering strategy: {director.get('lettering_strategy', '')}",
                    f"- Page-turn hook: {director.get('page_turn_hook', '')}",
                ]
            )
        lines.append("")
    lines.extend(
        [
        "## Panel Checks",
        "",
        ]
    )
    for panel in panels:
        lines.extend(
            [
                f"### {panel['panel_id']}",
                "",
                f"- Title: {panel.get('title', '')}",
                f"- Image exists: `{panel['exists']}`",
                f"- Panel image: `{panel['expected_panel_path']}`",
                f"- Used image: `{panel.get('used_panel_path', '')}`",
                "- [ ] identity and costume pass",
                "- [ ] setting pass",
                "- [ ] composition and readability pass",
                "- [ ] lettering pass",
                "",
            ]
        )
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
