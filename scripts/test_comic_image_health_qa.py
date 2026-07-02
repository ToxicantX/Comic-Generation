import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image


WORKSPACE = Path(r"E:\workspace\ComfyUIProjects")
MANIFESTS = WORKSPACE / "manifests"
SCRIPTS = WORKSPACE / "scripts"
OUTPUT_ROOT = Path(r"G:\ComfyUI\output\ComicPipeline")

TEST_DIR = OUTPUT_ROOT / "image_health_test"
GOOD_PANEL = TEST_DIR / "GOOD_PANEL_00001_.png"
BAD_PANEL = TEST_DIR / "BAD_PANEL_00001_.png"
PAGE_IMAGE = TEST_DIR / "IMAGE_HEALTH_TEST_P001.png"
PLAN_PATH = MANIFESTS / "comic_image_health_test_plan.json"
STATUS_PATH = MANIFESTS / "comic_image_health_test_status.json"
QA_JSON = MANIFESTS / "comic_image_health_test_qa.json"
QA_MD = OUTPUT_ROOT / "review_packages" / "IMAGE_HEALTH_TEST_image_health_qa.md"
RESULT_PATH = MANIFESTS / "comic_image_health_test_result.json"


def main() -> int:
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    write_test_images()
    write_json(PLAN_PATH, build_plan())
    write_json(STATUS_PATH, build_status())

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    run = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_comic_image_health_qa.py"),
            str(STATUS_PATH),
            str(QA_JSON),
            str(QA_MD),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    qa = read_json(QA_JSON) if QA_JSON.is_file() else {}
    issue_codes = [item.get("code") for item in qa.get("issues", [])]
    result = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "status_path": str(STATUS_PATH),
        "qa_json": str(QA_JSON),
        "qa_md": str(QA_MD),
        "exit_code": run.returncode,
        "stdout_tail": tail_lines(run.stdout),
        "stderr_tail": tail_lines(run.stderr),
        "qa_summary": qa.get("summary", {}),
        "issue_codes": issue_codes,
    }
    result["passed"] = (
        run.returncode != 0
        and qa.get("summary", {}).get("passed") is False
        and "panel_image_blank_or_flat" in issue_codes
        and not any(
            item.get("code") == "panel_image_blank_or_flat"
            and item.get("panel_id") == "IMAGE_HEALTH_TEST_P001_PANEL01"
            for item in qa.get("issues", [])
        )
    )
    write_json(RESULT_PATH, result)
    safe_print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def write_test_images() -> None:
    good = Image.new("RGB", (1024, 1536), "#23364f")
    pixels = good.load()
    for y in range(good.height):
        for x in range(good.width):
            if (x + y) % 97 == 0:
                pixels[x, y] = (220, 210, 180)
            elif (x * 3 + y * 5) % 131 == 0:
                pixels[x, y] = (70, 120, 95)
    good.save(GOOD_PANEL)
    Image.new("RGB", (1024, 1536), "#ded7c8").save(BAD_PANEL)
    page = Image.new("RGB", (1600, 2400), "#f7f4ec")
    page.paste(good.resize((700, 1000)), (60, 80))
    page.paste(Image.new("RGB", (700, 1000), "#ded7c8"), (840, 80))
    page.save(PAGE_IMAGE)


def build_plan() -> dict:
    return {
        "episode_id": "IMAGE_HEALTH_TEST",
        "page_id": "IMAGE_HEALTH_TEST_P001",
        "page": {"width": 1600, "height": 2400},
        "panels": [],
    }


def build_status() -> dict:
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_plan": str(PLAN_PATH),
        "episode_id": "IMAGE_HEALTH_TEST",
        "episode_title": "Image Health Test",
        "summary": {
            "total_pages": 1,
            "complete_pages": 1,
            "incomplete_pages": 0,
            "total_panels": 2,
            "generated_panels": 2,
            "missing_panels": 0,
        },
        "pages": [
            {
                "page_id": "IMAGE_HEALTH_TEST_P001",
                "status": "complete",
                "plan_path": str(PLAN_PATH),
                "page_image": str(PAGE_IMAGE),
                "panels": [
                    {
                        "panel_id": "IMAGE_HEALTH_TEST_P001_PANEL01",
                        "exists": True,
                        "used_panel_path": str(GOOD_PANEL),
                        "expected_panel_path": str(GOOD_PANEL),
                        "workflow": "",
                    },
                    {
                        "panel_id": "IMAGE_HEALTH_TEST_P001_PANEL02",
                        "exists": True,
                        "used_panel_path": str(BAD_PANEL),
                        "expected_panel_path": str(BAD_PANEL),
                        "workflow": "",
                    },
                ],
            }
        ],
    }


def tail_lines(text: str, limit: int = 20) -> list[str]:
    return text.splitlines()[-limit:]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    raise SystemExit(main())
