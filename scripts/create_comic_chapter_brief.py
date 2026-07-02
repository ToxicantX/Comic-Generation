import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from text_model_client import chat_json, is_configured, text_model_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--novel", default=r"E:\workspace\ComfyUIProjects\搜神记.txt")
    parser.add_argument("--chapter-index", default=r"E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_chapter_index.json")
    parser.add_argument("--series-plan", default=r"E:\workspace\ComfyUIProjects\manifests\sou_shen_ji_comic_series_plan.json")
    parser.add_argument("--episode-number", type=int, required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--encoding", default="gb18030")
    parser.add_argument("--excerpt-chars", type=int, default=3600)
    parser.add_argument("--pages", type=int, default=8)
    args = parser.parse_args()

    chapter_index = read_json(Path(args.chapter_index))
    series_plan = read_json(Path(args.series_plan))
    episode = episode_by_number(series_plan, args.episode_number)
    if not episode:
        raise SystemExit(f"Episode {args.episode_number} not found in series plan")

    novel_lines = Path(args.novel).read_text(encoding=args.encoding, errors="replace").splitlines()
    chapter = matching_chapter(chapter_index, episode)
    if not chapter:
        raise SystemExit(f"Chapter not found for episode {episode.get('episode_id')}")
    next_chapter = next_chapter_after(chapter_index, chapter)

    start = max(0, int(chapter["line"]) - 1)
    end = max(start + 1, int(next_chapter["line"]) - 1) if next_chapter else len(novel_lines)
    chapter_text = "\n".join(line.strip() for line in novel_lines[start:end] if line.strip())
    clean_text = normalize_text(chapter_text)
    excerpt = clean_text[: args.excerpt_chars]
    cues = visual_cues(excerpt)
    page_beats = build_page_beats(episode, excerpt, cues, args.pages)
    model_error = ""
    model_used = False
    if is_configured():
        try:
            model_result = build_page_beats_with_model(episode, excerpt, cues, args.pages)
            if model_result.get("page_beats"):
                page_beats = model_result["page_beats"][: args.pages]
                model_used = True
        except Exception as exc:
            model_error = str(exc)

    output = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "project": "Longform Comic Generation Pipeline",
        "episode_id": comic_episode_id(args.episode_number),
        "series_episode_id": episode.get("episode_id"),
        "source_volume": episode.get("source_volume"),
        "chapter_title": episode.get("chapter_title"),
        "chapter_line": chapter.get("line"),
        "next_chapter_line": next_chapter.get("line") if next_chapter else None,
        "source_encoding": args.encoding,
        "chapter_char_count": len(clean_text),
        "excerpt_char_count": len(excerpt),
        "adaptation_status": "brief_from_source_excerpt_needs_human_close_reading",
        "source_excerpt": excerpt,
        "visual_cues": cues,
        "page_beats": page_beats,
        "text_model": {
            "configured": is_configured(),
            "model": text_model_config().get("model", ""),
            "used": model_used,
            "error": model_error,
        },
        "notes": [
            "This brief is grounded in the chapter excerpt but is still a production draft.",
            "Before final image generation, replace skeleton prompts with close-read panel prompts and verify names, props, and continuity.",
        ],
    }

    output_path = Path(args.output) if args.output else Path(r"E:\workspace\ComfyUIProjects\manifests") / f"ssj_comic_ep{args.episode_number:02d}_chapter_brief.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def episode_by_number(series_plan: dict, number: int) -> dict | None:
    pattern = re.compile(r"EP0*(\d+)$")
    for episode in series_plan.get("episodes", []):
        match = pattern.search(str(episode.get("episode_id", "")))
        if match and int(match.group(1)) == number:
            return episode
    return None


def matching_chapter(chapter_index: list[dict], episode: dict) -> dict | None:
    volume = episode.get("source_volume")
    title = episode.get("chapter_title")
    for item in chapter_index:
        if item.get("type") == "chapter" and item.get("volume") == volume and item.get("title") == title:
            return item
    return None


def next_chapter_after(chapter_index: list[dict], chapter: dict) -> dict | None:
    seen = False
    for item in chapter_index:
        if item is chapter:
            seen = True
            continue
        if seen and item.get("type") == "chapter":
            return item
    return None


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def visual_cues(text: str) -> list[str]:
    keywords = [
        "山", "海", "湖", "水", "火", "风", "云", "月", "日", "光", "城", "宫", "舟", "龙", "鸟", "花", "草", "树", "血", "剑",
        "少女", "少年", "老人", "男子", "女子", "神", "妖", "仙", "兽", "衣", "笑", "哭", "怒", "惊",
    ]
    cues = []
    for keyword in keywords:
        count = text.count(keyword)
        if count:
            cues.append({"cue": keyword, "count": count})
    cues.sort(key=lambda item: item["count"], reverse=True)
    return cues[:20]


def build_page_beats(episode: dict, excerpt: str, cues: list[dict], pages: int) -> list[dict]:
    chunks = split_text(excerpt, pages)
    cue_text = ", ".join(item["cue"] for item in cues[:8]) or "mythic wilderness"
    beats = []
    for index, chunk in enumerate(chunks, start=1):
        summary = summarize_chunk(chunk)
        beats.append(
            {
                "page_number": index,
                "title": f"{episode.get('chapter_title')} P{index:02d}",
                "source_excerpt": chunk,
                "summary": summary,
                "panel_intent": [
                    f"Establish the scene and dominant visual cues: {cue_text}.",
                    "Show the character action or discovery from this text chunk.",
                    "Hold on the emotional reaction or conflict turn.",
                    "End with a readable page-turn hook connected to the next chunk.",
                ],
            }
        )
    return beats


def build_page_beats_with_model(episode: dict, excerpt: str, cues: list[dict], pages: int) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "你是漫画改编的小说拆解助手。只返回 JSON。"
                "根据原文片段拆成漫画页，每页必须包含中文 title、summary、source_excerpt、panel_intent。"
                "panel_intent 是 4 条中文分镜意图，后续会给人工审核。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "chapter_title": episode.get("chapter_title"),
                    "source_volume": episode.get("source_volume"),
                    "pages": pages,
                    "visual_cues": cues[:12],
                    "source_excerpt": excerpt,
                    "required_schema": {
                        "page_beats": [
                            {
                                "page_number": 1,
                                "title": "中文页标题",
                                "source_excerpt": "对应原文片段",
                                "summary": "中文页面摘要",
                                "panel_intent": ["分镜1", "分镜2", "分镜3", "分镜4"],
                            }
                        ]
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    return chat_json(messages)


def split_text(text: str, parts: int) -> list[str]:
    if parts <= 1:
        return [text]
    length = len(text)
    chunks = []
    for index in range(parts):
        start = int(length * index / parts)
        end = int(length * (index + 1) / parts)
        chunks.append(text[start:end].strip())
    return chunks


def summarize_chunk(chunk: str) -> str:
    compact = re.sub(r"\s+", "", chunk)
    if len(compact) <= 90:
        return compact
    return compact[:90] + "..."


def comic_episode_id(number: int) -> str:
    return f"SSJ_COMIC_EP{number:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
