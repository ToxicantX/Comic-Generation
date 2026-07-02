import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from text_model_client import chat_json, is_configured, text_model_config


def project_token(slug: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(slug or "")).strip("_").upper()
    return token or "NOVEL"


def episode_code(slug: str, number: int) -> str:
    return f"{project_token(slug)}_EP{number:02d}"


def episode_stem(slug: str, number: int) -> str:
    return f"{project_token(slug).lower()}_episode{number:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a novel into comic project manifests.")
    parser.add_argument("--novel", required=True)
    parser.add_argument("--project-slug", required=True)
    parser.add_argument("--project-title", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--encoding", default="gb18030")
    parser.add_argument("--pages-per-chapter", type=int, default=8)
    parser.add_argument("--panels-per-page", type=int, default=4)
    parser.add_argument("--skeleton-count", type=int, default=3)
    parser.add_argument("--skip-text-model", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    novel_path = Path(args.novel)
    if not novel_path.is_file():
        raise SystemExit(f"Novel file not found: {novel_path}")

    project_dir = Path(args.output_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    text = novel_path.read_text(encoding=args.encoding, errors="replace")
    lines = text.splitlines()
    title = args.project_title.strip() or novel_path.stem
    chapter_index = build_chapter_index(lines, title)
    if not any(item.get("type") == "chapter" for item in chapter_index):
        chapter_index = fallback_chapter_index(lines, title)
    attach_chapter_excerpts(chapter_index, lines)

    model_result = {}
    model_error = ""
    if is_configured() and not args.skip_text_model:
        try:
            model_result = enrich_with_text_model(title, chapter_index, text[:8000])
            apply_model_result(chapter_index, model_result)
        except Exception as exc:
            model_error = str(exc)

    series = build_series_plan(
        title=title,
        slug=args.project_slug,
        novel_path=novel_path,
        chapter_index=chapter_index,
        pages_per_chapter=args.pages_per_chapter,
        panels_per_page=args.panels_per_page,
        model_result=model_result,
        model_error=model_error,
    )
    chapter_index_path = project_dir / f"{args.project_slug}_chapter_index.json"
    series_plan_path = project_dir / f"{args.project_slug}_comic_series_plan.json"
    chapter_index_path.write_text(json.dumps(chapter_index, ensure_ascii=False, indent=2), encoding="utf-8")
    series_plan_path.write_text(json.dumps(series, ensure_ascii=False, indent=2), encoding="utf-8")

    skeletons = create_episode_skeletons(
        project_dir=project_dir,
        series=series,
        count=args.skeleton_count,
        pages_per_chapter=args.pages_per_chapter,
        panels_per_page=args.panels_per_page,
        force=args.force,
    )

    result = {
        "ok": True,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "project_slug": args.project_slug,
        "project_title": title,
        "novel_path": str(novel_path),
        "chapter_index_path": str(chapter_index_path),
        "series_plan_path": str(series_plan_path),
        "chapters": len([item for item in chapter_index if item.get("type") == "chapter"]),
        "episodes": len(series.get("episodes", [])),
        "skeletons": skeletons,
        "text_model": {
            "configured": is_configured(),
            "model": text_model_config().get("model", ""),
            "used": bool(model_result),
            "error": model_error,
        },
    }
    result_path = project_dir / f"{args.project_slug}_novel_process_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_chapter_index(lines: list[str], title: str) -> list[dict]:
    entries = [{"type": "volume", "title": title, "line": 1}]
    current_volume = title
    chapter_pattern = re.compile(
        r"^\s*(第[一二三四五六七八九十百千万零〇两\d]+[章节回卷部集].{0,48}|卷[一二三四五六七八九十百千万零〇两\d]+.{0,48}|Chapter\s+\d+.{0,80})\s*$",
        re.IGNORECASE,
    )
    volume_pattern = re.compile(r"^\s*(第[一二三四五六七八九十百千万零〇两\d]+卷.{0,48}|卷[一二三四五六七八九十百千万零〇两\d]+.{0,48})\s*$")
    seen_chapter_lines = set()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or len(stripped) > 90:
            continue
        if volume_pattern.match(stripped) and "章" not in stripped:
            current_volume = stripped
            entries.append({"type": "volume", "title": stripped, "line": number})
            continue
        if chapter_pattern.match(stripped):
            if number in seen_chapter_lines:
                continue
            seen_chapter_lines.add(number)
            entries.append({"type": "chapter", "volume": current_volume, "title": stripped, "line": number})
    return entries


def fallback_chapter_index(lines: list[str], title: str) -> list[dict]:
    body_lines = [line for line in lines if line.strip()]
    chunk_size = max(1, len(body_lines) // 12)
    entries = [{"type": "volume", "title": title, "line": 1}]
    source_line = 1
    chapter_number = 1
    for index in range(0, len(body_lines), chunk_size):
        entries.append({
            "type": "chapter",
            "volume": title,
            "title": f"第{chapter_number}章",
            "line": source_line,
        })
        source_line += chunk_size
        chapter_number += 1
        if chapter_number > 12:
            break
    return entries


def attach_chapter_excerpts(chapter_index: list[dict], lines: list[str], max_chars: int = 1200) -> None:
    chapters = [item for item in chapter_index if item.get("type") == "chapter"]
    for index, chapter in enumerate(chapters):
        start_line = max(int(chapter.get("line") or 1), 1)
        next_line = int(chapters[index + 1].get("line") or len(lines) + 1) if index + 1 < len(chapters) else len(lines) + 1
        body = "\n".join(line.strip() for line in lines[start_line: max(start_line, next_line - 1)] if line.strip())
        excerpt = body[:max_chars].strip()
        if excerpt:
            chapter["excerpt"] = excerpt


def enrich_with_text_model(title: str, chapter_index: list[dict], excerpt: str) -> dict:
    chapters = [item for item in chapter_index if item.get("type") == "chapter"][:30]
    messages = [
        {
            "role": "system",
            "content": (
                "你是漫画改编的小说处理助手。只返回 JSON。"
                "任务是检查章节识别结果，给出中文项目名、章节标题清理建议和改编备注。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "novel_title": title,
                    "detected_chapters": chapters,
                    "novel_excerpt": excerpt,
                    "required_schema": {
                        "project_title": "中文作品名",
                        "chapters": [{"line": 1, "title": "清理后的章节名", "volume": "卷名"}],
                        "adaptation_notes": ["改编注意事项"],
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    return chat_json(messages)


def apply_model_result(chapter_index: list[dict], model_result: dict) -> None:
    by_line = {
        int(item.get("line")): item
        for item in model_result.get("chapters", [])
        if str(item.get("line", "")).isdigit()
    }
    for item in chapter_index:
        if item.get("type") != "chapter":
            continue
        suggestion = by_line.get(int(item.get("line", 0)))
        if not suggestion:
            continue
        item["raw_title"] = item.get("title", "")
        item["title"] = str(suggestion.get("title") or item.get("title") or "").strip()
        if suggestion.get("volume"):
            item["volume"] = str(suggestion["volume"]).strip()
        item["text_model_enriched"] = True


def build_series_plan(
    title: str,
    slug: str,
    novel_path: Path,
    chapter_index: list[dict],
    pages_per_chapter: int,
    panels_per_page: int,
    model_result: dict,
    model_error: str,
) -> dict:
    chapters = [item for item in chapter_index if item.get("type") == "chapter"]
    volumes = [item for item in chapter_index if item.get("type") == "volume"]
    episodes = []
    volume_stats = {}
    for index, chapter in enumerate(chapters, start=1):
        volume = str(chapter.get("volume") or title)
        stats = volume_stats.setdefault(volume, {"volume": volume, "chapters": 0, "planned_pages": 0, "planned_panels": 0})
        stats["chapters"] += 1
        stats["planned_pages"] += pages_per_chapter
        stats["planned_panels"] += pages_per_chapter * panels_per_page
        episodes.append({
            "episode_id": episode_code(slug, index),
            "source_volume": volume,
            "chapter_title": chapter.get("title", f"第{index}章"),
            "chapter_line": chapter.get("line", 1),
            "chapter_number_in_volume": stats["chapters"],
            "priority": "P0_first_batch" if index <= 6 else "P1_backlog",
            "planned_pages": pages_per_chapter,
            "planned_panels": pages_per_chapter * panels_per_page,
            "status": "needs_close_reading",
            "next_required_inputs": ["章节细读", "分镜草稿", "素材确认", "漫画生成"],
        })
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "project": title,
        "project_slug": slug,
        "source": title,
        "source_novel": str(novel_path),
        "assumptions": {
            "pages_per_chapter": pages_per_chapter,
            "panels_per_page": panels_per_page,
            "note": "这是小说处理生成的初始计划，每章仍需要人工审核。",
        },
        "text_model": {
            "configured": is_configured(),
            "model": text_model_config().get("model", ""),
            "used": bool(model_result),
            "error": model_error,
            "adaptation_notes": model_result.get("adaptation_notes", []) if isinstance(model_result, dict) else [],
        },
        "totals": {
            "volumes": len(volumes),
            "chapters": len(chapters),
            "planned_pages": len(chapters) * pages_per_chapter,
            "planned_panels": len(chapters) * pages_per_chapter * panels_per_page,
        },
        "volumes": list(volume_stats.values()),
        "episodes": episodes,
    }


def create_episode_skeletons(
    project_dir: Path,
    series: dict,
    count: int,
    pages_per_chapter: int,
    panels_per_page: int,
    force: bool,
) -> list[dict]:
    if count <= 0:
        return []
    created = []
    for episode in series.get("episodes", [])[: max(1, count)]:
        number = episode_number_from_id(episode.get("episode_id", ""))
        if not number:
            continue
        episode_id = episode.get("episode_id") or episode_code(series.get("project_slug", ""), number)
        output_path = project_dir / f"{episode_stem(series.get('project_slug', ''), number)}_pages.json"
        if output_path.exists() and not force:
            created.append({"episode_number": number, "status": "existing_kept", "path": str(output_path)})
            continue
        pages = []
        for page_index in range(1, pages_per_chapter + 1):
            page_id = f"{episode_id}_P{page_index:03d}"
            panels = []
            for panel_index in range(1, panels_per_page + 1):
                panels.append({
                    "title": f"待细读分镜 {panel_index}",
                    "reference_alias": "",
                    "caption": "",
                    "dialogue": [],
                    "panel_id": f"{page_id}_PANEL{panel_index:02d}",
                    "prompt": (
                        f"待细读：{episode.get('source_volume')} {episode.get('chapter_title')}，"
                        f"第 {page_index} 页第 {panel_index} 格。中国神话幻想漫画，无画面文字。"
                    ),
                })
            pages.append({
                "page_id": page_id,
                "status": "skeleton_needs_close_reading",
                "beat_ids": [],
                "title": f"{episode.get('chapter_title')} P{page_index:02d}",
                "summary": f"{episode.get('chapter_title')} 的初始页面骨架，需要小说处理和人工审核后再生成。",
                "panels": panels,
            })
        episode_plan = {
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "project": series.get("project", ""),
            "source": f"{series.get('source', '')} {episode.get('source_volume', '')} {episode.get('chapter_title', '')}".strip(),
            "source_volume": episode.get("source_volume"),
            "source_chapter_title": episode.get("chapter_title"),
            "source_chapter_line": episode.get("chapter_line"),
            "episode_id": episode_id,
            "episode_title": episode.get("chapter_title"),
            "skeleton": True,
            "close_reading_required": True,
            "style_bible": "",
            "character_cards": [],
            "page_defaults": {
                "width": 1600,
                "height": 2400,
                "background": "#f8f1df",
                "gutter": 36,
                "border": 8,
                "reading_order": "left-to-right, top-to-bottom",
            },
            "asset_aliases": {},
            "global_prompt_block": "中国神话幻想漫画，水墨与厚涂结合，清晰剪影，电影分镜。",
            "negative_prompt": "text, watermark, logo, extra fingers, distorted hands, gore, nudity",
            "pages": pages,
        }
        output_path.write_text(json.dumps(episode_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append({"episode_number": number, "status": "created", "path": str(output_path), "pages": len(pages)})
    return created


def episode_number_from_id(value: str) -> int:
    match = re.search(r"EP0*(\d+)$", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


if __name__ == "__main__":
    raise SystemExit(main())
