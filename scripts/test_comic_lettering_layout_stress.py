import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WORKSPACE = Path(r"E:\workspace\ComfyUIProjects")
MANIFESTS = WORKSPACE / "manifests"
SCRIPTS = WORKSPACE / "scripts"
OUTPUT_ROOT = Path(r"G:\ComfyUI\output\ComicPipeline")

PLAN_PATH = MANIFESTS / "comic_lettering_stress_plan.json"
WORKFLOW_PATH = MANIFESTS / "comic_lettering_stress_workflows.json"
ASSEMBLY_PATH = MANIFESTS / "comic_lettering_stress_assembly.json"
STATUS_PATH = MANIFESTS / "comic_lettering_stress_status.json"
QA_JSON = MANIFESTS / "comic_lettering_stress_lettering_qa.json"
QA_MD = OUTPUT_ROOT / "review_packages" / "LETTERING_STRESS_lettering_qa.md"
RESULT_PATH = MANIFESTS / "comic_lettering_stress_result.json"
PAGE_OUTPUT_DIR = OUTPUT_ROOT / "pages"
REVIEW_DIR = OUTPUT_ROOT / "review_packages" / "LETTERING_STRESS"


def main() -> int:
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    write_synthetic_panels(plan)
    write_json(PLAN_PATH, plan)
    write_json(WORKFLOW_PATH, {"created": []})
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    assembler = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_comic_page_from_panels.py"),
            str(PLAN_PATH),
            str(WORKFLOW_PATH),
            str(PAGE_OUTPUT_DIR),
            str(REVIEW_DIR),
            str(ASSEMBLY_PATH),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    write_json(STATUS_PATH, build_status())
    qa_run = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_comic_lettering_qa.py"),
            str(STATUS_PATH),
            str(QA_JSON),
            str(QA_MD),
            "--allow-missing-assemblies",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    checks = inspect_assembly()
    qa = read_json(QA_JSON) if QA_JSON.is_file() else {}
    result = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "plan_path": str(PLAN_PATH),
        "assembly_path": str(ASSEMBLY_PATH),
        "status_path": str(STATUS_PATH),
        "qa_json": str(QA_JSON),
        "qa_md": str(QA_MD),
        "assembler_exit_code": assembler.returncode,
        "assembler_exit_code_expected": 0,
        "assembler_stdout_tail": tail_lines(assembler.stdout),
        "assembler_stderr_tail": tail_lines(assembler.stderr),
        "qa_exit_code": qa_run.returncode,
        "qa_stdout_tail": tail_lines(qa_run.stdout),
        "qa_stderr_tail": tail_lines(qa_run.stderr),
        "checks": checks,
        "qa_summary": qa.get("summary", {}),
    }
    result["passed"] = (
        ASSEMBLY_PATH.is_file()
        and assembler.returncode == 0
        and qa_run.returncode == 0
        and qa.get("summary", {}).get("passed") is True
        and checks["dialogue_not_speech_bubble"] == 0
        and checks["caption_not_box"] == 0
        and checks["text_pixels_out_of_box"] == 0
        and checks["text_box_out_of_panel"] == 0
        and checks["lettering_out_of_panel"] == 0
        and checks["truncated"] == 0
        and checks["dialogue_items"] >= 5
        and checks["caption_items"] >= 2
    )
    write_json(RESULT_PATH, result)
    safe_print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def build_plan() -> dict:
    return {
        "updated": datetime.now().date().isoformat(),
        "project": "Longform Comic Generation Pipeline",
        "episode_id": "LETTERING_STRESS",
        "page_id": "LETTERING_STRESS_P001",
        "title": "Lettering Stress Page",
        "source": "synthetic regression case",
        "page": {
            "width": 1200,
            "height": 1600,
            "background": "#f7f4ec",
            "gutter": 24,
            "border": 8,
        },
        "panels": [
            {
                "panel_id": "LETTERING_STRESS_P001_PANEL01",
                "order": 1,
                "title": "narrow long dialogue",
                "layout": {"x": 40, "y": 50, "w": 360, "h": 300},
                "filename_prefix": "ComicPipeline/lettering_stress/PANEL01",
                "caption": "",
                "dialogue": [
                    {
                        "text": "灵感仰老匹夫，你龟缩屋中不敢见人，难道真怕故人问你三十年前的旧账吗？",
                        "position": "bottom",
                    }
                ],
            },
            {
                "panel_id": "LETTERING_STRESS_P001_PANEL02",
                "order": 2,
                "title": "caption quote extraction",
                "layout": {"x": 430, "y": 50, "w": 700, "h": 300},
                "filename_prefix": "ComicPipeline/lettering_stress/PANEL02",
                "caption": "黑衣老者低声道：“公子，此地不可妄动刀兵。”竹影摇晃，众人屏息。",
                "dialogue": [],
            },
            {
                "panel_id": "LETTERING_STRESS_P001_PANEL03",
                "order": 3,
                "title": "long narration box",
                "layout": {"x": 40, "y": 390, "w": 1090, "h": 360},
                "filename_prefix": "ComicPipeline/lettering_stress/PANEL03",
                "caption": "山风卷过玉屏峰，竹楼与庭院之间只剩冷光，所有人的视线都被那道忽然膨胀的黑影牵住。",
                "dialogue": [],
            },
            {
                "panel_id": "LETTERING_STRESS_P001_PANEL04",
                "order": 4,
                "title": "multiple bubbles",
                "layout": {"x": 40, "y": 790, "w": 1090, "h": 620},
                "filename_prefix": "ComicPipeline/lettering_stress/PANEL04",
                "caption": "玄蛇压低身形，庭院内外同时变色。",
                "dialogue": [
                    {"text": "啊！那不是鞭子，是活物！", "position": "top"},
                    {"text": "退后，别让它越过竹门。", "position": "right"},
                    "十四郎，你还要硬撑到什么时候？",
                ],
            },
        ],
    }


def build_status() -> dict:
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_id": "LETTERING_STRESS",
        "episode_title": "Lettering Stress Page",
        "summary": {
            "total_pages": 1,
            "complete_pages": 0,
            "incomplete_pages": 1,
            "total_panels": 4,
            "generated_panels": 0,
            "missing_panels": 4,
        },
        "pages": [
            {
                "page_id": "LETTERING_STRESS_P001",
                "status": "incomplete",
                "assembly_path": str(ASSEMBLY_PATH),
                "page_image": str(PAGE_OUTPUT_DIR / "LETTERING_STRESS_P001.png"),
            }
        ],
}


def write_synthetic_panels(plan: dict) -> None:
    palette = ["#6f8f72", "#9b7b5a", "#5f789c", "#8e6a86"]
    font = load_font(32)
    for index, panel in enumerate(plan.get("panels", [])):
        layout = panel.get("layout", {})
        width = int(layout.get("w", 400))
        height = int(layout.get("h", 300))
        path = expected_panel_output_path(panel)
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (width, height), palette[index % len(palette)])
        draw = ImageDraw.Draw(image)
        draw.rectangle([10, 10, width - 11, height - 11], outline="#f8f1df", width=5)
        title = str(panel.get("title", panel.get("panel_id", "")))
        draw.text((28, 28), title[:28], fill="#fff8e8", font=font)
        draw.line([20, height - 40, width - 20, height - 80], fill="#241f1b", width=6)
        image.save(path)


def expected_panel_output_path(panel: dict) -> Path:
    prefix = panel.get("fallback_filename_prefix") or panel.get("filename_prefix") or ""
    return Path(r"G:\ComfyUI\output") / f"{prefix}_00001_.png"


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def inspect_assembly() -> dict:
    checks = {
        "lettering_items": 0,
        "dialogue_items": 0,
        "caption_items": 0,
        "dialogue_not_speech_bubble": 0,
        "caption_not_box": 0,
        "text_pixels_out_of_box": 0,
        "text_box_out_of_panel": 0,
        "lettering_out_of_panel": 0,
        "truncated": 0,
        "short_caption_too_wide": 0,
        "short_dialogue_too_wide": 0,
        "min_font_size": None,
        "max_font_size": None,
        "bad_items": [],
    }
    if not ASSEMBLY_PATH.is_file():
        checks["bad_items"].append({"code": "missing_assembly", "path": str(ASSEMBLY_PATH)})
        return checks

    assembly = read_json(ASSEMBLY_PATH)
    font_sizes = []
    for panel in assembly.get("panels", []):
        panel_id = panel.get("panel_id", "")
        layout = panel.get("layout") or {}
        panel_width = int(layout.get("w", 0) or 0)
        for item in panel.get("lettering") or []:
            checks["lettering_items"] += 1
            kind = item.get("kind", "")
            style = item.get("style", "")
            if kind == "dialogue":
                checks["dialogue_items"] += 1
                if style != "speech_bubble":
                    add_bad(checks, panel_id, "dialogue_not_speech_bubble", item)
            if kind == "caption":
                checks["caption_items"] += 1
                if style != "box":
                    add_bad(checks, panel_id, "caption_not_box", item)
            if not item.get("text_bounds_within_text_box", True):
                add_bad(checks, panel_id, "text_pixels_out_of_box", item)
            if not item.get("text_box_within_panel", True):
                add_bad(checks, panel_id, "text_box_out_of_panel", item)
            if not item.get("within_panel", True):
                add_bad(checks, panel_id, "lettering_out_of_panel", item)
            if item.get("rendered_text_was_truncated", False):
                add_bad(checks, panel_id, "truncated", item)
            if kind == "caption" and len(str(item.get("text", ""))) <= 24 and panel_width:
                text_box = item.get("text_box") or [0, 0, 0, 0]
                box_width = int(text_box[2]) - int(text_box[0])
                if box_width > int(panel_width * 0.78):
                    add_bad(checks, panel_id, "short_caption_too_wide", item)
            if kind == "dialogue" and len(str(item.get("text", ""))) <= 6 and panel_width:
                text_box = item.get("text_box") or [0, 0, 0, 0]
                box_width = int(text_box[2]) - int(text_box[0])
                if box_width > 260:
                    add_bad(checks, panel_id, "short_dialogue_too_wide", item)
            if item.get("font_size"):
                font_sizes.append(int(item["font_size"]))

    if font_sizes:
        checks["min_font_size"] = min(font_sizes)
        checks["max_font_size"] = max(font_sizes)
    return checks


def add_bad(checks: dict, panel_id: str, code: str, item: dict) -> None:
    checks[code] += 1
    checks["bad_items"].append(
        {
            "panel_id": panel_id,
            "code": code,
            "kind": item.get("kind"),
            "style": item.get("style"),
            "text": item.get("text"),
            "text_box": item.get("text_box"),
            "text_bounds": item.get("text_bounds"),
        }
    )


def tail_lines(text: str, limit: int = 20) -> list[str]:
    return text.splitlines()[-limit:]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
    sys.stdout.buffer.write(b"\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
