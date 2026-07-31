import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageStat


DEFAULT_STATUS = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode03_status.json")
DEFAULT_OUTPUT_JSON = Path(r"E:\workspace\ComfyUIProjects\manifests\ssj_comic_episode03_image_health_qa.json")
DEFAULT_OUTPUT_MD = Path(r"G:\ComfyUI\output\ComicPipeline\review_packages\SSJ_COMIC_EP03_image_health_qa.md")


def main() -> int:
    args = parse_args()
    status_path = Path(args.status_path)
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    status = read_json(status_path)

    pages = []
    issues = []
    warnings = []
    checked_panel_images = 0
    checked_page_images = 0
    pending_generation = 0

    for page in status.get("pages", []):
        page_result = check_page(page, args)
        pages.append(page_result)
        issues.extend(page_result["issues"])
        warnings.extend(page_result["warnings"])
        checked_page_images += 1 if page_result.get("page_image", {}).get("checked") else 0
        for panel in page_result.get("panels", []):
            if panel.get("checked"):
                checked_panel_images += 1
            if panel.get("pending_generation"):
                pending_generation += 1

    qa = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "status_path": str(status_path),
        "episode_id": status.get("episode_id"),
        "episode_title": status.get("episode_title"),
        "summary": {
            "pages": len(pages),
            "checked_page_images": checked_page_images,
            "generated_panels": checked_panel_images,
            "checked_panel_images": checked_panel_images,
            "pending_generation": pending_generation,
            "issues": len(issues),
            "warnings": len(warnings),
            "passed": len(issues) == 0,
        },
        "issues": issues,
        "warnings": warnings,
        "pages": pages,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(build_markdown(qa), encoding="utf-8")
    print(json.dumps(qa["summary"], ensure_ascii=False, indent=2))
    return 0 if qa["summary"]["passed"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate basic health of comic panel and page image files.")
    parser.add_argument("status_path", nargs="?", default=str(DEFAULT_STATUS))
    parser.add_argument("output_json", nargs="?", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("output_md", nargs="?", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-panel-width", type=int, default=512)
    parser.add_argument("--min-panel-height", type=int, default=512)
    parser.add_argument("--min-page-width", type=int, default=800)
    parser.add_argument("--min-page-height", type=int, default=1000)
    parser.add_argument("--blank-stddev", type=float, default=2.0)
    parser.add_argument("--low-contrast-stddev", type=float, default=8.0)
    parser.add_argument("--min-panel-bytes", type=int, default=30000)
    parser.add_argument("--min-page-bytes", type=int, default=30000)
    return parser.parse_args()


def check_page(page: dict, args: argparse.Namespace) -> dict:
    page_id = page.get("page_id", "")
    issues = []
    warnings = []
    expected_page_size = read_expected_page_size(page)
    page_image = check_image_file(
        path=page.get("page_image", ""),
        page_id=page_id,
        panel_id="",
        image_kind="page",
        min_width=args.min_page_width,
        min_height=args.min_page_height,
        min_bytes=args.min_page_bytes,
        expected_size=expected_page_size,
        args=args,
    )
    issues.extend(page_image["issues"])
    warnings.extend(page_image["warnings"])

    panels = []
    for panel in page.get("panels", []):
        panel_id = panel.get("panel_id", "")
        layout = panel_layout_from_page_plan(page, panel_id)
        expected_layout_size = expected_size_for_layout(layout)
        workflow_size = read_expected_workflow_size(panel.get("workflow", ""))
        if not panel.get("exists", False):
            if expected_layout_size and workflow_size and workflow_size != expected_layout_size:
                warnings.append(
                    issue(
                        page_id,
                        panel_id,
                        "pending_panel_workflow_size_aspect_mismatch",
                        f"workflow={workflow_size[0]}x{workflow_size[1]} expected_for_layout={expected_layout_size[0]}x{expected_layout_size[1]} layout={layout.get('w')}x{layout.get('h')}",
                    )
                )
            pending = issue(page_id, panel_id, "pending_generation", panel.get("expected_panel_path", ""))
            warnings.append(pending)
            panels.append(
                {
                    "panel_id": panel_id,
                    "path": panel.get("expected_panel_path", ""),
                    "checked": False,
                    "pending_generation": True,
                    "issues": [],
                    "warnings": [pending],
                }
            )
            continue
        panel_result = check_image_file(
            path=panel.get("used_panel_path") or panel.get("expected_panel_path", ""),
            page_id=page_id,
            panel_id=panel_id,
            image_kind="panel",
            min_width=args.min_panel_width,
            min_height=args.min_panel_height,
            min_bytes=args.min_panel_bytes,
            expected_size=workflow_size,
            args=args,
        )
        panels.append(panel_result)
        issues.extend(panel_result["issues"])
        warnings.extend(panel_result["warnings"])

    return {
        "page_id": page_id,
        "status": page.get("status", ""),
        "page_image": page_image,
        "panels": panels,
        "issues": issues,
        "warnings": warnings,
    }


def check_image_file(
    path: str,
    page_id: str,
    panel_id: str,
    image_kind: str,
    min_width: int,
    min_height: int,
    min_bytes: int,
    expected_size: tuple[int, int] | None,
    args: argparse.Namespace,
) -> dict:
    result = {
        "panel_id": panel_id,
        "path": path,
        "kind": image_kind,
        "checked": False,
        "pending_generation": False,
        "expected_size": list(expected_size) if expected_size else None,
        "metrics": {},
        "issues": [],
        "warnings": [],
    }
    if not path:
        result["issues"].append(issue(page_id, panel_id, f"missing_{image_kind}_image_path", ""))
        return result
    image_path = Path(path)
    if not image_path.is_file():
        result["issues"].append(issue(page_id, panel_id, f"missing_{image_kind}_image_file", path))
        return result

    try:
        metrics = image_metrics(image_path)
    except Exception as exc:
        result["issues"].append(issue(page_id, panel_id, f"unreadable_{image_kind}_image", f"{path}: {exc}"))
        return result

    result["checked"] = True
    result["metrics"] = metrics
    width = int(metrics["width"])
    height = int(metrics["height"])
    if width < min_width or height < min_height:
        result["issues"].append(issue(page_id, panel_id, f"{image_kind}_image_too_small", f"{path} {width}x{height}"))
    if expected_size and (width, height) != expected_size:
        size_delta = max(abs(width - expected_size[0]), abs(height - expected_size[1]))
        target = result["warnings"] if size_delta <= 1 else result["issues"]
        code = f"{image_kind}_image_size_variance" if size_delta <= 1 else f"{image_kind}_image_size_mismatch"
        target.append(
            issue(page_id, panel_id, code, f"{path} actual={width}x{height} expected={expected_size[0]}x{expected_size[1]}")
        )
    if int(metrics["bytes"]) < min_bytes:
        result["warnings"].append(issue(page_id, panel_id, f"{image_kind}_image_file_small", f"{path} bytes={metrics['bytes']}"))
    if is_blank_or_flat(metrics, args.blank_stddev):
        result["issues"].append(issue(page_id, panel_id, f"{image_kind}_image_blank_or_flat", path))
    elif float(metrics["max_stddev"]) < args.low_contrast_stddev:
        result["warnings"].append(issue(page_id, panel_id, f"{image_kind}_image_low_contrast", f"{path} max_stddev={metrics['max_stddev']:.2f}"))
    return result


def image_metrics(path: Path) -> dict:
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
        rgb = image.convert("RGB")
        sample = rgb.resize((64, 64), Image.Resampling.BILINEAR)
        stat = ImageStat.Stat(sample)
        colors = sample.getcolors(maxcolors=4096)
        unique_colors = len(colors) if colors is not None else 4097
        extrema = sample.getextrema()
        stddev = [float(value) for value in stat.stddev]
        mean = [float(value) for value in stat.mean]
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "mode": mode,
        "mean": mean,
        "stddev": stddev,
        "max_stddev": max(stddev) if stddev else 0.0,
        "unique_colors_64px": unique_colors,
        "extrema_64px": extrema,
    }


def is_blank_or_flat(metrics: dict, blank_stddev: float) -> bool:
    if int(metrics.get("unique_colors_64px", 0)) <= 2:
        return True
    return float(metrics.get("max_stddev", 0.0)) <= blank_stddev


def read_expected_page_size(page: dict) -> tuple[int, int] | None:
    plan_path = Path(page.get("plan_path") or "")
    if not plan_path.is_file():
        return None
    plan = read_json(plan_path)
    page_cfg = plan.get("page", {})
    width = int(page_cfg.get("width", 0) or 0)
    height = int(page_cfg.get("height", 0) or 0)
    return (width, height) if width and height else None


def panel_layout_from_page_plan(page: dict, panel_id: str) -> dict:
    plan_path = Path(page.get("plan_path") or "")
    if not plan_path.is_file():
        return {}
    plan = read_json(plan_path)
    for panel in plan.get("panels", []):
        if panel.get("panel_id") == panel_id:
            return panel.get("layout", {}) or {}
    return {}


def expected_size_for_layout(layout: dict) -> tuple[int, int] | None:
    width = float(layout.get("w", 0) or 0)
    height = float(layout.get("h", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    if ratio >= 1.25:
        return (1536, 1024)
    if ratio <= 0.80:
        return (1024, 1536)
    return (1024, 1024)


def read_expected_workflow_size(workflow_path: str) -> tuple[int, int] | None:
    path = Path(workflow_path or "")
    if not path.is_file():
        return None
    workflow = read_json(path)
    prompt = workflow.get("prompt", {})
    if not isinstance(prompt, dict):
        return None
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        if node.get("class_type") == "OpenAICompatibleImageGenerate":
            size = str(inputs.get("size", ""))
            match = re.match(r"^\s*(\d+)\s*x\s*(\d+)\s*$", size)
            if match:
                return (int(match.group(1)), int(match.group(2)))
        if node.get("class_type") == "EmptyLatentImage":
            try:
                return (int(inputs.get("width")), int(inputs.get("height")))
            except (TypeError, ValueError):
                continue
    return None


def issue(page_id: str, panel_id: str, code: str, detail: str) -> dict:
    return {
        "page_id": page_id,
        "panel_id": panel_id,
        "code": code,
        "detail": detail,
    }


def build_markdown(qa: dict) -> str:
    summary = qa["summary"]
    lines = [
        f"# {qa.get('episode_id')} Image Health QA",
        "",
        f"- Updated: {qa.get('updated')}",
        f"- Title: {qa.get('episode_title', '')}",
        f"- Passed: `{summary['passed']}`",
        f"- Checked page images: {summary['checked_page_images']} / {summary['pages']}",
        f"- Checked generated panel images: {summary['checked_panel_images']}",
        f"- Pending generation: {summary['pending_generation']}",
        f"- Issues: {summary['issues']}",
        f"- Warnings: {summary['warnings']}",
        "",
        "This report catches low-level image-file failures. It does not judge character likeness or art direction.",
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
    return "\n".join(lines)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
