import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urlparse

import db

_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT_FOR_IMPORTS / "scripts"))
from process_novel import build_chapter_index, fallback_chapter_index
from image_provider import image_api_url, normalize_backend
from text_model_client import chat_json


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_PATH = Path(os.environ.get("COMIC_PIPELINE_CONFIG_PATH") or (ROOT / "config" / ".env"))
TEXT_ENV_PATH = ROOT / "config" / "text.env"
IMAGE_ENV_PATH = ROOT / "config" / "image.env"
CONFIG_EXAMPLE_PATH = ROOT / "config" / ".env.example"
TEXT_ENV_EXAMPLE_PATH = ROOT / "config" / "text.env.example"
IMAGE_ENV_EXAMPLE_PATH = ROOT / "config" / "image.env.example"
SCRIPTS_DIR = ROOT / "scripts"
MANIFESTS_DIR = ROOT / "manifests"
PROJECT_MANIFESTS_ROOT = MANIFESTS_DIR / "projects"
NOVELS_DIR = ROOT / "novels"
BACKUPS_DIR = ROOT / "backups"
LOG_DIR = ROOT / "logs"
RUN_SCRIPT = SCRIPTS_DIR / "run_comic_episode_pipeline.ps1"
RUN_IMAGE_WORKFLOW_SCRIPT = SCRIPTS_DIR / "run_image_workflow_and_wait.ps1"
IMAGE_PROVIDER_SCRIPT = SCRIPTS_DIR / "image_provider.py"
ASSEMBLE_PAGE_SCRIPT = SCRIPTS_DIR / "build_comic_page_from_panels.ps1"
PROCESS_NOVEL_SCRIPT = SCRIPTS_DIR / "process_novel.py"
CLOSE_READING_SCRIPT = SCRIPTS_DIR / "refine_comic_episode_close_reading.py"
DEFAULT_PROJECT_SLUG = "sou_shen_ji"
GENERATED_ASSET_WORKFLOW_DIR = ROOT / "workflows" / "comic" / "generated_assets"
MAX_NOVEL_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ASSET_BATCH_SIZE = 20
MAX_BACKUP_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_BACKUP_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_BACKUP_FILES = 20000
ALLOWED_NOVEL_EXTENSIONS = {".txt", ".md", ".text", ".novel"}

PIPELINE_KEYS = [
    "COMIC_PIPELINE_WORKSPACE",
    "COMIC_PIPELINE_COMFY_ROOT",
    "COMIC_PIPELINE_COMFY_URL",
    "COMIC_PIPELINE_OUTPUT_ROOT",
    "COMIC_PIPELINE_COMFY_OUTPUT_ROOT",
    "COMIC_PIPELINE_NOVEL_PATH",
    "COMIC_PIPELINE_TEXT_ENV_PATH",
    "COMIC_PIPELINE_IMAGE_ENV_PATH",
    "COMIC_PIPELINE_IMAGE_BACKEND",
    "COMIC_PIPELINE_DATABASE_URL",
    "COMIC_PIPELINE_TEXT_MODEL",
    "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT",
    "COMIC_PIPELINE_TEXT_MODEL_STREAM",
    "COMIC_PIPELINE_IMAGE_MODEL",
    "COMIC_PIPELINE_IMAGE_QUALITY",
    "COMIC_PIPELINE_PYTHON_PATH",
    "COMIC_PIPELINE_DEFAULT_PAGES",
    "COMIC_PIPELINE_ENCODING",
    "COMIC_PIPELINE_ACTIVE_PROJECT",
]

DEFAULTS = {
    "COMIC_PIPELINE_WORKSPACE": str(ROOT),
    "COMIC_PIPELINE_COMFY_ROOT": str(ROOT / "ComfyUI"),
    "COMIC_PIPELINE_COMFY_URL": "http://127.0.0.1:8188",
    "COMIC_PIPELINE_OUTPUT_ROOT": str(ROOT / "output" / "ComicPipeline"),
    "COMIC_PIPELINE_COMFY_OUTPUT_ROOT": str(ROOT / "output"),
    "COMIC_PIPELINE_NOVEL_PATH": str(ROOT / "novel.txt"),
    "COMIC_PIPELINE_TEXT_ENV_PATH": str(TEXT_ENV_PATH),
    "COMIC_PIPELINE_IMAGE_ENV_PATH": str(IMAGE_ENV_PATH),
    "COMIC_PIPELINE_IMAGE_BACKEND": "direct_api",
    "COMIC_PIPELINE_DATABASE_URL": "postgresql://comic_pipeline:comic_pipeline@127.0.0.1:54329/comic_pipeline",
    "COMIC_PIPELINE_TEXT_MODEL": "gpt-4.1-mini",
    "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": "300",
    "COMIC_PIPELINE_TEXT_MODEL_STREAM": "true",
    "COMIC_PIPELINE_IMAGE_MODEL": "gpt-image-2",
    "COMIC_PIPELINE_IMAGE_QUALITY": "auto",
    "COMIC_PIPELINE_PYTHON_PATH": sys.executable,
    "COMIC_PIPELINE_DEFAULT_PAGES": "8",
    "COMIC_PIPELINE_ENCODING": "gb18030",
    "COMIC_PIPELINE_ACTIVE_PROJECT": DEFAULT_PROJECT_SLUG,
}

STAGE_MAP = {
    "preflight": {"label": "预检", "args": ["-OnlyStage", "preflight", "-DryRun", "-SkipImageGeneration", "-AllowDraftWarnings"]},
    "breakdown": {
        "label": "AI 拆解",
        "args": ["-FromStage", "page_plans", "-UntilStage", "draft_qa", "-AllowDraftWarnings"],
    },
    "draft_review": {
        "label": "生成拆解审稿包",
        "args": ["-FromStage", "draft_review", "-UntilStage", "draft_qa", "-AllowDraftWarnings"],
    },
    "close_reading": {
        "label": "细读拆解",
        "custom": "close_reading",
    },
    "generate": {
        "label": "小批量生成漫画",
        "args": ["-FromStage", "comfy_health", "-UntilStage", "generate_panels", "-GenerateImages", "-CheckComfyHealth", "-AllowDraftWarnings"],
        "needs_generation": True,
    },
    "review": {
        "label": "页面组装和 QA",
        "args": ["-FromStage", "assemble_pages", "-UntilStage", "image_health_qa", "-AssemblePages", "-RunLetteringQa", "-RunConsistencyQa", "-RunImageHealthQa", "-AllowDraftWarnings"],
    },
    "status": {
        "label": "刷新状态报告",
        "args": ["-OnlyStage", "status_report", "-AllowDraftWarnings"],
    },
}

JOB_LOCK = threading.Lock()
JOBS = {}
JOB_PROCESSES = {}
DB_INIT_LOCK = threading.Lock()
DB_READY = False
INTERRUPTED_ON_STARTUP = []
_REQUEST_CONTEXT = threading.local()

WORKFLOW_STEPS = [
    {"key": "preflight", "label": "预检", "gate": "检查后端与配置"},
    {"key": "breakdown", "label": "拆解审核", "gate": "人工确认分镜草稿"},
    {"key": "assets", "label": "素材确认", "gate": "检查一致性资产"},
    {"key": "generation", "label": "生成审核", "gate": "查看页面与分镜"},
    {"key": "qa", "label": "QA / 下一章", "gate": "通过后继续循环"},
]

CATEGORY_LABELS = {
    "characters": "角色资产",
    "world_scenes": "世界/场景资产",
    "weapons": "武器资产",
    "clothing": "服装资产",
    "creatures": "异兽/生物资产",
    "uncategorized": "未分类资产",
}

SETTING_TYPE_LABELS = {
    "character": "角色",
    "location": "场景",
    "prop": "道具/武器",
    "faction": "组织/阵营",
    "world_rule": "世界观",
    "style_rule": "画风规范",
}

ASSET_NEGATIVE_PROMPT = (
    "modern city, sci-fi, western medieval armor, European castle, anime parody, "
    "plastic skin, neon cyberpunk, text, watermark, logo, child, teenager, minor, "
    "extra fingers, distorted hands, melted face, gore, nudity"
)


def read_env(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_keys(path: Path) -> list[str]:
    if not path.is_file():
        return []
    keys = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return keys


def write_env(path: Path, values: dict, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in keys:
        value = str(values.get(key, "")).strip()
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def runtime_config() -> dict:
    config = DEFAULTS | read_env(CONFIG_PATH)
    for key in PIPELINE_KEYS:
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def provider_env_state(path: Path) -> dict:
    values = read_env(path)
    return {
        "path": str(path),
        "exists": path.is_file(),
        "OPENAI_BASE_URL": values.get("OPENAI_BASE_URL", ""),
        "OPENAI_API_KEY_CONFIGURED": bool(values.get("OPENAI_API_KEY", "").strip()),
    }


def restore_file(path: Path, content: bytes | None) -> None:
    if content is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def example_consistency_checks(config: dict | None = None) -> list[dict]:
    config = config or runtime_config()
    pipeline_example_keys = env_keys(CONFIG_EXAMPLE_PATH)
    text_path = Path(config.get("COMIC_PIPELINE_TEXT_ENV_PATH") or TEXT_ENV_PATH)
    text_example_keys = env_keys(TEXT_ENV_EXAMPLE_PATH)
    image_path = Path(config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or IMAGE_ENV_PATH)
    image_example_keys = env_keys(IMAGE_ENV_EXAMPLE_PATH)
    expected_provider_keys = ["OPENAI_API_KEY", "OPENAI_BASE_URL"]

    checks = []
    missing_pipeline = [key for key in PIPELINE_KEYS if key not in pipeline_example_keys]
    extra_pipeline = [key for key in pipeline_example_keys if key not in PIPELINE_KEYS]
    checks.append({
        "name": "pipeline_example",
        "label": ".env 示例配置",
        "ok": CONFIG_EXAMPLE_PATH.is_file() and not missing_pipeline and not extra_pipeline,
        "message": (
            f"{CONFIG_EXAMPLE_PATH} 与 UI 设置项一致"
            if CONFIG_EXAMPLE_PATH.is_file() and not missing_pipeline and not extra_pipeline
            else "config/.env.example 与 UI 设置项不一致"
        ),
        "detail": {
            "path": str(CONFIG_EXAMPLE_PATH),
            "missing": missing_pipeline,
            "extra": extra_pipeline,
        },
    })

    missing_text = [key for key in expected_provider_keys if key not in text_example_keys]
    checks.append({
        "name": "text_example",
        "label": "text.env 示例配置",
        "ok": TEXT_ENV_EXAMPLE_PATH.is_file() and not missing_text,
        "message": (
            f"{TEXT_ENV_EXAMPLE_PATH} 包含必需密钥项"
            if TEXT_ENV_EXAMPLE_PATH.is_file() and not missing_text
            else "config/text.env.example 缺少必需密钥项"
        ),
        "detail": {
            "path": str(TEXT_ENV_EXAMPLE_PATH),
            "runtime_path": str(text_path),
            "missing": missing_text,
        },
    })

    missing_image = [key for key in expected_provider_keys if key not in image_example_keys]
    checks.append({
        "name": "image_example",
        "label": "image.env 示例配置",
        "ok": IMAGE_ENV_EXAMPLE_PATH.is_file() and not missing_image,
        "message": (
            f"{IMAGE_ENV_EXAMPLE_PATH} 包含必需密钥项"
            if IMAGE_ENV_EXAMPLE_PATH.is_file() and not missing_image
            else "config/image.env.example 缺少必需密钥项"
        ),
        "detail": {
            "path": str(IMAGE_ENV_EXAMPLE_PATH),
            "runtime_path": str(image_path),
            "missing": missing_image,
        },
    })
    return checks


def slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", value or "").strip("_").lower()
    if not text:
        text = f"novel_{int(time.time())}"
    ascii_text = re.sub(r"[^A-Za-z0-9_\-]+", "", text)
    return ascii_text or f"novel_{int(time.time())}"


def safe_upload_filename(filename: str) -> str:
    raw_name = Path(filename or "").name
    stem = Path(raw_name).stem.strip() or "novel"
    suffix = Path(raw_name).suffix.lower()
    if suffix not in ALLOWED_NOVEL_EXTENSIONS:
        raise ValueError("仅支持 txt、md、text、novel 格式的小说文件")
    safe_stem = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", stem).strip("_") or "novel"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{safe_stem}{suffix}"


def decode_base64_upload(content_base64: str) -> bytes:
    value = str(content_base64 or "")
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        data = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("小说文件内容不是有效的 base64 数据") from exc
    if not data:
        raise ValueError("小说文件为空")
    if len(data) > MAX_NOVEL_UPLOAD_BYTES:
        raise ValueError("小说文件超过 100MB，请先拆分后再导入")
    return data


def slug_token(project: dict | str | None) -> str:
    raw = project if isinstance(project, str) else (project or {}).get("slug", "")
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(raw or "")).strip("_").upper()
    return token or f"NOVEL_{int(time.time())}"


def default_projects() -> list[dict]:
    default_novel = ROOT.parent / "搜神记.txt"
    return [
        {
            "slug": DEFAULT_PROJECT_SLUG,
            "title": "搜神记",
            "novel_path": str(default_novel),
            "manifest_dir": str(MANIFESTS_DIR),
            "chapter_index_path": str(MANIFESTS_DIR / "sou_shen_ji_chapter_index.json"),
            "series_plan_path": str(MANIFESTS_DIR / "sou_shen_ji_comic_series_plan.json"),
            "legacy": True,
            "updated": "",
        }
    ]


def database_url() -> str:
    config = runtime_config()
    return config.get("COMIC_PIPELINE_DATABASE_URL", "")


def ensure_database() -> None:
    global DB_READY, INTERRUPTED_ON_STARTUP
    if DB_READY:
        return
    with DB_INIT_LOCK:
        if DB_READY:
            return
        db.init_schema(database_url())
        interrupted_note = "控制台服务已重启，上一轮运行中的任务没有可恢复的本地进程。"
        INTERRUPTED_ON_STARTUP = db.mark_interrupted_jobs(
            database_url(),
            interrupted_note,
            datetime.now().isoformat(timespec="seconds"),
        )
        DB_READY = True


def read_projects() -> list[dict]:
    ensure_database()
    return db.list_projects(database_url())


def active_project_slug() -> str:
    config = runtime_config()
    return config.get("COMIC_PIPELINE_ACTIVE_PROJECT") or ""


def project_by_slug(slug: str = "") -> dict:
    requested = slug or active_project_slug()
    projects = read_projects()
    for project in projects:
        if project.get("slug") == requested and project.get("status", "active") != "archived":
            return project
    for project in projects:
        if project.get("status", "active") != "archived":
            return project
    raise db.DatabaseUnavailable("PostgreSQL 中没有可用作品")


def active_project() -> dict:
    return project_by_slug()


def project_manifest_dir(project: dict | None = None) -> Path:
    project = project or active_project()
    return Path(project.get("manifest_dir") or MANIFESTS_DIR)


def series_plan_path(project: dict | None = None) -> Path:
    project = project or active_project()
    return Path(project.get("series_plan_path") or (project_manifest_dir(project) / f"{project.get('slug', DEFAULT_PROJECT_SLUG)}_comic_series_plan.json"))


def chapter_index_path(project: dict | None = None) -> Path:
    project = project or active_project()
    return Path(project.get("chapter_index_path") or (project_manifest_dir(project) / f"{project.get('slug', DEFAULT_PROJECT_SLUG)}_chapter_index.json"))


def approval_path(project: dict | None = None) -> Path:
    return project_manifest_dir(project) / "agent_approvals.json"


def project_episode_stem(project: dict | None, episode_number: int) -> str:
    project = project or active_project()
    if project.get("legacy"):
        return f"ssj_comic_episode{episode_number:02d}"
    return f"{slug_token(project).lower()}_episode{episode_number:02d}"


def project_episode_plan_path(episode_number: int, project: dict | None = None) -> Path:
    project = project or active_project()
    return project_manifest_dir(project) / f"{project_episode_stem(project, episode_number)}_pages.json"


def project_episode_id(project: dict | None, episode_number: int) -> str:
    project = project or active_project()
    if project.get("legacy"):
        return episode_id_short(episode_number)
    return f"{slug_token(project)}_EP{episode_number:02d}"


def sync_project_from_manifests(project: dict) -> None:
    chapter_path = chapter_index_path(project)
    series_path = series_plan_path(project)
    if chapter_path.is_file():
        chapter_index = read_optional_json(chapter_path) or []
        chapters = [item for item in chapter_index if isinstance(item, dict) and item.get("type") == "chapter"]
        db.replace_project_chapters(database_url(), project["slug"], chapters)
    if series_path.is_file():
        series = read_optional_json(series_path) or {}
        episodes = []
        for item in series.get("episodes", []) if isinstance(series, dict) else []:
            number = episode_number_from_id(item.get("episode_id", ""))
            if number and not item.get("episode_plan_path"):
                item = {**item, "episode_plan_path": str(project_episode_plan_path(number, project))}
            episodes.append(item)
        db.replace_project_episodes(database_url(), project["slug"], episodes)


def config_snapshot() -> dict:
    config = runtime_config()
    text = provider_env_state(Path(config.get("COMIC_PIPELINE_TEXT_ENV_PATH") or TEXT_ENV_PATH))
    image = provider_env_state(Path(config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or IMAGE_ENV_PATH))
    database = db.status(config.get("COMIC_PIPELINE_DATABASE_URL", ""))
    return {
        "root": str(ROOT),
        "config_path": str(CONFIG_PATH),
        "text_env_path": config.get("COMIC_PIPELINE_TEXT_ENV_PATH") or str(TEXT_ENV_PATH),
        "image_env_path": config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or str(IMAGE_ENV_PATH),
        "config": {key: config.get(key, "") for key in PIPELINE_KEYS},
        "projects": {
            "active": active_project_slug(),
            "items": read_projects() if database.get("schema_ready") else [],
        },
        "database": database,
        "text": text,
        "image": image,
    }


def save_config(payload: dict) -> dict:
    current = config_snapshot()["config"]
    incoming = payload.get("config") or {}
    if "COMIC_PIPELINE_IMAGE_BACKEND" in incoming:
        incoming = dict(incoming)
        incoming["COMIC_PIPELINE_IMAGE_BACKEND"] = normalize_backend(incoming["COMIC_PIPELINE_IMAGE_BACKEND"])
    for key in PIPELINE_KEYS:
        if key in incoming:
            current[key] = str(incoming[key])
    text_path = Path(current.get("COMIC_PIPELINE_TEXT_ENV_PATH") or TEXT_ENV_PATH)
    image_path = Path(current.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or IMAGE_ENV_PATH)
    backups = {
        CONFIG_PATH: CONFIG_PATH.read_bytes() if CONFIG_PATH.is_file() else None,
        text_path: text_path.read_bytes() if text_path.is_file() else None,
        image_path: image_path.read_bytes() if image_path.is_file() else None,
    }
    try:
        write_env(CONFIG_PATH, current, PIPELINE_KEYS)
        if payload.get("__simulate_image_write_failure"):
            raise RuntimeError("模拟 image.env 写入失败")

        text_current = read_env(text_path)
        text_payload = payload.get("text") or {}
        text_base_url = str(text_payload.get("OPENAI_BASE_URL", text_current.get("OPENAI_BASE_URL", ""))).strip()
        text_api_key = str(text_payload.get("OPENAI_API_KEY", "")).strip()
        if text_api_key:
            text_current["OPENAI_API_KEY"] = text_api_key
        elif "OPENAI_API_KEY" not in text_current:
            text_current["OPENAI_API_KEY"] = ""
        text_current["OPENAI_BASE_URL"] = text_base_url
        write_env(text_path, text_current, ["OPENAI_API_KEY", "OPENAI_BASE_URL"])

        image_current = read_env(image_path)
        image_payload = payload.get("image") or {}
        base_url = str(image_payload.get("OPENAI_BASE_URL", image_current.get("OPENAI_BASE_URL", ""))).strip()
        api_key = str(image_payload.get("OPENAI_API_KEY", "")).strip()
        if api_key:
            image_current["OPENAI_API_KEY"] = api_key
        elif "OPENAI_API_KEY" not in image_current:
            image_current["OPENAI_API_KEY"] = ""
        image_current["OPENAI_BASE_URL"] = base_url
        write_env(image_path, image_current, ["OPENAI_API_KEY", "OPENAI_BASE_URL"])
        return config_snapshot() | {"save": {"ok": True, "rollback": False}}
    except Exception as exc:
        for path, content in backups.items():
            restore_file(path, content)
        raise RuntimeError(f"保存配置失败，已恢复原配置：{exc}") from exc


def latest_pipeline_result(episode_number: int) -> dict | None:
    path = project_manifest_dir() / f"{project_episode_stem(None, episode_number)}_pipeline_run.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


def read_optional_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


def file_stamp(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.is_file() else "",
        "size": path.stat().st_size if path.is_file() else 0,
    }


def episode_number_from_id(value: str) -> int:
    match = re.search(r"EP0*(\d+)", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


def page_number_from_id(value: str) -> int:
    match = re.search(r"P0*(\d+)", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


def panel_number_from_id(value: str) -> int:
    match = re.search(r"PANEL0*(\d+)", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


def episode_id_short(episode_number: int) -> str:
    return f"SSJ_COMIC_EP{episode_number:02d}"


def episode_id_long(episode_number: int) -> str:
    return f"SSJ_COMIC_EP{episode_number:03d}"


def long_stem(episode_number: int) -> str:
    return f"ssj_comic_episode{episode_number:02d}"


def short_stem(episode_number: int) -> str:
    return f"ssj_comic_ep{episode_number:02d}"


def load_episode_plan(episode_number: int) -> dict:
    return read_optional_json(project_episode_plan_path(episode_number)) or {}


def project_episode_record(project: dict, episode_number: int) -> dict:
    for item in db.list_episodes(database_url(), project["slug"]):
        if int(item.get("episode_number") or 0) == int(episode_number):
            return item
    return {}


def project_chapter_record(project: dict, chapter_number: int) -> dict:
    for item in db.list_chapters(database_url(), project["slug"]):
        if int(item.get("chapter_number") or 0) == int(chapter_number):
            return item
    return {}


def create_episode_skeleton_plan(project: dict, episode_number: int, target_path: Path, pages: int = 8) -> dict:
    episode = project_episode_record(project, episode_number)
    chapter_number = int(episode.get("chapter_number") or episode_number)
    chapter = project_chapter_record(project, chapter_number)
    title = str(episode.get("title") or chapter.get("title") or f"第 {episode_number} 章")
    volume = str(chapter.get("volume") or "")
    episode_id = project_episode_id(project, episode_number)
    page_count = max(1, int(pages or 8))
    planned_panels = max(0, int(episode.get("planned_panels") or 0))
    base_panels, extra_panels = divmod(planned_panels, page_count) if planned_panels else (4, 0)
    page_items = []
    for page_index in range(1, page_count + 1):
        page_id = f"{episode_id}_P{page_index:03d}"
        panel_items = []
        panels_this_page = max(1, base_panels + (1 if page_index <= extra_panels else 0))
        for panel_index in range(1, panels_this_page + 1):
            panel_id = f"{page_id}_PANEL{panel_index:02d}"
            panel_items.append({
                "title": f"待细读分镜 {panel_index}",
                "reference_alias": "",
                "caption": "",
                "dialogue": [],
                "panel_id": panel_id,
                "prompt": f"待细读：{volume} {title}，第 {page_index} 页第 {panel_index} 格。中国神话幻想漫画，无画面文字。",
            })
        page_items.append({
            "page_id": page_id,
            "status": "skeleton_needs_close_reading",
            "beat_ids": [],
            "title": f"{title} P{page_index:02d}",
            "summary": f"{title} 的初始页面骨架，需要 AI 细读拆解和人工审核后再生成。",
            "panels": panel_items,
        })
    plan = {
        "updated": datetime.now().date().isoformat(),
        "project": project.get("title") or project.get("slug") or "",
        "source": f"{project.get('title') or ''} {volume} {title}".strip(),
        "source_volume": volume,
        "source_chapter_title": title,
        "source_chapter_line": chapter.get("line_number", ""),
        "episode_id": episode_id,
        "episode_title": title,
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
        "pages": page_items,
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "created": True, "path": str(target_path), "episode_number": episode_number, "pages": len(page_items)}


def read_novel_lines(project: dict) -> tuple[list[str], str, str]:
    config = runtime_config()
    novel_path = Path(project.get("novel_path") or config.get("COMIC_PIPELINE_NOVEL_PATH", ""))
    if not novel_path.is_file():
        return [], str(novel_path), ""
    encodings = [
        str(config.get("COMIC_PIPELINE_ENCODING") or "").strip(),
        "utf-8-sig",
        "gb18030",
        "utf-8",
    ]
    tried = set()
    for encoding in encodings:
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return novel_path.read_text(encoding=encoding).splitlines(), str(novel_path), encoding
        except UnicodeDecodeError:
            continue
    return novel_path.read_text(encoding=encodings[0] or "utf-8", errors="replace").splitlines(), str(novel_path), "replace"


def chapter_entries(project: dict) -> list[dict]:
    index = read_optional_json(chapter_index_path(project)) or []
    return [item for item in index if isinstance(item, dict) and item.get("type") == "chapter"]


def chapter_for_episode(episode_number: int, plan: dict, project: dict) -> tuple[dict, dict | None]:
    chapters = chapter_entries(project)
    if not chapters:
        return {}, None
    source_line = int(plan.get("source_chapter_line") or 0) if isinstance(plan, dict) else 0
    current_index = -1
    if source_line:
        current_index = next((index for index, item in enumerate(chapters) if int(item.get("line") or 0) == source_line), -1)
    if current_index < 0 and isinstance(plan, dict):
        source_title = str(plan.get("source_chapter_title") or plan.get("episode_title") or "").strip()
        if source_title:
            current_index = next((index for index, item in enumerate(chapters) if str(item.get("title") or "").strip() == source_title), -1)
    if current_index < 0 and 1 <= episode_number <= len(chapters):
        current_index = episode_number - 1
    if current_index < 0:
        return {}, None
    next_chapter = chapters[current_index + 1] if current_index + 1 < len(chapters) else None
    return chapters[current_index], next_chapter


def split_source_lines(lines: list[str], page_count: int, base_line: int) -> list[dict]:
    if not lines:
        return []
    count = max(int(page_count or 1), 1)
    chunks = []
    total = len(lines)
    for index in range(count):
        start = (total * index) // count
        end = (total * (index + 1)) // count
        chunk_lines = lines[start:end] or lines[start:start + 1]
        chunks.append(
            {
                "page_index": index + 1,
                "line_start": base_line + start,
                "line_end": base_line + start + len(chunk_lines) - 1,
                "text": "\n".join(chunk_lines).strip(),
            }
        )
    return chunks


def novel_source_for_episode(episode_number: int, plan: dict, pages: list[dict], project: dict) -> dict:
    lines, novel_path, encoding = read_novel_lines(project)
    chapter, next_chapter = chapter_for_episode(episode_number, plan, project)
    if not lines or not chapter:
        return {
            "available": False,
            "novel_path": novel_path,
            "encoding": encoding,
            "reason": "缺少小说文件或章节索引",
            "pages": [],
        }
    start_line = max(int(chapter.get("line") or 1), 1)
    next_line = int((next_chapter or {}).get("line") or (len(lines) + 1))
    end_line = max(min(next_line - 1, len(lines)), start_line)
    chapter_lines = lines[start_line - 1:end_line]
    page_chunks = split_source_lines(chapter_lines, len(pages), start_line)
    return {
        "available": True,
        "novel_path": novel_path,
        "encoding": encoding,
        "volume": chapter.get("volume", ""),
        "chapter_title": chapter.get("title", ""),
        "line_start": start_line,
        "line_end": end_line,
        "line_count": len(chapter_lines),
        "text": "\n".join(chapter_lines).strip(),
        "pages": page_chunks,
    }


def hydrate_episode_plan_source_excerpts(project: dict, episode_number: int, plan_path: Path | None = None) -> dict:
    plan_path = plan_path or project_episode_plan_path(episode_number, project)
    plan = read_optional_json(plan_path) or {}
    pages = plan.get("pages") or []
    if not isinstance(plan, dict) or not isinstance(pages, list) or not pages:
        return {"updated": False, "reason": "章节计划没有页面", "pages": 0}
    source = novel_source_for_episode(episode_number, plan, pages, project)
    source_pages = {int(item.get("page_index") or 0): item for item in source.get("pages", [])}
    changed = False
    hydrated = 0
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        source_page = source_pages.get(index, {})
        text = source_page.get("text", "")
        if text and not page.get("source_excerpt"):
            page["source_excerpt"] = text
            changed = True
        if source_page.get("line_start") and page.get("source_line_start") != source_page.get("line_start"):
            page["source_line_start"] = source_page.get("line_start")
            changed = True
        if source_page.get("line_end") and page.get("source_line_end") != source_page.get("line_end"):
            page["source_line_end"] = source_page.get("line_end")
            changed = True
        if page.get("source_excerpt"):
            hydrated += 1
    if changed:
        plan["updated"] = datetime.now().date().isoformat()
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "updated": changed,
        "pages": hydrated,
        "available": bool(source.get("available")),
        "novel_path": source.get("novel_path", ""),
    }


def output_root() -> Path:
    config = effective_config(active_project())
    return Path(config.get("COMIC_PIPELINE_OUTPUT_ROOT", DEFAULTS["COMIC_PIPELINE_OUTPUT_ROOT"]))


def comfy_output_root() -> Path:
    config = runtime_config()
    return Path(config.get("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", DEFAULTS["COMIC_PIPELINE_COMFY_OUTPUT_ROOT"]))


def project_config_overrides(project: dict | None = None) -> dict:
    project = project or active_project()
    raw = project.get("project_config") if isinstance(project.get("project_config"), dict) else {}
    return {
        "COMIC_PIPELINE_TEXT_MODEL": str(raw.get("text_model") or "").strip(),
        "COMIC_PIPELINE_IMAGE_MODEL": str(raw.get("image_model") or "").strip(),
        "COMIC_PIPELINE_OUTPUT_ROOT": str(raw.get("output_root") or "").strip(),
    }


def effective_config(project: dict | None = None) -> dict:
    config = runtime_config()
    if project:
        for key, value in project_config_overrides(project).items():
            if value:
                config[key] = value
    return config


def effective_config_sources(project: dict | None = None) -> dict:
    overrides = project_config_overrides(project) if project else {}
    return {
        "novel_model": "project" if overrides.get("COMIC_PIPELINE_TEXT_MODEL") else "global",
        "image_model": "project" if overrides.get("COMIC_PIPELINE_IMAGE_MODEL") else "global",
        "output_root": "project" if overrides.get("COMIC_PIPELINE_OUTPUT_ROOT") else "global",
    }


def media_url(path: str | Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        rel = candidate.resolve().relative_to(comfy_output_root().resolve())
        return "/media/" + quote(str(rel).replace("\\", "/"))
    except Exception:
        try:
            rel = candidate.resolve().relative_to(output_root().resolve())
            return "/media/" + quote(str(Path("ComicPipeline") / rel).replace("\\", "/"))
        except Exception:
            return ""


def comfy_view_url(path: str | Path) -> str:
    if not path:
        return ""
    config = runtime_config()
    if normalize_backend(config.get("COMIC_PIPELINE_IMAGE_BACKEND")) != "comfyui":
        return ""
    candidate = Path(path)
    try:
        rel = candidate.resolve().relative_to(comfy_output_root().resolve())
    except Exception:
        return ""
    comfy_url = config.get("COMIC_PIPELINE_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    filename = quote(rel.name)
    subfolder = quote(str(rel.parent).replace("\\", "/"))
    return f"{comfy_url}/view?filename={filename}&subfolder={subfolder}&type=output"


def safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", value or "").strip("_").lower()
    return stem or "asset"


def find_latest_output(prefix: str, folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    files = sorted(
        folder.glob(f"{prefix}_*.png"),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    return files[0] if files else None


def page_image_path(episode_number: int, page_id: str) -> Path:
    return output_root() / "pages" / f"{page_id}.png"


def panel_prefix_from_id(panel_id: str) -> str:
    return f"{panel_id}_v001"


def panel_image_path(panel_id: str) -> Path | None:
    return find_latest_output(panel_prefix_from_id(panel_id), output_root() / "panels")


def workflow_path_for_panel(panel_id: str) -> Path | None:
    safe = panel_id.lower()
    candidates = [
        ROOT / "workflows" / "comic" / f"{safe}_fallback_v001.json",
        ROOT / "workflows" / "comic" / f"{safe}_image_v001.json",
        ROOT / "workflows" / "comic" / f"{safe}_micro_fallback_v001.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted((ROOT / "workflows" / "comic").glob(f"{safe}_*.json"))
    return matches[0] if matches else None


def expected_output_from_workflow(workflow: dict) -> str:
    for node in workflow.get("prompt", {}).values():
        if not isinstance(node, dict) or node.get("class_type") != "SaveImage":
            continue
        prefix = node.get("inputs", {}).get("filename_prefix")
        if prefix:
            return str(comfy_output_root() / f"{prefix}_00001_.png")
    return ""


def image_workflow_command(
    project: dict,
    workflow_path: str | Path,
    output_path: str | Path,
    result_path: str | Path,
    shot_id: str,
    poll_seconds: int = 5,
    max_polls: int = 180,
) -> tuple[str, list[str]]:
    config = effective_config(project)
    backend = normalize_backend(config.get("COMIC_PIPELINE_IMAGE_BACKEND"))
    if backend == "direct_api":
        if Path(output_path).suffix.lower() != ".png":
            raise ValueError("direct image output path must be a PNG file")
        return backend, [
            config.get("COMIC_PIPELINE_PYTHON_PATH") or sys.executable,
            str(IMAGE_PROVIDER_SCRIPT),
            "--workflow-path",
            str(workflow_path),
            "--output-path",
            str(output_path),
            "--result-path",
            str(result_path),
            "--env-path",
            config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or str(IMAGE_ENV_PATH),
        ]
    return backend, [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUN_IMAGE_WORKFLOW_SCRIPT),
        "-WorkflowPath",
        str(workflow_path),
        "-ShotId",
        shot_id,
        "-ResultPath",
        str(result_path),
        "-PollSeconds",
        str(int(poll_seconds)),
        "-MaxPolls",
        str(int(max_polls)),
    ]


def normalize_path(value: str | Path) -> str:
    return str(Path(value)).lower()


def existing_workflow_for_output(path: str | Path) -> Path | None:
    expected = normalize_path(path)
    workflows_root = ROOT / "workflows"
    if not workflows_root.is_dir():
        return None
    for workflow in workflows_root.rglob("*.json"):
        try:
            data = json.loads(workflow.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if normalize_path(expected_output_from_workflow(data)) == expected:
            return workflow
    return None


def filename_prefix_for_output(path: str | Path) -> str:
    candidate = Path(path)
    try:
        rel = candidate.resolve().relative_to(comfy_output_root().resolve())
    except Exception:
        return safe_stem(candidate.stem)
    stem = re.sub(r"_\d{5}_$", "", rel.stem)
    return str(rel.with_name(stem).with_suffix("")).replace("\\", "/")


def asset_prompt(alias: str, category: str, has_reference: bool) -> str:
    label = alias.replace("_", " ")
    base = (
        "Ancient Chinese mythic fantasy comic production reference asset, "
        "premium graphic novel illustration, restrained ink-and-watercolor finish, "
        "clean silhouette, consistent design language, no text, no watermark."
    )
    if category == "characters":
        specific = f"Create a character turnaround reference sheet for {label}, stable face, hair, clothing, and proportions."
    elif category == "world_scenes":
        specific = f"Create an environment key art reference for {label}, geography, architecture, lighting, vegetation, and atmosphere."
    elif category == "weapons":
        specific = f"Create a weapon prop reference sheet for {label}, clear shape language, materials, scale, and details."
    elif category == "clothing":
        specific = f"Create a costume reference sheet for {label}, fabric layers, silhouette, trims, colors, and construction details."
    elif category == "creatures":
        specific = f"Create a creature reference sheet for {label}, full body design, head details, scale cues, texture, and markings."
    else:
        specific = f"Create a production reference sheet for {label}, clear design, materials, scale, and repeatable visual details."
    if has_reference:
        specific += " Use the previous asset image as a strict consistency reference while improving clarity."
    return f"{base}\n\nAsset category: {CATEGORY_LABELS.get(category, '一致性资产')}.\n{specific}"


def asset_image_size(category: str) -> str:
    if category in {"world_scenes", "weapons", "creatures"}:
        return "1536x1024"
    return "1024x1536"


def create_asset_workflow(
    alias: str,
    category: str,
    target_path: str | Path,
    reference_path: str = "",
    approved_prompt: str = "",
    approved_negative_prompt: str = "",
    project: dict | None = None,
) -> Path:
    config = effective_config(project) if project else config_snapshot()["config"]
    GENERATED_ASSET_WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    project_prefix = f"{safe_stem(project.get('slug', ''))}_" if project else ""
    target_stem = safe_stem(Path(target_path).stem)
    workflow_path = GENERATED_ASSET_WORKFLOW_DIR / f"{project_prefix}{target_stem}_asset_regenerate_v001.json"
    prompt = asset_prompt(alias, category, bool(reference_path))
    if approved_prompt.strip():
        prompt += f"\n\nApproved novel setting (must follow):\n{approved_prompt.strip()}"
    negative_prompt = ASSET_NEGATIVE_PROMPT
    if approved_negative_prompt.strip():
        negative_prompt += f", {approved_negative_prompt.strip()}"
    inputs = {
        "prompt": prompt,
        "model": config.get("COMIC_PIPELINE_IMAGE_MODEL", DEFAULTS["COMIC_PIPELINE_IMAGE_MODEL"]),
        "size": asset_image_size(category),
        "quality": config.get("COMIC_PIPELINE_IMAGE_QUALITY", DEFAULTS["COMIC_PIPELINE_IMAGE_QUALITY"]),
        "negative_prompt": negative_prompt,
        "api_key_env_path": ".comic-pipeline/image.env",
    }
    if reference_path:
        inputs["reference_image_paths"] = reference_path
    workflow = {
        "client_id": "codex-comic-asset-console",
        "prompt": {
            "1": {"class_type": "OpenAICompatibleImageGenerate", "inputs": inputs},
            "2": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["1", 0],
                    "filename_prefix": filename_prefix_for_output(target_path),
                },
            },
        },
    }
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return workflow_path


def plan_path_for_page(page_id: str) -> Path:
    safe = page_id.lower()
    candidates = [
        project_manifest_dir() / f"{safe}_plan.json",
        project_manifest_dir() / f"{safe.replace('_comic_', '_comic_')}_plan.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(project_manifest_dir().glob(f"*{safe.split('_', 1)[-1]}*_plan.json"))
    return matches[0] if matches else candidates[0]


def workflow_result_path_for_page(page_id: str) -> Path:
    safe = page_id.lower()
    candidates = [
        project_manifest_dir() / f"{safe}_workflows.json",
        project_manifest_dir() / f"{safe}_fallback_workflows.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(project_manifest_dir().glob(f"*{safe.split('_', 1)[-1]}*_workflows.json"))
    return matches[0] if matches else candidates[0]


def workflow_entries_for_page(page_id: str) -> list[dict]:
    path = workflow_result_path_for_page(page_id)
    data = read_optional_json(path) or {}
    created = data.get("created") if isinstance(data, dict) else []
    if isinstance(created, list):
        return [item for item in created if isinstance(item, dict)]
    return []


def assembly_path_for_page(page_id: str) -> Path:
    return project_manifest_dir() / f"{page_id.lower()}_assembly.json"


def make_media_item(kind: str, item_id: str, path: Path | None, title: str = "", page_id: str = "", panel_id: str = "") -> dict:
    exists = bool(path and path.is_file())
    return {
        "kind": kind,
        "id": item_id,
        "title": title or item_id,
        "page_id": page_id,
        "panel_id": panel_id,
        "path": str(path) if path else "",
        "exists": exists,
        "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if exists else "",
        "size": path.stat().st_size if exists else 0,
        "url": media_url(path) if exists else "",
        "comfy_url": comfy_view_url(path) if exists else "",
    }


def read_optional_text(path: Path, limit: int = 12000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return text[:limit]


def preview_paths(episode_number: int) -> dict:
    config = config_snapshot()["config"]
    image_backend = normalize_backend(config.get("COMIC_PIPELINE_IMAGE_BACKEND"))
    if image_backend != "comfyui":
        return {
            "backend": image_backend,
            "latest_file": "",
            "episode_file": "",
            "latest_url": "",
            "episode_url": "",
        }
    comfy_url = config.get("COMIC_PIPELINE_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    installed = Path(config.get("COMIC_PIPELINE_COMFY_ROOT", DEFAULTS["COMIC_PIPELINE_COMFY_ROOT"]))
    preview_dir = (
        installed
        / "custom_nodes"
        / "comic_episode_pipeline"
        / "comic_episode_pipeline_web.disabled"
        / "comic_previews"
    )
    return {
        "backend": image_backend,
        "latest_file": str(preview_dir / "latest.html"),
        "episode_file": str(preview_dir / f"episode{episode_number:02d}.html"),
        "latest_url": f"{comfy_url}/extensions/comic_episode_pipeline_node/comic_previews/latest.html",
        "episode_url": f"{comfy_url}/extensions/comic_episode_pipeline_node/comic_previews/episode{episode_number:02d}.html",
    }


def status_snapshot(episode_number: int) -> dict:
    try:
        project = active_project()
    except Exception:
        return {
            "episode_number": episode_number,
            "episode_id": "",
            "episode_title": "",
            "updated": datetime.now().isoformat(timespec="seconds"),
            "pipeline_result": None,
            "stage_files": [],
            "preview": preview_paths(episode_number),
            "texts": {
                "draft_review_md": "尚未导入小说。",
                "draft_qa_md": "",
                "status_md": "",
                "lettering_qa_md": "",
                "consistency_qa_md": "",
                "image_health_qa_md": "",
            },
        }
    manifest_dir = project_manifest_dir(project)
    long_stem = project_episode_stem(project, episode_number)
    episode_id = project_episode_id(project, episode_number)
    effective_output_root = output_root()
    review_root = effective_output_root / "review_packages"
    paths = {
        "episode_plan": manifest_dir / f"{long_stem}_pages.json",
        "pipeline_result": manifest_dir / f"{long_stem}_pipeline_run.json",
        "page_plan_result": manifest_dir / f"{long_stem}_page_plan_create_result.json",
        "workflow_create_result": manifest_dir / f"{long_stem}_workflow_create_result.json",
        "draft_review_json": manifest_dir / f"{long_stem}_draft_review.json",
        "draft_qa_json": manifest_dir / f"{long_stem}_draft_qa.json",
        "status_json": manifest_dir / f"{long_stem}_status.json",
        "draft_review_md": review_root / f"{episode_id}_draft_review.md",
        "draft_qa_md": review_root / f"{episode_id}_draft_qa.md",
        "status_md": review_root / f"{episode_id}_status.md",
        "lettering_qa_md": review_root / f"{episode_id}_lettering_qa.md",
        "consistency_qa_md": review_root / f"{episode_id}_consistency_qa.md",
        "image_health_qa_md": review_root / f"{episode_id}_image_health_qa.md",
    }
    stages = []
    for name, path in paths.items():
        stages.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.is_file(),
                "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.is_file() else "",
            }
        )
    result = read_optional_json(paths["pipeline_result"])
    plan = read_optional_json(paths["episode_plan"])
    return {
        "episode_number": episode_number,
        "episode_id": episode_id,
        "episode_title": (plan or {}).get("episode_title", "") if isinstance(plan, dict) else "",
        "updated": datetime.now().isoformat(timespec="seconds"),
        "pipeline_result": result,
        "stage_files": stages,
        "preview": preview_paths(episode_number),
        "texts": {
            "draft_review_md": read_optional_text(paths["draft_review_md"]),
            "draft_qa_md": read_optional_text(paths["draft_qa_md"]),
            "status_md": read_optional_text(paths["status_md"]),
            "lettering_qa_md": read_optional_text(paths["lettering_qa_md"], 8000),
            "consistency_qa_md": read_optional_text(paths["consistency_qa_md"], 8000),
            "image_health_qa_md": read_optional_text(paths["image_health_qa_md"], 8000),
        },
    }


def episode_output_counts(episode_number: int) -> dict:
    return output_count_map(active_project()).get(episode_number, empty_output_counts())


def empty_output_counts() -> dict:
    return {
        "generated_pages": 0,
        "generated_panels": 0,
        "latest_page_updated": "",
        "latest_panel_updated": "",
    }


def output_count_map(project: dict | None = None) -> dict[int, dict]:
    project = project or active_project()
    page_to_episode: dict[str, int] = {}
    for plan_path in sorted(project_manifest_dir(project).glob("*_pages.json")):
        plan_number = episode_number_from_id(plan_path.stem)
        plan = read_optional_json(plan_path) or {}
        if not isinstance(plan, dict):
            continue
        episode_number = episode_number_from_id(plan.get("episode_id", "")) or plan_number
        if not episode_number:
            continue
        for page in plan.get("pages", []):
            page_id = str(page.get("page_id") or "")
            if page_id:
                page_to_episode[page_id.upper()] = episode_number
    counts: dict[int, dict] = {}
    pages_dir = output_root() / "pages"
    panels_dir = output_root() / "panels"
    if pages_dir.is_dir():
        for path in pages_dir.glob("*.png"):
            upper_name = path.name.upper()
            episode_number = next((number for page_id, number in page_to_episode.items() if upper_name.startswith(page_id)), 0)
            if not episode_number:
                continue
            item = counts.setdefault(episode_number, empty_output_counts())
            item["generated_pages"] += 1
            updated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            if updated > item["latest_page_updated"]:
                item["latest_page_updated"] = updated
    seen_panels: dict[int, set[str]] = {}
    if panels_dir.is_dir():
        for path in panels_dir.glob("*.png"):
            upper_name = path.name.upper()
            matched_page_id = next((page_id for page_id in page_to_episode if upper_name.startswith(page_id)), "")
            episode_number = page_to_episode.get(matched_page_id, 0)
            if not episode_number:
                continue
            item = counts.setdefault(episode_number, empty_output_counts())
            match = re.search(r"((?:[A-Z0-9_]+_)?EP\d+_P\d+_PANEL\d+)", path.name, re.IGNORECASE)
            panel_key = match.group(1).upper() if match else path.stem
            seen_panels.setdefault(episode_number, set()).add(panel_key)
            updated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            if updated > item["latest_panel_updated"]:
                item["latest_panel_updated"] = updated
    for episode_number, panel_keys in seen_panels.items():
        counts.setdefault(episode_number, empty_output_counts())["generated_panels"] = len(panel_keys)
    return counts


def episode_output_counts_legacy(episode_number: int) -> dict:
    prefixes = {episode_id_short(episode_number), episode_id_long(episode_number)}
    pages_dir = output_root() / "pages"
    panels_dir = output_root() / "panels"
    page_files = []
    panel_files = []
    if pages_dir.is_dir():
        for prefix in prefixes:
            page_files.extend(pages_dir.glob(f"{prefix}_P*.png"))
    if panels_dir.is_dir():
        for prefix in prefixes:
            panel_files.extend(panels_dir.glob(f"{prefix}_P*_PANEL*_*.png"))
    page_files = sorted(set(page_files))
    panel_files = sorted(set(panel_files))
    unique_panels = set()
    for path in panel_files:
        match = re.search(r"(SSJ_COMIC_EP\d+_P\d+_PANEL\d+)", path.name, re.IGNORECASE)
        if match:
            unique_panels.add(match.group(1).upper())
    return {
        "generated_pages": len(page_files),
        "generated_panels": len(unique_panels) or len(panel_files),
        "latest_page_updated": datetime.fromtimestamp(max(path.stat().st_mtime for path in page_files)).isoformat(timespec="seconds") if page_files else "",
        "latest_panel_updated": datetime.fromtimestamp(max(path.stat().st_mtime for path in panel_files)).isoformat(timespec="seconds") if panel_files else "",
    }


def list_episodes() -> dict:
    try:
        project = active_project()
    except Exception:
        return {
            "updated": datetime.now().isoformat(timespec="seconds"),
            "series": {
                "project": "",
                "source": "",
                "project_slug": "",
                "project_title": "",
                "novel_path": "",
                "series_plan_path": "",
                "totals": {},
            },
            "episodes": [],
        }
    series = read_optional_json(series_plan_path(project)) or {}
    episodes = []
    db_episodes = db.list_episodes(database_url(), project["slug"])
    source_items = db_episodes or (series.get("episodes", []) if isinstance(series, dict) else [])
    counts_by_episode = output_count_map(project)
    for item in source_items:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
        episode_number = int(item.get("episode_number") or episode_number_from_id(raw.get("episode_id", "")))
        if not episode_number:
            continue
        plan = load_episode_plan(episode_number)
        counts = counts_by_episode.get(episode_number, empty_output_counts())
        planned_pages = int(item.get("planned_pages") or raw.get("planned_pages") or len(plan.get("pages", [])) or 0)
        planned_panels = int(item.get("planned_panels") or raw.get("planned_panels") or sum(len(page.get("panels", [])) for page in plan.get("pages", [])) or 0)
        has_plan = bool(plan and not plan.get("error"))
        has_outputs = counts["generated_pages"] > 0 or counts["generated_panels"] > 0
        if has_outputs:
            production_state = "generated"
        elif has_plan:
            production_state = "draft_ready"
        else:
            production_state = "not_started"
        episodes.append(
            {
                "episode_number": episode_number,
                "episode_id": project_episode_id(project, episode_number),
                "series_episode_id": raw.get("episode_id", item.get("episode_code", project_episode_id(project, episode_number))),
                "source_volume": raw.get("source_volume", ""),
                "chapter_title": raw.get("chapter_title", item.get("title", "")),
                "chapter_line": raw.get("chapter_line", 0),
                "priority": raw.get("priority", ""),
                "series_status": item.get("status", raw.get("status", "")),
                "production_state": production_state,
                "has_plan": has_plan,
                "planned_pages": planned_pages,
                "planned_panels": planned_panels,
                **counts,
            }
        )
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "series": {
            "project": series.get("project", "") if isinstance(series, dict) else "",
            "source": series.get("source", "") if isinstance(series, dict) else "",
            "project_slug": project.get("slug", ""),
            "project_title": project.get("title", ""),
            "novel_path": project.get("novel_path", ""),
            "series_plan_path": str(series_plan_path(project)),
            "totals": series.get("totals", {}) if isinstance(series, dict) else {},
        },
        "episodes": episodes,
    }


def panel_id_for(page_id: str, panel: dict, index: int) -> str:
    return str(panel.get("panel_id") or f"{page_id}_PANEL{index + 1:02d}")


def episode_media(episode_number: int) -> dict:
    project = active_project()
    plan = load_episode_plan(episode_number)
    pages = []
    panels = []
    for page in plan.get("pages", []) if isinstance(plan, dict) else []:
        page_id = str(page.get("page_id") or "")
        if not page_id:
            continue
        pages.append(make_media_item("page", page_id, page_image_path(episode_number, page_id), page.get("title", ""), page_id=page_id))
        for index, panel in enumerate(page.get("panels", [])):
            panel_id = panel_id_for(page_id, panel, index)
            panels.append(
                make_media_item(
                    "panel",
                    panel_id,
                    panel_image_path(panel_id),
                    panel.get("title", ""),
                    page_id=page_id,
                    panel_id=panel_id,
                )
            )
    panel_counts_by_page = {}
    panel_ready_by_page = {}
    for panel in panels:
        page_id = panel.get("page_id", "")
        if not page_id:
            continue
        counts = panel_counts_by_page.setdefault(page_id, {"total": 0, "ready": 0})
        counts["total"] += 1
        if panel.get("exists") and panel.get("path"):
            counts["ready"] += 1
            panel_ready_by_page[page_id] = True
    for page in pages:
        page_id = page.get("page_id", "")
        counts = panel_counts_by_page.get(page_id, {"total": 0, "ready": 0})
        total_panels = int(counts.get("total") or 0)
        ready_panels = int(counts.get("ready") or 0)
        page["panel_total"] = total_panels
        page["panel_ready"] = ready_panels
        page_complete = bool(total_panels) and ready_panels >= total_panels
        is_placeholder = bool(page.get("exists")) and ready_panels == 0
        page["placeholder"] = is_placeholder
        if is_placeholder:
            page["production_status"] = "placeholder"
        elif page.get("exists") and page_complete:
            page["production_status"] = "ready"
        elif page.get("exists") and ready_panels:
            page["production_status"] = "partial"
        else:
            page["production_status"] = "missing"
    for panel in panels:
        panel["placeholder"] = False
        panel["production_status"] = "ready" if panel.get("exists") else "missing"
    missing_panels = [item for item in panels if not item.get("exists")]
    missing_pages = [item for item in pages if not item.get("exists")]
    real_pages_ready = len([item for item in pages if item["exists"] and item.get("production_status") == "ready"])
    return {
        "episode_number": episode_number,
        "episode_id": project_episode_id(project, episode_number),
        "pages": pages,
        "panels": panels,
        "missing": {
            "pages": missing_pages,
            "panels": missing_panels,
            "panel_ids": [item.get("panel_id") or item.get("id", "") for item in missing_panels],
        },
        "summary": {
            "pages_total": len(pages),
            "pages_ready": len([item for item in pages if item["exists"]]),
            "real_pages_ready": real_pages_ready,
            "placeholder_pages": len([item for item in pages if item.get("placeholder")]),
            "partial_pages": len([item for item in pages if item.get("production_status") == "partial"]),
            "panels_total": len(panels),
            "panels_ready": len([item for item in panels if item["exists"]]),
            "missing_pages": len(missing_pages),
            "missing_panels": len(missing_panels),
        },
    }


def classify_generation_issue(value: str) -> dict:
    text = str(value or "")
    lower = text.lower()
    if not text:
        return {
            "type": "unknown",
            "severity": "info",
            "message": "",
            "action": "查看任务日志并重试。",
            "retry_hint": "可以重试",
            "cooldown_seconds": 0,
        }
    if "b64_json" in lower:
        return {
            "type": "empty_image_response",
            "severity": "blocked",
            "message": "图片接口没有返回可用图像数据，通常是上游图片模型、API Key、额度或响应格式异常。",
            "action": "先检查图片生成模型、API Key、接口地址和额度；确认后再单格补生成。",
            "retry_hint": "检查配置后重试",
            "cooldown_seconds": 0,
        }
    if "unsupported content type" in lower or "invalid_request_error" in lower and "content type" in lower:
        return {
            "type": "unsupported_content_type",
            "severity": "blocked",
            "message": "图片接口返回内容类型不兼容，通常是上游接口不支持当前图片请求格式。",
            "action": "检查模型接口地址、图片模型和响应格式兼容性；必要时切换到支持 OpenAI 图片接口格式的上游。",
            "retry_hint": "修复接口兼容后重试",
            "cooldown_seconds": 0,
        }
    if "rate limit" in lower or "429" in lower:
        return {
            "type": "rate_limited",
            "severity": "cooldown",
            "message": "图片接口限流或额度不足，建议稍后重试或检查账号额度。",
            "action": "等待接口冷却后只补生成缺失分镜；如果持续出现，请降低并发或更换额度充足的账号。",
            "retry_hint": "建议稍后重试",
            "cooldown_seconds": 120,
        }
    if "authentication" in lower or "unauthorized" in lower or "401" in lower or "api key" in lower:
        return {
            "type": "auth_failed",
            "severity": "blocked",
            "message": "图片接口鉴权失败，请到设置中检查 API Key。",
            "action": "打开设置页更新模型接口密钥，保存后先检查后端，再重试生成。",
            "retry_hint": "配置修复后重试",
            "cooldown_seconds": 0,
        }
    if "model" in lower and ("not found" in lower or "missing" in lower):
        return {
            "type": "model_unavailable",
            "severity": "blocked",
            "message": "图片模型不可用或模型名称配置错误，请检查图片生成模型设置。",
            "action": "打开设置页确认图片生成模型名称，并确认上游接口支持该模型。",
            "retry_hint": "模型修复后重试",
            "cooldown_seconds": 0,
        }
    if "workflow not found" in lower:
        return {
            "type": "workflow_missing",
            "severity": "blocked",
            "message": "分镜工作流文件缺失，需要重新生成章节工作流。",
            "action": "重新执行章节拆解或工作流生成，再补生成当前页。",
            "retry_hint": "重建工作流后重试",
            "cooldown_seconds": 0,
        }
    if "panel run failed" in lower:
        return {
            "type": "panel_failed",
            "severity": "retryable",
            "message": "分镜生成任务失败，请查看上方图片接口诊断，或稍后补生成该分镜。",
            "action": "进入生成结果分镜列表，只补生成失败分镜。",
            "retry_hint": "可以单格重试",
            "cooldown_seconds": 0,
        }
    if "timed out" in lower or "timeout" in lower:
        return {
            "type": "timeout",
            "severity": "cooldown",
            "message": "生成等待超时，可能是生成后端队列繁忙或上游响应过慢。",
            "action": "确认生成后端队列空闲后，只补生成缺失分镜；不要立即连续启动整页或整章任务。",
            "retry_hint": "队列空闲后重试",
            "cooldown_seconds": 60,
        }
    if "connection" in lower or "refused" in lower:
        return {
            "type": "backend_unreachable",
            "severity": "blocked",
            "message": "图片生成后端连接失败，请检查当前后端的接口地址和运行状态。",
            "action": "打开设置页检查所选图片后端；直连模式检查网络和接口地址，ComfyUI 模式检查本地服务。",
            "retry_hint": "后端恢复后重试",
            "cooldown_seconds": 0,
        }
    return {
        "type": "unknown",
        "severity": "retryable",
        "message": text,
        "action": "查看原始日志，确认不是配置或额度问题后再重试。",
        "retry_hint": "谨慎重试",
        "cooldown_seconds": 0,
    }


def chinese_generation_issue(value: str) -> str:
    return classify_generation_issue(value).get("message", "")


def generation_diagnostics_from_result(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    recovery_result = {}
    recovery_path = str((result.get("paths") or {}).get("recovery_result") or "")
    if recovery_path:
        recovery_result = read_optional_json(Path(recovery_path)) or {}
    issues = []

    def add_issue(panel_id: str = "", error: object = "") -> None:
        raw = str(error or "").strip()
        if not raw:
            return
        classification = classify_generation_issue(raw)
        issues.append({
            "panel_id": panel_id or "",
            "message": classification.get("message") or raw,
            "raw": raw,
            "type": classification.get("type", "unknown"),
            "severity": classification.get("severity", "retryable"),
            "action": classification.get("action", ""),
            "retry_hint": classification.get("retry_hint", ""),
            "cooldown_seconds": int(classification.get("cooldown_seconds") or 0),
        })

    direct_runs = result.get("runs")
    if isinstance(direct_runs, list):
        for run in direct_runs:
            if not isinstance(run, dict):
                continue
            panel_id = str(run.get("panel_id") or "")
            add_issue(panel_id, run.get("error"))
            add_issue(panel_id, run.get("last_error"))
            nested = run.get("result")
            if isinstance(nested, dict):
                add_issue(panel_id or str(nested.get("shot_id") or ""), nested.get("error"))
                wait_result = nested.get("wait_result")
                if isinstance(wait_result, dict):
                    add_issue(panel_id or str(nested.get("shot_id") or ""), wait_result.get("error"))

    attempted = result.get("jobs_attempted") or recovery_result.get("jobs_attempted") or []
    if isinstance(attempted, list):
        for item in attempted:
            if not isinstance(item, dict):
                continue
            run_summary = item.get("run_summary") or {}
            runs = run_summary.get("runs") or []
            if isinstance(runs, list):
                for run in runs:
                    if isinstance(run, dict) and run.get("last_error"):
                        add_issue(run.get("panel_id") or item.get("panel_id", ""), run.get("last_error"))
            add_issue(item.get("panel_id", ""), item.get("error"))
    missing_panels = []
    for source in (result.get("waiting_detail"), recovery_result.get("waiting_detail")):
        if isinstance(source, dict) and isinstance(source.get("missing_panels"), list):
            missing_panels.extend([str(item) for item in source.get("missing_panels") if item])
    waiting_for_panels = int(
        result.get("waiting_for_panels")
        or recovery_result.get("waiting_for_panels")
        or len(set(missing_panels))
        or 0
    )
    if waiting_for_panels:
        issues.append({
            "panel_id": "",
            "message": "仍有分镜没有生成，请在生成结果的分镜列表中逐格补生成，或从任务日志继续重试。",
            "raw": "waiting_for_panels",
            "type": "waiting_for_panels",
            "severity": "retryable",
            "action": "进入生成结果的分镜视图，优先补生成缺失分镜。",
            "retry_hint": "可以补生成",
            "cooldown_seconds": 0,
        })
    deduped = []
    seen = set()
    for issue in issues:
        key = (issue.get("panel_id", ""), issue.get("message", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return {
        "issues": deduped[:8],
        "waiting_for_panels": waiting_for_panels,
        "missing_panels": sorted(set(missing_panels)),
        "waiting_reason": str(result.get("waiting_reason") or ("waiting_for_panels" if result.get("waiting_for_panels") else "")),
    }


def text_model_diagnostics_from_result(result: dict | None, stderr_tail: str = "") -> dict:
    if not isinstance(result, dict) and not stderr_tail:
        return {}
    result = result if isinstance(result, dict) else {}
    raw_parts = [
        str(result.get("error_type") or ""),
        str(result.get("error") or ""),
        str(result.get("message") or ""),
        str(stderr_tail or ""),
    ]
    raw = "\n".join(part for part in raw_parts if part).strip()
    if not raw:
        return {}
    lower = raw.lower()
    error_type = str(result.get("error_type") or "")
    issue_type = "text_model_error"
    severity = "retryable"
    message = result.get("message") or "小说处理模型任务失败，页面计划未修改。"
    action = "查看模型接口状态和任务日志，确认后重试细读拆解。"
    retry_hint = "可以重试"
    cooldown_seconds = 0
    if error_type == "text_model_rate_limited" or "429" in lower or "rate_limit" in lower or "requests-per-minute" in lower:
        issue_type = "text_model_rate_limited"
        severity = "cooldown"
        message = "小说处理模型请求过于频繁，本次未修改章节计划。"
        action = "等待模型接口冷却后重试细读拆解；不要连续快速重试。"
        retry_hint = "稍后重试"
        cooldown_seconds = 60
    elif "503" in lower or "service temporarily unavailable" in lower or "service unavailable" in lower:
        issue_type = "text_model_unavailable"
        severity = "retryable"
        message = "小说处理模型服务临时不可用，本次未修改章节计划。"
        action = "稍后重试细读拆解；如果持续失败，检查小说处理模型接口地址和服务状态。"
        retry_hint = "稍后重试"
    elif "401" in lower or "403" in lower or "unauthorized" in lower or "forbidden" in lower or "api key" in lower or "auth" in lower:
        issue_type = "text_model_auth_failed"
        severity = "blocked"
        message = "小说处理模型鉴权失败，本次未修改章节计划。"
        action = "到设置中心检查小说处理模型 API Key、Base URL 和模型名称。"
        retry_hint = "修复配置后重试"
    elif "timeout" in lower or "timed out" in lower:
        issue_type = "text_model_timeout"
        severity = "retryable"
        message = "小说处理模型响应超时，本次未修改章节计划。"
        action = "稍后重试；如果章节过长，需要降低单次细读页数或检查模型服务稳定性。"
        retry_hint = "可以重试"
    candidate_pages = [str(item) for item in (result.get("candidate_pages") or []) if item]
    protected_pages = [
        str((item or {}).get("page_id") or item)
        for item in (result.get("protected_pages") or [])
        if item
    ]
    return {
        "domain": "text_model",
        "title": "小说处理诊断",
        "issues": [{
            "panel_id": "",
            "message": message,
            "raw": raw[:1200],
            "type": issue_type,
            "severity": severity,
            "action": action,
            "retry_hint": retry_hint,
            "cooldown_seconds": cooldown_seconds,
        }],
        "waiting_reason": issue_type,
        "candidate_pages": candidate_pages,
        "protected_pages": protected_pages,
    }


def job_diagnostics(job: dict, result: dict | None = None, stderr_tail: str = "") -> dict:
    stage = job.get("stage")
    result = result if result is not None else job.get("result")
    stderr_tail = stderr_tail or str(job.get("stderr_tail") or "")
    if stage in {"generate", "regenerate", "regenerate_page"}:
        return generation_diagnostics_from_result(result if isinstance(result, dict) else None)
    if stage == "close_reading":
        return text_model_diagnostics_from_result(result if isinstance(result, dict) else None, stderr_tail)
    return {}


def attach_output_db_state(project: dict, media: dict) -> dict:
    rows = db.list_generated_outputs(database_url(), project["slug"], int(media.get("episode_number") or 0))
    by_path = {str(row.get("file_path") or ""): row for row in rows if row.get("file_path")}
    versions = db.list_output_versions(
        database_url(),
        project["slug"],
        [int(row["id"]) for row in rows if row.get("id")],
    ) if rows else []
    versions_by_output: dict[int, list[dict]] = {}
    for version in versions:
        output_id = int(version.get("output_id") or 0)
        if output_id:
            versions_by_output.setdefault(output_id, []).append(version)
    for group in ("pages", "panels"):
        for item in media.get(group, []):
            row = by_path.get(str(item.get("path") or ""))
            if not row:
                item["db_output_id"] = ""
                item["db_review_status"] = ""
                item["db_review_action"] = ""
                item["db_reviewed_at"] = ""
                item["db_review_comment"] = ""
                item["db_versions"] = []
                item["db_version_count"] = 0
                item["db_synced"] = False
                continue
            metadata = row.get("metadata") or {}
            output_id = int(row.get("id") or 0)
            item["db_output_id"] = row.get("id", "")
            item["db_review_status"] = row.get("review_status", "")
            item["db_review_action"] = metadata.get("review_action", "")
            item["db_reviewed_at"] = metadata.get("reviewed_at", "")
            item["db_review_comment"] = metadata.get("review_comment", "")
            item["db_review_quality_checks"] = metadata.get("review_quality_checks", [])
            item["db_review_quality_summary"] = metadata.get("review_quality_summary", {})
            context_snapshot = metadata.get("generation_context") or {}
            item["db_generation_context"] = context_snapshot if isinstance(context_snapshot, dict) else {}
            item["db_versions"] = versions_by_output.get(output_id, [])
            item["db_version_count"] = len(item["db_versions"])
            item["db_synced"] = True
    media["db_summary"] = {
        "synced": len(rows),
        "approved": len([row for row in rows if row.get("review_status") == "approved"]),
        "pending": len([row for row in rows if row.get("review_status") in {"draft", "pending_review", "needs_work"}]),
    }
    media["review_blockers"] = generated_output_review_blockers_from_rows(rows)
    return media


def output_page_id(row: dict) -> str:
    metadata = row.get("metadata") or {}
    for key in ("page_id", "media_id", "panel_id"):
        value = str(metadata.get(key) or "")
        match = re.search(r"((?:[A-Z0-9]+_)*EP0*\d+_P0*\d+)", value, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    file_path = str(row.get("file_path") or "")
    match = re.search(r"((?:[A-Z0-9]+_)*EP0*\d+_P0*\d+)", file_path, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    chapter = int(row.get("chapter_number") or 0)
    page = int(row.get("page_index") or 0)
    if chapter and page:
        return f"SSJ_COMIC_EP{chapter:02d}_P{page:03d}"
    return ""


def generated_output_review_blockers_from_rows(rows: list[dict], ignored_page_id: str = "") -> dict:
    ignored = str(ignored_page_id or "").upper()
    pending_rows = [
        row for row in rows
        if row.get("review_status") in {"draft", "pending_review", "needs_work"}
        and (not ignored or output_page_id(row).upper() != ignored)
    ]
    by_page: dict[str, int] = {}
    for row in pending_rows:
        page_id = output_page_id(row)
        if page_id:
            by_page[page_id] = by_page.get(page_id, 0) + 1
    first_page_id = sorted(by_page.keys())[0] if by_page else ""
    return {
        "count": len(pending_rows),
        "pages": [{"page_id": page_id, "count": by_page[page_id]} for page_id in sorted(by_page.keys())],
        "first_page_id": first_page_id,
        "first_page_count": by_page.get(first_page_id, 0) if first_page_id else 0,
    }


def generated_output_review_blockers(project: dict, episode_number: int, ignored_page_id: str = "") -> dict:
    rows = db.list_generated_outputs(database_url(), project["slug"], episode_number)
    return generated_output_review_blockers_from_rows(rows, ignored_page_id)


def review_blocker_message(episode_number: int, blockers: dict) -> str:
    count = int(blockers.get("count") or 0)
    first_page = str(blockers.get("first_page_id") or "")
    first_count = int(blockers.get("first_page_count") or 0)
    if first_page and first_count:
        return f"{episode_display(episode_number)}{page_display(first_page)}还有 {first_count} 个生成结果待审核，请先完成当前页面审核后再生成下一页。"
    return f"{episode_display(episode_number)}还有 {count} 个生成结果待审核，请先完成当前页面审核后再生成下一页。"


def compact_text(value: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


CHAPTER_ASSET_SETTING_TYPES = {"character", "location", "prop"}
CHAPTER_ASSET_IMPORTANCE = {"core", "high"}


def chapter_reference_text(pages: list[dict]) -> str:
    values = []
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        for field in ("summary", "source_excerpt", "visual_priority"):
            if page.get(field):
                values.append(str(page[field]))
        for panel in page.get("panels") or []:
            if not isinstance(panel, dict):
                continue
            for field in ("title", "prompt", "caption", "visual_priority"):
                if panel.get(field):
                    values.append(str(panel[field]))
            dialogue = panel.get("dialogue") or []
            if isinstance(dialogue, list):
                for item in dialogue:
                    values.append(str(item.get("text") or item) if isinstance(item, dict) else str(item))
            elif dialogue:
                values.append(str(dialogue))
    return "\n".join(values)


def infer_referenced_setting_ids(
    episode_number: int,
    pages: list[dict],
    settings: list[dict],
    explicit_ids: list | None = None,
) -> list[int]:
    explicit = {int(item) for item in (explicit_ids or []) if str(item).strip().isdigit()}
    text = chapter_reference_text(pages)
    referenced = set(explicit)
    for setting in settings:
        setting_id = int(setting.get("id") or 0)
        if not setting_id:
            continue
        chapter_numbers = {
            int(item) for item in (setting.get("chapter_numbers") or [])
            if str(item).strip().isdigit()
        }
        terms = [str(setting.get("name") or "").strip()]
        aliases = setting.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        terms.extend(str(item).strip() for item in aliases)
        mentioned = any(term and len(term) >= 2 and term in text for term in terms)
        if episode_number in chapter_numbers or mentioned:
            referenced.add(setting_id)
    return sorted(referenced)


def chapter_asset_coverage(
    project: dict,
    episode_number: int,
    pages: list[dict] | None = None,
    settings: list[dict] | None = None,
    assets: list[dict] | None = None,
    breakdown: dict | None = None,
) -> dict:
    settings = settings if settings is not None else db.list_setting_items(database_url(), project["slug"])
    assets = assets if assets is not None else db.list_visual_assets(database_url(), project["slug"])
    breakdown = breakdown if breakdown is not None else db.get_chapter_breakdown(database_url(), project["slug"], episode_number)
    pages = pages if pages is not None else ((breakdown or {}).get("pages") or [])
    reference_ids = infer_referenced_setting_ids(
        episode_number,
        pages,
        settings,
        (breakdown or {}).get("referenced_setting_ids") or [],
    )
    by_id = {int(item.get("id") or 0): item for item in settings if int(item.get("id") or 0)}
    required = [
        by_id[setting_id]
        for setting_id in reference_ids
        if setting_id in by_id
        and str(by_id[setting_id].get("item_type") or "") in CHAPTER_ASSET_SETTING_TYPES
        and str(by_id[setting_id].get("importance") or "normal") in CHAPTER_ASSET_IMPORTANCE
    ]
    approved_required = [
        item for item in required
        if item.get("review_status") == "approved" or item.get("locked")
    ]
    approved_asset_setting_ids = set()
    for asset in assets:
        setting_id = int(asset.get("setting_item_id") or 0)
        file_path = str(asset.get("file_path") or "")
        if not setting_id or not file_path or not Path(file_path).is_file():
            continue
        if asset.get("review_status") == "approved" or asset.get("locked"):
            approved_asset_setting_ids.add(setting_id)
    missing_setting_review = [item for item in required if item not in approved_required]
    missing_assets = [
        item for item in approved_required
        if int(item.get("id") or 0) not in approved_asset_setting_ids
    ]
    blockers = []
    if missing_setting_review:
        blockers.append("本章核心设定待审核：" + "、".join(item.get("name") or "未命名设定" for item in missing_setting_review[:6]))
    if missing_assets:
        blockers.append("本章核心素材未生成或未审核：" + "、".join(item.get("name") or "未命名设定" for item in missing_assets[:6]))
    required_rows = [{
        "id": int(item.get("id") or 0),
        "name": item.get("name") or "",
        "item_type": item.get("item_type") or "",
        "type_label": setting_type_label(item.get("item_type") or ""),
        "importance": item.get("importance") or "normal",
        "setting_ready": item in approved_required,
        "asset_ready": int(item.get("id") or 0) in approved_asset_setting_ids,
    } for item in required]
    return {
        "ok": not blockers,
        "episode_number": episode_number,
        "reference_ids": reference_ids,
        "required": required_rows,
        "required_count": len(required_rows),
        "covered_count": len([item for item in required_rows if item["setting_ready"] and item["asset_ready"]]),
        "missing_setting_review": [item.get("name") or "" for item in missing_setting_review],
        "missing_assets": [item.get("name") or "" for item in missing_assets],
        "blockers": blockers,
        "message": "；".join(blockers),
    }


def build_generation_context_snapshot(project: dict, episode_number: int, page_id: str = "", panel_ids: list[str] | None = None) -> dict:
    settings = db.list_setting_items(database_url(), project["slug"])
    breakdown = db.get_chapter_breakdown(database_url(), project["slug"], episode_number)
    reference_ids = set(infer_referenced_setting_ids(
        episode_number,
        (breakdown or {}).get("pages") or [],
        settings,
        (breakdown or {}).get("referenced_setting_ids") or [],
    ))
    approved_settings = [
        item for item in settings
        if item.get("review_status") == "approved" or item.get("locked")
    ]
    if reference_ids:
        approved_settings = [item for item in approved_settings if int(item.get("id") or 0) in reference_ids]
    assets = db.list_visual_assets(database_url(), project["slug"])
    locked_assets = [
        item for item in assets
        if item.get("locked") or item.get("review_status") == "approved"
    ]
    if reference_ids:
        locked_assets = [item for item in locked_assets if int(item.get("setting_item_id") or 0) in reference_ids]
    setting_items = []
    for item in approved_settings[:24]:
        setting_items.append({
            "id": int(item.get("id") or 0),
            "type": item.get("item_type", ""),
            "name": item.get("name", ""),
            "locked": bool(item.get("locked")),
            "review_status": item.get("review_status", ""),
            "visual_prompt": compact_text(item.get("visual_prompt", ""), 220),
            "description": compact_text(item.get("description", ""), 220),
        })
    asset_items = []
    for item in locked_assets[:24]:
        asset_items.append({
            "id": int(item.get("id") or 0),
            "type": item.get("asset_type", ""),
            "title": item.get("setting_name") or item.get("title", ""),
            "setting_item_id": int(item.get("setting_item_id") or 0),
            "locked": bool(item.get("locked")),
            "review_status": item.get("review_status", ""),
            "file_path": item.get("file_path", ""),
        })
    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "project_slug": project.get("slug", ""),
        "episode_number": int(episode_number or 0),
        "page_id": page_id,
        "panel_ids": [str(item) for item in (panel_ids or []) if item],
        "referenced_setting_ids": sorted(reference_ids),
        "settings": setting_items,
        "assets": asset_items,
        "summary": {
            "approved_or_locked_settings": len(approved_settings),
            "locked_or_approved_assets": len(locked_assets),
            "settings_included": len(setting_items),
            "assets_included": len(asset_items),
        },
    }


def hydrate_episode_asset_aliases(project: dict, episode_number: int, context: dict) -> dict:
    plan_path = project_episode_plan_path(episode_number, project)
    plan = read_optional_json(plan_path) or {}
    assets = [
        item for item in (context.get("assets") or [])
        if str(item.get("title") or "").strip() and Path(str(item.get("file_path") or "")).is_file()
    ]
    assets.sort(key=lambda item: ({"characters": 0, "world_scenes": 1, "weapons": 2}.get(item.get("type"), 9), int(item.get("id") or 0)))
    aliases = {str(item["title"]).strip(): str(item["file_path"]) for item in assets}
    for page in plan.get("pages") or []:
        for panel in page.get("panels") or []:
            current = str(panel.get("reference_alias") or "").strip()
            if current in aliases:
                continue
            prompt = str(panel.get("prompt") or "")
            matches = [alias for alias in aliases if alias in current]
            if not matches:
                matches = [alias for alias in aliases if alias in prompt]
            panel["reference_alias"] = matches[0] if matches else ""
    plan["asset_aliases"] = aliases
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"aliases": aliases, "plan_path": str(plan_path)}


def generation_context_matches_item(context_snapshot: dict, item: dict) -> bool:
    if not isinstance(context_snapshot, dict) or not context_snapshot:
        return False
    context_page_id = str(context_snapshot.get("page_id") or "")
    context_page_ids = {str(value) for value in (context_snapshot.get("page_ids") or []) if value}
    context_panel_ids = {str(value) for value in (context_snapshot.get("panel_ids") or []) if value}
    item_kind = str(item.get("kind") or "")
    item_page_id = str(item.get("page_id") or item.get("id") or "")
    item_panel_id = str(item.get("panel_id") or item.get("id") or "")
    if item_kind == "page":
        if context_page_ids:
            return item_page_id in context_page_ids
        return bool(context_page_id and item_page_id == context_page_id)
    if item_kind == "panel" and context_panel_ids:
        return item_panel_id in context_panel_ids
    if item_kind == "panel" and context_page_id:
        return item_page_id == context_page_id
    if item_kind == "panel" and context_page_ids:
        return item_page_id in context_page_ids
    if not context_page_id and not context_panel_ids:
        return item_kind in {"page", "panel"}
    return False


def generation_context_prompt_block(context_snapshot: dict) -> str:
    if not isinstance(context_snapshot, dict) or not context_snapshot:
        return ""
    settings = context_snapshot.get("settings") if isinstance(context_snapshot.get("settings"), list) else []
    assets = context_snapshot.get("assets") if isinstance(context_snapshot.get("assets"), list) else []
    review_feedback = compact_text(context_snapshot.get("review_feedback", ""), 500)
    lines = []
    if settings:
        lines.append("已审核小说设定（必须保持一致）：")
        for item in settings[:8]:
            name = compact_text(item.get("name", ""), 80)
            description = compact_text(item.get("visual_prompt") or item.get("description", ""), 220)
            label = SETTING_TYPE_LABELS.get(str(item.get("type") or ""), str(item.get("type") or "设定"))
            locked = "，已锁定" if item.get("locked") else ""
            if name or description:
                lines.append(f"- {label}：{name}{locked}。{description}")
    if assets:
        lines.append("已确认视觉素材（作为画面一致性参考）：")
        for item in assets[:8]:
            title = compact_text(item.get("title", ""), 80)
            asset_type = CATEGORY_LABELS.get(str(item.get("type") or ""), str(item.get("type") or "素材"))
            locked = "，已锁定" if item.get("locked") else ""
            path_note = "已有参考图" if item.get("file_path") else "暂无参考图路径"
            lines.append(f"- {asset_type}：{title}{locked}，{path_note}。")
    if review_feedback:
        lines.append("本次重生成审核反馈（必须针对性修正）：")
        lines.append(f"- {review_feedback}")
    if not lines:
        return ""
    return "\n\n[生成上下文]\n" + "\n".join(lines) + "\n[/生成上下文]"


def output_panel_id(row: dict) -> str:
    metadata = row.get("metadata") or {}
    for key in ("panel_id", "media_id"):
        value = str(metadata.get(key) or "")
        match = re.search(r"((?:[A-Z0-9]+_)*EP0*\d+_P0*\d+_PANEL0*\d+)", value, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    file_path = str(row.get("file_path") or "")
    match = re.search(r"((?:[A-Z0-9]+_)*EP0*\d+_P0*\d+_PANEL0*\d+)", file_path, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    page_id = output_page_id(row)
    panel = int(row.get("panel_index") or 0)
    if page_id and panel:
        return f"{page_id}_PANEL{panel:02d}"
    return ""


def usage_reference_label(chapter_number: int, page_id: str = "", panel_id: str = "") -> str:
    parts = [episode_display(chapter_number)]
    if page_id:
        parts.append(page_display(page_id))
    if panel_id:
        panel = panel_number_from_id(panel_id)
        if panel:
            parts.append(f"第 {panel} 格")
    return " · ".join([item for item in parts if item])


def empty_usage_summary() -> dict:
    return {
        "outputs": 0,
        "chapters": 0,
        "pages": 0,
        "panels": 0,
        "asset_bindings": 0,
        "latest_at": "",
        "latest_label": "",
        "references": [],
    }


def add_usage_reference(index: dict, key: str, reference: dict, kind: str = "outputs") -> None:
    if not key:
        return
    entry = index.setdefault(str(key), {
        "outputs": 0,
        "chapters": set(),
        "pages": set(),
        "panels": set(),
        "asset_bindings": 0,
        "latest_at": "",
        "latest_label": "",
        "references": [],
        "_seen": set(),
    })
    if kind == "asset_binding":
        entry["asset_bindings"] += 1
    else:
        entry["outputs"] += 1
    chapter_number = int(reference.get("chapter_number") or 0)
    page_id = str(reference.get("page_id") or "")
    panel_id = str(reference.get("panel_id") or "")
    if chapter_number:
        entry["chapters"].add(chapter_number)
    if page_id:
        entry["pages"].add(page_id)
    if panel_id:
        entry["panels"].add(panel_id)
    seen_key = f"{kind}:{chapter_number}:{page_id}:{panel_id}:{reference.get('output_id') or reference.get('asset_id') or ''}"
    if seen_key not in entry["_seen"]:
        entry["_seen"].add(seen_key)
        entry["references"].append(reference)
    latest = str(reference.get("created_at") or reference.get("updated_at") or "")
    if latest and latest >= str(entry.get("latest_at") or ""):
        entry["latest_at"] = latest
        entry["latest_label"] = str(reference.get("label") or "")


def finalize_usage_index(index: dict) -> dict:
    finalized = {}
    for key, entry in index.items():
        references = sorted(
            entry.get("references") or [],
            key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""),
            reverse=True,
        )
        finalized[key] = {
            "outputs": int(entry.get("outputs") or 0),
            "chapters": len(entry.get("chapters") or []),
            "pages": len(entry.get("pages") or []),
            "panels": len(entry.get("panels") or []),
            "asset_bindings": int(entry.get("asset_bindings") or 0),
            "latest_at": entry.get("latest_at") or "",
            "latest_label": entry.get("latest_label") or "",
            "references": references[:6],
        }
    return finalized


def build_reference_usage_index(project: dict) -> dict:
    outputs = db.list_generated_outputs(database_url(), project["slug"])
    assets = db.list_visual_assets(database_url(), project["slug"])
    setting_usage: dict[str, dict] = {}
    asset_usage: dict[str, dict] = {}
    for row in outputs:
        metadata = row.get("metadata") or {}
        context = metadata.get("generation_context") or {}
        if not isinstance(context, dict):
            continue
        chapter_number = int(row.get("chapter_number") or context.get("episode_number") or 0)
        page_id = output_page_id(row)
        panel_id = output_panel_id(row)
        reference = {
            "output_id": row.get("id"),
            "output_type": row.get("output_type") or "",
            "review_status": row.get("review_status") or "",
            "chapter_number": chapter_number,
            "page_id": page_id,
            "panel_id": panel_id,
            "file_path": row.get("file_path") or "",
            "created_at": row.get("created_at") or "",
            "label": usage_reference_label(chapter_number, page_id, panel_id),
        }
        for setting in context.get("settings") if isinstance(context.get("settings"), list) else []:
            setting_id = str(setting.get("id") or "")
            setting_name = str(setting.get("name") or "")
            add_usage_reference(setting_usage, setting_id, reference)
            if setting_name:
                add_usage_reference(setting_usage, f"name:{setting_name}", reference)
        for asset in context.get("assets") if isinstance(context.get("assets"), list) else []:
            asset_id = str(asset.get("id") or "")
            setting_id = str(asset.get("setting_item_id") or "")
            title = str(asset.get("title") or "")
            file_path = str(asset.get("file_path") or "")
            add_usage_reference(asset_usage, asset_id, reference)
            if file_path:
                add_usage_reference(asset_usage, f"path:{file_path}", reference)
            if title:
                add_usage_reference(asset_usage, f"title:{title}", reference)
            add_usage_reference(setting_usage, setting_id, reference)
    for asset in assets:
        setting_id = str(asset.get("setting_item_id") or "")
        if not setting_id:
            continue
        chapter_number = int(asset.get("chapter_number") or 0)
        usage = asset.get("usage") or {}
        chapters = usage.get("chapter_numbers") if isinstance(usage, dict) else []
        if not chapter_number and isinstance(chapters, list) and chapters:
            chapter_number = int(chapters[0] or 0)
        reference = {
            "asset_id": asset.get("id"),
            "asset_title": asset.get("title") or "",
            "asset_type": asset.get("asset_type") or "",
            "chapter_number": chapter_number,
            "page_id": "",
            "panel_id": "",
            "review_status": asset.get("review_status") or "",
            "file_path": asset.get("file_path") or "",
            "updated_at": asset.get("updated_at") or "",
            "label": f"绑定素材：{asset.get('title') or '未命名素材'}",
        }
        add_usage_reference(setting_usage, setting_id, reference, "asset_binding")
    return {
        "settings": finalize_usage_index(setting_usage),
        "assets": finalize_usage_index(asset_usage),
    }


def setting_usage_for_item(usage_index: dict, item: dict) -> dict:
    by_setting = usage_index.get("settings") or {}
    item_id = str(item.get("id") or "")
    name_key = f"name:{item.get('name') or ''}"
    usage = by_setting.get(item_id) or by_setting.get(name_key) or {}
    return {**empty_usage_summary(), **usage}


def asset_usage_for_item(usage_index: dict, item: dict) -> dict:
    by_asset = usage_index.get("assets") or {}
    keys = [
        str(item.get("id") or item.get("db_asset_id") or ""),
        f"path:{item.get('file_path') or item.get('path') or ''}",
        f"title:{item.get('title') or item.get('db_title') or item.get('setting_name') or ''}",
    ]
    usage = {}
    for key in keys:
        if key and key in by_asset:
            usage = by_asset[key]
            break
    return {**empty_usage_summary(), **usage}


def inject_generation_context_into_workflow(workflow_path: Path, context_snapshot: dict, job_id: str, panel_id: str = "") -> Path:
    prompt_block = generation_context_prompt_block(context_snapshot)
    if not prompt_block:
        return workflow_path
    workflow = read_optional_json(workflow_path)
    if not isinstance(workflow, dict):
        return workflow_path
    changed = False
    for node in (workflow.get("prompt") or {}).values():
        if not isinstance(node, dict) or node.get("class_type") != "OpenAICompatibleImageGenerate":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        current_prompt = str(inputs.get("prompt") or "")
        if "[生成上下文]" in current_prompt:
            continue
        inputs["prompt"] = current_prompt.rstrip() + prompt_block
        changed = True
    if not changed:
        return workflow_path
    injected_dir = project_manifest_dir() / "comic_runs" / "context_workflows"
    injected_dir.mkdir(parents=True, exist_ok=True)
    suffix = safe_stem(panel_id or workflow_path.stem)
    injected_path = injected_dir / f"{safe_stem(job_id)}_{suffix}.json"
    injected_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return injected_path


def write_generation_context_file(context_snapshot: dict, job_id: str) -> str:
    if not isinstance(context_snapshot, dict) or not context_snapshot:
        return ""
    prompt_block = generation_context_prompt_block(context_snapshot)
    if not prompt_block:
        return ""
    context_with_prompt = {**context_snapshot, "prompt_block": prompt_block}
    context_dir = project_manifest_dir() / "comic_runs" / "generation_context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / f"{safe_stem(job_id)}_context.json"
    context_path.write_text(json.dumps(context_with_prompt, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(context_path)


def add_close_reading_protection_context(project: dict, episode_number: int, context_snapshot: dict) -> dict:
    detail = episode_detail(episode_number)
    protected_page_ids: set[str] = set()
    for item in (detail.get("media") or {}).get("pages", []) or []:
        if item.get("exists") or item.get("db_synced") or item.get("db_output_id"):
            protected_page_ids.add(str(item.get("page_id") or item.get("id") or ""))
    for item in (detail.get("media") or {}).get("panels", []) or []:
        if item.get("exists") or item.get("db_synced") or item.get("db_output_id"):
            protected_page_ids.add(str(item.get("page_id") or ""))
    context = dict(context_snapshot or {})
    context["protected_page_ids"] = sorted(value for value in protected_page_ids if value)
    context["protected_reason"] = "已有生成结果或入库审核记录的页面不会被细读拆解覆盖。"
    return context


def media_output_record(project: dict, episode_number: int, item: dict) -> dict:
    context_snapshot = getattr(_REQUEST_CONTEXT, "generation_context", None)
    source_job_id = str(getattr(_REQUEST_CONTEXT, "source_job_id", "") or "")
    metadata = {
        "media_id": item.get("id", ""),
        "page_id": item.get("page_id", ""),
        "panel_id": item.get("panel_id", ""),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "comfy_url": item.get("comfy_url", ""),
        "size": item.get("size", 0),
        "updated": item.get("updated", ""),
        "placeholder": bool(item.get("placeholder")),
        "production_status": item.get("production_status", ""),
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "source": "episode_media",
        "source_job_id": source_job_id,
    }
    if generation_context_matches_item(context_snapshot, item):
        metadata["generation_context"] = context_snapshot
    return {
        "chapter_number": episode_number,
        "job_id": source_job_id,
        "output_type": item.get("kind") or "panel",
        "page_index": page_number_from_id(item.get("page_id") or item.get("id")),
        "panel_index": panel_number_from_id(item.get("panel_id") or item.get("id")) or None,
        "file_path": item.get("path", ""),
        "thumbnail_path": item.get("path", ""),
        "metadata": metadata,
        "review_status": "pending_review",
    }


def output_version_record(output: dict, role: str, reason: str = "", source_job_id: str = "", file_path: str = "", metadata: dict | None = None) -> dict:
    path = file_path or str(output.get("file_path") or "")
    return {
        "output_id": output.get("id"),
        "chapter_number": output.get("chapter_number"),
        "output_type": output.get("output_type", ""),
        "page_index": output.get("page_index"),
        "panel_index": output.get("panel_index"),
        "file_path": path,
        "thumbnail_path": path or str(output.get("thumbnail_path") or ""),
        "role": role,
        "source_job_id": source_job_id,
        "reason": reason,
        "metadata": {
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            **(metadata or {}),
        },
    }


def ensure_initial_output_version(project: dict, output: dict) -> dict | None:
    output_id = int(output.get("id") or 0)
    if not output_id:
        return None
    existing = db.list_output_versions(database_url(), project["slug"], [output_id])
    if existing:
        return None
    return db.add_output_version(
        database_url(),
        project["slug"],
        output_version_record(output, "current", "首次同步生成结果"),
    )


def record_current_output_version(project: dict, output: dict, reason: str, source_job_id: str = "", metadata: dict | None = None) -> dict | None:
    output_id = int(output.get("id") or 0)
    if not output_id:
        return None
    return db.add_output_version(
        database_url(),
        project["slug"],
        output_version_record(output, "current", reason, source_job_id, metadata=metadata),
    )


def record_previous_output_version(project: dict, output: dict, backup_path: str, reason: str, source_job_id: str = "", metadata: dict | None = None) -> dict | None:
    output_id = int(output.get("id") or 0)
    if not output_id or not backup_path:
        return None
    return db.add_output_version(
        database_url(),
        project["slug"],
        output_version_record(output, "previous", reason, source_job_id, backup_path, metadata),
    )


def sync_and_record_job_output_versions(project: dict, episode_number: int, job: dict) -> dict:
    context_snapshot = dict(job.get("generation_context") or {}) if isinstance(job.get("generation_context"), dict) else {}
    if job.get("stage") == "generate":
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        attempted = result.get("jobs_attempted") if isinstance(result.get("jobs_attempted"), list) else []
        target_panel_ids = {str(item.get("panel_id") or "") for item in attempted if item.get("panel_id")}
        target_page_ids = {str(item.get("page_id") or "") for item in attempted if item.get("page_id")}
        if target_panel_ids:
            context_snapshot["panel_ids"] = sorted(target_panel_ids)
        if target_page_ids:
            context_snapshot["page_ids"] = sorted(target_page_ids)
    previous_context = getattr(_REQUEST_CONTEXT, "generation_context", None)
    previous_source_job_id = getattr(_REQUEST_CONTEXT, "source_job_id", "")
    if isinstance(context_snapshot, dict) and context_snapshot:
        _REQUEST_CONTEXT.generation_context = context_snapshot
    else:
        _REQUEST_CONTEXT.generation_context = None
    _REQUEST_CONTEXT.source_job_id = str(job.get("id") or "")
    try:
        sync_result = sync_outputs_api({"episode_number": episode_number})
    finally:
        _REQUEST_CONTEXT.generation_context = previous_context
        _REQUEST_CONTEXT.source_job_id = previous_source_job_id
    recorded = []
    output_ids = {int(item.get("id") or 0) for item in sync_result.get("outputs", []) if item.get("id")}
    target_panel_ids = {str(value) for value in (job.get("panel_ids") or context_snapshot.get("panel_ids") or []) if value}
    target_page_ids = {str(value) for value in (context_snapshot.get("page_ids") or []) if value}
    for output_id in output_ids:
        output = db.get_generated_output(database_url(), output_id)
        if not output:
            continue
        metadata = output.get("metadata") or {}
        page_id = str(metadata.get("page_id") or job.get("page_id") or "")
        panel_id = str(metadata.get("panel_id") or job.get("panel_id") or "")
        if job.get("stage") == "regenerate" and panel_id and panel_id != str(job.get("panel_id") or ""):
            continue
        if job.get("stage") == "regenerate_page" and page_id and page_id != str(job.get("page_id") or ""):
            continue
        if job.get("stage") == "regenerate_page" and panel_id and target_panel_ids and panel_id not in target_panel_ids:
            continue
        if job.get("stage") == "generate" and panel_id and target_panel_ids and panel_id not in target_panel_ids:
            continue
        if job.get("stage") == "generate" and not panel_id and page_id and target_page_ids and page_id not in target_page_ids:
            continue
        if job.get("stage") == "generate" and target_panel_ids and not panel_id and not page_id:
            continue
        reason = "小批量生成后记录当前版本"
        if job.get("stage") == "regenerate":
            reason = "重生成后记录当前版本"
        elif job.get("stage") == "regenerate_page":
            reason = "按页补生成后记录当前版本"
        version = record_current_output_version(
            project,
            output,
            reason,
            str(job.get("id") or ""),
            {
                "page_id": page_id,
                "panel_id": panel_id,
                "job_stage": job.get("stage", ""),
                "result_path": job.get("result_path", ""),
                "generation_context": context_snapshot if isinstance(context_snapshot, dict) else {},
            },
        )
        if version:
            recorded.append(version)
    sync_result["versions_recorded"] = recorded
    return sync_result


def sync_outputs_api(payload: dict) -> dict:
    ensure_database()
    project = active_project()
    episode_number = int(payload.get("episode_number") or payload.get("episode") or 3)
    media = episode_media(episode_number)
    synced = []
    skipped = []
    skipped_placeholder = []
    removed_incomplete_pages = []
    for item in [*media.get("pages", []), *media.get("panels", [])]:
        if not item.get("exists") or not item.get("path"):
            skipped.append(item.get("id", ""))
            continue
        if item.get("kind") == "page":
            existing = db.get_generated_output_by_path(database_url(), project["slug"], item.get("path", ""))
            if item.get("production_status") != "ready":
                skipped_placeholder.append(item.get("id", ""))
                if existing and existing.get("review_status") != "approved":
                    removed = db.delete_generated_output(database_url(), int(existing["id"]))
                    if removed:
                        removed_incomplete_pages.append(removed)
                        db.add_review(
                            database_url(),
                            project["slug"],
                            {
                                "target_type": "generated_output",
                                "target_id": str(removed["id"]),
                                "action": "remove_incomplete_page",
                                "comment": "页面分镜未齐全，移出生成结果入库清单。",
                                "before_data": removed,
                                "after_data": {
                                    "episode_number": episode_number,
                                    "page_id": item.get("page_id", ""),
                                    "production_status": item.get("production_status", ""),
                                },
                            },
                        )
                continue
        before = db.get_generated_output_by_path(database_url(), project["slug"], item.get("path", ""))
        saved = db.upsert_generated_output(database_url(), project["slug"], media_output_record(project, episode_number, item))
        synced.append(saved)
        ensure_initial_output_version(project, saved)
        if not before:
            db.add_review(database_url(), project["slug"], {
                "target_type": "generated_output",
                "target_id": saved["id"],
                "action": "sync",
                "comment": f"同步第 {episode_number} 章生成结果",
                "before_data": {},
                "after_data": saved,
            })
    return {
        "ok": True,
        "episode_number": episode_number,
        "synced": len(synced),
        "skipped": len([item for item in skipped if item]),
        "skipped_placeholder": len([item for item in skipped_placeholder if item]),
        "removed_incomplete_pages": len(removed_incomplete_pages),
        "outputs": synced,
        "media": attach_output_db_state(project, media),
    }


OUTPUT_QUALITY_DIMENSIONS = [
    ("character_consistency", "角色一致"),
    ("story_fit", "剧情贴合"),
    ("panel_continuity", "分镜连贯"),
    ("clean_image", "画面干净"),
    ("composition_readability", "构图可读"),
]


def clean_output_quality_checks(value) -> tuple[list[dict], dict]:
    labels = {key: label for key, label in OUTPUT_QUALITY_DIMENSIONS}
    allowed_status = {"pass", "fail", "unknown"}
    raw_items = value or []
    if isinstance(raw_items, dict):
        raw_items = [
            {"key": key, "status": status}
            for key, status in raw_items.items()
        ]
    if not isinstance(raw_items, list):
        raw_items = []
    by_key = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key not in labels:
            continue
        status = str(item.get("status") or "unknown").strip()
        if status not in allowed_status:
            status = "unknown"
        note = compact_text(item.get("note", ""), 120)
        by_key[key] = {
            "key": key,
            "label": labels[key],
            "status": status,
            "note": note,
        }
    checks = []
    for key, label in OUTPUT_QUALITY_DIMENSIONS:
        checks.append(by_key.get(key) or {
            "key": key,
            "label": label,
            "status": "unknown",
            "note": "",
        })
    summary = {
        "total": len(checks),
        "passed": len([item for item in checks if item["status"] == "pass"]),
        "failed": len([item for item in checks if item["status"] == "fail"]),
        "unknown": len([item for item in checks if item["status"] == "unknown"]),
    }
    return checks, summary


def review_output_api(output_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_generated_output(database_url(), output_id)
    if not before:
        raise ValueError("生成结果不存在")
    action = str(payload.get("action") or "approve").strip()
    comment = str(payload.get("comment") or "").strip()
    if action not in {"approve", "reject", "needs_work", "pending"}:
        raise ValueError("不支持的生成结果审核动作")
    if action in {"reject", "needs_work"} and not comment:
        raise ValueError("标记待改或拒绝时必须填写具体问题")
    status = {
        "approve": "approved",
        "reject": "rejected",
        "needs_work": "needs_work",
        "pending": "pending_review",
    }.get(action, action)
    quality_checks, quality_summary = clean_output_quality_checks(payload.get("quality_checks"))
    if action == "approve" and (quality_summary["failed"] or quality_summary["unknown"]):
        raise ValueError("审核通过前必须确认全部质量检查项")
    saved = db.update_generated_output(database_url(), output_id, {
        "review_status": status,
        "metadata": {
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
            "review_action": action,
            "review_comment": comment,
            "review_quality_checks": quality_checks,
            "review_quality_summary": quality_summary,
        },
    })
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "generated_output",
        "target_id": saved["id"],
        "action": f"review:{status}",
        "comment": comment,
        "before_data": before,
        "after_data": saved,
    })
    return {"ok": True, "output": saved}


def review_outputs_batch_api(payload: dict) -> dict:
    ensure_database()
    output_ids = [
        int(item)
        for item in (payload.get("output_ids") or [])
        if str(item or "").strip().isdigit()
    ]
    if not output_ids:
        raise ValueError("没有可审核的生成结果")
    action = str(payload.get("action") or "approve").strip()
    comment = str(payload.get("comment") or "").strip()
    quality_checks = payload.get("quality_checks")
    scope_page_id = str(payload.get("scope_page_id") or "").strip().upper()
    if scope_page_id:
        mismatched = []
        for output_id in output_ids:
            row = db.get_generated_output(database_url(), output_id)
            if not row:
                mismatched.append(str(output_id))
                continue
            page_id = output_page_id(row).upper()
            if page_id != scope_page_id:
                mismatched.append(f"{output_id}:{page_id or '未知页面'}")
        if mismatched:
            raise ValueError(f"批量审核范围不一致：当前聚焦 {page_display(scope_page_id)}，但包含其它页面输出 {', '.join(mismatched)}")
    reviewed = []
    skipped = []
    for output_id in output_ids:
        try:
            result = review_output_api(output_id, {
                "action": action,
                "comment": comment,
                "quality_checks": quality_checks,
            })
            reviewed.append(result["output"])
        except Exception as exc:
            skipped.append({"id": output_id, "error": str(exc)})
    return {
        "ok": True,
        "action": action,
        "reviewed": len(reviewed),
        "skipped": skipped,
        "outputs": reviewed,
    }


def classify_asset(alias: str, path: str) -> str:
    text = f"{alias} {path}".lower()
    clothing_terms = ("clothing", "costume", "robe", "dress", "garment", "衣", "服", "袍", "冠", "甲")
    weapon_terms = ("weapon", "sword", "blade", "knife", "whip", "bow", "spear", "鞭", "剑", "刀", "弓", "枪")
    scene_terms = ("location", "locations", "loc_", "scene", "nanjishan", "longtan", "yupingshan", "courtyard", "mountain", "palace", "山", "水", "城", "庭", "楼")
    creature_terms = ("creature", "creatures", "cre_", "dragonhorse", "snake", "bailonglu", "鹿", "蛇", "龙马", "异兽")
    character_terms = ("character", "characters", "charactersheets", "char_", "turnaround", "woman", "elder", "tuobaye", "shisilang")
    if any(term in text for term in clothing_terms):
        return "clothing"
    if any(term in text for term in weapon_terms):
        return "weapons"
    if any(term in text for term in scene_terms):
        return "world_scenes"
    if any(term in text for term in creature_terms):
        return "creatures"
    if any(term in text for term in character_terms):
        return "characters"
    return "uncategorized"


def episode_assets(episode_number: int) -> dict:
    project = active_project()
    selected_episode_id = project_episode_id(project, episode_number)
    asset_index: dict[str, dict] = {}
    for plan_path in sorted(project_manifest_dir(project).glob("*_pages.json")):
        plan = read_optional_json(plan_path) or {}
        if not isinstance(plan, dict) or plan.get("error"):
            continue
        plan_episode_id = str(plan.get("episode_id") or "")
        plan_episode_number = episode_number_from_id(plan_episode_id) or episode_number_from_id(plan_path.stem)
        normalized_episode_id = project_episode_id(project, plan_episode_number) if plan_episode_number else plan_episode_id
        episode_title = str(plan.get("episode_title") or "")

        references: dict[str, list[str]] = {}
        for page in plan.get("pages", []):
            page_id = str(page.get("page_id") or "")
            for index, panel in enumerate(page.get("panels", [])):
                alias = str(panel.get("reference_alias") or "").strip()
                if not alias:
                    continue
                references.setdefault(alias, []).append(panel_id_for(page_id, panel, index))

        aliases = plan.get("asset_aliases", {}) or {}
        if not isinstance(aliases, dict):
            continue
        for alias, path in aliases.items():
            alias = str(alias)
            path = str(path)
            category = classify_asset(alias, path)
            item = asset_index.setdefault(
                alias,
                {
                    "alias": alias,
                    "label": alias.replace("_", " "),
                    "category": category,
                    "paths": [],
                    "episodes": [],
                    "used_by": [],
                    "used_by_current": [],
                },
            )
            if path and path not in item["paths"]:
                item["paths"].append(path)
            if not item.get("category") or item["category"] == "uncategorized":
                item["category"] = category
            episode_record = {
                "episode_number": plan_episode_number,
                "episode_id": normalized_episode_id,
                "episode_title": episode_title,
                "is_current": normalized_episode_id == selected_episode_id,
                "panel_count": len(references.get(alias, [])),
            }
            item["episodes"].append(episode_record)
            item["used_by"].extend(references.get(alias, []))
            if normalized_episode_id == selected_episode_id:
                item["used_by_current"].extend(references.get(alias, []))

    categories = {key: [] for key in CATEGORY_LABELS}
    for alias, raw in sorted(asset_index.items()):
        category = raw.get("category") or "uncategorized"
        if category not in categories:
            category = "uncategorized"
        primary_path = raw["paths"][0] if raw["paths"] else ""
        path_obj = Path(primary_path) if primary_path else None
        exists = bool(path_obj and path_obj.is_file())
        workflow_path = existing_workflow_for_output(path_obj) if path_obj else None
        episodes = sorted(raw["episodes"], key=lambda item: item.get("episode_number") or 0)
        categories[category].append(
            {
                "alias": alias,
                "label": raw.get("label") or alias.replace("_", " "),
                "category": category,
                "category_label": CATEGORY_LABELS[category],
                "path": str(path_obj) if path_obj else "",
                "all_paths": raw["paths"],
                "exists": exists,
                "updated": datetime.fromtimestamp(path_obj.stat().st_mtime).isoformat(timespec="seconds") if exists else "",
                "url": media_url(path_obj) if exists else "",
                "comfy_url": comfy_view_url(path_obj) if exists else "",
                "workflow_path": str(workflow_path) if workflow_path else "",
                "can_regenerate": bool(path_obj),
                "action_note": "可从旧图生成一致性参考工作流" if path_obj else "缺少目标路径，不能生成",
                "episodes": episodes,
                "episode_count": len(episodes),
                "used_by": raw["used_by"],
                "used_by_current": raw["used_by_current"],
                "current_panel_count": len(raw["used_by_current"]),
                "is_used_in_current": bool(raw["used_by_current"]),
            }
        )
    return {
        "episode_number": episode_number,
        "episode_id": selected_episode_id,
        "scope": "global_series_assets",
        "labels": CATEGORY_LABELS,
        "categories": categories,
        "summary": {key: len(value) for key, value in categories.items()},
        "total_assets": sum(len(value) for value in categories.values()),
    }


def asset_db_map(project: dict) -> dict[str, dict]:
    rows = db.list_visual_assets(database_url(), project["slug"])
    return {str(item.get("file_path") or ""): item for item in rows if item.get("file_path")}


def setting_candidate_rows(project: dict) -> list[dict]:
    items = db.list_setting_items(database_url(), project["slug"])
    rank = {
        "character": 1,
        "location": 2,
        "prop": 3,
        "faction": 4,
        "world_rule": 5,
        "style_rule": 6,
    }
    return sorted(
        [
            {
                "id": item.get("id"),
                "item_type": item.get("item_type"),
                "type_label": setting_type_label(item.get("item_type") or ""),
                "name": item.get("name") or "",
                "review_status": item.get("review_status") or "draft",
                "locked": bool(item.get("locked")),
            }
            for item in items
            if item.get("id") and item.get("name")
        ],
        key=lambda item: (
            0 if item.get("locked") else 1,
            0 if item.get("review_status") == "approved" else 1,
            rank.get(str(item.get("item_type") or ""), 99),
            str(item.get("name") or ""),
        ),
    )


def setting_type_label(value: str) -> str:
    return {
        "character": "角色",
        "location": "场景",
        "prop": "道具/武器",
        "faction": "组织/阵营",
        "world_rule": "世界观",
        "style_rule": "画风规范",
    }.get(value, value or "未分类")


def attach_asset_db_state(project: dict, assets: dict, usage_index: dict | None = None) -> dict:
    by_path = asset_db_map(project)
    settings = {int(item["id"]): item for item in setting_candidate_rows(project) if item.get("id")}
    usage_index = usage_index or build_reference_usage_index(project)
    db_total = len(by_path)
    linked_total = 0
    listed_paths = set()
    for items in (assets.get("categories") or {}).values():
        for item in items:
            row = by_path.get(str(item.get("path") or ""))
            listed_paths.add(str(item.get("path") or ""))
            if row:
                linked_total += 1
            setting_id = int(row.get("setting_item_id") or 0) if row else 0
            setting = settings.get(setting_id)
            item["db_asset_id"] = row.get("id") if row else None
            item["db_title"] = row.get("title") if row else ""
            item["setting_item_id"] = setting_id or None
            item["setting_name"] = setting.get("name") if setting else ""
            item["setting_type"] = setting.get("item_type") if setting else ""
            item["setting_type_label"] = setting.get("type_label") if setting else ""
            item["setting_review_status"] = setting.get("review_status") if setting else ""
            item["setting_locked"] = bool(setting.get("locked")) if setting else False
            item["db_review_status"] = row.get("review_status") if row else "not_synced"
            item["db_locked"] = bool(row.get("locked")) if row else False
            item["db_synced"] = bool(row)
            item["usage_summary"] = asset_usage_for_item(usage_index, row or item)
    for row in by_path.values():
        file_path = str(row.get("file_path") or "")
        if file_path in listed_paths:
            continue
        category = str(row.get("asset_type") or "uncategorized")
        if category not in assets.get("categories", {}):
            category = "uncategorized"
        path_obj = Path(file_path) if file_path else None
        exists = bool(path_obj and path_obj.is_file())
        setting_id = int(row.get("setting_item_id") or 0)
        setting = settings.get(setting_id)
        assets.setdefault("categories", {}).setdefault(category, []).append({
            "alias": safe_stem(row.get("title") or file_path),
            "label": row.get("title") or "未命名素材",
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, "未分类资产"),
            "path": file_path,
            "all_paths": [file_path] if file_path else [],
            "exists": exists,
            "updated": datetime.fromtimestamp(path_obj.stat().st_mtime).isoformat(timespec="seconds") if exists else "",
            "url": media_url(path_obj) if exists else "",
            "comfy_url": comfy_view_url(path_obj) if exists else "",
            "workflow_path": "",
            "can_regenerate": bool(file_path),
            "action_note": "可按已审核设定生成参考图" if file_path else "缺少目标路径，不能生成",
            "episodes": [],
            "episode_count": 0,
            "used_by": [],
            "used_by_current": [],
            "current_panel_count": 0,
            "is_used_in_current": False,
            "db_asset_id": row.get("id"),
            "db_title": row.get("title") or "",
            "setting_item_id": setting_id or None,
            "setting_name": setting.get("name") if setting else "",
            "setting_type": setting.get("item_type") if setting else "",
            "setting_type_label": setting.get("type_label") if setting else "",
            "setting_review_status": setting.get("review_status") if setting else "",
            "setting_locked": bool(setting.get("locked")) if setting else False,
            "db_review_status": row.get("review_status") or "pending_review",
            "db_locked": bool(row.get("locked")),
            "db_synced": True,
            "usage_summary": asset_usage_for_item(usage_index, row),
        })
    assets["database"] = {
        "total": db_total,
        "linked": linked_total,
        "pending_sync": max(0, int(assets.get("total_assets") or 0) - linked_total),
        "pending_review": len([item for item in by_path.values() if item.get("review_status") in {"draft", "pending_review"}]),
        "locked": len([item for item in by_path.values() if item.get("locked")]),
    }
    assets["summary"] = {key: len(value) for key, value in assets.get("categories", {}).items()}
    assets["total_assets"] = sum(len(value) for value in assets.get("categories", {}).values())
    assets["setting_candidates"] = list(settings.values())
    return assets


def scanned_asset_to_db_payload(item: dict) -> dict:
    episodes = item.get("episodes") or []
    chapter_numbers = sorted({int(ep.get("episode_number") or 0) for ep in episodes if int(ep.get("episode_number") or 0)})
    first_chapter = chapter_numbers[0] if chapter_numbers else None
    return {
        "setting_item_id": None,
        "chapter_number": first_chapter,
        "asset_type": item.get("category") or "uncategorized",
        "title": asset_display_title(item.get("alias") or item.get("label") or ""),
        "description": f"{item.get('category_label') or '素材'}，跨章节复用参考图。",
        "file_path": str(item.get("path") or ""),
        "thumbnail_path": str(item.get("path") or ""),
        "prompt": "",
        "source_job_id": "",
        "usage": {
            "scope": "novel",
            "chapter_numbers": chapter_numbers,
            "episodes": episodes,
            "used_by": item.get("used_by") or [],
            "used_by_current": item.get("used_by_current") or [],
            "current_panel_count": item.get("current_panel_count") or 0,
        },
        "review_status": "pending_review",
        "locked": False,
        "raw": {
            "source": "legacy_asset_scan",
            "alias": item.get("alias") or "",
            "label": item.get("label") or "",
            "all_paths": item.get("all_paths") or [],
            "exists": bool(item.get("exists")),
            "url": item.get("url") or "",
            "comfy_url": item.get("comfy_url") or "",
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def asset_display_title(alias: str) -> str:
    title = re.sub(r"_(turnaround|reference)$", "", alias or "", flags=re.IGNORECASE)
    title = title.replace("_", " ").strip()
    return title or "未命名素材"


def setting_asset_type(setting: dict) -> str:
    return {
        "character": "characters",
        "location": "world_scenes",
        "prop": "weapons",
        "faction": "world_scenes",
        "world_rule": "world_scenes",
        "style_rule": "uncategorized",
    }.get(str(setting.get("item_type") or ""), "uncategorized")


def setting_to_visual_asset_payload(project: dict, setting: dict) -> dict:
    asset_type = setting_asset_type(setting)
    title = str(setting.get("name") or "").strip() or f"设定 #{setting.get('id') or 'asset'}"
    chapter_numbers = [
        int(item) for item in (setting.get("chapter_numbers") or [])
        if str(item).strip().isdigit()
    ]
    first_chapter = int(setting.get("first_chapter_number") or 0) or (chapter_numbers[0] if chapter_numbers else None)
    setting_key = f"setting_{int(setting.get('id') or 0)}" if int(setting.get("id") or 0) else safe_stem(title)
    file_name = f"{safe_stem(project.get('slug') or 'novel')}_{setting_key}_reference.png"
    file_path = output_root() / "assets" / file_name
    visual_prompt = str(setting.get("visual_prompt") or "").strip()
    description = str(setting.get("description") or "").strip()
    prompt = visual_prompt or description or f"{title}，{setting_type_label(setting.get('item_type') or '')}，漫画视觉设定参考图。"
    return {
        "setting_item_id": int(setting.get("id") or 0) or None,
        "chapter_number": first_chapter,
        "asset_type": asset_type,
        "title": title,
        "description": description,
        "file_path": str(file_path),
        "thumbnail_path": str(file_path),
        "prompt": prompt,
        "source_job_id": "",
        "usage": {
            "scope": "novel",
            "source": "approved_setting",
            "setting_item_id": int(setting.get("id") or 0) or None,
            "chapter_numbers": chapter_numbers,
        },
        "review_status": "pending_review",
        "locked": False,
        "raw": {
            "source": "approved_setting_asset_candidate",
            "setting_item_id": int(setting.get("id") or 0) or None,
            "setting_type": setting.get("item_type") or "",
            "negative_prompt": setting.get("negative_prompt") or "",
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def sync_assets_api(payload: dict) -> dict:
    project = active_project()
    episode_number = int(payload.get("episode_number") or 3)
    assets = episode_assets(episode_number)
    saved = []
    setting_saved = []
    skipped = []
    for item in [entry for values in assets.get("categories", {}).values() for entry in values]:
        if not item.get("path"):
            skipped.append({"alias": item.get("alias"), "reason": "缺少文件路径"})
            continue
        saved.append(db.upsert_visual_asset(database_url(), project["slug"], scanned_asset_to_db_payload(item)))
    settings = db.list_setting_items(database_url(), project["slug"])
    for setting in settings:
        if not setting.get("id") or not setting.get("name"):
            continue
        if not (setting.get("review_status") == "approved" or setting.get("locked")):
            continue
        setting_saved.append(
            db.upsert_visual_asset(
                database_url(),
                project["slug"],
                setting_to_visual_asset_payload(project, setting),
            )
        )
    total_saved = len(saved) + len(setting_saved)
    db.add_review(
        database_url(),
        project["slug"],
        {
            "target_type": "visual_asset",
            "target_id": "bulk",
            "action": "sync",
            "comment": f"同步 {total_saved} 个素材到数据库，其中全局设定候选 {len(setting_saved)} 个。",
            "after_data": {
                "count": total_saved,
                "legacy_scan_count": len(saved),
                "setting_candidates_created": len(setting_saved),
                "skipped": skipped,
            },
        },
    )
    return {
        "ok": True,
        "message": f"已同步 {total_saved} 个素材：旧素材 {len(saved)} 个，全局设定候选 {len(setting_saved)} 个，跳过 {len(skipped)} 个。",
        "assets": attach_asset_db_state(project, episode_assets(episode_number)),
        "saved": saved,
        "setting_candidates": setting_saved,
        "setting_candidates_created": len(setting_saved),
        "skipped": skipped,
    }


def review_asset_api(asset_id: int, payload: dict) -> dict:
    current = db.get_visual_asset(database_url(), asset_id)
    if not current:
        raise ValueError("视觉素材不存在")
    action = str(payload.get("action") or "approve").strip()
    status = {
        "approve": "approved",
        "needs_work": "needs_work",
        "reject": "rejected",
        "pending": "pending_review",
    }.get(action, action)
    updated = db.update_visual_asset(database_url(), asset_id, {"review_status": status})
    db.add_review(
        database_url(),
        updated["project_slug"],
        {
            "target_type": "visual_asset",
            "target_id": asset_id,
            "action": f"review:{status}",
            "comment": payload.get("comment") or "",
            "before_data": {"review_status": current.get("review_status")},
            "after_data": {"review_status": updated.get("review_status")},
        },
    )
    return {"ok": True, "asset": updated}


def lock_asset_api(asset_id: int, payload: dict) -> dict:
    current = db.get_visual_asset(database_url(), asset_id)
    if not current:
        raise ValueError("视觉素材不存在")
    locked = bool(payload.get("locked", True))
    updates = {"locked": locked}
    if locked and current.get("review_status") in {"draft", "pending_review", "needs_work"}:
        updates["review_status"] = "approved"
    updated = db.update_visual_asset(database_url(), asset_id, updates)
    db.add_review(
        database_url(),
        updated["project_slug"],
        {
            "target_type": "visual_asset",
            "target_id": asset_id,
            "action": "lock" if locked else "unlock",
            "comment": payload.get("comment") or "",
            "before_data": {
                "locked": current.get("locked"),
                "review_status": current.get("review_status"),
            },
            "after_data": {
                "locked": updated.get("locked"),
                "review_status": updated.get("review_status"),
            },
        },
    )
    return {"ok": True, "asset": updated}


def bind_asset_setting_api(asset_id: int, payload: dict) -> dict:
    current = db.get_visual_asset(database_url(), asset_id)
    if not current:
        raise ValueError("视觉素材不存在")
    raw_setting_id = payload.get("setting_item_id")
    setting_id = int(raw_setting_id or 0)
    setting = None
    if setting_id:
        setting = db.get_setting_item(database_url(), setting_id)
        if not setting:
            raise ValueError("设定条目不存在")
        if setting.get("project_slug") != current.get("project_slug"):
            raise ValueError("素材和设定不属于同一本小说")
    updates = {
        "setting_item_id": setting_id or None,
        "raw": {
            "bound_setting_at": datetime.now().isoformat(timespec="seconds"),
            "bound_setting_name": setting.get("name") if setting else "",
        },
    }
    if setting:
        updates["title"] = setting.get("name") or current.get("title") or ""
    updated = db.update_visual_asset(database_url(), asset_id, updates)
    db.add_review(
        database_url(),
        updated["project_slug"],
        {
            "target_type": "visual_asset",
            "target_id": asset_id,
            "action": "bind_setting" if setting else "unbind_setting",
            "comment": payload.get("comment") or "",
            "before_data": {
                "setting_item_id": current.get("setting_item_id"),
                "title": current.get("title"),
            },
            "after_data": {
                "setting_item_id": updated.get("setting_item_id"),
                "title": updated.get("title"),
            },
        },
    )
    return {"ok": True, "asset": updated}


def episode_detail(episode_number: int) -> dict:
    try:
        project = active_project()
    except Exception:
        return {
            "novel_source": {
                "available": False,
                "novel_path": "",
                "encoding": "",
                "reason": "尚未导入小说",
                "pages": [],
            },
            "breakdown": {},
            "episode_number": episode_number,
            "episode_id": "",
            "episode_title": "",
            "plan_path": "",
            "workflow": WORKFLOW_STEPS,
            "assets": {"categories": {}, "labels": {}, "total_assets": 0, "database": {}},
            "media": {"pages": [], "panels": [], "summary": {}},
            "storyline": [],
            "pages": [],
        }
    plan = load_episode_plan(episode_number)
    media = attach_output_db_state(project, episode_media(episode_number))
    pages = episode_pages_from_plan(project, episode_number, plan, media)
    novel_source = novel_source_for_episode(episode_number, plan, pages, project)
    source_pages = {int(item.get("page_index") or 0): item for item in novel_source.get("pages", [])}
    for page in pages:
        source_page = source_pages.get(int(page.get("index") or 0), {})
        if not page.get("source_excerpt"):
            page["source_excerpt"] = source_page.get("text", "")
        page["source_line_start"] = source_page.get("line_start", "")
        page["source_line_end"] = source_page.get("line_end", "")
    breakdown = ensure_episode_breakdown(project, episode_number, plan, pages)
    return {
        "novel_source": novel_source,
        "breakdown": breakdown,
        "episode_number": episode_number,
        "episode_id": plan.get("episode_id", project_episode_id(project, episode_number)) if isinstance(plan, dict) else project_episode_id(project, episode_number),
        "episode_title": plan.get("episode_title", "") if isinstance(plan, dict) else "",
        "plan_path": str(project_episode_plan_path(episode_number, project)),
        "workflow": WORKFLOW_STEPS,
        "assets": attach_asset_db_state(project, episode_assets(episode_number)),
        "media": media,
        "storyline": [
            {
                "page_id": page["page_id"],
                "title": page["title"],
                "summary": page["summary"],
                "source_excerpt": page["source_excerpt"][:520],
            }
            for page in pages
        ],
        "pages": pages,
    }


def episode_pages_from_plan(project: dict, episode_number: int, plan: dict, media: dict | None = None) -> list[dict]:
    media = media or attach_output_db_state(project, episode_media(episode_number))
    media_by_page = {item["page_id"]: item for item in media["pages"]}
    media_by_panel = {item["panel_id"]: item for item in media["panels"]}
    pages = []
    for page_index, page in enumerate(plan.get("pages", []) if isinstance(plan, dict) else []):
        page_id = str(page.get("page_id") or f"{project_episode_id(project, episode_number)}_P{page_index + 1:03d}")
        panels = []
        for panel_index, panel in enumerate(page.get("panels", [])):
            panel_id = panel_id_for(page_id, panel, panel_index)
            panels.append(
                {
                    "panel_id": panel_id,
                    "index": panel_index + 1,
                    "title": panel.get("title", ""),
                    "reference_alias": panel.get("reference_alias", ""),
                    "caption": panel.get("caption", ""),
                    "dialogue": panel.get("dialogue", []),
                    "prompt": panel.get("prompt", panel.get("fallback_prompt", "")),
                    "panel_role": panel.get("panel_role", ""),
                    "shot_type": panel.get("shot_type", ""),
                    "visual_priority": panel.get("visual_priority", ""),
                    "camera_direction": panel.get("camera_direction", ""),
                    "close_reading_refined": bool(panel.get("close_reading_refined")),
                    "layout": panel.get("layout", {}),
                    "media": media_by_panel.get(panel_id, {}),
                    "workflow_path": str(workflow_path_for_panel(panel_id) or ""),
                }
            )
        pages.append(
            {
                "page_id": page_id,
                "index": page_index + 1,
                "title": page.get("title", ""),
                "status": page.get("status", ""),
                "summary": page.get("summary", ""),
                "source_excerpt": page.get("source_excerpt", ""),
                "panel_intent": page.get("panel_intent", []),
                "director": page.get("director", {}),
                "layout_style": page.get("layout_style", ""),
                "reading_flow": page.get("reading_flow", ""),
                "visual_priority": page.get("visual_priority", ""),
                "close_reading_required": bool(page.get("close_reading_required")),
                "close_reading_refined": bool(page.get("close_reading_refined")),
                "close_reading_updated": page.get("close_reading_updated", ""),
                "plan_path": page.get("plan", str(plan_path_for_page(page_id))),
                "media": media_by_page.get(page_id, {}),
                "panels": panels,
            }
        )
    return pages


def flatten_panels(pages: list[dict]) -> list[dict]:
    panels = []
    for page in pages:
        for panel in page.get("panels", []) or []:
            item = dict(panel)
            item["page_id"] = page.get("page_id", "")
            item["page_index"] = page.get("index", 0)
            panels.append(item)
    return panels


def ensure_episode_breakdown(
    project: dict,
    episode_number: int,
    plan: dict,
    pages: list[dict],
    *,
    source: str = "legacy_manifest",
    force: bool = False,
    job: dict | None = None,
) -> dict:
    existing = db.get_chapter_breakdown(database_url(), project["slug"], episode_number, 1)
    if existing and not force:
        return existing
    if not pages:
        return {
            "id": "",
            "project_slug": project["slug"],
            "chapter_number": episode_number,
            "version": 1,
            "pages": [],
            "panels": [],
            "status": "empty",
            "review_status": "draft",
            "raw": {"source": "episode_detail", "note": "当前章节还没有可同步的拆解结果。"},
        }
    plan_path = project_episode_plan_path(episode_number, project)
    settings = db.list_setting_items(database_url(), project["slug"])
    referenced_setting_ids = infer_referenced_setting_ids(episode_number, pages, settings)
    saved = db.upsert_chapter_breakdown(database_url(), project["slug"], episode_number, {
        "version": 1,
        "pages": pages,
        "panels": flatten_panels(pages),
        "referenced_setting_ids": referenced_setting_ids,
        "prompt_version": str((plan or {}).get("prompt_version") or "legacy.page_plan.v1"),
        "model_name": str((plan or {}).get("model") or ""),
        "status": "draft_ready",
        "review_status": "pending_review",
        "raw": {
            "source": source,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
            "episode_plan_path": str(plan_path),
            "source_job_id": (job or {}).get("id", ""),
            "source_stage": (job or {}).get("stage", ""),
            "source_result_path": (job or {}).get("result_path", ""),
            "editor_note": "",
        },
    })
    db.add_review(database_url(), project["slug"], {
        "target_type": "chapter_breakdown",
        "target_id": saved["id"],
        "action": "sync",
        "comment": "章节拆解任务完成后同步到数据库。" if job else "从章节拆解文件同步到数据库。",
        "before_data": existing or {},
        "after_data": saved,
    })
    return saved


def sync_episode_breakdown_from_plan(project: dict, episode_number: int, job: dict | None = None) -> dict:
    plan = read_optional_json(project_episode_plan_path(episode_number, project)) or {}
    if not isinstance(plan, dict) or plan.get("error"):
        return {
            "ok": False,
            "episode_number": episode_number,
            "error": "章节拆解文件不存在或格式无效",
            "plan_path": str(project_episode_plan_path(episode_number, project)),
        }
    media = attach_output_db_state(project, episode_media(episode_number))
    pages = episode_pages_from_plan(project, episode_number, plan, media)
    saved = ensure_episode_breakdown(
        project,
        episode_number,
        plan,
        pages,
        source="pipeline_job",
        force=True,
        job=job,
    )
    return {"ok": True, "episode_number": episode_number, "breakdown": saved}


def load_agent_approvals() -> dict:
    project = active_project()
    rows = {}
    for episode in db.list_episodes(database_url(), project["slug"]):
        number = int(episode.get("episode_number") or 0)
        approval = db.get_approvals(database_url(), project["slug"], number)
        if approval:
            rows[approval_key(number)] = {
                "draft": bool(approval.get("draft")),
                "assets": bool(approval.get("assets")),
                "generation": bool(approval.get("generation")),
                "qa": bool(approval.get("qa")),
                "next_episode": bool(approval.get("next_episode")),
                "updated": approval.get("updated", ""),
            }
    return rows


def save_agent_approvals(data: dict) -> None:
    project = active_project()
    for key, approvals in data.items():
        number = episode_number_from_id(key)
        if number:
            db.save_approvals(database_url(), project["slug"], number, approvals)


def approval_key(episode_number: int) -> str:
    return project_episode_id(active_project(), episode_number)


def default_approval_state() -> dict:
    return {
        "draft": False,
        "assets": False,
        "generation": False,
        "qa": False,
        "next_episode": False,
        "updated": "",
    }


def get_episode_approvals(episode_number: int) -> dict:
    approvals = load_agent_approvals()
    current = default_approval_state()
    current.update(approvals.get(approval_key(episode_number), {}))
    return current


def update_episode_approval(payload: dict) -> dict:
    episode_number = int(payload.get("episode_number") or 3)
    gate = str(payload.get("gate") or "").strip()
    if gate not in {"draft", "assets", "generation", "qa", "next_episode"}:
        raise ValueError(f"Unknown approval gate: {gate}")
    approved = bool(payload.get("approved"))
    set_episode_approval_gate(episode_number, gate, approved, validate=True)
    return agent_inspect(episode_number)


def set_episode_approval_gate(episode_number: int, gate: str, approved: bool, validate: bool = False) -> dict:
    if gate not in {"draft", "assets", "generation", "qa", "next_episode"}:
        raise ValueError(f"Unknown approval gate: {gate}")
    approvals = load_agent_approvals()
    key = approval_key(episode_number)
    current = default_approval_state()
    current.update(approvals.get(key, {}))
    if approved and validate:
        assert_approval_allowed(episode_number, gate, current)
    current[gate] = approved
    if not approved:
        cascade = {
            "draft": ["assets", "generation", "qa", "next_episode"],
            "assets": ["generation", "qa", "next_episode"],
            "generation": ["qa", "next_episode"],
            "qa": ["next_episode"],
        }
        for downstream in cascade.get(gate, []):
            current[downstream] = False
    if approved and gate != "next_episode":
        current["next_episode"] = False
    current["updated"] = datetime.now().isoformat(timespec="seconds")
    approvals[key] = current
    save_agent_approvals(approvals)
    sync_gate_side_effects(episode_number, gate, approved)
    return current


def sync_gate_side_effects(episode_number: int, gate: str, approved: bool) -> None:
    project = active_project()
    if gate != "generation":
        return
    rows = db.list_generated_outputs(database_url(), project["slug"], episode_number)
    target_status = "approved" if approved else "pending_review"
    for row in rows:
        if row.get("review_status") == target_status:
            continue
        saved = db.update_generated_output(database_url(), int(row["id"]), {
            "review_status": target_status,
            "metadata": {
                "gate_synced_at": datetime.now().isoformat(timespec="seconds"),
                "gate": gate,
                "gate_approved": approved,
            },
        })
        db.add_review(database_url(), project["slug"], {
            "target_type": "generated_output",
            "target_id": saved["id"],
            "action": f"gate:{target_status}",
            "comment": "生成审核门禁同步",
            "before_data": row,
            "after_data": saved,
        })


def next_episode_number(episode_number: int) -> int:
    episodes = list_episodes().get("episodes", [])
    numbers = sorted(item.get("episode_number", 0) for item in episodes if item.get("episode_number", 0))
    for number in numbers:
        if number > episode_number:
            return number
    return 0


def stage_exists(status: dict, name: str) -> bool:
    return any(item.get("name") == name and item.get("exists") for item in status.get("stage_files", []))


def media_progress(detail: dict) -> dict:
    media_summary = detail.get("media", {}).get("summary", {})
    pages_total = int(media_summary.get("pages_total") or 0)
    pages_ready = int(media_summary.get("pages_ready") or 0)
    real_pages_ready = int(media_summary.get("real_pages_ready") or 0)
    placeholder_pages = int(media_summary.get("placeholder_pages") or 0)
    panels_total = int(media_summary.get("panels_total") or 0)
    panels_ready = int(media_summary.get("panels_ready") or 0)
    expected_pages = max(pages_total, 1)
    expected_panels = max(panels_total, 1)
    return {
        "pages_total": pages_total,
        "pages_ready": pages_ready,
        "real_pages_ready": real_pages_ready,
        "placeholder_pages": placeholder_pages,
        "panels_total": panels_total,
        "panels_ready": panels_ready,
        "started": bool(real_pages_ready or panels_ready or placeholder_pages),
        "complete": bool((pages_total or panels_total) and real_pages_ready >= expected_pages and panels_ready >= expected_panels),
    }


def page_requires_close_reading(page: dict) -> bool:
    status = str(page.get("status") or "").lower()
    if "skeleton" in status or page.get("close_reading_required"):
        return True
    summary = str(page.get("summary") or "")
    if "初始页面骨架" in summary or "待细读" in summary:
        return True
    for panel in page.get("panels") or []:
        text = f"{panel.get('title') or ''} {panel.get('prompt') or ''}"
        if "待细读" in text:
            return True
    return False


def pending_close_reading_pages(detail: dict) -> list[dict]:
    return [page for page in detail.get("pages", []) if page_requires_close_reading(page)]


def generated_output_quality_status(project: dict, episode_number: int) -> dict:
    rows = db.list_generated_outputs(database_url(), project["slug"], episode_number)
    approved_rows = [row for row in rows if row.get("review_status") == "approved"]
    missing_quality = 0
    failed_quality = 0
    checked_quality = 0
    for row in approved_rows:
        metadata = row.get("metadata") or {}
        summary = metadata.get("review_quality_summary") or {}
        failed = int(summary.get("failed") or 0)
        unknown = int(summary.get("unknown") or 0)
        passed = int(summary.get("passed") or 0)
        total = int(summary.get("total") or 0)
        if failed:
            failed_quality += 1
        elif not total or unknown:
            missing_quality += 1
        elif passed:
            checked_quality += 1
    return {
        "total_outputs": len(rows),
        "approved_outputs": len(approved_rows),
        "quality_checked": checked_quality,
        "quality_missing": missing_quality,
        "quality_failed": failed_quality,
        "ready": bool(approved_rows) and not missing_quality and not failed_quality,
    }


def qa_report_ready(status: dict) -> bool:
    texts = status.get("texts", {})
    return bool(texts.get("image_health_qa_md") or texts.get("status_md"))


def generation_backend_ready(health: dict) -> bool:
    if "generation_ready" in health:
        return bool(health.get("ok") and health.get("generation_ready"))
    return bool(
        health.get("ok")
        and (health.get("image_backend") == "comfyui" or health.get("image_api_key_configured"))
    )


def global_asset_readiness(project: dict) -> dict:
    settings = db.list_setting_items(database_url(), project["slug"])
    visual_assets = db.list_visual_assets(database_url(), project["slug"])
    approved_settings = [
        item for item in settings
        if item.get("review_status") == "approved" or item.get("locked")
    ]
    pending_settings = [
        item for item in settings
        if item.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    approved_assets = [
        item for item in visual_assets
        if item.get("review_status") == "approved" or item.get("locked")
    ]
    pending_assets = [
        item for item in visual_assets
        if item.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    blockers = []
    if not approved_settings:
        if pending_settings:
            blockers.append("全局设定库已有候选项，请先审核并锁定关键角色、场景、道具或画风规则。")
        else:
            blockers.append("全局设定库还没有已审核设定，请先在小说设定库运行全书扫描并审核关键设定。")
    if not approved_assets:
        if pending_assets:
            blockers.append("全局素材库已有待审核素材，请先通过或锁定关键视觉素材。")
        else:
            blockers.append("全局素材库还没有已审核素材，请先生成/同步关键角色、场景或道具素材并审核。")
    return {
        "ok": not blockers,
        "settings_total": len(settings),
        "approved_settings": len(approved_settings),
        "pending_settings": len(pending_settings),
        "assets_total": len(visual_assets),
        "approved_assets": len(approved_assets),
        "pending_assets": len(pending_assets),
        "blockers": blockers,
        "message": "；".join(blockers),
    }


def approval_gate_states(health: dict, detail: dict, status: dict, approvals: dict) -> list[dict]:
    pages = detail.get("pages", [])
    pending_close_reading = pending_close_reading_pages(detail)
    assets = detail.get("assets", {})
    asset_total = int(assets.get("total_assets") or 0)
    media = media_progress(detail)
    detail_episode = int(detail.get("episode_number") or 0) or episode_number_from_id(str(detail.get("episode_id") or ""))
    global_ready = global_asset_readiness(active_project())
    chapter_coverage = chapter_asset_coverage(active_project(), detail_episode, detail.get("pages") or [])
    quality = generated_output_quality_status(active_project(), detail_episode)
    qa_ready = qa_report_ready(status)
    image_backend = health.get("image_backend") or "direct_api"
    image_api_required = image_backend == "direct_api"
    paths_ok = all(
        item.get("exists")
        for key, item in health.get("paths", {}).items()
        if key not in ({"image_env"} if image_backend == "comfyui" else {"comfy_root"})
    )
    preflight_ready = bool(generation_backend_ready(health) and paths_ok)

    if preflight_ready:
        backend_label = "ComfyUI" if image_backend == "comfyui" else "图片直连接口"
        credential_label = "本地模型环境" if image_backend == "comfyui" else "API Key"
        preflight = ("done", "就绪", f"{backend_label}、路径和{credential_label}已通过检查。")
    elif image_api_required and health.get("ok") and paths_ok:
        preflight = ("attention", "需配置", "生成图片前还需要配置图片 API Key。")
    else:
        preflight = ("attention", "需检查", "生成前需要检查当前图片后端和本地路径。")

    if not pages:
        breakdown = ("ready", "可拆解", "选择小说与章节后，先生成页面摘要、分镜提示和审稿包。")
    elif pending_close_reading and not global_ready["ok"]:
        breakdown = ("locked", "等待全局素材", global_ready["message"] or "全局设定和素材确认后才能执行章节细读。")
    elif pending_close_reading:
        breakdown = ("ready", "可细读", f"还有 {len(pending_close_reading)} 个骨架页面需要细读，完成后才能审核拆解。")
    elif approvals.get("draft"):
        breakdown = ("done", "已通过", "拆解结果已人工确认。")
    else:
        breakdown = ("review", "待审核", "检查页面摘要、分镜提示和原文片段。")

    if not global_ready["approved_settings"]:
        assets_state = ("locked", "等待设定审核", global_ready["message"] or "请先审核小说设定库。")
    elif not global_ready["approved_assets"]:
        assets_state = ("review", "待确认", global_ready["message"] or "请先确认全局视觉素材。")
    elif not chapter_coverage["ok"]:
        assets_state = ("review", "本章素材不完整", chapter_coverage["message"])
    elif approvals.get("assets"):
        assets_state = ("done", "已通过", f"全局素材已确认：设定 {global_ready['approved_settings']} 条，素材 {global_ready['approved_assets']} 个。")
    else:
        assets_state = ("review", "待确认", f"确认项目级素材库：设定 {global_ready['approved_settings']} 条，素材 {global_ready['approved_assets']} 个。")

    if not approvals.get("draft") or not approvals.get("assets"):
        generation = ("locked", "等待门禁", "章节细读审核和全局素材确认通过后才允许生成。")
    elif media["complete"] and approvals.get("generation"):
        generation = ("done", "已通过", "漫画页面与分镜结果已人工确认。")
    elif media["complete"] and quality["quality_failed"]:
        generation = ("review", "质量有问题", f"已有 {quality['quality_failed']} 个已通过输出标记质量问题，请先处理待改或重生成。")
    elif media["complete"] and quality["quality_missing"]:
        generation = ("review", "待质量检查", f"还有 {quality['quality_missing']} 个已通过输出缺少质量检查，请补齐质量维度。")
    elif media["complete"]:
        generation = ("review", "待审核", f"检查生成图：页面 {media['real_pages_ready']}/{media['pages_total']}，分镜 {media['panels_ready']}/{media['panels_total']}。")
    elif media["panels_ready"] or media["real_pages_ready"]:
        generation = ("review", "待审核", f"已有部分真实输出：页面 {media['real_pages_ready']}/{media['pages_total']}，分镜 {media['panels_ready']}/{media['panels_total']}。")
    elif media["placeholder_pages"]:
        generation = ("ready", "等待分镜", f"已有 {media['placeholder_pages']} 张占位页，真实分镜 0/{media['panels_total']}。请补生成分镜。")
    elif generation_backend_ready(health):
        generation = ("ready", "可生成", "后端已就绪，可以进入小批量生成。")
    else:
        generation = ("blocked", "生成受阻", "生成需要当前图片后端就绪并配置图片 API Key。")

    if not approvals.get("generation"):
        qa_state = ("locked", "等待生成审核", "生成结果通过后再运行 QA。")
    elif qa_ready and approvals.get("qa"):
        qa_state = ("done", "已通过", "QA 已确认，可以进入下一章循环。")
    elif qa_ready:
        qa_state = ("review", "待审核", "检查 QA 文本并确认问题已处理。")
    else:
        qa_state = ("ready", "可执行 QA", "生成结果已审核，可以执行页面组装与 QA。")

    specs = [
        ("preflight", "预检", "检查后端与配置", preflight),
        ("breakdown", "拆解审核", "人工确认分镜草稿", breakdown),
        ("assets", "素材确认", "检查全局复用资产", assets_state),
        ("generation", "生成审核", "查看页面与分镜", generation),
        ("qa", "QA / 下一章", "通过后继续循环", qa_state),
    ]
    return [
        {
            "key": key,
            "label": label,
            "gate": gate,
            "state": state_name,
            "state_label": state_label,
            "detail": detail_text,
        }
        for key, label, gate, (state_name, state_label, detail_text) in specs
    ]


def assert_approval_allowed(episode_number: int, gate: str, approvals: dict) -> None:
    detail = episode_detail(episode_number)
    status = status_snapshot(episode_number)
    media = media_progress(detail)
    if gate == "draft" and not detail.get("pages"):
        raise ValueError("请先完成 AI 拆解，再通过拆解审核。")
    if gate == "draft" and pending_close_reading_pages(detail):
        raise ValueError("当前章节仍有骨架页面，请先完成细读拆解，再通过拆解审核。")
    if gate == "assets":
        project = active_project()
        readiness = global_asset_readiness(project)
        if not readiness["ok"]:
            raise ValueError(readiness["message"] or "请先完成全局设定和素材审核，再确认素材。")
        coverage = chapter_asset_coverage(project, episode_number, detail.get("pages") or [])
        if not coverage["ok"]:
            raise ValueError(coverage["message"] or "请先补齐本章核心角色、场景和道具素材。")
    if gate == "generation":
        if not approvals.get("draft") or not approvals.get("assets"):
            raise ValueError("请先通过章节细读审核和全局素材确认，再审核生成结果。")
        if not media["complete"]:
            raise ValueError("生成结果尚未完整，不能通过生成审核。")
        quality = generated_output_quality_status(active_project(), episode_number)
        if quality["quality_failed"]:
            raise ValueError(f"还有 {quality['quality_failed']} 个已通过输出标记质量问题，不能通过生成审核。")
        if quality["quality_missing"]:
            raise ValueError(f"还有 {quality['quality_missing']} 个已通过输出缺少质量检查，不能通过生成审核。")
    if gate == "qa":
        if not approvals.get("generation"):
            raise ValueError("请先通过生成审核，再确认 QA。")
        if not qa_report_ready(status):
            raise ValueError("QA 报告尚未生成，不能通过 QA 审核。")
    if gate == "next_episode":
        if not approvals.get("qa"):
            raise ValueError("请先通过 QA 审核，再进入下一章。")
        if not next_episode_number(episode_number):
            raise ValueError("没有可进入的下一章。")


def assert_stage_allowed(stage: str, episode_number: int) -> None:
    if stage == "close_reading":
        project = active_project()
        if not project_episode_plan_path(episode_number, project).is_file():
            raise ValueError("请先执行智能拆解，生成章节页面计划后再进行细读拆解。")
        config = config_snapshot()["config"]
        if not config.get("COMIC_PIPELINE_TEXT_MODEL"):
            raise ValueError("请先在设置中配置小说处理模型。")
        readiness = global_asset_readiness(project)
        if not readiness["ok"]:
            raise ValueError(f"细读拆解前需要先完成项目级全局设定和全局素材确认：{readiness['message']}")
        return
    if stage not in {"generate", "review"}:
        return
    approvals = get_episode_approvals(episode_number)
    detail = episode_detail(episode_number)
    media = media_progress(detail)
    project = active_project()
    if stage == "generate":
        if not detail.get("pages"):
            raise ValueError("请先完成 AI 拆解，再生成漫画。")
        if not approvals.get("draft") or not approvals.get("assets"):
            raise ValueError("生成漫画前必须先通过拆解审核和素材确认。")
        coverage = chapter_asset_coverage(project, episode_number, detail.get("pages") or [])
        if not coverage["ok"]:
            raise ValueError(f"生成漫画前需要补齐本章核心素材：{coverage['message']}")
        blockers = generated_output_review_blockers(project, episode_number)
        if blockers.get("count"):
            raise ValueError(review_blocker_message(episode_number, blockers))
        health = comfy_health()
        if not health.get("ok"):
            if health.get("image_backend") == "comfyui":
                raise ValueError("生成漫画前需要 ComfyUI、节点注册和队列接口可访问。")
            raise ValueError("生成漫画前需要图片直连后端和 PostgreSQL 可用。")
        if health.get("image_backend") != "comfyui" and not health.get("image_api_key_configured"):
            raise ValueError("生成漫画前需要在配置中填写图片 API Key。")
    if stage == "review":
        if not approvals.get("generation"):
            raise ValueError("运行 QA 前必须先通过生成审核。")
        if not media["complete"]:
            raise ValueError("生成结果尚未完整，不能进入 QA。")


def agent_health_findings(health: dict) -> list[dict]:
    findings = []
    image_backend = health.get("image_backend") or "direct_api"
    for key, check in health.get("checks", {}).items():
        findings.append(
            {
                "label": {
                    "root": "ComfyUI 首页",
                    "object_info": "节点注册",
                    "extensions": "前端扩展",
                    "queue": "队列接口",
                }.get(key, key),
                "ok": bool(check.get("ok")),
                "detail": str(check.get("status") or check.get("error") or ""),
            }
        )
    for key, item in health.get("paths", {}).items():
        if image_backend == "direct_api" and key in {"comfy_root", "comfy_output_root"}:
            continue
        if image_backend == "comfyui" and key == "image_env":
            continue
        findings.append(
            {
                "label": {
                    "root": "项目目录",
                    "novel": "小说文件",
                    "comfy_root": "ComfyUI 根目录",
                    "comfy_output_root": "ComfyUI 输出目录",
                    "output_root": "输出目录",
                    "image_env": "图片环境配置",
                }.get(key, key),
                "ok": bool(item.get("exists")),
                "detail": item.get("path", ""),
            }
        )
    image_key_optional = image_backend == "comfyui"
    findings.append({
        "label": "图片 API Key",
        "ok": bool(health.get("image_api_key_configured")) or image_key_optional,
        "detail": (
            "已配置"
            if health.get("image_api_key_configured")
            else "本地模型模式可选"
            if image_key_optional
            else "未配置"
        ),
    })
    return findings


def agent_recommendation(
    episode_number: int,
    health: dict,
    detail: dict,
    status: dict,
    approvals: dict,
    ignored_review_page_id: str = "",
) -> dict:
    pages = detail.get("pages", [])
    assets = detail.get("assets", {})
    asset_total = int(assets.get("total_assets") or 0)
    media = media_progress(detail)
    project = active_project()
    quality = generated_output_quality_status(project, episode_number)
    blockers = generated_output_review_blockers(project, episode_number, ignored_review_page_id)
    qa_ready = qa_report_ready(status)
    global_ready = global_asset_readiness(project)
    chapter_coverage = chapter_asset_coverage(project, episode_number, pages)

    if not pages:
        if not global_ready["approved_settings"]:
            return {
                "state": "review",
                "title": "先完成全局设定",
                "detail": global_ready["message"],
                "stage": "",
                "action_label": "打开设定库",
                "requires_approval": False,
                "gate": "",
                "target_module": "settingsLibrary",
            }
        if not global_ready["approved_assets"]:
            return {
                "state": "review",
                "title": "先确认全局素材",
                "detail": global_ready["message"],
                "stage": "",
                "action_label": "打开素材库",
                "requires_approval": False,
                "gate": "",
                "target_module": "assets",
            }
        if not health.get("text_api_key_configured"):
            return {
                "state": "blocked",
                "title": "先配置小说处理 API Key",
                "detail": "AI 拆解需要小说处理模型配置。请先在设置中填写小说处理 API Key。",
                "stage": "",
                "action_label": "填写配置",
                "requires_approval": False,
                "gate": "",
            }
        return {
            "state": "ready",
            "title": "可以生成章节骨架",
            "detail": "全局设定和素材已准备，可以生成当前章节的页面计划和初始分镜骨架。",
            "stage": "breakdown",
            "action_label": "生成章节骨架",
            "requires_approval": False,
            "gate": "",
        }
    if not global_ready["ok"]:
        return {
            "state": "review",
            "title": "细读前先确认全局素材",
            "detail": global_ready["message"],
            "stage": "",
            "action_label": "打开素材库",
            "requires_approval": False,
            "gate": "",
            "target_module": "assets" if global_ready["approved_settings"] else "settingsLibrary",
        }
    pending_close_reading = pending_close_reading_pages(detail)
    if pending_close_reading:
        return {
            "state": "ready",
            "title": "可以执行章节细读",
            "detail": f"全局设定和素材已确认，还有 {len(pending_close_reading)} 个骨架页面需要细读后才能审核拆解。",
            "stage": "close_reading",
            "action_label": "运行细读拆解",
            "requires_approval": False,
            "gate": "",
        }
    if not approvals.get("draft"):
        return {
            "state": "review",
            "title": "等待人工审核拆解",
            "detail": "已生成章节拆解。请检查页面摘要、分镜提示和原文片段，通过后再进入素材确认。",
            "stage": "",
            "action_label": "通过拆解审核",
            "requires_approval": True,
            "gate": "draft",
        }
    if not approvals.get("assets"):
        if not chapter_coverage["ok"]:
            return {
                "state": "review",
                "title": "先补齐本章核心素材",
                "detail": chapter_coverage["message"],
                "stage": "",
                "action_label": "打开素材库",
                "requires_approval": False,
                "gate": "",
                "target_module": "assets",
            }
        return {
            "state": "review",
            "title": "等待人工确认全局素材",
            "detail": f"检测到 {asset_total} 个全局素材。确认角色、场景、异兽资产后再生成漫画；如数量为 0，请先判断是否需要补充。",
            "stage": "",
            "action_label": "通过素材确认",
            "requires_approval": True,
            "gate": "assets",
        }
    if not media["complete"]:
        if blockers.get("count"):
            return {
                "state": "review",
                "title": "先审核当前页面",
                "detail": review_blocker_message(episode_number, blockers),
                "stage": "",
                "action_label": "审核输出",
                "requires_approval": False,
                "gate": "",
            }
        if not generation_backend_ready(health):
            return {
                "state": "blocked",
                "title": "生成前需要修复后端配置",
                "detail": "拆解与素材门禁已通过，但当前图片生成后端未就绪。审核可继续查看，生成会被阻止。",
                "stage": "preflight",
                "action_label": "运行预检",
                "requires_approval": False,
                "gate": "",
            }
        return {
            "state": "ready",
            "title": "可以小批量生成漫画",
            "detail": f"当前进度：真实页面 {media['real_pages_ready']}/{media['pages_total']}，占位页 {media['placeholder_pages']}，分镜 {media['panels_ready']}/{media['panels_total']}。建议补生成缺失分镜。",
            "stage": "generate",
            "action_label": "小批量生成",
            "requires_approval": False,
            "gate": "",
        }
    if not approvals.get("generation"):
        if media["complete"] and quality["quality_failed"]:
            return {
                "state": "review",
                "title": "生成结果存在质量问题",
                "detail": f"已有 {quality['quality_failed']} 个已通过输出标记质量问题，请先标记待改或重生成后再通过生成审核。",
                "stage": "",
                "action_label": "检查生成结果",
                "requires_approval": False,
                "gate": "",
            }
        if media["complete"] and quality["quality_missing"]:
            return {
                "state": "review",
                "title": "等待补齐质量检查",
                "detail": f"还有 {quality['quality_missing']} 个已通过输出缺少质量检查。请在生成结果卡片补齐质量维度。",
                "stage": "",
                "action_label": "检查质量维度",
                "requires_approval": False,
                "gate": "",
            }
        return {
            "state": "review",
            "title": "等待人工审核生成结果",
            "detail": "页面与分镜已生成。请检查画面、文字、角色一致性，通过后再运行 QA。",
            "stage": "",
            "action_label": "通过生成审核",
            "requires_approval": True,
            "gate": "generation",
        }
    if not qa_ready:
        return {
            "state": "ready",
            "title": "可以生成 QA 报告",
            "detail": "生成结果已审核，建议执行页面组装与 QA。",
            "stage": "review",
            "action_label": "页面审核 / QA",
            "requires_approval": False,
            "gate": "",
        }
    if not approvals.get("qa"):
        return {
            "state": "review",
            "title": "等待人工确认 QA",
            "detail": "QA 文本已生成。确认问题处理完成后，可进入下一章循环。",
            "stage": "",
            "action_label": "通过 QA 审核",
            "requires_approval": True,
            "gate": "qa",
        }
    next_number = next_episode_number(episode_number)
    if not next_number:
        return {
            "state": "complete",
            "title": "全书章节已完成",
            "detail": "当前已是最后一个可识别章节，全部审核门禁已通过。",
            "stage": "",
            "action_label": "",
            "requires_approval": False,
            "gate": "",
            "next_episode": 0,
        }
    return {
        "state": "complete",
        "title": "当前章节可进入下一章",
        "detail": f"审核门禁已通过。下一章：第 {next_number} 章",
        "stage": "",
        "action_label": "进入下一章",
        "requires_approval": True,
        "gate": "next_episode",
        "next_episode": next_number,
    }


def agent_inspect(episode_number: int) -> dict:
    health = comfy_health()
    detail = episode_detail(episode_number)
    status = status_snapshot(episode_number)
    approvals = get_episode_approvals(episode_number)
    media = media_progress(detail)
    project = active_project()
    global_ready = global_asset_readiness(project)
    chapter_coverage = chapter_asset_coverage(project, episode_number, detail.get("pages") or [])
    checks = agent_health_findings(health)
    recommendation = agent_recommendation(episode_number, health, detail, status, approvals)
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_number": episode_number,
        "episode_id": detail.get("episode_id", project_episode_id(active_project(), episode_number)),
        "episode_title": detail.get("episode_title", ""),
        "health_ok": bool(health.get("ok")),
        "approvals": approvals,
        "recommendation": recommendation,
        "checks": checks,
        "gate_states": approval_gate_states(health, detail, status, approvals),
        "metrics": {
            "pages_total": media["pages_total"],
            "pages_ready": media["pages_ready"],
            "real_pages_ready": media["real_pages_ready"],
            "placeholder_pages": media["placeholder_pages"],
            "panels_total": media["panels_total"],
            "panels_ready": media["panels_ready"],
            "assets_total": int(detail.get("assets", {}).get("total_assets") or 0),
            "global_settings_total": global_ready["settings_total"],
            "global_settings_ready": global_ready["approved_settings"],
            "global_assets_total": global_ready["assets_total"],
            "global_assets_ready": global_ready["approved_assets"],
            "global_assets_ready_for_close_reading": global_ready["ok"],
            "global_assets_blocker": global_ready["message"],
            "chapter_assets_required": chapter_coverage["required_count"],
            "chapter_assets_covered": chapter_coverage["covered_count"],
            "chapter_assets_ready": chapter_coverage["ok"],
            "chapter_assets_blocker": chapter_coverage["message"],
            "close_reading_pending_pages": len(pending_close_reading_pages(detail)),
            "draft_exists": bool(detail.get("pages")),
            "qa_exists": qa_report_ready(status),
            "draft_review_exists": stage_exists(status, "draft_review_md"),
        },
        "links": {
            "preview": status.get("preview", {}).get("latest_url", ""),
            "episode_preview": status.get("preview", {}).get("episode_url", ""),
        },
    }


def agent_simulate(episode_number: int) -> dict:
    health = comfy_health()
    detail = episode_detail(episode_number)
    status = status_snapshot(episode_number)
    approvals = get_episode_approvals(episode_number)
    project = active_project()
    current_blockers = generated_output_review_blockers(project, episode_number)
    simulated_page_id = str(current_blockers.get("first_page_id") or "")
    simulated_recommendation = agent_recommendation(
        episode_number,
        health,
        detail,
        status,
        approvals,
        ignored_review_page_id=simulated_page_id,
    )
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_number": episode_number,
        "episode_title": detail.get("episode_title", ""),
        "mode": "review_current_page",
        "read_only": True,
        "assumption": (
            f"假设{episode_display(episode_number)}{page_display(simulated_page_id)}的待审输出已通过。"
            if simulated_page_id
            else "当前没有待审页面阻断，演练结果等同于真实推荐。"
        ),
        "simulated_page_id": simulated_page_id,
        "current_blockers": current_blockers,
        "recommendation": simulated_recommendation,
    }


def backup_existing_panel_image(panel_id: str) -> str:
    path = panel_image_path(panel_id)
    if not path or not path.is_file():
        return ""
    backup_dir = path.parent / "_regenerate_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}_backup_{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(backup_path))
    return str(backup_path)


def backup_existing_file(path: str | Path, label: str) -> str:
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    backup_dir = candidate.parent / "_regenerate_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{candidate.stem}_{safe_stem(label)}_backup_{int(time.time())}{candidate.suffix}"
    shutil.move(str(candidate), str(backup_path))
    return str(backup_path)


def restore_asset_backup(job: dict) -> str:
    if job.get("stage") != "asset_regenerate":
        return ""
    backup = Path(str(job.get("backup_path") or ""))
    target = Path(str(job.get("asset_path") or ""))
    if not backup.is_file() or not str(target):
        return ""
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
    return str(target)


def restore_job_backup(job: dict) -> str:
    if job.get("stage") == "asset_regenerate":
        return restore_asset_backup(job)
    if job.get("stage") != "regenerate":
        return ""
    backup = Path(str(job.get("backup_path") or ""))
    target = Path(str(job.get("panel_path") or ""))
    if not backup.is_file() or not str(job.get("panel_path") or ""):
        return ""
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
    return str(target)


def complete_asset_regeneration(project: dict, job: dict) -> dict:
    target = Path(str(job.get("asset_path") or ""))
    if not target.is_file():
        numbered_target = target.with_name(f"{target.stem}_00001_{target.suffix}")
        if numbered_target.is_file():
            target = numbered_target
    if not target.is_file():
        workflow = read_optional_json(Path(str(job.get("workflow_path") or ""))) or {}
        generated_path = expected_output_from_workflow(workflow)
        if generated_path and Path(generated_path).is_file():
            target = Path(generated_path)
    if not target.is_file():
        raise ValueError(f"素材生成任务已结束，但目标文件未生成：{target}")
    asset_id = int(job.get("asset_id") or 0)
    current = db.get_visual_asset(database_url(), asset_id) if asset_id else None
    if not current:
        current = db.get_visual_asset_by_path(database_url(), project["slug"], str(target))
    if not current:
        raise ValueError("素材生成完成，但没有找到对应的数据库素材记录")
    if current.get("project_slug") != project.get("slug"):
        raise ValueError("素材生成结果与当前小说不匹配")
    regenerated_at = datetime.now().isoformat(timespec="seconds")
    raw = current.get("raw") if isinstance(current.get("raw"), dict) else {}
    versions = list(raw.get("regeneration_versions") or [])
    version = {
        "job_id": job["id"],
        "generated_at": regenerated_at,
        "file_path": str(target),
        "backup_path": str(job.get("backup_path") or ""),
        "workflow_path": str(job.get("workflow_path") or ""),
        "result_path": str(job.get("result_path") or ""),
    }
    versions.append(version)
    updated = db.update_visual_asset(database_url(), int(current["id"]), {
        "file_path": str(target),
        "thumbnail_path": str(target),
        "source_job_id": job["id"],
        "review_status": "pending_review",
        "locked": False,
        "raw": {
            "last_regenerated_at": regenerated_at,
            "last_backup_path": str(job.get("backup_path") or ""),
            "last_workflow_path": str(job.get("workflow_path") or ""),
            "regeneration_versions": versions,
        },
    })
    db.add_review(database_url(), project["slug"], {
        "target_type": "visual_asset",
        "target_id": updated["id"],
        "action": "regenerate",
        "comment": "素材已重新生成，已解除锁定并返回待审核。",
        "before_data": {
            "source_job_id": current.get("source_job_id"),
            "review_status": current.get("review_status"),
            "locked": current.get("locked"),
        },
        "after_data": {
            "source_job_id": updated.get("source_job_id"),
            "review_status": updated.get("review_status"),
            "locked": updated.get("locked"),
            "version": version,
        },
    })
    return {"asset": updated, "version": version}


def assemble_page_for_panel(page_id: str) -> dict:
    plan_path = plan_path_for_page(page_id)
    workflow_result_path = workflow_result_path_for_page(page_id)
    if not workflow_result_path.is_file():
        workflow_result_path = Path("")
    manifest_path = assembly_path_for_page(page_id)
    if not plan_path.is_file() or not workflow_result_path.is_file():
        return {
            "attempted": False,
            "reason": "missing_page_plan_or_workflow_result",
            "plan_path": str(plan_path),
            "workflow_result_path": str(workflow_result_path),
        }
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ASSEMBLE_PAGE_SCRIPT),
        "-PlanPath",
        str(plan_path),
        "-WorkflowResultPath",
        str(workflow_result_path),
        "-ManifestPath",
        str(manifest_path),
    ]
    completed = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "attempted": True,
        "exit_code": completed.returncode,
        "command": cmd,
        "manifest_path": str(manifest_path),
        "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-40:]),
        "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-40:]),
    }


def start_asset_regenerate_job(payload: dict) -> dict:
    requested_project_slug = str(payload.get("project_slug") or "").strip()
    project = project_by_slug(requested_project_slug) if requested_project_slug else active_project()
    if requested_project_slug and project.get("slug") != requested_project_slug:
        raise ValueError("指定的小说项目不存在或已归档")
    asset_id = int(payload.get("asset_id") or 0)
    asset = db.get_visual_asset(database_url(), asset_id) if asset_id else None
    if asset_id and not asset:
        raise ValueError("视觉素材不存在")
    if asset and asset.get("project_slug") != project.get("slug"):
        raise ValueError("素材不属于当前小说")
    setting = None
    if asset and int(asset.get("setting_item_id") or 0):
        setting = db.get_setting_item(database_url(), int(asset["setting_item_id"]))
        if not setting or setting.get("project_slug") != project.get("slug"):
            raise ValueError("素材绑定的小说设定不存在")
        if setting.get("review_status") != "approved" and not setting.get("locked"):
            raise ValueError("请先审核素材绑定的小说设定，再生成视觉素材")
    alias = str(payload.get("asset_alias") or "").strip()
    target_path = str(payload.get("asset_path") or "").strip()
    category = str(payload.get("asset_category") or "uncategorized").strip() or "uncategorized"
    if asset:
        alias = str(asset.get("title") or alias).strip()
        target_path = str(asset.get("file_path") or target_path).strip()
        category = str(asset.get("asset_type") or category).strip() or "uncategorized"
    episode_number = int(payload.get("episode_number") or 3)
    if not alias:
        raise ValueError("asset_alias is required")
    if not target_path:
        raise ValueError("asset_path is required")

    target = Path(target_path)
    workflow_path = existing_workflow_for_output(target)
    backup_path = ""
    reference_path = str(target) if target.is_file() else ""
    if target.is_file():
        backup_path = backup_existing_file(target, alias)
        reference_path = backup_path
    try:
        if asset:
            approved_prompt = str(asset.get("prompt") or "")
            approved_negative_prompt = str((asset.get("raw") or {}).get("negative_prompt") or "")
            if setting:
                approved_prompt = str(
                    setting.get("visual_prompt")
                    or setting.get("description")
                    or approved_prompt
                )
                approved_negative_prompt = str(setting.get("negative_prompt") or approved_negative_prompt)
            workflow_path = create_asset_workflow(
                alias,
                category,
                target,
                reference_path,
                approved_prompt,
                approved_negative_prompt,
                project,
            )
        elif not workflow_path:
            workflow_path = create_asset_workflow(alias, category, target, reference_path, project=project)
    except Exception:
        restore_asset_backup({
            "stage": "asset_regenerate",
            "backup_path": backup_path,
            "asset_path": str(target),
        })
        raise

    job_id = f"{int(time.time() * 1000)}-{asset_id or safe_stem(alias)}-asset-regenerate"
    result_path = project_manifest_dir(project) / "anchor_runs" / f"{safe_stem(alias)}_console_regenerate_{int(time.time())}.json"
    image_backend, cmd = image_workflow_command(
        project,
        workflow_path,
        target,
        result_path,
        alias,
        int(payload.get("poll_seconds") or 5),
        int(payload.get("max_polls") or 180),
    )
    job = {
        "id": job_id,
        "stage": "asset_regenerate",
        "label": "单素材重新生成",
        "project_slug": project["slug"],
        "episode_number": episode_number,
        "asset_alias": alias,
        "asset_id": int(asset.get("id") or 0) if asset else 0,
        "asset_category": category,
        "asset_path": str(target),
        "image_backend": image_backend,
        "workflow_path": str(workflow_path),
        "backup_path": backup_path,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": cmd,
        "result_path": str(result_path),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "progress": job_progress_state(current="单素材重新生成"),
        "retry_payload": {
            "project_slug": project["slug"],
            "episode_number": episode_number,
            "asset_alias": alias,
            "asset_id": int(asset.get("id") or 0) if asset else 0,
            "asset_path": str(target),
            "asset_category": category,
            "poll_seconds": int(payload.get("poll_seconds") or 5),
            "max_polls": int(payload.get("max_polls") or 180),
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project["slug"], job)
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def start_asset_batch_job(payload: dict) -> dict:
    raw_ids = payload.get("asset_ids")
    if not isinstance(raw_ids, list):
        raise ValueError("asset_ids must be a list")
    try:
        asset_ids = list(dict.fromkeys(int(item) for item in raw_ids if int(item) > 0))
    except (TypeError, ValueError):
        raise ValueError("asset_ids 只能包含素材编号") from None
    if not asset_ids:
        raise ValueError("请至少选择 1 个可生成素材")
    if len(asset_ids) > MAX_ASSET_BATCH_SIZE:
        raise ValueError(f"单次最多选择 {MAX_ASSET_BATCH_SIZE} 个素材")

    requested_project_slug = str(payload.get("project_slug") or "").strip()
    project = project_by_slug(requested_project_slug) if requested_project_slug else active_project()
    if requested_project_slug and project.get("slug") != requested_project_slug:
        raise ValueError("指定的小说项目不存在或已归档")
    assets = []
    for asset_id in asset_ids:
        asset = db.get_visual_asset(database_url(), asset_id)
        if not asset:
            raise ValueError(f"视觉素材不存在：{asset_id}")
        if asset.get("project_slug") != project.get("slug"):
            raise ValueError(f"素材不属于当前小说：{asset_id}")
        assets.append(asset)

    episode_number = int(payload.get("episode_number") or 1)
    job_id = f"{int(time.time() * 1000)}-asset-batch"
    job = {
        "id": job_id,
        "stage": "asset_batch",
        "label": "批量生成视觉素材",
        "project_slug": project["slug"],
        "episode_number": episode_number,
        "asset_ids": asset_ids,
        "asset_labels": {str(item["id"]): item.get("title") or f"素材 {item['id']}" for item in assets},
        "estimated_image_calls": len(asset_ids),
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "result_path": "",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "progress": job_progress_state(len(asset_ids), current="准备批量生成素材"),
        "child_job_ids": [],
        "completed_asset_ids": [],
        "failed_asset_ids": [],
        "retry_payload": {
            "project_slug": project["slug"],
            "episode_number": episode_number,
            "asset_ids": asset_ids,
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project["slug"], job)
    thread = threading.Thread(target=run_asset_batch_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def run_asset_batch_job(job_id: str) -> None:
    with JOB_LOCK:
        parent = dict(JOBS[job_id])
    project = project_by_slug(parent.get("project_slug", ""))
    completed_asset_ids = []
    failed_asset_ids = []
    failures = []

    for asset_id in parent.get("asset_ids") or []:
        with JOB_LOCK:
            live_parent = JOBS[job_id]
            if live_parent.get("status") == "cancelled":
                return
            label = (live_parent.get("asset_labels") or {}).get(str(asset_id)) or f"素材 {asset_id}"
            live_parent["progress"] = job_progress_state(
                len(parent.get("asset_ids") or []),
                len(completed_asset_ids),
                len(failed_asset_ids),
                f"正在生成：{label}",
            )
            snapshot = dict(live_parent)
        db.save_job(database_url(), project["slug"], snapshot)

        child = None
        try:
            child = start_asset_regenerate_job({
                "project_slug": project["slug"],
                "episode_number": int(parent.get("episode_number") or 1),
                "asset_id": asset_id,
            })
            child_id = str(child.get("id") or "")
            with JOB_LOCK:
                live_parent = JOBS[job_id]
                live_parent.setdefault("child_job_ids", []).append(child_id)
                live_parent["active_child_job_id"] = child_id
            while True:
                with JOB_LOCK:
                    if JOBS[job_id].get("status") == "cancelled":
                        return
                    child_state = dict(JOBS.get(child_id) or child)
                if str(child_state.get("status") or "") not in {"running", "queued", "starting"}:
                    break
                time.sleep(0.5)
            if child_state.get("status") == "passed":
                completed_asset_ids.append(asset_id)
            else:
                failed_asset_ids.append(asset_id)
                diagnostics = child_state.get("diagnostics") or {}
                failures.append({
                    "asset_id": asset_id,
                    "child_job_id": child_id,
                    "message": diagnostics.get("title") or child_state.get("stderr_tail") or "素材生成失败",
                })
        except Exception as exc:
            failed_asset_ids.append(asset_id)
            failures.append({"asset_id": asset_id, "child_job_id": str((child or {}).get("id") or ""), "message": str(exc)})
        finally:
            with JOB_LOCK:
                live_parent = JOBS[job_id]
                live_parent["active_child_job_id"] = ""
                live_parent["completed_asset_ids"] = list(completed_asset_ids)
                live_parent["failed_asset_ids"] = list(failed_asset_ids)
                live_parent["progress"] = job_progress_state(
                    len(parent.get("asset_ids") or []),
                    len(completed_asset_ids),
                    len(failed_asset_ids),
                    "继续下一项" if len(completed_asset_ids) + len(failed_asset_ids) < len(parent.get("asset_ids") or []) else "批量任务已结束",
                )
                snapshot = dict(live_parent)
            db.save_job(database_url(), project["slug"], snapshot)

    with JOB_LOCK:
        live_parent = JOBS[job_id]
        if live_parent.get("status") == "cancelled":
            return
        if failed_asset_ids and completed_asset_ids:
            status = "partial"
        elif failed_asset_ids:
            status = "failed"
        else:
            status = "passed"
        live_parent.update({
            "status": status,
            "finished": datetime.now().isoformat(timespec="seconds"),
            "exit_code": 0 if not failed_asset_ids else 1,
            "result": {
                "ok": not failed_asset_ids,
                "completed_asset_ids": list(completed_asset_ids),
                "failed_asset_ids": list(failed_asset_ids),
                "failures": failures,
            },
            "retry_payload": {
                "project_slug": project["slug"],
                "episode_number": int(parent.get("episode_number") or 1),
                "asset_ids": list(failed_asset_ids or parent.get("asset_ids") or []),
            },
            "progress": job_progress_state(
                len(parent.get("asset_ids") or []),
                len(completed_asset_ids),
                len(failed_asset_ids),
                "全部生成完成" if not failed_asset_ids else "部分素材生成失败",
                partial=bool(failed_asset_ids and completed_asset_ids),
            ),
        })
        if failures:
            live_parent["diagnostics"] = {
                "domain": "asset_batch",
                "title": f"{len(failed_asset_ids)} 个素材生成失败",
                "issues": [{
                    "type": "asset_generation_failed",
                    "severity": "retryable",
                    "message": item["message"],
                    "action": "检查图片模型、额度和生成后端后重试失败项。",
                    "retry_hint": "仅重试失败素材",
                } for item in failures],
            }
        snapshot = dict(live_parent)
    db.save_job(database_url(), project["slug"], snapshot)


def start_regenerate_job(payload: dict) -> dict:
    if payload.get("asset_alias"):
        return start_asset_regenerate_job(payload)

    episode_number = int(payload.get("episode_number") or 3)
    page_id = str(payload.get("page_id") or "").strip()
    panel_id = str(payload.get("panel_id") or "").strip()
    if not panel_id:
        raise ValueError("panel_id is required")
    if not page_id:
        match = re.search(r"((?:[A-Z0-9_]+_)?EP\d+_P\d+)_PANEL\d+", panel_id, re.IGNORECASE)
        page_id = match.group(1).upper() if match else ""
    workflow_path = workflow_path_for_panel(panel_id)
    if not workflow_path:
        raise ValueError(f"workflow not found for panel: {panel_id}")

    job_id = f"{int(time.time())}-regenerate"
    result_path = project_manifest_dir() / "comic_runs" / f"{panel_id.lower()}_console_regenerate_{int(time.time())}.json"
    project = active_project()
    generation_context = build_generation_context_snapshot(project, episode_number, page_id, [panel_id])
    workflow = read_optional_json(workflow_path) or {}
    panel_path = str(panel_image_path(panel_id) or expected_output_from_workflow(workflow))
    previous_output = db.get_generated_output_by_path(database_url(), project["slug"], panel_path)
    previous_metadata = previous_output.get("metadata") if previous_output and isinstance(previous_output.get("metadata"), dict) else {}
    regenerate_reason = str(payload.get("reason") or previous_metadata.get("review_comment") or "").strip()
    if regenerate_reason:
        generation_context["review_feedback"] = regenerate_reason
    runtime_workflow_path = inject_generation_context_into_workflow(workflow_path, generation_context, job_id, panel_id)
    backup_path = backup_existing_panel_image(panel_id)
    if previous_output and backup_path:
        record_previous_output_version(
            project,
            previous_output,
            backup_path,
            regenerate_reason or "单图重生成前备份旧图",
            job_id,
            {"panel_id": panel_id, "page_id": page_id},
        )
    image_backend, cmd = image_workflow_command(
        project,
        runtime_workflow_path,
        panel_path,
        result_path,
        panel_id,
        int(payload.get("poll_seconds") or 5),
        int(payload.get("max_polls") or 180),
    )
    job = {
        "id": job_id,
        "stage": "regenerate",
        "label": "单图重新生成",
        "project_slug": project["slug"],
        "episode_number": episode_number,
        "page_id": page_id,
        "panel_id": panel_id,
        "workflow_path": str(workflow_path),
        "runtime_workflow_path": str(runtime_workflow_path),
        "backup_path": backup_path,
        "panel_path": panel_path,
        "image_backend": image_backend,
        "previous_output_id": previous_output.get("id") if previous_output else "",
        "regenerate_reason": regenerate_reason,
        "generation_context": generation_context,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": cmd,
        "result_path": str(result_path),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "progress": job_progress_state(current="单图重新生成"),
        "retry_payload": {
            "episode_number": episode_number,
            "page_id": page_id,
            "panel_id": panel_id,
            "reason": regenerate_reason,
            "poll_seconds": int(payload.get("poll_seconds") or 5),
            "max_polls": int(payload.get("max_polls") or 180),
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project["slug"], job)
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def page_panels_from_media(episode_number: int, page_id: str) -> list[dict]:
    media = episode_media(episode_number)
    return [item for item in media.get("panels", []) if item.get("page_id") == page_id]


def start_regenerate_page_job(payload: dict) -> dict:
    episode_number = int(payload.get("episode_number") or 3)
    page_id = str(payload.get("page_id") or "").strip()
    if not page_id:
        raise ValueError("page_id is required")
    project = active_project()
    blockers = generated_output_review_blockers(project, episode_number, page_id)
    if blockers.get("count"):
        raise ValueError(review_blocker_message(episode_number, blockers))
    panels = page_panels_from_media(episode_number, page_id)
    if not panels:
        raise ValueError(f"page has no panels: {page_id}")
    include_existing = bool(payload.get("include_existing"))
    targets = [item for item in panels if include_existing or not item.get("exists")]
    if not targets:
        raise ValueError("当前页没有缺失分镜")
    workflow_entries = {str(item.get("panel_id") or ""): item for item in workflow_entries_for_page(page_id)}
    missing_workflows = []
    for panel in targets:
        panel_id = str(panel.get("panel_id") or "")
        workflow_path = workflow_path_for_panel(panel_id) or Path(str(workflow_entries.get(panel_id, {}).get("workflow") or ""))
        if not workflow_path or not workflow_path.is_file():
            missing_workflows.append(panel_id)
    if missing_workflows:
        raise ValueError("缺少分镜工作流: " + ", ".join(missing_workflows))

    now = int(time.time())
    job_id = f"{now}-regenerate-page"
    result_path = project_manifest_dir() / "comic_runs" / f"{page_id.lower()}_console_regenerate_page_{now}.json"
    panel_ids = [str(item.get("panel_id") or "") for item in targets]
    generation_context = build_generation_context_snapshot(project, episode_number, page_id, panel_ids)
    job = {
        "id": job_id,
        "stage": "regenerate_page",
        "label": "按页补生成",
        "project_slug": project["slug"],
        "episode_number": episode_number,
        "page_id": page_id,
        "panel_ids": panel_ids,
        "generation_context": generation_context,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": [],
        "result_path": str(result_path),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "progress": {"total": len(targets), "completed": 0, "failed": 0},
        "retry_payload": {
            "episode_number": episode_number,
            "page_id": page_id,
            "include_existing": include_existing,
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project["slug"], job)
    thread = threading.Thread(target=run_regenerate_page_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def was_job_cancelled(job_id: str) -> bool:
    with JOB_LOCK:
        return str(JOBS.get(job_id, {}).get("status") or "") == "cancelled"


def run_job_process(job_id: str, command: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    popen_kwargs = {
        "cwd": str(ROOT),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        **popen_kwargs,
    )
    with JOB_LOCK:
        JOB_PROCESSES[job_id] = process
    try:
        stdout, stderr = process.communicate()
    finally:
        with JOB_LOCK:
            JOB_PROCESSES.pop(job_id, None)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def job_progress_state(total: int = 1, completed: int = 0, failed: int = 0, current: str = "", **extra) -> dict:
    total = max(int(total or 0), 1)
    completed = max(int(completed or 0), 0)
    failed = max(int(failed or 0), 0)
    progress = {
        "total": total,
        "completed": min(completed, total),
        "failed": min(failed, total),
    }
    if current:
        progress["current"] = current
    progress.update({key: value for key, value in extra.items() if value not in (None, "")})
    return progress


def terminate_job_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def cancel_job_api(job_id: str) -> dict:
    if not job_id:
        raise ValueError("job_id is required")
    with JOB_LOCK:
        job = JOBS.get(job_id)
        process = JOB_PROCESSES.get(job_id)
        if not job:
            raise ValueError("任务不存在或已经不在当前运行队列中")
        if str(job.get("status") or "") not in {"running", "queued", "starting"}:
            raise ValueError("当前任务状态不能取消")
        job["status"] = "cancelled"
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        job["exit_code"] = -1
        job["stderr_tail"] = ""
        job["stdout_tail"] = "任务已由用户取消。"
        job["result"] = {"ok": False, "cancelled": True, "message": "任务已取消"}
        current = job.get("progress", {}).get("current") if isinstance(job.get("progress"), dict) else ""
        job["progress"] = job_progress_state(
            job.get("progress", {}).get("total", 1) if isinstance(job.get("progress"), dict) else 1,
            job.get("progress", {}).get("completed", 0) if isinstance(job.get("progress"), dict) else 0,
            job.get("progress", {}).get("failed", 0) if isinstance(job.get("progress"), dict) else 0,
            current or "任务已取消",
            cancelled=True,
        )
        job["diagnostics"] = {
            "domain": "task",
            "title": "任务已取消",
            "issues": [{
                "type": "task_cancelled",
                "severity": "info",
                "message": "任务已由用户取消。",
                "action": "如需继续，请从原流程入口重新启动任务。",
                "retry_hint": "可重新启动",
            }],
            "waiting_reason": "task_cancelled",
        }
        active_child_job_id = str(job.get("active_child_job_id") or "")
        snapshot = dict(job)
    if process:
        terminate_job_process(process)
    if active_child_job_id:
        try:
            cancel_job_api(active_child_job_id)
        except ValueError:
            pass
    db.save_job(database_url(), snapshot.get("project_slug") or active_project_slug(), snapshot)
    return {"ok": True, "job": snapshot}


def retry_job_api(job_id: str) -> dict:
    job = next(
        (item for item in recent_jobs() if str(item.get("id") or item.get("job_id") or "") == str(job_id)),
        None,
    )
    if not job:
        raise ValueError("任务不存在")
    if str(job.get("status") or "") not in {"failed", "waiting", "partial", "interrupted", "cancelled"}:
        raise ValueError("当前任务状态不能重试")
    retry_payload = job.get("retry_payload")
    if not isinstance(retry_payload, dict) or not retry_payload:
        raise ValueError("该历史任务没有可用的重试参数，请从原流程入口重新启动")
    project_slug = str(job.get("project_slug") or "")
    if project_slug and project_slug != active_project()["slug"]:
        raise ValueError("请先切换到该任务所属小说，再执行重试")

    payload = {**retry_payload, "retried_from": str(job_id)}
    stage = str(job.get("stage") or "")
    if stage == "asset_regenerate" and int(job.get("exit_code") if job.get("exit_code") is not None else -1) == 0:
        project = project_by_slug(project_slug) if project_slug else active_project()
        try:
            post_process = complete_asset_regeneration(project, job)
        except ValueError:
            pass
        else:
            repaired = {
                **job,
                "status": "passed",
                "finished": datetime.now().isoformat(timespec="seconds"),
                "exit_code": 0,
                "result": {"ok": True, "reconciled": True, "post_process": post_process},
                "post_process": post_process,
                "diagnostics": {},
                "progress": job_progress_state(completed=1, current="已同步生成结果"),
            }
            with JOB_LOCK:
                JOBS[str(job_id)] = repaired
            db.save_job(database_url(), project["slug"], repaired)
            return repaired
    if stage == "process_novel":
        if payload.get("import_strategy") != "refresh_chapters":
            payload["import_strategy"] = "update"
        return start_process_novel_job(payload)
    if stage == "setting_scan":
        payload["confirmed"] = True
        return start_setting_scan_job(project_slug or active_project()["slug"], payload)
    if stage == "asset_batch":
        return start_asset_batch_job(payload)
    if stage in {"asset_regenerate", "regenerate"}:
        return start_regenerate_job(payload)
    if stage == "regenerate_page":
        return start_regenerate_page_job(payload)
    if stage in STAGE_MAP:
        return start_job(payload)
    raise ValueError("该任务类型暂不支持重试，请从原流程入口重新启动")


def run_regenerate_page_job(job_id: str) -> None:
    with JOB_LOCK:
        job = dict(JOBS[job_id])
    project = project_by_slug(job.get("project_slug", ""))
    config = runtime_config()
    env = os.environ.copy()
    env.update({
        "COMIC_PIPELINE_WORKSPACE": str(ROOT),
        "COMIC_PIPELINE_MANIFEST_DIR": str(project_manifest_dir()),
        "COMIC_PIPELINE_COMFY_ROOT": config.get("COMIC_PIPELINE_COMFY_ROOT", ""),
        "COMIC_PIPELINE_COMFY_URL": config.get("COMIC_PIPELINE_COMFY_URL", ""),
        "COMIC_PIPELINE_COMFY_OUTPUT_ROOT": config.get("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", ""),
        "COMIC_PIPELINE_OUTPUT_ROOT": config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
        "COMIC_PIPELINE_IMAGE_ENV_PATH": config.get("COMIC_PIPELINE_IMAGE_ENV_PATH", ""),
        "COMIC_PIPELINE_IMAGE_BACKEND": config.get("COMIC_PIPELINE_IMAGE_BACKEND", "direct_api"),
        "COMIC_PIPELINE_IMAGE_MODEL": config.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
        "COMIC_PIPELINE_PYTHON_PATH": config.get("COMIC_PIPELINE_PYTHON_PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    })
    page_id = str(job.get("page_id") or "")
    episode_number = int(job.get("episode_number") or 0)
    panel_ids = [str(item) for item in job.get("panel_ids", []) if item]
    runs = []
    failed = 0
    command_log = []
    result_path = Path(job["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)

    for index, panel_id in enumerate(panel_ids, start=1):
        workflow_path = workflow_path_for_panel(panel_id)
        runtime_workflow_path = inject_generation_context_into_workflow(workflow_path, job.get("generation_context") or {}, job_id, panel_id)
        panel_result_path = project_manifest_dir() / "comic_runs" / f"{panel_id.lower()}_page_regenerate_{int(time.time())}.json"
        workflow = read_optional_json(runtime_workflow_path) or {}
        panel_target_path = panel_image_path(panel_id) or Path(expected_output_from_workflow(workflow))
        backup_path = ""
        previous_output = db.get_generated_output_by_path(database_url(), project["slug"], str(panel_image_path(panel_id) or ""))
        if panel_image_path(panel_id):
            backup_path = backup_existing_panel_image(panel_id)
        if previous_output and backup_path:
            record_previous_output_version(
                project,
                previous_output,
                backup_path,
                "按页补生成前备份旧图",
                job_id,
                {"panel_id": panel_id, "page_id": page_id},
            )
        image_backend, cmd = image_workflow_command(
            project,
            runtime_workflow_path,
            panel_target_path,
            panel_result_path,
            panel_id,
        )
        command_log.append(cmd)
        completed = run_job_process(job_id, cmd, env)
        if was_job_cancelled(job_id):
            break
        panel_result = read_optional_json(panel_result_path) or {}
        ok = completed.returncode == 0 or bool(panel_result.get("completed"))
        if not ok:
            failed += 1
        runs.append({
            "panel_id": panel_id,
            "workflow_path": str(workflow_path),
            "runtime_workflow_path": str(runtime_workflow_path),
            "result_path": str(panel_result_path),
            "image_backend": image_backend,
            "panel_path": str(panel_target_path),
            "backup_path": backup_path,
            "previous_output_id": previous_output.get("id") if previous_output else "",
            "exit_code": completed.returncode,
            "ok": ok,
            "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-20:]),
            "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-20:]),
            "result": panel_result,
        })
        with JOB_LOCK:
            live = JOBS[job_id]
            live["progress"] = {"total": len(panel_ids), "completed": index - failed, "failed": failed, "current": panel_id}
            live["stdout_tail"] = f"{index}/{len(panel_ids)} {panel_id} {'完成' if ok else '失败'}"

    if was_job_cancelled(job_id):
        result = {
            "ok": False,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "page_id": page_id,
            "episode_number": episode_number,
            "completed": False,
            "cancelled": True,
            "message": "任务已取消",
            "status": "cancelled",
            "runs": runs,
            "error": "任务已取消",
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with JOB_LOCK:
            live = JOBS[job_id]
            live["status"] = "cancelled"
            live["finished"] = datetime.now().isoformat(timespec="seconds")
            live["exit_code"] = -1
            live["command"] = command_log
            live["result"] = result
            live["stdout_tail"] = f"任务已取消：已处理 {len(runs)}/{len(panel_ids)} 个分镜。"
            live["stderr_tail"] = ""
            live["progress"] = {"total": len(panel_ids), "completed": len(runs) - failed, "failed": failed, "cancelled": True}
            db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)
        return

    post_process = assemble_page_for_panel(page_id)
    sync_result = {}
    if post_process.get("attempted"):
        try:
            sync_result = sync_and_record_job_output_versions(project, episode_number, {**job, "stage": "regenerate_page"})
        except Exception as exc:
            sync_result = {"ok": False, "error": str(exc)}
    result = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "page_id": page_id,
        "episode_number": episode_number,
        "completed": failed == 0 and bool(post_process.get("attempted")),
        "status": "success" if failed == 0 else "partial",
        "runs": runs,
        "post_process": post_process,
        "sync_result": sync_result,
        "error": "" if failed == 0 else f"{failed} panel(s) failed",
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with JOB_LOCK:
        live = JOBS[job_id]
        live["status"] = "passed" if result["completed"] else ("partial" if runs else "failed")
        live["finished"] = datetime.now().isoformat(timespec="seconds")
        live["exit_code"] = 0 if result["completed"] else 1
        live["command"] = command_log
        live["result"] = result
        live["stdout_tail"] = f"页面补生成完成：成功 {len(panel_ids) - failed}/{len(panel_ids)}，页面合成 {'已执行' if post_process.get('attempted') else '未执行'}。"
        live["stderr_tail"] = "\n".join([run["stderr_tail"] for run in runs if run.get("stderr_tail")][-5:])
        live["post_process"] = post_process
        live["progress"] = {"total": len(panel_ids), "completed": len(panel_ids) - failed, "failed": failed}
        try:
            db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)
        except Exception as exc:
            live["database_warning"] = str(exc)


def comfy_health() -> dict:
    config = config_snapshot()["config"]
    try:
        active = active_project()
    except Exception:
        active = {}
    effective = effective_config(active) if active else config
    sources = effective_config_sources(active) if active else {}
    image_backend = normalize_backend(effective.get("COMIC_PIPELINE_IMAGE_BACKEND"))
    comfy_url = effective.get("COMIC_PIPELINE_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    checks = {}
    endpoints = {
        "root": "/",
        "object_info": "/object_info",
        "extensions": "/extensions",
        "queue": "/queue",
    }

    def check_endpoint(name: str, endpoint: str) -> tuple[str, dict]:
        try:
            with urllib.request.urlopen(f"{comfy_url}{endpoint}", timeout=1.2) as response:
                return name, {"ok": 200 <= response.status < 300, "status": response.status}
        except Exception as exc:
            return name, {"ok": False, "error": str(exc)}

    if image_backend == "comfyui":
        with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
            futures = [pool.submit(check_endpoint, name, endpoint) for name, endpoint in endpoints.items()]
            for future in as_completed(futures):
                name, result = future.result()
                checks[name] = result

    text_key_path = Path(config.get("COMIC_PIPELINE_TEXT_ENV_PATH") or TEXT_ENV_PATH)
    image_key_path = Path(config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or IMAGE_ENV_PATH)
    text = read_env(text_key_path)
    image = read_env(image_key_path)
    database = db.status(config.get("COMIC_PIPELINE_DATABASE_URL", ""))
    comfy_root_value = str(config.get("COMIC_PIPELINE_COMFY_ROOT") or "").strip()
    comfy_output_value = str(config.get("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or "").strip()
    comfy_root_exists = bool(comfy_root_value and Path(comfy_root_value).is_dir())
    comfy_output_exists = bool(comfy_output_value and Path(comfy_output_value).is_dir())
    output_root_value = str(effective.get("COMIC_PIPELINE_OUTPUT_ROOT") or "").strip()
    output_root_error = ""
    if image_backend == "direct_api" and output_root_value:
        try:
            Path(output_root_value).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            output_root_error = str(exc)
    output_root_exists = bool(output_root_value and Path(output_root_value).is_dir())
    generation_ready = (
        all(item.get("ok") for item in checks.values()) and comfy_root_exists and comfy_output_exists
        if image_backend == "comfyui"
        else bool(image.get("OPENAI_API_KEY", "").strip()) and output_root_exists
    )
    return {
        "comfy_url": comfy_url,
        "image_backend": image_backend,
        "checks": checks,
        "generation_ready": generation_ready,
        "ok": bool(database.get("schema_ready")) and generation_ready,
        "paths": {
            "root": {"path": str(ROOT), "exists": ROOT.is_dir()},
            "novel": {"path": config.get("COMIC_PIPELINE_NOVEL_PATH", ""), "exists": Path(config.get("COMIC_PIPELINE_NOVEL_PATH", "")).is_file()},
            "comfy_root": {"path": comfy_root_value, "exists": comfy_root_exists},
            "comfy_output_root": {"path": comfy_output_value, "exists": comfy_output_exists},
            "output_root": {
                "path": output_root_value,
                "exists": output_root_exists,
                "error": output_root_error,
                "source": sources.get("output_root", "global"),
                "global_path": config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
            },
            "text_env": {"path": str(text_key_path), "exists": text_key_path.is_file()},
            "image_env": {"path": str(image_key_path), "exists": image_key_path.is_file()},
        },
        "text_api_key_configured": bool(text.get("OPENAI_API_KEY", "").strip()),
        "image_api_key_configured": bool(image.get("OPENAI_API_KEY", "").strip()),
        "database": database,
    }


def url_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url or "")
    return parsed.hostname or "127.0.0.1", parsed.port or 8188


def tcp_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def tail_text(path: Path, max_chars: int = 4000) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def comfy_runtime_diagnostics() -> dict:
    config = config_snapshot()["config"]
    health = comfy_health()
    if health.get("image_backend") == "direct_api":
        image_env_path = Path(config.get("COMIC_PIPELINE_IMAGE_ENV_PATH") or IMAGE_ENV_PATH)
        image = read_env(image_env_path)
        configured = bool(image.get("OPENAI_API_KEY", "").strip())
        return {
            "ok": bool(health.get("generation_ready") and configured),
            "image_backend": "direct_api",
            "start_not_required": True,
            "start_supported": False,
            "health": health,
            "provider": {
                "base_url": image.get("OPENAI_BASE_URL", ""),
                "api_key_configured": configured,
                "env_path": str(image_env_path),
            },
            "paths": {},
            "logs": {},
            "start_command": {},
            "start_blocker": "直连 API 模式无需启动独立生成后端。",
        }
    comfy_root = Path(config.get("COMIC_PIPELINE_COMFY_ROOT") or DEFAULTS["COMIC_PIPELINE_COMFY_ROOT"])
    comfy_url = (config.get("COMIC_PIPELINE_COMFY_URL") or DEFAULTS["COMIC_PIPELINE_COMFY_URL"]).rstrip("/")
    host, port = url_host_port(comfy_url)
    main_py = comfy_root / "main.py"
    venv_python = comfy_root / "venv" / "Scripts" / "python.exe"
    python_exe = venv_python if venv_python.is_file() else Path("python")
    windows_python_from_linux = os.name != "nt" and venv_python.is_file() and venv_python.suffix.lower() == ".exe"
    out_log = LOG_DIR / "generation-backend.out.log"
    err_log = LOG_DIR / "generation-backend.err.log"
    models_root = comfy_root / "models"
    model_dirs = {
        "checkpoints": models_root / "checkpoints",
        "loras": models_root / "loras",
        "vae": models_root / "vae",
        "clip": models_root / "clip",
        "controlnet": models_root / "controlnet",
    }
    return {
        "ok": bool(health.get("generation_ready")),
        "image_backend": "comfyui",
        "comfy_url": comfy_url,
        "host": host,
        "port": port,
        "port_open": tcp_port_open(host, port),
        "health": health,
        "paths": {
            "comfy_root": {"path": str(comfy_root), "exists": comfy_root.is_dir()},
            "main_py": {"path": str(main_py), "exists": main_py.is_file()},
            "python": {"path": str(python_exe), "exists": venv_python.is_file() or shutil.which("python") is not None},
            "models": {"path": str(models_root), "exists": models_root.is_dir()},
            **{
                key: {
                    "path": str(path),
                    "exists": path.is_dir(),
                    "files": len([item for item in path.iterdir() if item.is_file()]) if path.is_dir() else 0,
                }
                for key, path in model_dirs.items()
            },
        },
        "logs": {
            "stdout": {"path": str(out_log), "tail": tail_text(out_log)},
            "stderr": {"path": str(err_log), "tail": tail_text(err_log)},
        },
        "start_command": {
            "program": str(python_exe),
            "args": [str(main_py), "--listen", host, "--port", str(port)],
            "working_directory": str(comfy_root),
        },
        "start_supported": not windows_python_from_linux,
        "start_blocker": (
            "当前控制台运行在 Docker/Linux 容器中，不能直接执行宿主机 Windows 的 ComfyUI python.exe。"
            if windows_python_from_linux
            else ""
        ),
        "host_start_hint": {
            "shell": "PowerShell",
            "command": r'cd <ComfyUI根目录>; .\venv\Scripts\python.exe .\main.py --listen 0.0.0.0 --port 8188',
            "note": "Docker 控制台会通过 http://host.docker.internal:8188 连接宿主机后端。",
        },
    }


def start_generation_backend_api(payload: dict | None = None) -> dict:
    before = comfy_runtime_diagnostics()
    if before.get("image_backend") == "direct_api":
        return {
            "ok": bool(before.get("ok")),
            "started": False,
            "message": (
                "直连 API 模式无需启动独立生成后端。"
                if before.get("ok")
                else "直连 API 模式无需启动服务，请先配置并测试图片 API。"
            ),
            "diagnostics": before,
        }
    if before.get("ok"):
        return {"ok": True, "started": False, "message": "生成后端已经可访问。", "diagnostics": before}
    if not before.get("start_supported", True):
        return {
            "ok": False,
            "started": False,
            "message": before.get("start_blocker") or "当前运行环境不支持直接启动生成后端，请在宿主机启动 ComfyUI。",
            "diagnostics": before,
        }
    paths = before.get("paths", {})
    if not paths.get("comfy_root", {}).get("exists"):
        raise ValueError(f"ComfyUI 根目录不存在：{paths.get('comfy_root', {}).get('path', '')}")
    if not paths.get("main_py", {}).get("exists"):
        raise ValueError(f"ComfyUI 启动入口不存在：{paths.get('main_py', {}).get('path', '')}")
    if not paths.get("python", {}).get("exists"):
        raise ValueError("未找到可用于启动 ComfyUI 的 Python。")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = before["start_command"]
    out_log = LOG_DIR / "generation-backend.out.log"
    err_log = LOG_DIR / "generation-backend.err.log"
    with out_log.open("ab") as stdout, err_log.open("ab") as stderr:
        subprocess.Popen(
            [cmd["program"], *cmd["args"]],
            cwd=cmd["working_directory"],
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    deadline = time.time() + int((payload or {}).get("wait_seconds") or 20)
    latest = before
    while time.time() < deadline:
        time.sleep(1)
        latest = comfy_runtime_diagnostics()
        if latest.get("ok"):
            return {"ok": True, "started": True, "message": "生成后端已启动并通过健康检查。", "diagnostics": latest}
    latest = comfy_runtime_diagnostics()
    return {
        "ok": False,
        "started": True,
        "message": "已尝试启动生成后端，但健康检查仍未通过。请查看日志和模型目录状态。",
        "diagnostics": latest,
    }


def allowed_file_roots() -> list[Path]:
    config = config_snapshot()["config"]
    roots = [
        ROOT,
        MANIFESTS_DIR,
        LOG_DIR,
        output_root(),
        comfy_output_root(),
        Path(config.get("COMIC_PIPELINE_COMFY_ROOT", DEFAULTS["COMIC_PIPELINE_COMFY_ROOT"])),
    ]
    return [root.resolve() for root in roots if str(root).strip()]


def resolve_allowed_file_path(value: str) -> Path:
    if not value:
        raise ValueError("缺少文件路径")
    target = Path(value).expanduser().resolve()
    for root in allowed_file_roots():
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue
    raise ValueError("路径不在允许打开的项目目录内")


def open_path_in_shell(target: Path, mode: str) -> None:
    if os.name == "nt":
        if mode == "select" and target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)], creationflags=subprocess.CREATE_NO_WINDOW)
            return
        subprocess.Popen(["explorer", str(target)], creationflags=subprocess.CREATE_NO_WINDOW)
        return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        raise ValueError("当前系统没有可用的文件管理器打开命令")
    subprocess.Popen([opener, str(target if target.is_dir() else target.parent)])


def file_action_api(payload: dict) -> dict:
    path = resolve_allowed_file_path(str(payload.get("path") or ""))
    mode = str(payload.get("mode") or "select").strip() or "select"
    if mode not in {"select", "folder"}:
        raise ValueError("不支持的文件操作")
    if not path.exists():
        raise ValueError(f"路径不存在：{path}")
    target = path.parent if mode == "folder" and path.is_file() else path
    open_path_in_shell(target, mode)
    return {
        "ok": True,
        "mode": mode,
        "path": str(path),
        "opened": str(target),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


TEXT_PREVIEW_EXTENSIONS = {
    ".txt",
    ".log",
    ".json",
    ".jsonl",
    ".md",
    ".csv",
    ".yaml",
    ".yml",
    ".ps1",
    ".py",
    ".err",
    ".out",
}


def file_preview_api(payload: dict) -> dict:
    path = resolve_allowed_file_path(str(payload.get("path") or ""))
    if not path.exists():
        raise ValueError(f"路径不存在：{path}")
    if not path.is_file():
        raise ValueError("只能预览文件，目录请使用打开目录")
    if path.suffix.lower() not in TEXT_PREVIEW_EXTENSIONS:
        raise ValueError("当前文件类型不支持文本预览")
    max_bytes = min(max(int(payload.get("max_bytes") or 120000), 1000), 500000)
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8-sig", errors="replace")
    line_limit = min(max(int(payload.get("max_lines") or 300), 20), 1200)
    lines = text.splitlines()
    line_truncated = len(lines) > line_limit
    if line_truncated:
        text = "\n".join(lines[:line_limit])
    return {
        "ok": True,
        "path": str(path),
        "name": path.name,
        "size": len(data),
        "shown_bytes": min(len(data), max_bytes),
        "truncated": truncated or line_truncated,
        "line_count": len(lines),
        "shown_lines": min(len(lines), line_limit),
        "content": text,
    }


def settings_summary() -> dict:
    snapshot = config_snapshot()
    try:
        active = active_project()
    except Exception:
        active = {}
    config = snapshot.get("config", {})
    effective = effective_config(active) if active else config
    sources = effective_config_sources(active) if active else {}
    text = snapshot.get("text", {})
    image = snapshot.get("image", {})
    return {
        "image_backend": normalize_backend(effective.get("COMIC_PIPELINE_IMAGE_BACKEND")),
        "models": {
            "novel_model": effective.get("COMIC_PIPELINE_TEXT_MODEL", ""),
            "novel_timeout": effective.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", ""),
            "novel_stream": effective.get("COMIC_PIPELINE_TEXT_MODEL_STREAM", ""),
            "image_model": effective.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
            "global_novel_model": config.get("COMIC_PIPELINE_TEXT_MODEL", ""),
            "global_novel_timeout": config.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", ""),
            "global_novel_stream": config.get("COMIC_PIPELINE_TEXT_MODEL_STREAM", ""),
            "global_image_model": config.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
            "sources": {
                "novel_model": sources.get("novel_model", "global"),
                "image_model": sources.get("image_model", "global"),
            },
        },
        "endpoints": {
            "comfy_url": config.get("COMIC_PIPELINE_COMFY_URL", ""),
            "text_base_url": text.get("OPENAI_BASE_URL", ""),
            "image_base_url": image.get("OPENAI_BASE_URL", ""),
            "model_base_url": image.get("OPENAI_BASE_URL", ""),
        },
        "paths": {
            "workspace": config.get("COMIC_PIPELINE_WORKSPACE", ""),
            "output_root": effective.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
            "global_output_root": config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
            "comfy_output_root": config.get("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", ""),
            "novel_path": config.get("COMIC_PIPELINE_NOVEL_PATH", ""),
            "sources": {
                "output_root": sources.get("output_root", "global"),
            },
        },
        "project": {
            "slug": active.get("slug", ""),
            "title": active.get("title", ""),
            "project_config": active.get("project_config") if isinstance(active.get("project_config"), dict) else {},
        },
        "api_keys": {
            "text": {
                "configured": bool(text.get("OPENAI_API_KEY_CONFIGURED")),
            },
            "image": {
                "configured": bool(image.get("OPENAI_API_KEY_CONFIGURED")),
            },
            "openai": {
                "configured": bool(image.get("OPENAI_API_KEY_CONFIGURED")),
            },
        },
        "database": snapshot.get("database", {}),
    }


def health_check_summary() -> dict:
    health = comfy_health()
    settings = settings_summary()
    image_backend = settings.get("image_backend") or "direct_api"
    image_api_required = image_backend == "direct_api"
    output_root_path = settings.get("paths", {}).get("output_root", "")
    checks = [
        {
            "name": "postgres",
            "label": "PostgreSQL",
            "ok": bool(health.get("database", {}).get("schema_ready")),
            "message": "连接正常" if health.get("database", {}).get("schema_ready") else (health.get("database", {}).get("error") or "数据库未就绪"),
        },
        {
            "name": "image_backend",
            "label": "图片生成后端",
            "ok": bool(health.get("generation_ready")),
            "message": (
                "直连 API 模式已就绪"
                if health.get("generation_ready") and image_backend == "direct_api"
                else "ComfyUI 可访问"
                if health.get("generation_ready")
                else "直连 API 未就绪，请配置图片 API Key"
                if image_backend == "direct_api"
                else "ComfyUI 输出目录未挂载"
                if not health.get("paths", {}).get("comfy_root", {}).get("exists")
                or not health.get("paths", {}).get("comfy_output_root", {}).get("exists")
                else "ComfyUI 不可访问"
            ),
            "detail": health.get("checks", {}),
        },
        {
            "name": "text_api_key",
            "label": "小说处理 API Key",
            "ok": bool(health.get("text_api_key_configured")),
            "message": "已配置" if health.get("text_api_key_configured") else "未配置小说处理 API Key",
        },
        {
            "name": "image_api_key",
            "label": "图片 API Key",
            "ok": bool(health.get("image_api_key_configured")) or not image_api_required,
            "message": (
                "已配置"
                if health.get("image_api_key_configured")
                else "ComfyUI 本地模型模式无需配置"
                if not image_api_required
                else "未配置图片 API Key"
            ),
        },
        {
            "name": "output_root",
            "label": "输出目录",
            "ok": bool(output_root_path and Path(output_root_path).is_dir()),
            "message": output_root_path,
            "source": settings.get("paths", {}).get("sources", {}).get("output_root", "global"),
        },
        {
            "name": "novel_model",
            "label": "小说处理模型",
            "ok": bool(settings.get("models", {}).get("novel_model")),
            "message": settings.get("models", {}).get("novel_model") or "未配置",
            "source": settings.get("models", {}).get("sources", {}).get("novel_model", "global"),
        },
        {
            "name": "image_model",
            "label": "图片生成模型",
            "ok": bool(settings.get("models", {}).get("image_model")) or not image_api_required,
            "message": settings.get("models", {}).get("image_model") or (
                "由 ComfyUI 工作流选择本地模型" if not image_api_required else "未配置"
            ),
            "source": settings.get("models", {}).get("sources", {}).get("image_model", "global"),
        },
    ]
    checks.extend(example_consistency_checks())
    return {"ok": all(item.get("ok") for item in checks), "checks": checks, "settings": settings}


def call_text_model_test(model: str, text_env_path: str, timeout: int = 30) -> dict:
    previous = {
        "COMIC_PIPELINE_TEXT_MODEL": os.environ.get("COMIC_PIPELINE_TEXT_MODEL"),
        "COMIC_PIPELINE_TEXT_ENV_PATH": os.environ.get("COMIC_PIPELINE_TEXT_ENV_PATH"),
    }
    try:
        os.environ["COMIC_PIPELINE_TEXT_MODEL"] = model
        os.environ["COMIC_PIPELINE_TEXT_ENV_PATH"] = text_env_path
        started = time.time()
        result = chat_json([
            {"role": "system", "content": "只返回 JSON，不要解释。"},
            {"role": "user", "content": "返回 JSON：{\"ok\":true,\"purpose\":\"settings_model_test\"}"},
        ], temperature=0, timeout=timeout)
        return {
            "ok": True,
            "elapsed_seconds": round(time.time() - started, 2),
            "response": result,
        }
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def call_image_model_test(model: str, base_url: str, image_env_path: str, timeout: int = 120) -> dict:
    image_env = read_env(Path(image_env_path))
    api_key = str(image_env.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("图片生成 API Key 未配置")
    url = image_api_url(str(base_url or "").strip(), "images/generations")
    payload = {
        "model": model,
        "prompt": "A simple black ink circle on a plain white background, no text.",
        "size": "1024x1024",
        "quality": "low",
        "n": 1,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ComicPipeline/2.0",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=max(30, min(int(timeout or 120), 600))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {body[:600]}") from exc
    data = json.loads(raw)
    images = data.get("data") or data.get("images") or data.get("output") or []
    if isinstance(images, dict):
        images = [images]
    first = images[0] if isinstance(images, list) and images else {}
    if not isinstance(first, dict) or not any(first.get(key) for key in ("b64_json", "base64", "url", "image_url")):
        raise RuntimeError("图片接口返回成功，但响应中没有可用图片数据")
    response_kind = next(key for key in ("b64_json", "base64", "url", "image_url") if first.get(key))
    return {
        "ok": True,
        "elapsed_seconds": round(time.time() - started, 2),
        "status": status,
        "response_kind": response_kind,
        "generates_image": True,
        "saved": False,
    }


def test_model_api(payload: dict) -> dict:
    target = str(payload.get("target") or "").strip().lower()
    if target not in {"text", "image"}:
        raise ValueError("target must be text or image")
    settings = settings_summary()
    health = comfy_health()
    config = config_snapshot()
    timeout = int(payload.get("timeout") or 30)
    if target == "text":
        model = settings.get("models", {}).get("novel_model", "")
        base_url = settings.get("endpoints", {}).get("text_base_url", "")
        if not model:
            return {"ok": False, "target": "text", "message": "小说处理模型未配置。"}
        if not base_url:
            return {"ok": False, "target": "text", "message": "小说处理接口地址未配置。"}
        if not health.get("text_api_key_configured"):
            return {"ok": False, "target": "text", "message": "小说处理 API Key 未配置。"}
        try:
            result = call_text_model_test(model, config.get("text_env_path", ""), timeout=timeout)
            return {
                "ok": True,
                "target": "text",
                "model": model,
                "base_url": base_url,
                "message": f"小说处理模型连接成功，耗时 {result.get('elapsed_seconds')} 秒。",
                "detail": result,
            }
        except Exception as exc:
            return {
                "ok": False,
                "target": "text",
                "model": model,
                "base_url": base_url,
                "message": f"小说处理模型测试失败：{exc}",
            }

    model = settings.get("models", {}).get("image_model", "")
    base_url = settings.get("endpoints", {}).get("image_base_url", "")
    image_backend = settings.get("image_backend") or health.get("image_backend") or "direct_api"
    object_info = health.get("checks", {}).get("object_info", {})
    node_registered = bool(object_info.get("ok"))
    problems = []
    if image_backend == "comfyui":
        if not health.get("generation_ready", health.get("ok")):
            problems.append("ComfyUI 不可访问")
        if not node_registered:
            problems.append("ComfyUI 节点接口不可访问")
        ok = not problems
        return {
            "ok": ok,
            "target": "image",
            "dry_run": True,
            "model": model,
            "base_url": base_url,
            "message": (
                "ComfyUI 本地模型环境检查通过，具体模型由工作流选择。"
                if ok
                else "ComfyUI 本地模型环境检查未通过：" + "、".join(problems)
            ),
            "detail": {
                "image_backend": image_backend,
                "comfy_url": health.get("comfy_url", ""),
                "node_registered": node_registered,
                "image_api_key_configured": bool(health.get("image_api_key_configured")),
                "generates_image": False,
            },
        }
    if not model:
        problems.append("图片生成模型未配置")
    if not base_url:
        problems.append("图片生成接口地址未配置")
    if not health.get("image_api_key_configured"):
        problems.append("图片生成 API Key 未配置")
    ok = not problems
    live = bool(payload.get("live"))
    if ok and live:
        try:
            result = call_image_model_test(
                model,
                base_url,
                config.get("image_env_path", ""),
                timeout=max(30, min(timeout, 600)),
            )
            return {
                "ok": True,
                "target": "image",
                "dry_run": False,
                "model": model,
                "base_url": base_url,
                "message": f"图片生成业务调用成功，耗时 {result.get('elapsed_seconds')} 秒；测试图未保存。",
                "detail": {
                    **result,
                    "image_backend": image_backend,
                },
            }
        except Exception as exc:
            return {
                "ok": False,
                "target": "image",
                "dry_run": False,
                "model": model,
                "base_url": base_url,
                "message": f"图片生成业务调用失败：{exc}",
                "detail": {
                    "image_backend": image_backend,
                    "generates_image": True,
                },
            }
    return {
        "ok": ok,
        "target": "image",
        "dry_run": True,
        "model": model,
        "base_url": base_url,
        "message": "图片生成模型配置检查通过。本测试不生成图片，不消耗图片额度。" if ok else "图片生成模型配置检查未通过：" + "、".join(problems),
        "detail": {
            "image_backend": image_backend,
            "image_api_key_configured": bool(health.get("image_api_key_configured")),
            "generates_image": False,
        },
    }


def todo_priority(value: str) -> int:
    return {
        "blocked": 10,
        "resume": 20,
        "review": 30,
        "generate": 40,
        "history": 50,
        "settings": 60,
        "next": 70,
        "info": 90,
    }.get(value, 80)


def episode_display(episode_number: int) -> str:
    return f"第 {int(episode_number)} 章" if episode_number else "未绑定章节"


def page_display(page_id: str) -> str:
    match = re.search(r"_P0*(\d+)", str(page_id or ""), re.I)
    page = int(match.group(1)) if match else 0
    return f"第 {page} 页" if page else "下一缺失页"


def next_media_generation_target(media: dict) -> dict:
    pages = media.get("pages") or []
    panels = media.get("panels") or []
    panels_by_page: dict[str, list[dict]] = {}
    for panel in panels:
        page_id = str(panel.get("page_id") or "")
        if page_id:
            panels_by_page.setdefault(page_id, []).append(panel)
    partial_pages = [
        page for page in pages
        if page.get("production_status") == "partial"
    ]
    partial_pages.sort(key=lambda item: int(item.get("index") or 0))
    if partial_pages:
        page = partial_pages[0]
        page_id = str(page.get("page_id") or page.get("id") or "")
        missing_count = len([item for item in panels_by_page.get(page_id, []) if not item.get("exists")])
        return {
            "page_id": page_id,
            "missing_count": missing_count,
            "partial": True,
        }
    missing_page = ((media.get("missing") or {}).get("pages") or [{}])[0]
    page_id = str(missing_page.get("page_id") or missing_page.get("id") or "")
    return {
        "page_id": page_id,
        "missing_count": 0,
        "partial": False,
    }


def generation_issue_detail(issue: dict | None) -> str:
    if not isinstance(issue, dict):
        return ""
    message = str(issue.get("message") or "").strip()
    if not message:
        return ""
    parts = [message]
    retry_hint = str(issue.get("retry_hint") or "").strip()
    cooldown = int(issue.get("cooldown_seconds") or 0)
    if retry_hint:
        parts.append(f"建议：{retry_hint}")
    if cooldown:
        parts.append(f"冷却约 {cooldown} 秒")
    return "；".join(parts)


def latest_generation_issue_for_page(jobs: list[dict], episode: int, page_id: str) -> str:
    if not page_id:
        return ""
    for job in jobs:
        if int(job.get("episode_number") or 0) != int(episode or 0):
            continue
        if str(job.get("page_id") or "") != page_id:
            continue
        if job.get("stage") not in {"generate", "regenerate", "regenerate_page"}:
            continue
        diagnostics = job.get("diagnostics") or job_diagnostics(job)
        issues = diagnostics.get("issues") if isinstance(diagnostics, dict) else []
        if isinstance(issues, list) and issues:
            return generation_issue_detail(issues[0])
    return ""


def stage_label(value: str) -> str:
    return {
        "preflight": "预检",
        "breakdown": "AI 拆解",
        "draft_review": "拆解审稿",
        "generate": "生成漫画",
        "review": "生成审核",
        "status": "状态刷新",
        "asset": "素材",
        "process_novel": "处理小说",
        "regenerate": "单图重生成",
        "regenerate_page": "按页补生成",
        "close_reading": "细读拆解",
    }.get(value or "", value or "任务")


def job_status_label(value: str) -> str:
    return {
        "running": "运行中",
        "waiting": "等待重试",
        "partial": "部分完成",
        "passed": "已通过",
        "failed": "失败",
        "cancelled": "已取消",
        "error": "异常",
    }.get(value or "", value or "-")


def review_status_label(value: str) -> str:
    return {
        "draft": "草稿",
        "pending_review": "待审核",
        "approved": "已通过",
        "needs_work": "待修改",
        "rejected": "已退回",
    }.get(value or "", value or "-")


def make_dashboard_todo(
    todo_id: str,
    kind: str,
    title: str,
    detail: str,
    action_label: str,
    target: dict,
    state: str = "info",
    count: int = 0,
) -> dict:
    return {
        "id": todo_id,
        "kind": kind,
        "state": state,
        "priority": todo_priority(state),
        "title": title,
        "detail": detail,
        "action_label": action_label,
        "target": target,
        "count": int(count or 0),
    }


def make_review_item(
    item_id: str,
    kind: str,
    title: str,
    detail: str,
    status: str,
    action_label: str,
    target: dict,
    updated: str = "",
    count: int = 1,
    priority: int = 50,
) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "kind_label": {
            "output": "生成结果",
            "setting": "小说设定",
            "asset": "视觉素材",
            "breakdown": "章节拆解",
            "job": "任务诊断",
        }.get(kind, kind),
        "title": title,
        "detail": detail,
        "status": status,
        "status_label": review_status_label(status) if kind != "job" else job_status_label(status),
        "action_label": action_label,
        "target": target,
        "updated": updated,
        "count": int(count or 0),
        "priority": int(priority or 50),
    }


def review_target_type_label(value: str) -> str:
    return {
        "output": "生成结果",
        "generated_output": "生成结果",
        "breakdown": "章节拆解",
        "chapter_breakdown": "章节拆解",
        "setting": "小说设定",
        "setting_scan": "设定扫描",
        "asset": "视觉素材",
        "visual_asset": "视觉素材",
        "page": "漫画页面",
        "panel": "漫画分镜",
        "job": "任务诊断",
    }.get(value or "", value or "审核记录")


def review_action_label(value: str) -> str:
    if value.startswith("review:"):
        status = value.split(":", 1)[1]
        return f"审核状态：{review_status_label(status)}"
    if value.startswith("gate:"):
        status = value.split(":", 1)[1]
        return f"门禁同步：{review_status_label(status)}"
    return {
        "approve": "审核通过",
        "approved": "审核通过",
        "needs_work": "标记修改",
        "reject": "退回",
        "rejected": "退回",
        "update": "更新",
        "create": "创建",
        "sync": "同步",
        "scan": "扫描设定",
        "close_reading": "细读拆解",
        "remove_incomplete_page": "移出不完整页面",
        "lock": "锁定",
        "unlock": "取消锁定",
        "bind_setting": "绑定设定",
        "unbind_setting": "解除绑定",
        "note": "备注",
    }.get(value or "", value or "审核")


def review_setting_value_label(value) -> str:
    if value is None or value == "":
        return "空"
    try:
        setting_id = int(value)
    except (TypeError, ValueError):
        return compact_text(str(value), 40)
    try:
        setting = db.get_setting_item(database_url(), setting_id)
    except Exception:
        setting = None
    if not setting:
        return f"设定 #{setting_id}"
    type_text = setting_type_label(str(setting.get("item_type") or ""))
    status_text = review_status_label(str(setting.get("review_status") or ""))
    locked_text = "已锁定" if setting.get("locked") else "未锁定"
    return compact_text(f"{setting.get('name') or f'设定 #{setting_id}'} / {type_text} / {status_text} / {locked_text}", 60)


def review_value_label(key: str, value) -> str:
    if value is None or value == "":
        return "空"
    text = str(value)
    if key in {"review_status", "status"}:
        return review_status_label(text)
    if key in {"item_type", "setting_type"}:
        return setting_type_label(text)
    if key in {"asset_type", "category"}:
        return CATEGORY_LABELS.get(text, text)
    if key == "locked":
        return "已锁定" if str(value).lower() in {"true", "1", "yes"} else "未锁定"
    if key == "setting_item_id":
        return review_setting_value_label(value)
    return compact_text(text, 40)


REVIEW_CHANGE_LABELS = {
    "review_status": "审核状态",
    "status": "状态",
    "name": "名称",
    "title": "标题",
    "comment": "备注",
    "item_type": "设定类型",
    "asset_type": "素材类型",
    "quality_score": "质量评分",
    "locked": "锁定状态",
    "chapter_number": "章节",
    "page_id": "页码",
    "setting_item_id": "绑定设定",
    "description": "描述",
}


def review_change_details(before_data, after_data, limit: int = 8) -> list[dict]:
    before = before_data if isinstance(before_data, dict) else {}
    after = after_data if isinstance(after_data, dict) else {}
    changes: list[dict] = []
    keys = [
        key for key in REVIEW_CHANGE_LABELS
        if before.get(key) != after.get(key) and (key in before or key in after)
    ]
    for key in keys[:limit]:
        changes.append({
            "field": key,
            "label": REVIEW_CHANGE_LABELS[key],
            "before": review_value_label(key, before.get(key)),
            "after": review_value_label(key, after.get(key)),
        })
    return changes


def review_change_summary(before_data, after_data) -> list[str]:
    after = after_data if isinstance(after_data, dict) else {}
    changes = [
        f"{item['label']}：{item['before']} → {item['after']}"
        for item in review_change_details(before_data, after_data, limit=4)
    ]
    if not changes and after:
        changes.append("记录已更新")
    return changes


def review_target_label(target_type: str, data: dict) -> str:
    if not isinstance(data, dict):
        return review_target_type_label(target_type)
    for key in ("name", "title", "label"):
        if data.get(key):
            return compact_text(str(data.get(key)), 80)
    if target_type == "generated_output":
        episode = int(data.get("chapter_number") or 0)
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        page_id = str(metadata.get("page_id") or metadata.get("media_id") or metadata.get("panel_id") or "")
        output_type = str(data.get("output_type") or "")
        suffix = "页面" if output_type == "page" else "分镜" if output_type == "panel" else "生成结果"
        return f"{episode_display(episode)}{page_display(page_id)}{suffix}" if episode or page_id else "生成结果"
    if target_type == "chapter_breakdown":
        episode = int(data.get("chapter_number") or 0)
        return f"{episode_display(episode)}章节拆解" if episode else "章节拆解"
    if target_type == "visual_asset":
        asset_type = str(data.get("asset_type") or "")
        return CATEGORY_LABELS.get(asset_type, "视觉素材")
    if target_type == "setting_scan":
        count = data.get("count")
        return f"设定扫描 {count} 条" if count is not None else "设定扫描"
    return review_target_type_label(target_type)


def review_timeline_target(target_type: str, target_id: str, data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}
    if target_type == "generated_output":
        episode = int(data.get("chapter_number") or 0)
        page_id = output_page_id(data)
        return {
            "module": "workflow",
            "tab": "media",
            "episode": episode,
            "media_filter": "page_review",
            "focus_page_id": page_id,
        }
    if target_type == "chapter_breakdown":
        episode = int(data.get("chapter_number") or 0)
        return {"module": "workflow", "tab": "breakdown", "episode": episode}
    if target_type in {"setting", "setting_item"}:
        try:
            setting_id = int(target_id)
        except ValueError:
            setting_id = int(data.get("id") or 0)
        return {"module": "settingsLibrary", "setting_id": setting_id}
    if target_type == "setting_scan":
        return {"module": "settingsLibrary"}
    if target_type in {"visual_asset", "asset"}:
        try:
            asset_id = int(target_id)
        except ValueError:
            asset_id = int(data.get("id") or 0)
        return {"module": "assets", "asset_id": asset_id}
    return {}


def make_review_timeline_item(row: dict) -> dict:
    target_type = str(row.get("target_type") or "")
    target_id = str(row.get("target_id") or "")
    after = row.get("after_data") if isinstance(row.get("after_data"), dict) else {}
    target_label = review_target_label(target_type, after)
    return {
        "id": int(row.get("id") or 0),
        "target_type": target_type,
        "target_type_label": review_target_type_label(target_type),
        "target_id": target_id,
        "target_label": target_label,
        "action": str(row.get("action") or ""),
        "action_label": review_action_label(str(row.get("action") or "")),
        "comment": compact_text(str(row.get("comment") or ""), 120),
        "created_at": str(row.get("created_at") or ""),
        "change_summary": review_change_summary(row.get("before_data"), row.get("after_data")),
        "change_details": review_change_details(row.get("before_data"), row.get("after_data")),
        "target": review_timeline_target(target_type, target_id, after),
    }


def review_timeline_query_type(value: str) -> str:
    return {
        "generated_output": "generated_output",
        "chapter_breakdown": "chapter_breakdown",
        "setting": "setting",
        "setting_scan": "setting_scan",
        "visual_asset": "visual_asset",
        "all": "",
        "": "",
    }.get(str(value or ""), "")


def review_timeline_days(value: str) -> int:
    return {
        "all": 0,
        "": 0,
        "7d": 7,
        "30d": 30,
        "90d": 90,
    }.get(str(value or ""), 0)


def review_range_label(days: int) -> str:
    return "全部时间" if not days else f"最近 {days} 天"


def review_return_reason(value: str) -> str:
    text = compact_text(str(value or "").strip(), 80)
    if not text or text == "无备注":
        return "未填写原因"
    return text


def review_stats_from_rows(rows: list[dict], days: int) -> dict:
    reason_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("action") or "")
        action_label = review_action_label(action)
        action_counts[action_label] = action_counts.get(action_label, 0) + 1
        target_label = review_target_type_label(str(row.get("target_type") or ""))
        target_counts[target_label] = target_counts.get(target_label, 0) + 1
        if any(token in action for token in ("needs_work", "reject", "failed", "cancelled", "interrupted")):
            reason = review_return_reason(row.get("comment"))
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    def top_items(source: dict[str, int], limit: int = 6) -> list[dict]:
        return [
            {"label": label, "count": count}
            for label, count in sorted(source.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    return {
        "range": "all" if not days else f"{days}d",
        "range_label": review_range_label(days),
        "total": len(rows),
        "return_total": sum(reason_counts.values()),
        "return_reasons": top_items(reason_counts),
        "actions": top_items(action_counts),
        "target_types": top_items(target_counts),
    }


def review_center_api(query: dict | None = None) -> dict:
    ensure_database()
    project = active_project()
    slug = project.get("slug", "")
    query = query or {}
    timeline_type = review_timeline_query_type((query.get("timeline_type") or [""])[0])
    timeline_days = review_timeline_days((query.get("timeline_range") or ["all"])[0])
    try:
        timeline_limit = int((query.get("timeline_limit") or ["40"])[0])
    except (TypeError, ValueError):
        timeline_limit = 40
    timeline_limit = min(max(timeline_limit, 10), 100)
    jobs = recent_jobs()
    items: list[dict] = []
    summary = {
        "outputs": 0,
        "settings": 0,
        "assets": 0,
        "breakdowns": 0,
        "jobs": 0,
    }

    output_rows = [
        row for row in db.list_generated_outputs(database_url(), slug)
        if row.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    output_groups: dict[tuple[int, str], dict] = {}
    for row in output_rows:
        episode = int(row.get("chapter_number") or 0)
        page_id = output_page_id(row)
        key = (episode, page_id)
        group = output_groups.setdefault(key, {
            "episode": episode,
            "page_id": page_id,
            "count": 0,
            "pages": 0,
            "panels": 0,
            "statuses": {},
            "updated": "",
            "output_ids": [],
        })
        group["count"] += 1
        group["output_ids"].append(int(row.get("id") or 0))
        if row.get("output_type") == "page":
            group["pages"] += 1
        else:
            group["panels"] += 1
        status = str(row.get("review_status") or "pending_review")
        group["statuses"][status] = group["statuses"].get(status, 0) + 1
        group["updated"] = max(group["updated"], str(row.get("created_at") or ""))
    for group in output_groups.values():
        episode = int(group.get("episode") or 0)
        page_id = str(group.get("page_id") or "")
        count = int(group.get("count") or 0)
        status = "needs_work" if group["statuses"].get("needs_work") else "pending_review"
        review_item = make_review_item(
            f"output-{episode}-{page_id}",
            "output",
            f"{episode_display(episode)}{page_display(page_id)}有 {count} 个生成结果待处理",
            f"页面 {group.get('pages', 0)} · 分镜 {group.get('panels', 0)}。必须审核后才能继续下一页。",
            status,
            "审核本页",
            {
                "module": "workflow",
                "tab": "media",
                "episode": episode,
                "media_filter": "page_review",
                "focus_page_id": page_id,
                "focus_review_status": "pending_review",
            },
            group.get("updated", ""),
            count,
            10,
        )
        review_item["batch"] = {
            "output_ids": [item for item in group.get("output_ids", []) if item],
            "scope_page_id": page_id,
        }
        items.append(review_item)
    summary["outputs"] = len(output_rows)

    breakdowns = [
        row for row in db.list_chapter_breakdowns(database_url(), slug)
        if row.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    for row in breakdowns[:20]:
        episode = int(row.get("chapter_number") or 0)
        pages = len(row.get("pages") or [])
        panels = len(row.get("panels") or [])
        items.append(make_review_item(
            f"breakdown-{row.get('id')}",
            "breakdown",
            f"{episode_display(episode)}拆解待审核",
            f"页面 {pages} · 分镜 {panels} · 版本 {row.get('version') or 1}",
            str(row.get("review_status") or "pending_review"),
            "查看拆解",
            {"module": "workflow", "tab": "source", "episode": episode},
            str(row.get("updated_at") or ""),
            1,
            20,
        ))
    summary["breakdowns"] = len(breakdowns)

    settings = [
        row for row in db.list_setting_items(database_url(), slug)
        if row.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    for row in settings[:30]:
        items.append(make_review_item(
            f"setting-{row.get('id')}",
            "setting",
            f"设定待审核：{row.get('name')}",
            f"{setting_type_label(row.get('item_type', ''))} · {review_status_label(row.get('review_status', ''))}",
            str(row.get("review_status") or "pending_review"),
            "审核设定",
            {"module": "settingsLibrary", "setting_id": int(row.get("id") or 0)},
            str(row.get("updated_at") or ""),
            1,
            40,
        ))
    summary["settings"] = len(settings)

    assets = [
        row for row in db.list_visual_assets(database_url(), slug)
        if row.get("review_status") in {"draft", "pending_review", "needs_work"}
    ]
    settings_by_id = {
        int(row.get("id") or 0): row
        for row in db.list_setting_items(database_url(), slug)
    }
    for row in assets[:30]:
        setting = settings_by_id.get(int(row.get("setting_item_id") or 0), {})
        asset_type = str(row.get("asset_type") or "")
        asset_label = CATEGORY_LABELS.get(asset_type, asset_type or "素材")
        title = setting.get("name") or row.get("title") or ""
        if not setting.get("name"):
            title = f"待绑定{asset_label} #{row.get('id')}"
        items.append(make_review_item(
            f"asset-{row.get('id')}",
            "asset",
            f"素材待审核：{title}",
            f"{asset_label} · {review_status_label(row.get('review_status', ''))}",
            str(row.get("review_status") or "pending_review"),
            "查看素材",
            {"module": "assets", "asset_id": int(row.get("id") or 0)},
            str(row.get("updated_at") or ""),
            1,
            50,
        ))
    summary["assets"] = len(assets)

    problem_jobs = [job for job in jobs if job.get("status") in {"failed", "error", "waiting"}]
    for job in problem_jobs[:12]:
        episode = int(job.get("episode_number") or 0)
        diagnostics = job.get("diagnostics") or job_diagnostics(job)
        issue = ""
        if isinstance(diagnostics, dict):
            issues = diagnostics.get("issues") or []
            if isinstance(issues, list) and issues:
                issue = generation_issue_detail(issues[0])
        items.append(make_review_item(
            f"job-{job.get('id') or job.get('job_id')}",
            "job",
            f"{stage_label(job.get('stage'))} · {job_status_label(job.get('status'))}",
            issue or f"{episode_display(episode) if episode else '全局任务'} · 查看任务日志和诊断。",
            str(job.get("status") or ""),
            "查看任务",
            {"module": "taskCenter", "episode": episode},
            str(job.get("finished") or job.get("started") or ""),
            1,
            70 if job.get("status") == "waiting" else 60,
        ))
    summary["jobs"] = len(problem_jobs)

    items = sorted(items, key=lambda item: (item.get("priority", 80), -int(item.get("count") or 0), item.get("updated", "")))
    summary["total"] = len(items)
    timeline_rows = db.list_reviews(database_url(), slug, target_type=timeline_type, limit=timeline_limit, days=timeline_days)
    timeline = [make_review_timeline_item(row) for row in timeline_rows]
    return {
        "ok": True,
        "project": {"slug": slug, "title": project.get("title", slug)},
        "summary": summary,
        "items": items,
        "timeline": timeline,
        "review_stats": review_stats_from_rows(timeline_rows, timeline_days),
        "timeline_query": {
            "type": timeline_type or "all",
            "limit": timeline_limit,
            "range": "all" if not timeline_days else f"{timeline_days}d",
        },
    }


def waiting_job_still_actionable(job: dict) -> bool:
    episode = int(job.get("episode_number") or 0)
    if not episode:
        return True
    diagnostics = job.get("diagnostics") or job_diagnostics(job)
    missing = []
    if isinstance(diagnostics, dict):
        missing = [str(item) for item in (diagnostics.get("missing_panels") or []) if item]
    if not missing:
        return True
    try:
        detail = episode_detail(episode)
    except Exception:
        return True
    current_missing = {
        str(item.get("panel_id") or item.get("id") or "")
        for item in (((detail.get("media") or {}).get("missing") or {}).get("panels") or [])
    }
    return any(panel_id in current_missing for panel_id in missing)


def dashboard_todos(project: dict, health: dict, jobs: list[dict], limit: int = 8) -> list[dict]:
    slug = project.get("slug", "")
    title = project.get("title", slug)
    todos: list[dict] = []
    output_blockers_by_episode: dict[int, dict] = {}

    if not generation_backend_ready(health):
        missing = []
        if not health.get("ok"):
            missing.append("生成后端不可访问")
        if health.get("image_backend") != "comfyui" and not health.get("image_api_key_configured"):
            missing.append("图片 API Key 未配置")
        todos.append(make_dashboard_todo(
            "system-preflight",
            "system",
            "生成环境需要处理",
            "、".join(missing) or "生成环境未就绪",
            "打开设置",
            {"module": "settings"},
            "blocked",
            len(missing),
        ))

    failed_jobs = [job for job in jobs if job.get("status") in {"failed", "error"}]
    waiting_jobs = [job for job in jobs if job.get("status") == "waiting" and waiting_job_still_actionable(job)]
    if failed_jobs:
        first = failed_jobs[0]
        episode = int(first.get("episode_number") or 0)
        todos.append(make_dashboard_todo(
            "failed-jobs",
            "job",
            f"有 {len(failed_jobs)} 个历史失败任务",
            f"最近失败：{stage_label(first.get('stage'))} · {title} · {episode_display(episode) if episode else '全局任务'}。",
            "查看任务",
            {"module": "workflow", "tab": "jobs", "episode": episode},
            "history",
            len(failed_jobs),
        ))
    if waiting_jobs:
        first = waiting_jobs[0]
        episode = int(first.get("episode_number") or 0)
        diagnostics = first.get("diagnostics") or job_diagnostics(first)
        issue_message = ""
        if isinstance(diagnostics, dict):
            issues = diagnostics.get("issues") or []
            if isinstance(issues, list) and issues:
                issue_message = generation_issue_detail(issues[0])
        waiting_detail = issue_message or f"最近等待：{stage_label(first.get('stage'))} · {title} · {episode_display(episode) if episode else '全局任务'}。"
        todos.append(make_dashboard_todo(
            "waiting-jobs",
            "job",
            f"有 {len(waiting_jobs)} 个等待任务",
            waiting_detail,
            "继续处理",
            {"module": "workflow", "tab": "jobs", "episode": episode},
            "generate",
            len(waiting_jobs),
        ))

    pending_output_rows = db.dashboard_pending_outputs(database_url(), slug, limit=6)
    pending_output_episodes = []
    for row in pending_output_rows:
        episode = int(row.get("chapter_number") or 0)
        if episode and episode not in pending_output_episodes:
            pending_output_episodes.append(episode)
    for episode in pending_output_episodes:
        if episode not in output_blockers_by_episode:
            output_blockers_by_episode[episode] = generated_output_review_blockers(project, episode)
        blockers = output_blockers_by_episode.get(episode, {})
        for page in blockers.get("pages", [])[:3]:
            page_id = str(page.get("page_id") or "")
            count = int(page.get("count") or 0)
            if not page_id or not count:
                continue
            todos.append(make_dashboard_todo(
                f"output-{episode}-{page_id}",
                "output",
                f"{episode_display(episode)}{page_display(page_id)}有 {count} 个生成结果待处理",
                "待审核 · 本页页面和分镜一起审核。",
                "审核本页",
                {
                    "module": "workflow",
                    "tab": "media",
                    "episode": episode,
                    "media_filter": "page_review",
                    "focus_page_id": page_id,
                    "focus_review_status": "pending_review",
                },
                "review",
                count,
            ))

    active_episode = db.dashboard_active_approval(database_url(), slug)
    if active_episode:
        episode = int(active_episode.get("episode_number") or 0)
        try:
            detail = episode_detail(episode)
            media = detail.get("media", {})
            summary = media.get("summary", {})
            quality = generated_output_quality_status(project, episode)
            if quality["quality_failed"]:
                todos.append(make_dashboard_todo(
                    f"quality-failed-{episode}",
                    "output_quality",
                    f"{episode_display(episode)}有 {quality['quality_failed']} 个质量问题",
                    "已通过输出中仍有质量维度标记为问题，需要待改或重生成。",
                    "检查质量",
                    {"module": "workflow", "tab": "media", "episode": episode},
                    "review",
                    quality["quality_failed"],
                ))
            elif quality["quality_missing"] and int(summary.get("missing_panels") or 0) == 0:
                todos.append(make_dashboard_todo(
                    f"quality-missing-{episode}",
                    "output_quality",
                    f"{episode_display(episode)}有 {quality['quality_missing']} 个输出未质检",
                    "生成结果已通过但缺少质量维度，请补齐后再进入整章审核。",
                    "补质量检查",
                    {"module": "workflow", "tab": "media", "episode": episode},
                    "review",
                    quality["quality_missing"],
                ))
            next_target = next_media_generation_target(media)
            next_page_id = str(next_target.get("page_id") or "")
            missing_pages = int(summary.get("missing_pages") or 0)
            missing_panels = int(summary.get("missing_panels") or 0)
            blockers = generated_output_review_blockers(project, episode)
            if active_episode.get("draft") and active_episode.get("assets") and (missing_pages or missing_panels) and not blockers.get("count"):
                is_partial = bool(next_target.get("partial"))
                page_missing_count = int(next_target.get("missing_count") or 0)
                latest_issue = latest_generation_issue_for_page(jobs, episode, next_page_id)
                if is_partial and page_missing_count:
                    todo_title = f"{episode_display(episode)}{page_display(next_page_id)}还缺 {page_missing_count} 格"
                    todo_detail = f"本页已有部分分镜，先补齐{page_display(next_page_id)}，再进入下一页。"
                    action_label = "补齐本页"
                    count = page_missing_count
                else:
                    todo_title = f"{episode_display(episode)}还缺 {missing_pages} 页 / {missing_panels} 格"
                    todo_detail = f"拆解和素材已确认，下一步补生成{page_display(next_page_id)}。"
                    action_label = "生成下一页"
                    count = missing_panels or missing_pages
                if latest_issue:
                    todo_detail = f"{todo_detail} 上次失败：{latest_issue}"
                todo_state = "resume" if is_partial and page_missing_count else "generate"
                todos.append(make_dashboard_todo(
                    f"missing-media-{episode}",
                    "generation",
                    todo_title,
                    todo_detail,
                    action_label,
                    {
                        "module": "workflow",
                        "tab": "media",
                        "episode": episode,
                        "media_filter": "pages",
                        "quick_action": "regenerate_page",
                        "page_id": next_page_id,
                    },
                    todo_state,
                    count,
                ))
            if active_episode.get("generation") and not active_episode.get("qa"):
                todos.append(make_dashboard_todo(
                    f"qa-{episode}",
                    "qa",
                    f"{episode_display(episode)}等待 QA 审核",
                    "生成审核已通过，下一步检查质检结果。",
                    "进入质检",
                    {"module": "workflow", "tab": "qa", "episode": episode},
                    "review",
                    1,
                ))
            if active_episode.get("qa") and not active_episode.get("next_episode"):
                next_episode = next_episode_number(episode)
                if next_episode:
                    todos.append(make_dashboard_todo(
                        f"next-{episode}",
                        "next",
                        f"{episode_display(episode)}可以进入下一章",
                        f"QA 已通过，建议进入 {episode_display(next_episode)}。",
                        "进入下一章",
                        {"module": "workflow", "tab": "source", "episode": next_episode},
                        "next",
                        1,
                    ))
        except Exception as exc:
            todos.append(make_dashboard_todo(
                f"episode-diagnostic-{episode}",
                "system",
                f"{episode_display(episode)}状态读取异常",
                str(exc),
                "查看章节",
                {"module": "workflow", "tab": "jobs", "episode": episode},
                "blocked",
                1,
            ))

    for row in db.dashboard_pending_settings(database_url(), slug, limit=4):
        todos.append(make_dashboard_todo(
            f"setting-{row.get('id')}",
            "setting",
            f"设定待审核：{row.get('name')}",
            f"{setting_type_label(row.get('item_type', ''))} · {review_status_label(row.get('review_status', ''))}",
            "审核设定",
            {"module": "settingsLibrary", "setting_id": int(row.get("id") or 0)},
            "settings",
            1,
        ))

    unique = {}
    for item in sorted(todos, key=lambda value: (value.get("priority", 80), -int(value.get("count") or 0), value.get("id", ""))):
        unique.setdefault(item["id"], item)
    return list(unique.values())[:limit]


def dashboard() -> dict:
    ensure_database()
    health = comfy_health()
    projects = list_projects()
    stats = db.dashboard_stats(database_url())
    jobs = recent_jobs()
    try:
        active = project_by_slug(projects.get("active", ""))
    except Exception:
        active = {}
    return {
        "ok": True,
        "stats": {
            "novels": int(stats.get("novels") or 0),
            "chapters": int(stats.get("chapters") or 0),
            "pending_settings": int(stats.get("pending_settings") or 0),
            "pending_reviews": int(stats.get("pending_reviews") or 0),
            "failed_jobs": int(stats.get("failed_jobs") or 0),
        },
        "system_status": {
            "database": health.get("database", {}),
            "image_backend": {
                "type": health.get("image_backend", "direct_api"),
                "ok": bool(health.get("generation_ready")),
                "url": health.get("comfy_url", "") if health.get("image_backend") == "comfyui" else "",
                "checks": health.get("checks", {}),
            },
            "comfyui": {
                "ok": bool(health.get("generation_ready")) if health.get("image_backend") == "comfyui" else True,
                "url": health.get("comfy_url", ""),
                "checks": health.get("checks", {}),
            },
            "api_key": {
                "configured": bool(health.get("image_api_key_configured")),
                "required": health.get("image_backend") != "comfyui",
            },
            "text_api_key": {"configured": bool(health.get("text_api_key_configured"))},
            "image_api_key": {"configured": bool(health.get("image_api_key_configured"))},
        },
        "recent_work": jobs,
        "failed_jobs": [job for job in jobs if job.get("status") in {"failed", "error"}],
        "todos": dashboard_todos(active, health, jobs) if active else [],
        "novels": projects.get("projects", []),
        "active": projects.get("active", ""),
    }


def list_projects() -> dict:
    projects = read_projects()
    active = active_project_slug()
    if active and not any(project.get("slug") == active and project.get("status", "active") != "archived" for project in projects):
        active = ""
    enriched = []
    for project in projects:
        status = project.get("status") or "active"
        enriched.append({
            **project,
            "active": project.get("slug") == active,
            "archived": status == "archived",
            "status": status,
            "project_config": project.get("project_config") if isinstance(project.get("project_config"), dict) else {},
            "series_exists": series_plan_path(project).is_file(),
            "chapter_index_exists": chapter_index_path(project).is_file(),
            "chapters": int(project.get("chapters") or 0),
            "episodes": int(project.get("episodes") or 0),
        })
    return {"active": active, "projects": enriched}


def list_novels_api() -> dict:
    projects = list_projects()
    return {
        "ok": True,
        "active": projects.get("active", ""),
        "items": [
            {
                "id": item.get("slug", ""),
                "slug": item.get("slug", ""),
                "title": item.get("title", ""),
                "source_file_path": item.get("novel_path", ""),
                "chapter_count": int(item.get("chapters") or 0),
                "episode_count": int(item.get("episodes") or 0),
                "status": item.get("status") or ("legacy" if item.get("legacy") else "active"),
                "archived": bool(item.get("archived")),
                "active": bool(item.get("active")),
                "updated_at": item.get("updated_at") or item.get("updated") or "",
                "last_opened_at": item.get("last_opened_at") or "",
                "project_config": item.get("project_config") if isinstance(item.get("project_config"), dict) else {},
            }
            for item in projects.get("projects", [])
        ],
    }


def novel_detail_api(slug: str) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    counts = db.project_counts(database_url(), project["slug"])
    chapters = db.list_chapters(database_url(), project["slug"])
    setting_items = db.list_setting_items(database_url(), project["slug"])
    visual_assets = db.list_visual_assets(database_url(), project["slug"])
    usage_index = build_reference_usage_index(project)
    setting_items = [
        {**item, "usage": setting_usage_for_item(usage_index, item)}
        for item in setting_items
    ]
    visual_assets = [
        {**item, "usage_summary": asset_usage_for_item(usage_index, item)}
        for item in visual_assets
    ]
    reviews = db.list_reviews(database_url(), project["slug"], limit=20)
    return {
        "ok": True,
        "novel": {
            "id": project.get("slug", ""),
            "slug": project.get("slug", ""),
            "title": project.get("title", ""),
            "source_file_path": project.get("novel_path", ""),
            "manifest_dir": project.get("manifest_dir", ""),
            "created_at": project.get("created_at", ""),
            "updated_at": project.get("updated_at", ""),
            "legacy": bool(project.get("legacy")),
        },
        "counts": counts,
        "chapters": chapters,
        "setting_library": {
            "items": setting_items,
            "total": len(setting_items),
            "pending_review": sum(1 for item in setting_items if item.get("review_status") in {"draft", "pending_review"}),
            "locked": sum(1 for item in setting_items if item.get("locked")),
        },
        "visual_assets": {
            "items": visual_assets,
            "total": len(visual_assets),
            "pending_review": sum(1 for item in visual_assets if item.get("review_status") in {"draft", "pending_review"}),
            "locked": sum(1 for item in visual_assets if item.get("locked")),
        },
        "reviews": reviews,
    }


def setting_library_api(slug: str, query: dict | None = None) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    query = query or {}
    item_type = str((query.get("type") or [""])[0] if isinstance(query.get("type"), list) else query.get("type") or "").strip()
    review_status = str((query.get("review_status") or [""])[0] if isinstance(query.get("review_status"), list) else query.get("review_status") or "").strip()
    items = db.list_setting_items(database_url(), project["slug"], item_type=item_type, review_status=review_status)
    usage_index = build_reference_usage_index(project)
    items = [
        {**item, "usage": setting_usage_for_item(usage_index, item)}
        for item in items
    ]
    return {
        "ok": True,
        "novel": {"slug": project.get("slug", ""), "title": project.get("title", "")},
        "types": SETTING_TYPE_LABELS,
        "items": items,
        "summary": summarize_settings(items),
    }


def summarize_settings(items: list[dict]) -> dict:
    by_type = {}
    by_status = {}
    for item in items:
        by_type[item.get("item_type") or "unknown"] = by_type.get(item.get("item_type") or "unknown", 0) + 1
        by_status[item.get("review_status") or "draft"] = by_status.get(item.get("review_status") or "draft", 0) + 1
    return {
        "total": len(items),
        "locked": sum(1 for item in items if item.get("locked")),
        "by_type": by_type,
        "by_status": by_status,
    }


def setting_identity(item: dict) -> tuple[str, str]:
    return (
        str(item.get("item_type") or "").strip(),
        str(item.get("name") or "").strip(),
    )


def normalized_setting_value(value):
    if isinstance(value, dict):
        return {str(key): normalized_setting_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalized_setting_value(item) for item in value]
    if value is None:
        return ""
    return value


def normalized_setting_field(item: dict, field: str):
    if field in {"aliases", "chapter_numbers", "source_evidence"}:
        return normalized_setting_value(item.get(field) or [])
    if field == "relations":
        return normalized_setting_value(item.get(field) or {})
    return normalized_setting_value(item.get(field))


def settings_meaningful_diff(existing: dict, candidate: dict) -> list[str]:
    labels = {
        "aliases": "别名",
        "description": "描述",
        "first_chapter_number": "首次出现章节",
        "chapter_numbers": "关联章节",
        "visual_prompt": "视觉提示",
        "negative_prompt": "负面提示",
        "relations": "关系",
        "source_evidence": "证据",
        "importance": "重要性",
        "review_status": "审核状态",
    }
    changed = []
    for field, label in labels.items():
        before = normalized_setting_field(existing, field)
        after = normalized_setting_field(candidate, field)
        if before != after:
            changed.append(label)
    return changed


def setting_report_item(item: dict, action: str, changes: list[str] | None = None) -> dict:
    return {
        "id": item.get("id"),
        "item_type": item.get("item_type") or "",
        "name": item.get("name") or "",
        "review_status": item.get("review_status") or "",
        "locked": bool(item.get("locked")),
        "action": action,
        "changes": changes or [],
    }


def build_setting_scan_report(existing: list[dict], candidates: list[dict], saved: list[dict], enhancement: dict | None = None) -> dict:
    existing_by_key = {setting_identity(item): item for item in existing}
    saved_by_key = {setting_identity(item): item for item in saved}
    actions = []
    protected_items = []
    counts = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "protected": 0,
    }
    for candidate in candidates:
        key = setting_identity(candidate)
        existing_item = existing_by_key.get(key)
        saved_item = saved_by_key.get(key) or candidate
        if not existing_item:
            action = "created"
            changes = []
        elif existing_item.get("locked"):
            action = "protected"
            changes = settings_meaningful_diff(existing_item, candidate)
        else:
            changes = settings_meaningful_diff(existing_item, candidate)
            action = "updated" if changes else "unchanged"
        counts[action] += 1
        row = setting_report_item(saved_item, action, changes)
        actions.append(row)
        if action == "protected":
            protected_items.append(row)
    enhancement = enhancement or {"requested": False, "used_count": 0, "error_count": 0, "errors": []}
    notes = [
        "已锁定设定会保留原审核状态和锁定状态。",
    ]
    if enhancement.get("requested"):
        notes.append(
            f"AI 增强已处理 {int(enhancement.get('used_count') or 0)} 条候选"
            f"，失败 {int(enhancement.get('error_count') or 0)} 条；失败项已保留脚本扫描结果。"
        )
    else:
        notes.append("当前扫描使用脚本候选，不调用小说处理模型。")
    return {
        "candidate_count": len(candidates),
        "saved_count": len(saved),
        "created_count": counts["created"],
        "updated_count": counts["updated"],
        "unchanged_count": counts["unchanged"],
        "protected_count": counts["protected"],
        "ai_requested": bool(enhancement.get("requested")),
        "ai_used_count": int(enhancement.get("used_count") or 0),
        "ai_error_count": int(enhancement.get("error_count") or 0),
        "ai_errors": list(enhancement.get("errors") or [])[:10],
        "by_type": summarize_settings(saved).get("by_type", {}),
        "by_status": summarize_settings(saved).get("by_status", {}),
        "actions": actions[:30],
        "protected_items": protected_items[:20],
        "truncated": len(actions) > 30,
        "notes": notes,
    }


KNOWN_CHARACTER_NAMES = [
    "拓拔野",
    "蚩尤",
    "神农使者",
    "神农",
    "雨师妾",
    "姑射仙子",
    "晏紫苏",
    "烈烟石",
    "姬远玄",
    "赤松子",
    "西王母",
    "刑天",
    "夸父",
    "祝融",
    "共工",
]


def tokenize_setting_instruction(instruction: str) -> list[str]:
    text = str(instruction or "").strip()
    if not text:
        return []
    tokens: list[str] = []
    for name in KNOWN_CHARACTER_NAMES:
        if name in text and name not in tokens:
            tokens.append(name)
    for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_\-]{1,32}", text):
        if token not in {"角色设定", "视觉设定", "出现章节", "提取", "补充", "搜索", "录入", "全文", "扫描"} and token not in tokens:
            tokens.append(token)
    return tokens[:12]


def chapter_setting_scan_text(chapter: dict) -> str:
    raw = chapter.get("raw") if isinstance(chapter.get("raw"), dict) else {}
    parts = [
        chapter.get("title") or "",
        raw.get("title") or "",
        raw.get("summary") or "",
        raw.get("excerpt") or "",
        raw.get("text") or "",
        raw.get("content") or "",
    ]
    return "\n".join(str(part) for part in parts if part)


CHARACTER_FEATURE_KEYWORDS = (
    "身穿", "披着", "穿着", "腰悬", "手持", "执", "佩", "戴", "披", "束",
    "长发", "白发", "黑发", "青衣", "白衣", "黑衣", "红衣", "短袍", "长袍",
    "面容", "容貌", "眉", "眼", "目光", "神情", "气质", "威严", "倔强",
    "少年", "少女", "老人", "女子", "男子", "仙子", "神帝", "使者",
)


def character_context_snippet(text: str, name: str, radius: int = 90) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean or not name:
        return ""
    positions = [match.start() for match in re.finditer(re.escape(name), clean)]
    if not positions:
        return compact_text(clean, 160)
    best = ""
    best_score = -1
    for pos in positions[:6]:
        start = max(0, pos - radius)
        end = min(len(clean), pos + len(name) + radius)
        snippet = clean[start:end].strip(" ，。；、")
        score = sum(1 for keyword in CHARACTER_FEATURE_KEYWORDS if keyword in snippet)
        if score > best_score:
            best = snippet
            best_score = score
    return compact_text(best, 160)


def extract_character_feature_phrases(name: str, evidence_items: list[dict], limit: int = 3) -> list[str]:
    phrases: list[str] = []
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if not text or name not in text:
            continue
        for match in re.finditer(re.escape(name), text):
            prefix = text[max(0, match.start() - 8):match.start()]
            suffix = text[match.end(): min(len(text), match.end() + 56)]
            prefix_terms = re.findall(r"(少年|少女|老人|女子|男子|仙子|神帝|使者)$", prefix)
            parts = []
            if prefix_terms:
                parts.append(prefix_terms[-1])
            suffix_segment = re.split(r"[。！？!?；;]", suffix, maxsplit=1)[0]
            for clause in re.split(r"[，,、]", suffix_segment)[:4]:
                clause = clause.strip(" ，。；、")
                if re.match(r"(身穿|穿着|披着|腰悬|手持|执|佩|戴|披|束|长发|白发|黑发|青衣|白衣|黑衣|红衣|面容|容貌|目光|神情|气质)", clause):
                    parts.append(clause[:36])
            if not parts:
                continue
            phrase = compact_text(f"{name}{''.join(parts)}", 72)
            if phrase and phrase not in phrases:
                phrases.append(phrase)
            if len(phrases) >= limit:
                return phrases
    return phrases


def extract_character_candidates_from_chapters(chapters: list[dict], limit: int = 24) -> list[dict]:
    index: dict[str, dict] = {}
    for chapter in chapters:
        text = chapter_setting_scan_text(chapter)
        if not text:
            continue
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("title") or "").strip()
        for name in KNOWN_CHARACTER_NAMES:
            if name not in text:
                continue
            row = index.setdefault(name, {
                "name": name,
                "chapter_numbers": [],
                "source_evidence": [],
                "mentions": 0,
            })
            row["mentions"] += text.count(name)
            if chapter_number and chapter_number not in row["chapter_numbers"]:
                row["chapter_numbers"].append(chapter_number)
            if len(row["source_evidence"]) < 4:
                evidence = character_context_snippet(text, name)
                row["source_evidence"].append({
                    "type": "chapter_text",
                    "chapter_number": chapter_number,
                    "chapter_title": title,
                    "text": evidence,
                })
    ordered = sorted(
        index.values(),
        key=lambda item: (
            -(int(item.get("mentions") or 0)),
            min(item.get("chapter_numbers") or [9999]),
            str(item.get("name") or ""),
        ),
    )
    candidates = []
    for item in ordered[:limit]:
        chapter_numbers = sorted(item.get("chapter_numbers") or [])
        first_chapter = chapter_numbers[0] if chapter_numbers else None
        name = item["name"]
        feature_phrases = extract_character_feature_phrases(name, item.get("source_evidence") or [])
        feature_text = "；".join(feature_phrases) if feature_phrases else "原文暂未提取到稳定外貌特征，需人工补充面部、发型、服饰、体型、气质和标志物"
        candidates.append({
            "item_type": "character",
            "name": name,
            "aliases": [],
            "description": (
                f"{name} 是《搜神记》中从章节原文/摘要识别出的角色候选。"
                f"识别特征：{feature_text}。"
                "需人工确认身份、外貌、阵营和后续出场权重。"
            ),
            "first_chapter_number": first_chapter,
            "chapter_numbers": chapter_numbers,
            "visual_prompt": (
                f"{name}，角色特征：{feature_text}，"
                "东方上古神话幻想漫画角色设定图，稳定面部、发型、服饰、体型比例和标志物，全身比例参考，画面不加文字。"
            ),
            "negative_prompt": ASSET_NEGATIVE_PROMPT,
            "relations": {},
            "source_evidence": item.get("source_evidence") or [],
            "importance": "core" if int(item.get("mentions") or 0) >= 2 else "normal",
            "review_status": "pending_review",
            "locked": False,
            "raw": {
                "source": "deterministic_character_scan",
                "scan_version": "settings.v2",
                "mentions": int(item.get("mentions") or 0),
                "feature_phrases": feature_phrases,
            },
        })
    return candidates


def setting_aliases(setting: dict) -> list[str]:
    aliases = setting.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [item.strip() for item in aliases.split(",") if item.strip()]
    return [str(item).strip() for item in aliases if str(item).strip()]


def normalized_source_evidence_items(value) -> list[dict]:
    items = value if isinstance(value, list) else []
    output: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = compact_text(item.get("text") or "", 260)
        if not text:
            continue
        output.append({
            **item,
            "text": text,
        })
    return output


def setting_reference_chapter_numbers(setting: dict) -> list[int]:
    numbers: list[int] = []
    for value in setting.get("chapter_numbers") or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in numbers:
            numbers.append(number)
    try:
        first = int(setting.get("first_chapter_number") or 0)
    except (TypeError, ValueError):
        first = 0
    if first > 0 and first not in numbers:
        numbers.insert(0, first)
    return numbers


def setting_recall_terms(setting: dict) -> list[str]:
    terms: list[str] = []
    raw = setting.get("raw") if isinstance(setting.get("raw"), dict) else {}
    sources = [
        setting.get("name") or "",
        " ".join(setting_aliases(setting)),
        setting.get("description") or "",
        setting.get("visual_prompt") or "",
        " ".join(str(item) for item in raw.get("feature_phrases") or [] if str(item).strip()),
    ]
    stop_words = {
        "角色", "设定", "视觉", "提示", "提示词", "关键", "场景", "主角", "世界观",
        "需要", "人工", "确认", "漫画", "东方", "上古", "神话", "幻想",
    }
    for source in sources:
        for token in tokenize_setting_instruction(str(source)):
            if token in stop_words or len(token) < 2:
                continue
            if token not in terms:
                terms.append(token)
    return terms[:16]


def fallback_setting_evidence(setting: dict, chapters: list[dict], max_items: int = 6) -> list[dict]:
    existing = normalized_source_evidence_items(setting.get("source_evidence"))
    if existing:
        return existing[:max_items]

    referenced_numbers = set(setting_reference_chapter_numbers(setting))
    recall_terms = setting_recall_terms(setting)
    scored: list[tuple[int, int, dict, str]] = []
    for index, chapter in enumerate(chapters):
        text = chapter_setting_scan_text(chapter)
        if not text:
            continue
        chapter_number = int(chapter.get("chapter_number") or 0)
        score = 0
        if chapter_number in referenced_numbers:
            score += 80
        score += sum(text.count(term) * 8 for term in recall_terms if term and term in text)
        if score:
            scored.append((score, -chapter_number if chapter_number else -index, chapter, text))

    if not scored and referenced_numbers:
        for index, chapter in enumerate(chapters):
            chapter_number = int(chapter.get("chapter_number") or 0)
            if chapter_number not in referenced_numbers:
                continue
            text = chapter_setting_scan_text(chapter)
            if text:
                scored.append((40, -chapter_number if chapter_number else -index, chapter, text))

    if not scored:
        for index, chapter in enumerate(chapters[:max_items]):
            text = chapter_setting_scan_text(chapter)
            if text:
                chapter_number = int(chapter.get("chapter_number") or 0)
                scored.append((10, -chapter_number if chapter_number else -index, chapter, text))

    scored.sort(key=lambda item: (-item[0], item[1]))
    evidence: list[dict] = []
    for score, _order, chapter, text in scored[:max_items]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("title") or "").strip()
        evidence.append({
            "type": "fallback_chapter_context",
            "chapter_number": chapter_number,
            "chapter_title": title,
            "matched_term": next((term for term in recall_terms if term and term in text), ""),
            "text": character_context_snippet(text, str(setting.get("name") or "").strip() or title),
            "score": score,
        })
    return evidence


def extract_target_character_candidate(setting: dict, chapters: list[dict]) -> dict:
    name = str(setting.get("name") or "").strip()
    search_terms = [name, *setting_aliases(setting)]
    search_terms = [term for index, term in enumerate(search_terms) if term and term not in search_terms[:index]]
    row = {
        "name": name,
        "chapter_numbers": [],
        "source_evidence": [],
        "mentions": 0,
    }
    for chapter in chapters:
        text = chapter_setting_scan_text(chapter)
        if not text:
            continue
        matched_terms = [term for term in search_terms if term in text]
        if not matched_terms:
            continue
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("title") or "").strip()
        row["mentions"] += sum(text.count(term) for term in matched_terms)
        if chapter_number and chapter_number not in row["chapter_numbers"]:
            row["chapter_numbers"].append(chapter_number)
        if len(row["source_evidence"]) < 6:
            best_term = max(matched_terms, key=lambda term: text.count(term))
            row["source_evidence"].append({
                "type": "chapter_text",
                "chapter_number": chapter_number,
                "chapter_title": title,
                "matched_term": best_term,
                "text": character_context_snippet(text, best_term),
            })
    chapter_numbers = sorted(row["chapter_numbers"])
    feature_phrases: list[str] = []
    for term in search_terms:
        for phrase in extract_character_feature_phrases(term, row["source_evidence"], limit=4):
            phrase = phrase.replace(term, name, 1) if term != name else phrase
            if phrase not in feature_phrases:
                feature_phrases.append(phrase)
            if len(feature_phrases) >= 4:
                break
    if not row["source_evidence"]:
        row["source_evidence"] = fallback_setting_evidence(setting, chapters)
    feature_text = "；".join(feature_phrases) if feature_phrases else "原文暂未提取到稳定外貌特征，需人工补充面部、发型、服饰、体型、气质和标志物"
    return {
        "item_type": "character",
        "name": name,
        "aliases": setting_aliases(setting),
        "description": (
            f"{name} 是《{project_title_for_setting(setting)}》中定向重提的角色设定。"
            f"识别特征：{feature_text}。"
            "需人工确认身份、外貌、阵营和后续出场权重。"
        ),
        "first_chapter_number": chapter_numbers[0] if chapter_numbers else setting.get("first_chapter_number"),
        "chapter_numbers": chapter_numbers or (setting.get("chapter_numbers") or []),
        "visual_prompt": (
            f"{name}，角色特征：{feature_text}，东方上古神话幻想漫画角色设定图，"
            "稳定面部、发型、服饰、体型比例和标志物，全身比例参考，画面不加文字。"
        ),
        "negative_prompt": ASSET_NEGATIVE_PROMPT,
        "relations": setting.get("relations") if isinstance(setting.get("relations"), dict) else {},
        "source_evidence": row["source_evidence"],
        "importance": setting.get("importance") or ("core" if int(row["mentions"] or 0) >= 2 else "normal"),
        "review_status": setting.get("review_status") or "pending_review",
        "locked": bool(setting.get("locked")),
        "raw": {
            **(setting.get("raw") if isinstance(setting.get("raw"), dict) else {}),
            "source": "targeted_setting_prompt_refresh",
            "refresh_version": "settings.refresh.v1",
            "mentions": int(row["mentions"] or 0),
            "feature_phrases": feature_phrases,
            "search_terms": search_terms,
            "refreshed_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def project_title_for_setting(setting: dict) -> str:
    return str(setting.get("project_title") or "当前小说").strip()


def extract_generic_setting_prompt_candidate(setting: dict, chapters: list[dict]) -> dict:
    name = str(setting.get("name") or "").strip()
    item_type = str(setting.get("item_type") or "world_rule").strip()
    matched = []
    chapter_numbers = []
    for chapter in chapters:
        text = chapter_setting_scan_text(chapter)
        if not text or name not in text:
            continue
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number and chapter_number not in chapter_numbers:
            chapter_numbers.append(chapter_number)
        if len(matched) < 6:
            matched.append({
                "type": "chapter_text",
                "chapter_number": chapter_number,
                "chapter_title": str(chapter.get("title") or "").strip(),
                "matched_term": name,
                "text": character_context_snippet(text, name),
            })
    if not matched:
        matched = fallback_setting_evidence(setting, chapters)
    chapter_numbers = sorted(chapter_numbers)
    label = setting_type_label(item_type)
    evidence_text = "；".join(item.get("text", "") for item in matched[:2] if item.get("text"))
    detail = compact_text(evidence_text, 160) if evidence_text else "原文暂未提取到稳定细节，需人工补充关键视觉要素和使用边界"
    return {
        "item_type": item_type,
        "name": name,
        "aliases": setting_aliases(setting),
        "description": f"{name} 是定向重提的{label}设定。识别要点：{detail}。",
        "first_chapter_number": chapter_numbers[0] if chapter_numbers else setting.get("first_chapter_number"),
        "chapter_numbers": chapter_numbers or (setting.get("chapter_numbers") or []),
        "visual_prompt": f"{name}，{label}视觉设定，{detail}，东方上古神话幻想漫画参考，清晰形状语言，画面不加文字。",
        "negative_prompt": setting.get("negative_prompt") or ASSET_NEGATIVE_PROMPT,
        "relations": setting.get("relations") if isinstance(setting.get("relations"), dict) else {},
        "source_evidence": matched,
        "importance": setting.get("importance") or "normal",
        "review_status": setting.get("review_status") or "pending_review",
        "locked": bool(setting.get("locked")),
        "raw": {
            **(setting.get("raw") if isinstance(setting.get("raw"), dict) else {}),
            "source": "targeted_setting_prompt_refresh",
            "refresh_version": "settings.refresh.v1",
            "search_terms": [name],
            "refreshed_at": datetime.now().isoformat(timespec="seconds"),
        },
    }


def evidence_for_model(candidate: dict, max_items: int = 8, max_chars: int = 1800) -> str:
    lines = []
    for item in (candidate.get("source_evidence") or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        chapter = item.get("chapter_number") or ""
        title = item.get("chapter_title") or ""
        text = compact_text(item.get("text") or "", 260)
        if text:
            lines.append(f"- 第{chapter}章 {title}：{text}".strip())
    return compact_text("\n".join(lines), max_chars)


def call_setting_prompt_model(messages: list[dict]) -> dict:
    config = runtime_config()
    keys = [
        "COMIC_PIPELINE_TEXT_MODEL",
        "COMIC_PIPELINE_TEXT_ENV_PATH",
        "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT",
        "COMIC_PIPELINE_TEXT_MODEL_STREAM",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            value = str(config.get(key) or "").strip()
            if value:
                os.environ[key] = value
        timeout = int(str(config.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT") or "300"))
        return chat_json(messages, temperature=0.15, timeout=timeout)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def ai_enhance_setting_candidate(setting: dict, candidate: dict) -> tuple[dict, dict]:
    evidence = evidence_for_model(candidate)
    if not evidence:
        return candidate, {
            "requested": True,
            "used": False,
            "model": "",
            "error": "没有可供 AI 增强的来源证据。",
        }
    item_type = str(setting.get("item_type") or candidate.get("item_type") or "character")
    type_label = setting_type_label(item_type)
    name = str(setting.get("name") or candidate.get("name") or "").strip()
    messages = [
        {
            "role": "system",
            "content": (
                "你是漫画项目的小说设定提取助手。只返回 JSON，不要解释。"
                "目标是基于证据提取可人工审核的漫画设定，不要编造证据中没有的专有关系。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请为《{project_title_for_setting(setting)}》中的{type_label}“{name}”重新提取设定。\n"
                f"当前类型：{item_type}\n"
                f"别名：{', '.join(setting_aliases(setting)) or '无'}\n"
                f"脚本初稿描述：{candidate.get('description') or ''}\n"
                f"脚本初稿视觉提示：{candidate.get('visual_prompt') or ''}\n"
                "来源证据：\n"
                f"{evidence}\n\n"
                "返回 JSON 对象，字段必须包括："
                "description, visual_prompt, negative_prompt, aliases, chapter_numbers, feature_phrases, importance。"
                "description 用中文，说明身份、性格/功能、外貌/结构和需要人工确认的点。"
                "visual_prompt 用中文漫画生成提示词，必须适合后续角色/场景/道具参考图生成。"
                "chapter_numbers 返回数字数组。importance 只能是 core/high/normal/low。"
            ),
        },
    ]
    result = call_setting_prompt_model(messages)
    enhanced = {**candidate}
    aliases = result.get("aliases") if isinstance(result.get("aliases"), list) else candidate.get("aliases") or []
    chapter_numbers = result.get("chapter_numbers") if isinstance(result.get("chapter_numbers"), list) else candidate.get("chapter_numbers") or []
    enhanced.update({
        "aliases": [str(item).strip() for item in aliases if str(item).strip()],
        "description": str(result.get("description") or candidate.get("description") or "").strip(),
        "visual_prompt": str(result.get("visual_prompt") or candidate.get("visual_prompt") or "").strip(),
        "negative_prompt": str(result.get("negative_prompt") or candidate.get("negative_prompt") or ASSET_NEGATIVE_PROMPT).strip(),
        "chapter_numbers": [int(item) for item in chapter_numbers if str(item).isdigit()],
        "importance": str(result.get("importance") or candidate.get("importance") or "normal").strip(),
    })
    raw = enhanced.get("raw") if isinstance(enhanced.get("raw"), dict) else {}
    enhanced["raw"] = {
        **raw,
        "source": "targeted_setting_prompt_ai_enhanced",
        "ai_feature_phrases": result.get("feature_phrases") if isinstance(result.get("feature_phrases"), list) else [],
        "ai_model": result.get("_model") or "",
        "ai_enhanced_at": datetime.now().isoformat(timespec="seconds"),
    }
    return enhanced, {
        "requested": True,
        "used": True,
        "model": result.get("_model") or "",
        "error": "",
    }


def setting_refresh_editor_payload(current: dict, candidate: dict, mode: str) -> dict:
    output = {}
    fields = [
        "item_type", "name", "aliases", "description", "first_chapter_number", "chapter_numbers",
        "visual_prompt", "negative_prompt", "relations", "source_evidence", "importance",
        "review_status", "locked", "raw",
    ]
    for field in fields:
        current_value = current.get(field)
        candidate_value = candidate.get(field)
        if mode == "fill_missing":
            if current_value not in (None, "", [], {}):
                output[field] = current_value
            else:
                output[field] = candidate_value
        else:
            output[field] = candidate_value
    return output


def setting_refresh_changes(current: dict, editor_payload: dict) -> dict:
    fields = ["description", "visual_prompt", "negative_prompt", "first_chapter_number", "chapter_numbers", "source_evidence"]
    changes = {}
    for field in fields:
        before = current.get(field)
        after = editor_payload.get(field)
        changes[field] = {
            "before": before,
            "after": after,
            "changed": normalized_setting_value(before) != normalized_setting_value(after),
        }
    return changes


def refresh_setting_prompt_api(setting_id: int, payload: dict) -> dict:
    ensure_database()
    current = db.get_setting_item(database_url(), setting_id)
    if not current:
        raise ValueError("设定条目不存在")
    mode = str(payload.get("mode") or "fill_missing").strip()
    if mode not in {"fill_missing", "overwrite"}:
        mode = "fill_missing"
    project_slug = str(current.get("project_slug") or "").strip()
    chapters = db.list_chapters(database_url(), project_slug) if project_slug else []
    if str(current.get("item_type") or "") == "character":
        candidate = extract_target_character_candidate(current, chapters)
    else:
        candidate = extract_generic_setting_prompt_candidate(current, chapters)
    extraction_mode = str(payload.get("extraction_mode") or "script").strip()
    enhancement = {
        "requested": extraction_mode == "ai",
        "used": False,
        "model": "",
        "error": "",
    }
    if extraction_mode == "ai":
        try:
            candidate, enhancement = ai_enhance_setting_candidate(current, candidate)
        except Exception as exc:
            enhancement = {
                "requested": True,
                "used": False,
                "model": "",
                "error": str(exc),
            }
    editor_payload = setting_refresh_editor_payload(current, candidate, mode)
    return {
        "ok": True,
        "setting_id": int(setting_id),
        "mode": mode,
        "extraction_mode": extraction_mode,
        "enhancement": enhancement,
        "locked": bool(current.get("locked")),
        "current": current,
        "candidate": candidate,
        "editor_payload": editor_payload,
        "changes": setting_refresh_changes(current, editor_payload),
        "message": "已重新提取提示词，请审核差异后应用到编辑器并保存。",
    }


def suggest_setting_candidates_from_instruction(project: dict, instruction: str, limit: int = 12) -> list[dict]:
    instruction = str(instruction or "").strip()
    if not instruction:
        raise ValueError("请输入需要补充的设定说明")
    chapters = db.list_chapters(database_url(), project["slug"])
    tokens = tokenize_setting_instruction(instruction)
    all_character_candidates = extract_character_candidates_from_chapters(chapters, limit=48)
    scored: list[tuple[int, dict]] = []
    for candidate in all_character_candidates:
        name = str(candidate.get("name") or "")
        chapter_numbers = candidate.get("chapter_numbers") or []
        evidence_text = " ".join(
            str(item.get("text") or "")
            for item in candidate.get("source_evidence") or []
            if isinstance(item, dict)
        )
        score = 0
        if name and name in instruction:
            score += 100
        score += sum(12 for token in tokens if token and (token in name or token in evidence_text))
        score += min(20, len(chapter_numbers) * 2)
        score += min(10, int((candidate.get("raw") or {}).get("mentions") or 0))
        if score:
            enriched = {
                **candidate,
                "description": (
                    f"根据人工说明“{compact_text(instruction, 80)}”从全文扫描得到的角色候选。"
                    f"{candidate.get('description') or ''}"
                ),
                "raw": {
                    **(candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}),
                    "source": "user_instruction_deterministic_scan",
                    "instruction": instruction,
                    "matched_tokens": [token for token in tokens if token and (token in name or token in evidence_text)],
                },
            }
            scored.append((score, enriched))
    if not scored:
        return [{
            "item_type": "character",
            "name": tokens[0] if tokens else compact_text(instruction, 16),
            "aliases": [],
            "description": f"根据人工说明“{compact_text(instruction, 120)}”创建的待补充设定候选。全文中暂未匹配到明确角色名，请人工确认后保存。",
            "first_chapter_number": None,
            "chapter_numbers": [],
            "visual_prompt": f"{tokens[0] if tokens else '角色'}，东方神话幻想漫画角色设定图，清晰面部特征，全身比例参考，画面不加文字。",
            "negative_prompt": ASSET_NEGATIVE_PROMPT,
            "relations": {},
            "source_evidence": [{"type": "user_instruction", "text": instruction}],
            "importance": "normal",
            "review_status": "pending_review",
            "locked": False,
            "raw": {"source": "user_instruction_manual_candidate", "instruction": instruction},
        }]
    scored.sort(key=lambda item: (-item[0], min(item[1].get("chapter_numbers") or [9999]), item[1].get("name") or ""))
    return [item for _, item in scored[: max(1, limit)]]


def ai_discover_setting_candidates(project: dict, chapters: list[dict], limit: int = 40, progress_callback=None) -> tuple[list[dict], dict]:
    supported_types = {"character", "location", "prop", "faction"}
    chapter_rows = [
        {
            "chapter_number": int(chapter.get("chapter_number") or 0),
            "chapter_title": str(chapter.get("title") or ""),
            "text": chapter_setting_scan_text(chapter)[:2400],
        }
        for chapter in chapters
        if chapter_setting_scan_text(chapter)
    ]
    batches = [chapter_rows[index:index + 8] for index in range(0, len(chapter_rows), 8)]
    report = {"requested": True, "used_count": 0, "error_count": 0, "errors": [], "discovered_count": 0}
    by_key: dict[tuple[str, str], dict] = {}
    for batch_index, batch in enumerate(batches, start=1):
        if len(by_key) >= limit:
            break
        if progress_callback:
            progress_callback(batch_index - 1, len(batches), f"AI 发现候选：章节批次 {batch_index}/{len(batches)}")
        try:
            result = call_setting_prompt_model([
                {
                    "role": "system",
                    "content": (
                        "你是漫画改编的小说设定发现助手。只返回 JSON。"
                        "仅提取正文明确出现且可复查的角色、地点、道具、组织，不得补写不存在的实体。"
                        "名称必须是原文中的专名；角色需区分身份称谓与姓名；道具需具有跨镜头复用价值。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "project_title": project.get("title") or project.get("slug") or "当前小说",
                        "chapters": batch,
                        "remaining_limit": max(1, min(16, limit - len(by_key))),
                        "required_schema": {
                            "items": [{
                                "item_type": "character|location|prop|faction",
                                "name": "原文专名",
                                "aliases": ["原文别名"],
                                "description": "只基于正文的中文设定描述",
                                "visual_prompt": "可直接用于漫画设定图的中文视觉提示词",
                                "negative_prompt": "需要避免的视觉错误",
                                "importance": "core|high|normal",
                            }],
                        },
                    }, ensure_ascii=False),
                },
            ])
            report["used_count"] += 1
        except Exception as exc:
            report["error_count"] += 1
            report["errors"].append({"batch": batch_index, "error": str(exc)})
            continue
        for item in result.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("item_type") or "").strip()
            name = str(item.get("name") or "").strip()
            if item_type not in supported_types or len(name) < 2 or len(name) > 40:
                continue
            aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
            terms = [name, *[str(alias).strip() for alias in aliases if str(alias).strip()]]
            matched_chapters = []
            evidence = []
            mentions = 0
            for chapter in chapters:
                text = chapter_setting_scan_text(chapter)
                matched = [term for term in terms if term and term in text]
                if not matched:
                    continue
                number = int(chapter.get("chapter_number") or 0)
                if number and number not in matched_chapters:
                    matched_chapters.append(number)
                mentions += sum(text.count(term) for term in matched)
                if len(evidence) < 5:
                    best_term = max(matched, key=lambda term: text.count(term))
                    evidence.append({
                        "type": "ai_discovery_verified_chapter_text",
                        "chapter_number": number,
                        "chapter_title": str(chapter.get("title") or ""),
                        "matched_term": best_term,
                        "text": character_context_snippet(text, best_term),
                    })
            if not evidence:
                continue
            importance = str(item.get("importance") or "normal").strip()
            if importance not in {"core", "high", "normal"}:
                importance = "core" if mentions >= 3 else "normal"
            candidate = {
                "item_type": item_type,
                "name": name,
                "aliases": terms[1:],
                "description": str(item.get("description") or f"{name} 是正文中明确出现的{setting_type_label(item_type)}设定。"),
                "first_chapter_number": min(matched_chapters) if matched_chapters else None,
                "chapter_numbers": sorted(matched_chapters),
                "visual_prompt": str(item.get("visual_prompt") or f"{name}，商业漫画{setting_type_label(item_type)}设定图，细节清晰，保持跨章节一致。"),
                "negative_prompt": str(item.get("negative_prompt") or ASSET_NEGATIVE_PROMPT),
                "relations": {},
                "source_evidence": evidence,
                "importance": importance,
                "review_status": "pending_review",
                "locked": False,
                "raw": {
                    "source": "ai_candidate_discovery",
                    "scan_version": "settings.ai_discovery.v1",
                    "ai_model": result.get("_model") or "",
                    "mentions": mentions,
                },
            }
            key = setting_identity(candidate)
            existing = by_key.get(key)
            if not existing:
                by_key[key] = candidate
                continue
            existing["chapter_numbers"] = sorted(set(existing.get("chapter_numbers") or []) | set(candidate["chapter_numbers"]))
            existing["source_evidence"] = (existing.get("source_evidence") or []) + [
                row for row in candidate["source_evidence"]
                if row not in (existing.get("source_evidence") or [])
            ]
        if progress_callback:
            progress_callback(batch_index, len(batches), f"已发现 {len(by_key)} 条正文候选")
    candidates = list(by_key.values())[:max(0, limit)]
    report["discovered_count"] = len(candidates)
    return candidates, report


def merge_setting_candidates(existing: list[dict], discovered: list[dict], limit: int) -> list[dict]:
    merged = list(existing)
    positions = {setting_identity(item): index for index, item in enumerate(merged)}
    for item in discovered:
        key = setting_identity(item)
        if key in positions:
            current = merged[positions[key]]
            merged[positions[key]] = {
                **current,
                **item,
                "source_evidence": item.get("source_evidence") or current.get("source_evidence") or [],
                "raw": {**(current.get("raw") or {}), **(item.get("raw") or {})},
            }
        elif len(merged) < limit:
            positions[key] = len(merged)
            merged.append(item)
    return merged[:limit]


def scan_setting_candidates(project: dict, limit: int = 80, chapters: list[dict] | None = None) -> list[dict]:
    chapters = chapters if chapters is not None else db.list_chapters(database_url(), project["slug"])
    volume_map: dict[str, list[dict]] = {}
    for chapter in chapters:
        volume = str(chapter.get("volume") or "").strip()
        if not volume:
            continue
        volume_map.setdefault(volume, []).append(chapter)

    candidates: list[dict] = [
        {
            "item_type": "style_rule",
            "name": "全书漫画画风",
            "description": f"《{project.get('title', project.get('slug', '当前小说'))}》的统一漫画风格基准：上古神话幻想题材，水墨与厚涂结合，清晰剪影，电影分镜，画面不加文字。",
            "visual_prompt": "上古神话幻想漫画，水墨与厚涂结合，清晰剪影，电影分镜，古代服饰和器物，不出现现代城市或现代科技元素。",
            "negative_prompt": ASSET_NEGATIVE_PROMPT,
            "importance": "core",
            "review_status": "pending_review",
            "locked": False,
            "source_evidence": [{"type": "system", "text": "根据项目默认漫画风格生成，需人工审核后锁定。"}],
            "raw": {"source": "deterministic_scan", "scan_version": "settings.v1"},
        },
        {
            "item_type": "world_rule",
            "name": "世界观基准",
            "description": "以小说章节索引为基础生成的世界观占位规则：当前作品按卷和章节推进，后续章节拆解必须继承已审核的时代感、神话规则、地理区域和禁用元素。",
            "visual_prompt": "东方神话大荒世界，山海经气质，古代部族、神灵、异兽、祭器、荒野山川。",
            "negative_prompt": "modern city, phone, car, skyscraper, sci-fi weapon, western medieval castle",
            "importance": "core",
            "review_status": "pending_review",
            "locked": False,
            "source_evidence": [{"type": "chapter_index", "text": f"已解析 {len(chapters)} 章，用于建立全书规则。"}],
            "raw": {"source": "deterministic_scan", "scan_version": "settings.v1"},
        },
    ]

    remaining = max(0, limit - len(candidates))
    if remaining:
        candidates.extend(extract_character_candidates_from_chapters(chapters, limit=min(24, remaining)))

    for volume, volume_chapters in volume_map.items():
        if len(candidates) >= limit:
            break
        chapter_numbers = [int(item.get("chapter_number") or 0) for item in volume_chapters if item.get("chapter_number")]
        chapter_titles = [str(item.get("title") or "").strip() for item in volume_chapters[:6] if item.get("title")]
        candidates.append({
            "item_type": "location",
            "name": volume,
            "description": f"{volume} 是《{project.get('title', '')}》中的卷/区域候选，覆盖 {len(volume_chapters)} 个章节。需人工确认它是地点、阶段还是叙事篇章。",
            "first_chapter_number": min(chapter_numbers) if chapter_numbers else None,
            "chapter_numbers": chapter_numbers,
            "visual_prompt": f"{volume}，东方神话幻想场景，参考章节：{'、'.join(chapter_titles[:4])}",
            "importance": "normal",
            "review_status": "pending_review",
            "locked": False,
            "source_evidence": [
                {
                    "type": "chapter_index",
                    "volume": volume,
                    "chapter_count": len(volume_chapters),
                    "sample_chapters": chapter_titles,
                }
            ],
            "raw": {"source": "deterministic_scan", "scan_version": "settings.v1"},
        })
    return candidates[:limit]


def setting_scan_extraction_mode(value: str | None) -> str:
    mode = str(value or "script").strip().lower()
    return "ai" if mode == "ai" else "script"


def ai_enhance_setting_scan_candidates(project: dict, candidates: list[dict], limit: int, progress_callback=None) -> tuple[list[dict], dict]:
    enhancement = {
        "requested": True,
        "used_count": 0,
        "error_count": 0,
        "errors": [],
    }
    output: list[dict] = []
    project_title = str(project.get("title") or project.get("slug") or "当前小说")
    scoped_candidates = candidates[:max(0, limit)]
    total = len(scoped_candidates)
    for index, candidate in enumerate(scoped_candidates, start=1):
        if (candidate.get("raw") or {}).get("source") == "ai_candidate_discovery":
            output.append(candidate)
            if progress_callback:
                progress_callback(index, total, f"已验证：{candidate.get('name') or f'候选 {index}'}")
            continue
        if progress_callback:
            progress_callback(index - 1, total, f"AI 增强：{candidate.get('name') or f'候选 {index}'}")
        setting = {
            **candidate,
            "project_title": project_title,
        }
        try:
            enhanced, item_enhancement = ai_enhance_setting_candidate(setting, candidate)
            if item_enhancement.get("used"):
                enhancement["used_count"] += 1
            else:
                enhancement["error_count"] += 1
                if item_enhancement.get("error"):
                    enhancement["errors"].append({
                        "name": candidate.get("name") or "",
                        "error": str(item_enhancement.get("error") or ""),
                    })
            output.append(enhanced)
        except Exception as exc:
            enhancement["error_count"] += 1
            enhancement["errors"].append({
                "name": candidate.get("name") or "",
                "error": str(exc),
            })
            output.append(candidate)
        if progress_callback:
            progress_callback(index, total, f"已增强：{candidate.get('name') or f'候选 {index}'}")
    if len(candidates) > limit:
        output.extend(candidates[limit:])
    return output, enhancement


def suggest_settings_api(slug: str, payload: dict) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    instruction = str(payload.get("instruction") or "").strip()
    limit = int(payload.get("limit") or 12)
    candidates = suggest_setting_candidates_from_instruction(project, instruction, limit=max(1, min(limit, 20)))
    return {
        "ok": True,
        "project": {"slug": project.get("slug", ""), "title": project.get("title", "")},
        "instruction": instruction,
        "items": candidates,
        "summary": summarize_settings(candidates),
        "message": f"已找到 {len(candidates)} 条候选设定，请选择后人工审核保存。",
    }


def scan_settings_api(slug: str, payload: dict, progress_callback=None) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    limit = int(payload.get("limit") or 80)
    extraction_mode = setting_scan_extraction_mode(payload.get("extraction_mode"))
    existing = db.list_setting_items(database_url(), project["slug"])
    chapters = db.list_chapters(database_url(), project["slug"])
    candidates = scan_setting_candidates(project, limit=max(2, limit), chapters=chapters)
    enhancement = {
        "requested": extraction_mode == "ai",
        "used_count": 0,
        "error_count": 0,
        "errors": [],
    }
    if extraction_mode == "ai":
        discovered, discovery = ai_discover_setting_candidates(
            project,
            chapters,
            limit=max(0, max(2, limit) - len(candidates)),
            progress_callback=progress_callback,
        )
        candidates = merge_setting_candidates(candidates, discovered, max(2, limit))
        candidates, item_enhancement = ai_enhance_setting_scan_candidates(project, candidates, limit=max(2, limit), progress_callback=progress_callback)
        enhancement = {
            "requested": True,
            "used_count": int(discovery.get("used_count") or 0) + int(item_enhancement.get("used_count") or 0),
            "error_count": int(discovery.get("error_count") or 0) + int(item_enhancement.get("error_count") or 0),
            "errors": [*(discovery.get("errors") or []), *(item_enhancement.get("errors") or [])],
            "discovered_count": int(discovery.get("discovered_count") or 0),
            "discovery_calls": int(discovery.get("used_count") or 0),
        }
    saved = []
    for item in candidates:
        saved.append(db.upsert_setting_item(database_url(), project["slug"], item))
    report = build_setting_scan_report(existing, candidates, saved, enhancement)
    db.add_review(database_url(), project["slug"], {
        "target_type": "setting_scan",
        "target_id": project["slug"],
        "action": "scan:ai" if extraction_mode == "ai" else "scan",
        "comment": f"生成 {len(saved)} 条待审核小说设定。模式：{'AI 增强' if extraction_mode == 'ai' else '脚本扫描'}。",
        "after_data": {
            "count": len(saved),
            "extraction_mode": extraction_mode,
            "types": summarize_settings(saved).get("by_type", {}),
            "report": report,
        },
    })
    return {
        "ok": True,
        "message": f"已生成 {len(saved)} 条待审核小说设定",
        "extraction_mode": extraction_mode,
        "enhancement": enhancement,
        "items": saved,
        "summary": summarize_settings(saved),
        "report": report,
    }


def scan_settings_preview_api(slug: str, query: dict | None = None) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    query = query or {}
    extraction_mode = setting_scan_extraction_mode(
        (query.get("extraction_mode") or ["script"])[0] if isinstance(query.get("extraction_mode"), list)
        else query.get("extraction_mode")
    )
    chapters = db.list_chapters(database_url(), project["slug"])
    existing = db.list_setting_items(database_url(), project["slug"])
    locked = [item for item in existing if item.get("locked")]
    pending = [item for item in existing if item.get("review_status") in {"draft", "pending_review", "needs_work"}]
    settings = settings_summary()
    return {
        "ok": True,
        "project": {"slug": project.get("slug", ""), "title": project.get("title", "")},
        "chapter_count": len(chapters),
        "existing_settings": len(existing),
        "locked_settings": len(locked),
        "pending_settings": len(pending),
        "model": {
            "name": settings.get("models", {}).get("novel_model", ""),
            "source": settings.get("models", {}).get("sources", {}).get("novel_model", "global"),
            "configured": bool(settings.get("models", {}).get("novel_model")),
        },
        "mode": "ai_enhanced_candidates_v1" if extraction_mode == "ai" else "deterministic_candidates_v1",
        "extraction_mode": extraction_mode,
        "estimated_candidates": min(80, max(2, len({str(item.get("volume") or "").strip() for item in chapters if item.get("volume")}) + 2)),
        "warnings": [
            "当前版本会生成待审核候选设定，不会自动锁定。",
            "已锁定设定不会被改成待审核。",
            "AI 增强会调用小说处理模型，可能耗时较长并消耗 API。" if extraction_mode == "ai" else "脚本扫描速度较快，可后续对单条设定再使用 AI 增强。",
        ],
    }


def run_inline_job(job_id: str, worker) -> None:
    with JOB_LOCK:
        live = JOBS.get(job_id)
        if live:
            live["status"] = "running"
            live["progress"] = job_progress_state(total=1, current=live.get("label") or "任务运行中")
            db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)
    try:
        result = worker()
        status = "passed" if result.get("ok", True) else "failed"
        exit_code = 0 if status == "passed" else 1
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        status = "failed"
        exit_code = 1
        diagnostics = {
            "domain": "setting_scan",
            "title": "全书扫描失败",
            "issues": [{
                "type": "setting_scan_failed",
                "severity": "error",
                "message": str(exc),
                "action": "查看任务详情后重试，必要时先检查小说处理模型和数据库连接。",
                "retry_hint": "可重试",
            }],
        }
    with JOB_LOCK:
        live = JOBS.get(job_id)
        if live:
            live.update({
                "status": status,
                "finished": datetime.now().isoformat(timespec="seconds"),
                "result": result,
                "exit_code": exit_code,
                "diagnostics": diagnostics,
                "stdout_tail": json.dumps(result, ensure_ascii=False, indent=2)[:12000],
                "stderr_tail": "" if status == "passed" else str(result.get("error") or ""),
                "progress": job_progress_state(total=1, completed=1 if status == "passed" else 0, failed=0 if status == "passed" else 1, current="已完成" if status == "passed" else "失败"),
            })
            db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)


def update_inline_job_progress(job_id: str, completed: int, total: int, current: str) -> None:
    with JOB_LOCK:
        live = JOBS.get(job_id)
        if not live:
            return
        live["progress"] = job_progress_state(
            total=max(1, int(total or 1)),
            completed=max(0, int(completed or 0)),
            failed=0,
            current=current or live.get("label") or "任务运行中",
        )
        db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)


def start_setting_scan_job(slug: str, payload: dict) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    if not payload.get("confirmed"):
        raise ValueError("全书扫描需要二次确认。请先预览影响范围，再确认启动。")
    limit = int(payload.get("limit") or 80)
    extraction_mode = setting_scan_extraction_mode(payload.get("extraction_mode"))
    job_id = f"{int(time.time())}-setting-scan"
    job = {
        "id": job_id,
        "stage": "setting_scan",
        "label": "全书设定扫描（AI增强）" if extraction_mode == "ai" else "全书设定扫描",
        "project_slug": project.get("slug", ""),
        "project_title": project.get("title", ""),
        "status": "queued",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": ["internal", "scan_settings_api", project.get("slug", ""), f"limit={limit}", f"mode={extraction_mode}"],
        "result_path": "",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "progress": job_progress_state(total=1, current="等待 AI 增强扫描" if extraction_mode == "ai" else "等待扫描"),
        "effective_config": {
            "project_slug": project.get("slug", ""),
            "sources": effective_config_sources(project),
            "text_model": effective_config(project).get("COMIC_PIPELINE_TEXT_MODEL", ""),
            "image_model": effective_config(project).get("COMIC_PIPELINE_IMAGE_MODEL", ""),
            "output_root": effective_config(project).get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
        },
        "retry_payload": {
            "limit": limit,
            "confirmed": True,
            "extraction_mode": extraction_mode,
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project.get("slug", ""), job)
    thread = threading.Thread(
        target=run_inline_job,
        args=(job_id, lambda: scan_settings_api(
            project.get("slug", ""),
            {"limit": limit, "extraction_mode": extraction_mode},
            progress_callback=lambda completed, total, current: update_inline_job_progress(job_id, completed, total, current),
        )),
        daemon=True,
    )
    thread.start()
    return job


def clean_setting_payload(payload: dict) -> dict:
    def list_value(value):
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def int_list(value):
        output = []
        for item in list_value(value):
            try:
                number = int(item)
            except Exception:
                continue
            if number > 0 and number not in output:
                output.append(number)
        return output

    first_chapter = payload.get("first_chapter_number")
    try:
        first_chapter = int(first_chapter) if str(first_chapter or "").strip() else None
    except Exception:
        first_chapter = None
    return {
        "item_type": str(payload.get("item_type") or "world_rule").strip(),
        "name": str(payload.get("name") or "").strip(),
        "aliases": list_value(payload.get("aliases")),
        "description": str(payload.get("description") or "").strip(),
        "first_chapter_number": first_chapter,
        "chapter_numbers": int_list(payload.get("chapter_numbers")),
        "visual_prompt": str(payload.get("visual_prompt") or "").strip(),
        "negative_prompt": str(payload.get("negative_prompt") or "").strip(),
        "relations": payload.get("relations") if isinstance(payload.get("relations"), dict) else {},
        "source_evidence": payload.get("source_evidence") if isinstance(payload.get("source_evidence"), list) else [],
        "importance": str(payload.get("importance") or "normal").strip(),
        "review_status": str(payload.get("review_status") or "pending_review").strip(),
        "locked": bool(payload.get("locked")),
        "raw": payload.get("raw") if isinstance(payload.get("raw"), dict) else {"source": "console"},
    }


def setting_review_relevant_changed(before: dict, after: dict) -> bool:
    fields = [
        "item_type",
        "name",
        "aliases",
        "description",
        "first_chapter_number",
        "chapter_numbers",
        "visual_prompt",
        "negative_prompt",
        "relations",
        "source_evidence",
        "importance",
        "raw",
    ]
    return any((before.get(field) or None) != (after.get(field) or None) for field in fields)


def create_setting_api(slug: str, payload: dict) -> dict:
    ensure_database()
    project = project_by_slug(slug)
    item = clean_setting_payload(payload)
    if not item["name"]:
        raise ValueError("设定名称不能为空")
    saved = db.upsert_setting_item(database_url(), project["slug"], item)
    db.add_review(database_url(), project["slug"], {
        "target_type": "setting",
        "target_id": saved["id"],
        "action": "create",
        "comment": "人工新增设定条目",
        "after_data": saved,
    })
    return {"ok": True, "item": saved}


def update_setting_api(setting_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_setting_item(database_url(), setting_id)
    if not before:
        raise ValueError("设定条目不存在")
    item = clean_setting_payload({**before, **payload})
    if not item["name"]:
        raise ValueError("设定名称不能为空")
    if setting_review_relevant_changed(before, item) and before.get("review_status") == "approved":
        item["review_status"] = "pending_review"
        item["locked"] = False
    saved = db.update_setting_item(database_url(), setting_id, item)
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "setting",
        "target_id": saved["id"],
        "action": "update",
        "comment": str(payload.get("comment") or "人工编辑设定条目"),
        "before_data": before,
        "after_data": saved,
    })
    return {"ok": True, "item": saved}


def review_setting_api(setting_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_setting_item(database_url(), setting_id)
    if not before:
        raise ValueError("设定条目不存在")
    action = str(payload.get("action") or "approve").strip()
    status = {
        "approve": "approved",
        "reject": "rejected",
        "needs_work": "needs_work",
        "pending": "pending_review",
    }.get(action, action)
    saved = db.update_setting_item(database_url(), setting_id, {"review_status": status})
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "setting",
        "target_id": saved["id"],
        "action": f"review:{status}",
        "comment": str(payload.get("comment") or ""),
        "before_data": before,
        "after_data": saved,
    })
    return {"ok": True, "item": saved}


def lock_setting_api(setting_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_setting_item(database_url(), setting_id)
    if not before:
        raise ValueError("设定条目不存在")
    locked = bool(payload.get("locked", True))
    updates = {"locked": locked}
    if locked and before.get("review_status") in {"draft", "pending_review", "needs_work"}:
        updates["review_status"] = "approved"
    saved = db.update_setting_item(database_url(), setting_id, updates)
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "setting",
        "target_id": saved["id"],
        "action": "lock" if locked else "unlock",
        "comment": str(payload.get("comment") or ""),
        "before_data": before,
        "after_data": saved,
    })
    return {"ok": True, "item": saved}


def update_breakdown_api(breakdown_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_chapter_breakdown_by_id(database_url(), breakdown_id)
    if not before:
        raise ValueError("章节拆解不存在")
    raw = dict(before.get("raw") or {})
    if "editor_note" in payload:
        raw["editor_note"] = str(payload.get("editor_note") or "").strip()
    if "summary_note" in payload:
        raw["summary_note"] = str(payload.get("summary_note") or "").strip()
    page_edits = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    updates = {
        "raw": raw,
        "status": str(payload.get("status") or before.get("status") or "draft_ready"),
        "review_status": str(payload.get("review_status") or before.get("review_status") or "pending_review"),
    }
    if page_edits:
        project = db.get_project(database_url(), before["project_slug"])
        if not project:
            raise ValueError("章节拆解所属小说不存在")
        plan_path = project_episode_plan_path(int(before.get("chapter_number") or 0), project)
        plan = read_optional_json(plan_path)
        if not isinstance(plan, dict):
            raise ValueError("章节计划文件不存在或无法读取")
        edited_plan = apply_breakdown_page_edits(plan, page_edits)
        plan_path.write_text(json.dumps(edited_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        edited_breakdown = apply_breakdown_page_edits({"pages": before.get("pages") or []}, page_edits)
        settings = db.list_setting_items(database_url(), before["project_slug"])
        updates.update({
            "pages": edited_breakdown["pages"],
            "panels": flatten_panels(edited_breakdown["pages"]),
            "referenced_setting_ids": infer_referenced_setting_ids(
                int(before.get("chapter_number") or 0),
                edited_breakdown["pages"],
                settings,
                before.get("referenced_setting_ids") or [],
            ),
            "status": "close_reading_refined_needs_review",
            "review_status": "pending_review",
        })
    saved = db.update_chapter_breakdown(database_url(), breakdown_id, updates)
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "chapter_breakdown",
        "target_id": saved["id"],
        "action": "update",
        "comment": str(payload.get("comment") or "人工编辑章节拆解备注"),
        "before_data": before,
        "after_data": saved,
    })
    approvals = None
    if page_edits and saved.get("project_slug") == active_project()["slug"]:
        approvals = set_episode_approval_gate(
            int(saved.get("chapter_number") or 0),
            "draft",
            False,
            validate=False,
        )
    return {"ok": True, "breakdown": saved, "approvals": approvals}


def apply_breakdown_page_edits(plan: dict, edits: list[dict]) -> dict:
    updated = json.loads(json.dumps(plan, ensure_ascii=False))
    pages = updated.get("pages") if isinstance(updated.get("pages"), list) else []
    page_index = {str(page.get("page_id") or ""): page for page in pages if isinstance(page, dict)}
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        page_id = str(edit.get("page_id") or "").strip()
        page = page_index.get(page_id)
        if not page:
            raise ValueError(f"拆解页面不存在：{page_id or '未指定'}")
        for field in ("summary", "layout_style", "reading_flow", "visual_priority"):
            if field in edit:
                page[field] = str(edit.get(field) or "").strip()
        if isinstance(edit.get("director"), dict):
            director = dict(page.get("director") or {})
            for field in (
                "page_rhythm",
                "emotional_arc",
                "layout_style",
                "visual_priority",
                "lettering_strategy",
                "page_turn_hook",
                "camera_flow",
            ):
                if field not in edit["director"]:
                    continue
                value = edit["director"].get(field)
                if field == "camera_flow" and isinstance(value, str):
                    value = [item.strip() for item in re.split(r"[；;\n]+", value) if item.strip()]
                director[field] = value if isinstance(value, list) else str(value or "").strip()
            page["director"] = director
        panel_index = {
            panel_id_for(page_id, panel, index): panel
            for index, panel in enumerate(page.get("panels") or [])
            if isinstance(panel, dict)
        }
        for panel_edit in edit.get("panels") or []:
            if not isinstance(panel_edit, dict):
                continue
            panel_id = str(panel_edit.get("panel_id") or "").strip()
            panel = panel_index.get(panel_id)
            if not panel:
                raise ValueError(f"拆解分镜不存在：{panel_id or '未指定'}")
            for field in ("title", "prompt", "panel_role", "shot_type", "visual_priority", "camera_direction"):
                if field in panel_edit:
                    panel[field] = str(panel_edit.get(field) or "").strip()
            panel["close_reading_refined"] = True
        page["status"] = "close_reading_refined_needs_review"
        page["close_reading_required"] = False
        page["close_reading_refined"] = True
        page["close_reading_updated"] = datetime.now().isoformat(timespec="seconds")
    return updated


def review_breakdown_api(breakdown_id: int, payload: dict) -> dict:
    ensure_database()
    before = db.get_chapter_breakdown_by_id(database_url(), breakdown_id)
    if not before:
        raise ValueError("章节拆解不存在")
    action = str(payload.get("action") or "approve").strip()
    status = {
        "approve": "approved",
        "reject": "rejected",
        "needs_work": "needs_work",
        "pending": "pending_review",
    }.get(action, action)
    saved = db.update_chapter_breakdown(database_url(), breakdown_id, {
        "review_status": status,
        "status": "reviewed" if status == "approved" else before.get("status", "draft_ready"),
    })
    db.add_review(database_url(), saved["project_slug"], {
        "target_type": "chapter_breakdown",
        "target_id": saved["id"],
        "action": f"review:{status}",
        "comment": str(payload.get("comment") or ""),
        "before_data": before,
        "after_data": saved,
    })
    approvals = None
    if saved.get("project_slug") == active_project()["slug"]:
        episode_number = int(saved.get("chapter_number") or 0)
        if episode_number:
            approvals = set_episode_approval_gate(
                episode_number,
                "draft",
                status == "approved",
                validate=False,
            )
    return {"ok": True, "breakdown": saved, "approvals": approvals}


def validate_backup_member_name(name: str) -> str:
    value = str(name or "")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
    ):
        raise ValueError(f"备份包含不安全路径：{value}")
    return path.as_posix()


def backup_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_backup_data(slug: str) -> dict:
    project = db.get_project(database_url(), slug)
    if not project:
        raise ValueError("小说项目不存在")
    approvals = db.execute(
        database_url(),
        """
        SELECT project_slug, episode_number, draft, assets, generation, qa, next_episode,
               raw, updated_at::text AS updated
        FROM comic_episode_approvals WHERE project_slug = %s ORDER BY episode_number
        """,
        (slug,),
        fetch="all",
    )
    job_rows = db.execute(
        database_url(),
        """
        SELECT job_id, project_slug, stage, label, status, result_path,
               raw, started_at::text AS started_at, finished_at::text AS finished_at
        FROM comic_jobs WHERE project_slug = %s ORDER BY started_at
        """,
        (slug,),
        fetch="all",
    )
    jobs = []
    for row in job_rows:
        raw = dict(row.get("raw") or {})
        raw.setdefault("id", row.get("job_id") or "")
        raw.setdefault("project_slug", slug)
        raw.setdefault("stage", row.get("stage") or "")
        raw.setdefault("label", row.get("label") or "")
        raw.setdefault("status", row.get("status") or "")
        raw.setdefault("result_path", row.get("result_path") or "")
        raw.setdefault("started", row.get("started_at") or "")
        raw.setdefault("finished", row.get("finished_at") or "")
        jobs.append(raw)
    reviews = db.execute(
        database_url(),
        """
        SELECT id, project_slug, target_type, target_id, action, comment,
               before_data, after_data, created_at::text
        FROM comic_reviews WHERE project_slug = %s ORDER BY id
        """,
        (slug,),
        fetch="all",
    )
    return {
        "project": project,
        "chapters": db.list_chapters(database_url(), slug),
        "episodes": db.list_episodes(database_url(), slug),
        "approvals": approvals,
        "jobs": jobs,
        "settings": db.list_setting_items(database_url(), slug),
        "breakdowns": db.list_chapter_breakdowns(database_url(), slug),
        "assets": db.list_visual_assets(database_url(), slug),
        "outputs": db.list_generated_outputs(database_url(), slug),
        "versions": db.list_output_versions(database_url(), slug),
        "reviews": reviews,
    }


def create_project_backup_archive(slug: str, include_media: bool = False) -> dict:
    data = project_backup_data(slug)
    project = data["project"]
    source_slug = project["slug"]
    file_specs: list[dict] = []
    by_source: dict[str, dict] = {}

    def add_file(source_value: str, archive_name: str, kind: str, reference: dict | None = None) -> None:
        source = Path(str(source_value or ""))
        if not source.is_file():
            return
        resolved = str(source.resolve())
        spec = by_source.get(resolved)
        if not spec:
            normalized = validate_backup_member_name(archive_name)
            spec = {"source": source, "archive_path": normalized, "kind": kind, "references": []}
            by_source[resolved] = spec
            file_specs.append(spec)
        if reference and reference not in spec["references"]:
            spec["references"].append(reference)

    manifest_root = Path(str(project.get("manifest_dir") or ""))
    if manifest_root.is_dir():
        for path in sorted(item for item in manifest_root.rglob("*") if item.is_file()):
            relative = path.relative_to(manifest_root).as_posix()
            add_file(str(path), f"files/manifests/{relative}", "manifest")

    novel_path = Path(str(project.get("novel_path") or ""))
    add_file(
        str(novel_path),
        f"files/novel/{safe_stem(novel_path.stem)}{novel_path.suffix.lower() or '.txt'}",
        "novel",
        {"table": "project", "id": source_slug, "field": "novel_path"},
    )

    def add_referenced_file(table: str, row_id, field: str, source_value: str, kind: str, fallback_name: str) -> None:
        source = Path(str(source_value or ""))
        if not source.is_file():
            return
        archive_name = fallback_name
        if manifest_root.is_dir():
            try:
                archive_name = f"files/manifests/{source.resolve().relative_to(manifest_root.resolve()).as_posix()}"
            except ValueError:
                pass
        add_file(str(source), archive_name, kind, {"table": table, "id": row_id, "field": field})

    add_referenced_file("project", source_slug, "chapter_index_path", project.get("chapter_index_path", ""), "manifest", "files/project/chapter_index.json")
    add_referenced_file("project", source_slug, "series_plan_path", project.get("series_plan_path", ""), "manifest", "files/project/series_plan.json")
    for episode in data["episodes"]:
        number = int(episode.get("episode_number") or 0)
        add_referenced_file("episodes", number, "episode_plan_path", episode.get("episode_plan_path", ""), "manifest", f"files/project/episodes/{number:04d}.json")
    for job in data["jobs"]:
        job_id = str(job.get("id") or "")
        for field in ("result_path", "generation_context_path"):
            add_referenced_file("jobs", job_id, field, job.get(field, ""), "manifest", f"files/project/jobs/{safe_stem(job_id)}_{field}.json")

    if include_media:
        media_groups = [
            ("assets", data["assets"], ("file_path", "thumbnail_path")),
            ("outputs", data["outputs"], ("file_path", "thumbnail_path")),
            ("versions", data["versions"], ("file_path", "thumbnail_path")),
        ]
        for table, rows, fields in media_groups:
            for row in rows:
                row_id = row.get("id")
                for field in fields:
                    source = Path(str(row.get(field) or ""))
                    if source.is_file():
                        add_file(
                            str(source),
                            f"files/media/{table}/{row_id}/{safe_stem(source.stem)}{source.suffix.lower()}",
                            "media",
                            {"table": table, "id": row_id, "field": field},
                        )

    if len(file_specs) > MAX_BACKUP_FILES:
        raise ValueError(f"备份文件数量超过上限：{MAX_BACKUP_FILES}")
    data_bytes = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    checksums = {"data.json": hashlib.sha256(data_bytes).hexdigest()}
    files = []
    total_file_bytes = 0
    for spec in file_specs:
        size = spec["source"].stat().st_size
        total_file_bytes += size
        checksum = backup_sha256(spec["source"])
        checksums[spec["archive_path"]] = checksum
        files.append({
            "archive_path": spec["archive_path"],
            "kind": spec["kind"],
            "size": size,
            "sha256": checksum,
            "references": spec["references"],
        })
    manifest = {
        "schema_version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source_project": {"slug": source_slug, "title": project.get("title") or source_slug},
        "include_media": bool(include_media),
        "record_counts": {key: len(value) for key, value in data.items() if isinstance(value, list)},
        "file_count": len(files),
        "file_bytes": total_file_bytes,
        "checksums": checksums,
        "files": files,
    }
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_stem(source_slug)}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    target = BACKUPS_DIR / filename
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("data.json", data_bytes)
        for spec in file_specs:
            archive.write(spec["source"], spec["archive_path"])
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return {
        "ok": True,
        "filename": filename,
        "path": str(target),
        "download_url": f"/backup-files/{quote(filename)}",
        "size": target.stat().st_size,
        "manifest": manifest,
    }


def read_project_backup_archive(raw: bytes) -> dict:
    if not raw:
        raise ValueError("备份文件为空")
    if len(raw) > MAX_BACKUP_ARCHIVE_BYTES:
        raise ValueError("备份文件超过 512MB 上传上限")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("备份文件不是有效的 ZIP 归档") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_BACKUP_FILES:
            raise ValueError(f"备份文件数量超过上限：{MAX_BACKUP_FILES}")
        total_size = 0
        names = set()
        for info in infos:
            name = validate_backup_member_name(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"备份不允许符号链接：{name}")
            total_size += int(info.file_size or 0)
            if total_size > MAX_BACKUP_EXPANDED_BYTES:
                raise ValueError("备份解压后超过 2GB 安全上限")
            names.add(name)
        if "manifest.json" not in names or "data.json" not in names:
            raise ValueError("备份缺少 manifest.json 或 data.json")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            data = json.loads(archive.read("data.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("备份元数据不是有效的 UTF-8 JSON") from exc
        if int(manifest.get("schema_version") or 0) != 1:
            raise ValueError("不支持的备份 schema 版本")
        checksums = manifest.get("checksums")
        if not isinstance(checksums, dict):
            raise ValueError("备份缺少校验和清单")
        expected_members = names - {"manifest.json"}
        if set(checksums) != expected_members:
            raise ValueError("备份校验和清单与文件列表不一致")
        for name, expected in checksums.items():
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != str(expected):
                raise ValueError(f"备份文件校验和不一致：{name}")
        listed_files = manifest.get("files")
        if not isinstance(listed_files, list):
            raise ValueError("备份文件映射格式无效")
        for item in listed_files:
            archive_path = validate_backup_member_name(item.get("archive_path", ""))
            if archive_path not in names or archive_path not in checksums:
                raise ValueError(f"备份文件映射缺少成员：{archive_path}")
        return {"manifest": manifest, "data": data, "raw": raw}


def decode_backup_upload(content_base64: str) -> bytes:
    value = str(content_base64 or "")
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("备份文件内容不是有效的 base64 数据") from exc
    if len(raw) > MAX_BACKUP_ARCHIVE_BYTES:
        raise ValueError("备份文件超过 512MB 上传上限")
    return raw


def import_project_backup_api(payload: dict) -> dict:
    requested_slug = str(payload.get("target_slug") or "").strip()
    if not requested_slug:
        raise ValueError("请输入新项目标识")
    target_slug = slugify(requested_slug)
    if db.get_project(database_url(), target_slug):
        raise ValueError(f"项目标识已存在：{target_slug}，导入不会覆盖已有项目")

    parsed = read_project_backup_archive(decode_backup_upload(payload.get("content_base64") or ""))
    manifest = parsed["manifest"]
    data = parsed["data"]
    source_project = data.get("project") if isinstance(data.get("project"), dict) else {}
    source_slug = str(source_project.get("slug") or (manifest.get("source_project") or {}).get("slug") or "")
    if not source_slug:
        raise ValueError("备份缺少源项目标识")
    target_title = str(payload.get("target_title") or f"{source_project.get('title') or source_slug}（导入）").strip()
    target_manifest_dir = PROJECT_MANIFESTS_ROOT / target_slug
    target_output_dir = Path(runtime_config().get("COMIC_PIPELINE_OUTPUT_ROOT") or (ROOT / "output")) / "Imported" / target_slug
    archive_targets: dict[str, Path] = {}
    novel_targets = []
    for item in manifest.get("files") or []:
        archive_path = validate_backup_member_name(item.get("archive_path", ""))
        relative = PurePosixPath(archive_path)
        if archive_path.startswith("files/novel/"):
            suffix = Path(relative.name).suffix.lower() or ".txt"
            target = NOVELS_DIR / f"{target_slug}{suffix}"
            novel_targets.append(target)
        elif archive_path.startswith("files/manifests/"):
            target = target_manifest_dir.joinpath(*relative.parts[2:])
        elif archive_path.startswith("files/project/"):
            target = target_manifest_dir.joinpath("supplemental", *relative.parts[2:])
        elif archive_path.startswith("files/media/"):
            target = target_output_dir.joinpath(*relative.parts[2:])
        else:
            raise ValueError(f"备份包含未知文件区域：{archive_path}")
        archive_targets[archive_path] = target
    if len(set(novel_targets)) != 1:
        raise ValueError("备份必须包含且只能包含一个小说源文件")
    if target_manifest_dir.exists() or target_output_dir.exists() or novel_targets[0].exists():
        raise ValueError("目标项目目录已存在，导入不会覆盖现有文件")

    references = {}
    for item in manifest.get("files") or []:
        archive_path = item["archive_path"]
        target = archive_targets[archive_path]
        for reference in item.get("references") or []:
            key = (str(reference.get("table") or ""), str(reference.get("id") or ""), str(reference.get("field") or ""))
            references[key] = str(target)

    def referenced_path(table: str, row_id, field: str, fallback: str = "") -> str:
        return references.get((table, str(row_id), field), fallback)

    written_files = []
    created_project = False
    try:
        with zipfile.ZipFile(io.BytesIO(parsed["raw"]), "r") as archive:
            for archive_path, target in archive_targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(archive_path) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
                written_files.append(target)

        project = db.upsert_project(database_url(), {
            "slug": target_slug,
            "title": target_title,
            "novel_path": referenced_path("project", source_slug, "novel_path", str(novel_targets[0])),
            "manifest_dir": str(target_manifest_dir),
            "chapter_index_path": referenced_path("project", source_slug, "chapter_index_path", str(target_manifest_dir / f"{target_slug}_chapter_index.json")),
            "series_plan_path": referenced_path("project", source_slug, "series_plan_path", str(target_manifest_dir / f"{target_slug}_comic_series_plan.json")),
            "legacy": False,
            "status": "active",
            "project_config": source_project.get("project_config") if isinstance(source_project.get("project_config"), dict) else {},
        })
        created_project = True

        chapters = []
        for row in data.get("chapters") or []:
            chapters.append({
                **(row.get("raw") or {}),
                "volume": row.get("volume") or "",
                "title": row.get("title") or "",
                "line_number": int(row.get("line_number") or 1),
            })
        db.replace_project_chapters(database_url(), target_slug, chapters)
        episodes = []
        for row in data.get("episodes") or []:
            number = int(row.get("episode_number") or 0)
            episodes.append({
                **(row.get("raw") or {}),
                "episode_id": row.get("episode_code") or f"EP{number:03d}",
                "chapter_title": row.get("title") or "",
                "status": row.get("status") or "needs_close_reading",
                "planned_pages": int(row.get("planned_pages") or 0),
                "planned_panels": int(row.get("planned_panels") or 0),
                "episode_plan_path": referenced_path("episodes", number, "episode_plan_path", ""),
            })
        db.replace_project_episodes(database_url(), target_slug, episodes)

        job_id_map = {
            str(row.get("id") or row.get("job_id") or ""): f"import-{target_slug}-{safe_stem(str(row.get('id') or row.get('job_id') or 'job'))}"
            for row in data.get("jobs") or []
        }
        setting_id_map = {}
        for row in data.get("settings") or []:
            old_id = int(row.get("id") or 0)
            saved = db.upsert_setting_item(database_url(), target_slug, {**row, "project_slug": target_slug})
            setting_id_map[old_id] = int(saved["id"])
        breakdown_id_map = {}
        for row in data.get("breakdowns") or []:
            old_id = int(row.get("id") or 0)
            saved = db.upsert_chapter_breakdown(database_url(), target_slug, int(row.get("chapter_number") or 0), {
                **row,
                "referenced_setting_ids": [setting_id_map.get(int(item), int(item)) for item in (row.get("referenced_setting_ids") or [])],
            })
            breakdown_id_map[old_id] = int(saved["id"])
        asset_id_map = {}
        for row in data.get("assets") or []:
            old_id = int(row.get("id") or 0)
            saved = db.upsert_visual_asset(database_url(), target_slug, {
                **row,
                "setting_item_id": setting_id_map.get(int(row.get("setting_item_id") or 0)) or None,
                "file_path": referenced_path("assets", old_id, "file_path", f"missing://{target_slug}/assets/{old_id}"),
                "thumbnail_path": referenced_path("assets", old_id, "thumbnail_path", ""),
                "source_job_id": job_id_map.get(str(row.get("source_job_id") or ""), ""),
            })
            asset_id_map[old_id] = int(saved["id"])
        output_id_map = {}
        for row in data.get("outputs") or []:
            old_id = int(row.get("id") or 0)
            saved = db.upsert_generated_output(database_url(), target_slug, {
                **row,
                "job_id": job_id_map.get(str(row.get("job_id") or ""), ""),
                "file_path": referenced_path("outputs", old_id, "file_path", f"missing://{target_slug}/outputs/{old_id}"),
                "thumbnail_path": referenced_path("outputs", old_id, "thumbnail_path", ""),
            })
            output_id_map[old_id] = int(saved["id"])
        for row in data.get("versions") or []:
            old_id = int(row.get("id") or 0)
            db.add_output_version(database_url(), target_slug, {
                **row,
                "output_id": output_id_map.get(int(row.get("output_id") or 0)) or None,
                "file_path": referenced_path("versions", old_id, "file_path", f"missing://{target_slug}/versions/{old_id}"),
                "thumbnail_path": referenced_path("versions", old_id, "thumbnail_path", ""),
                "source_job_id": job_id_map.get(str(row.get("source_job_id") or ""), ""),
            })
        for row in data.get("approvals") or []:
            raw = dict(row.get("raw") or {})
            raw.update({key: bool(row.get(key)) for key in ("draft", "assets", "generation", "qa", "next_episode")})
            db.save_approvals(database_url(), target_slug, int(row.get("episode_number") or 0), raw)
        for row in data.get("jobs") or []:
            old_id = str(row.get("id") or row.get("job_id") or "")
            imported = {
                **row,
                "id": job_id_map[old_id],
                "project_slug": target_slug,
                "status": "interrupted" if row.get("status") in {"running", "queued", "starting"} else row.get("status", "interrupted"),
                "result_path": referenced_path("jobs", old_id, "result_path", ""),
                "generation_context_path": referenced_path("jobs", old_id, "generation_context_path", ""),
                "command": [],
                "retry_payload": {},
                "imported_from_job_id": old_id,
            }
            db.save_job(database_url(), target_slug, imported)

        review_maps = {
            "setting": setting_id_map,
            "setting_item": setting_id_map,
            "visual_asset": asset_id_map,
            "chapter_breakdown": breakdown_id_map,
            "generated_output": output_id_map,
        }
        for row in data.get("reviews") or []:
            target_type = str(row.get("target_type") or "")
            target_id = str(row.get("target_id") or "")
            if target_type in review_maps and target_id.isdigit():
                target_id = str(review_maps[target_type].get(int(target_id), target_id))
            db.add_review(database_url(), target_slug, {
                **row,
                "target_id": target_id,
                "comment": row.get("comment") or "",
            })
        return {
            "ok": True,
            "project": project,
            "source_project": manifest.get("source_project") or {},
            "include_media": bool(manifest.get("include_media")),
            "record_counts": manifest.get("record_counts") or {},
            "file_count": len(written_files),
            "message": f"备份已导入为《{target_title}》，项目标识：{target_slug}",
        }
    except Exception:
        if created_project:
            db.execute(database_url(), "DELETE FROM comic_jobs WHERE project_slug = %s", (target_slug,))
            db.execute(database_url(), "DELETE FROM comic_projects WHERE slug = %s", (target_slug,))
        for root in (target_manifest_dir, target_output_dir):
            if root.exists():
                shutil.rmtree(root)
        for novel_target in novel_targets:
            if novel_target.is_file():
                novel_target.unlink()
        raise


def export_project_backup_api(slug: str, payload: dict) -> dict:
    return create_project_backup_archive(slug, bool(payload.get("include_media")))


def set_active_project(payload: dict) -> dict:
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise ValueError("slug is required")
    project = project_by_slug(slug)
    if project.get("slug") != slug:
        raise ValueError(f"project not found: {slug}")
    if project.get("status") == "archived":
        raise ValueError("归档小说不能设为当前项目，请先恢复项目。")
    current = config_snapshot()["config"]
    current["COMIC_PIPELINE_ACTIVE_PROJECT"] = slug
    current["COMIC_PIPELINE_NOVEL_PATH"] = project.get("novel_path", current.get("COMIC_PIPELINE_NOVEL_PATH", ""))
    write_env(CONFIG_PATH, current, PIPELINE_KEYS)
    opened = db.touch_project_opened(database_url(), slug) or project
    return {"ok": True, "active": slug, "project": opened, "config": config_snapshot()}


def update_project_api(slug: str, payload: dict) -> dict:
    ensure_database()
    project = db.get_project(database_url(), slug)
    if not project:
        raise ValueError("小说项目不存在")
    config_payload = payload.get("project_config") if isinstance(payload.get("project_config"), dict) else {}
    if "text_model" in payload:
        config_payload["text_model"] = str(payload.get("text_model") or "").strip()
    if "image_model" in payload:
        config_payload["image_model"] = str(payload.get("image_model") or "").strip()
    if "output_root" in payload:
        config_payload["output_root"] = str(payload.get("output_root") or "").strip()
    updates = {
        "title": str(payload.get("title") or project.get("title") or slug).strip(),
        "status": str(payload.get("status") or project.get("status") or "active").strip(),
        "project_config": config_payload,
    }
    if updates["status"] not in {"active", "archived"}:
        raise ValueError("项目状态只能是 active 或 archived")
    if updates["status"] == "archived" and slug == active_project_slug():
        raise ValueError("当前小说不能直接归档，请先切换到其他小说。")
    saved = db.update_project_metadata(database_url(), slug, updates)
    return {"ok": True, "project": saved}


def archive_project_api(slug: str, payload: dict) -> dict:
    ensure_database()
    project = db.get_project(database_url(), slug)
    if not project:
        raise ValueError("小说项目不存在")
    archived = bool(payload.get("archived", True))
    if archived and slug == active_project_slug():
        raise ValueError("当前小说不能归档，请先切换到其他小说。")
    saved = db.update_project_metadata(database_url(), slug, {
        "status": "archived" if archived else "active",
        "project_config": {},
    })
    return {"ok": True, "project": saved, "archived": archived}


def upsert_project(project: dict) -> dict:
    ensure_database()
    return db.upsert_project(database_url(), project)


def save_uploaded_novel(payload: dict) -> dict:
    filename = str(payload.get("filename") or "").strip()
    content_base64 = str(payload.get("content_base64") or "")
    saved_name = safe_upload_filename(filename)
    data = decode_base64_upload(content_base64)
    NOVELS_DIR.mkdir(parents=True, exist_ok=True)
    target = (NOVELS_DIR / saved_name).resolve()
    target.write_bytes(data)
    return {
        "ok": True,
        "filename": filename,
        "saved_name": saved_name,
        "path": str(target),
        "size": len(data),
    }


def decode_text_preview(path: Path, encoding: str) -> tuple[str, str, str]:
    preferred = [encoding, "utf-8-sig", "utf-8", "gb18030"]
    seen = set()
    errors = []
    for name in preferred:
        codec = str(name or "").strip()
        if not codec or codec in seen:
            continue
        seen.add(codec)
        try:
            return path.read_text(encoding=codec), codec, ""
        except UnicodeDecodeError as exc:
            errors.append(f"{codec}: {exc.reason}")
        except LookupError:
            errors.append(f"{codec}: 编码不存在")
    text = path.read_text(encoding=encoding or "utf-8", errors="replace")
    return text, str(encoding or "utf-8"), "文本包含无法按当前编码识别的字符，预览已使用替换字符。"


def import_duplicate_state(slug: str) -> dict:
    existing = next((item for item in read_projects() if item.get("slug") == slug), None)
    if not existing:
        return {
            "exists": False,
            "strategy": "create",
            "strategy_label": "创建新项目",
            "warning": "",
            "existing": None,
        }
    chapters = int(existing.get("chapters") or 0)
    return {
        "exists": True,
        "strategy": "update",
        "strategy_label": "更新已有项目",
        "warning": f"项目标识已存在：将更新《{existing.get('title') or slug}》的小说路径和章节索引，保留已有审核与生成数据。",
        "existing": {
            "slug": existing.get("slug"),
            "title": existing.get("title"),
            "chapters": chapters,
            "episodes": int(existing.get("episodes") or 0),
            "updated": existing.get("updated") or "",
        },
    }


def preview_novel_import(payload: dict) -> dict:
    novel_path = str(payload.get("novel_path") or "").strip()
    if not novel_path:
        raise ValueError("请先选择小说文件")
    novel = Path(novel_path)
    if not novel.is_file():
        raise ValueError(f"小说文件不存在：{novel}")
    encoding = str(payload.get("encoding") or DEFAULTS["COMIC_PIPELINE_ENCODING"]).strip()
    title = str(payload.get("project_title") or novel.stem).strip() or novel.stem
    slug = slugify(str(payload.get("project_slug") or title or novel.stem))
    text, used_encoding, decode_warning = decode_text_preview(novel, encoding)
    lines = text.splitlines()
    chapter_index = build_chapter_index(lines, title)
    used_fallback = False
    if not any(item.get("type") == "chapter" for item in chapter_index):
        chapter_index = fallback_chapter_index(lines, title)
        used_fallback = True
    chapters = [item for item in chapter_index if item.get("type") == "chapter"]
    volumes = [item for item in chapter_index if item.get("type") == "volume"]
    sample = []
    for index, item in enumerate(chapters[:20], start=1):
        sample.append({
            "number": index,
            "title": item.get("title") or f"第{index}章",
            "volume": item.get("volume") or title,
            "line": int(item.get("line") or 1),
        })
    warnings = []
    if used_fallback:
        warnings.append("没有识别到标准章节标题，预览使用兜底分段。建议检查文本格式后再导入。")
    if decode_warning:
        warnings.append(decode_warning)
    if len(chapters) < 2:
        warnings.append("章节数量过少，可能不是完整小说文件或章节标题格式不匹配。")
    duplicate = import_duplicate_state(slug)
    if duplicate.get("warning"):
        warnings.append(duplicate["warning"])
    line_count = len(lines)
    char_count = len(text)
    return {
        "ok": True,
        "project": {
            "title": title,
            "slug": slug,
            "novel_path": str(novel),
        },
        "file": {
            "name": novel.name,
            "path": str(novel),
            "size": novel.stat().st_size,
            "encoding_requested": encoding,
            "encoding_used": used_encoding,
            "line_count": line_count,
            "char_count": char_count,
        },
        "parse": {
            "chapters": len(chapters),
            "volumes": len(volumes),
            "used_fallback": used_fallback,
            "sample": sample,
            "warnings": warnings,
        },
        "duplicate": duplicate,
        "strategies": [
            {
                "value": "create",
                "label": "创建新项目",
                "disabled": bool(duplicate.get("exists")),
                "description": "项目标识不存在时使用，生成新的小说项目、章节索引和初始骨架。",
            },
            {
                "value": "update",
                "label": "更新索引并保留审核",
                "disabled": not bool(duplicate.get("exists")),
                "description": "更新小说路径、章节索引和系列计划；已有章节骨架、审核、素材、生成结果会保留。",
            },
            {
                "value": "refresh_chapters",
                "label": "只刷新章节索引",
                "disabled": not bool(duplicate.get("exists")),
                "description": "只更新小说路径、章节索引和系列计划，不生成或覆盖初始章节骨架。",
            },
            {
                "value": "overwrite",
                "label": "覆盖重建",
                "disabled": True,
                "description": "危险操作：会影响已有章节计划。当前版本暂不开放，请先做备份和独立确认流程。",
            },
        ],
    }


def start_process_novel_job(payload: dict) -> dict:
    novel_path = str(payload.get("novel_path") or "").strip()
    if not novel_path:
        raise ValueError("novel_path is required")
    novel = Path(novel_path)
    if not novel.is_file():
        raise ValueError(f"小说文件不存在：{novel}")
    title = str(payload.get("project_title") or novel.stem).strip()
    slug = slugify(str(payload.get("project_slug") or title or novel.stem))
    import_strategy = str(payload.get("import_strategy") or "").strip()
    duplicate = import_duplicate_state(slug)
    allowed_update_strategies = {"update", "refresh_chapters"}
    if duplicate.get("exists") and import_strategy not in allowed_update_strategies:
        raise ValueError("项目标识已存在。请先预览并选择“更新已有项目”，避免误覆盖。")
    if import_strategy in {"overwrite", "overwrite_keep_reviews"}:
        raise ValueError("覆盖重建策略暂未开放。请先备份项目，再使用保留审核的更新策略。")
    if slug == DEFAULT_PROJECT_SLUG:
        project_dir = MANIFESTS_DIR
    else:
        project_dir = PROJECT_MANIFESTS_ROOT / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    project = upsert_project({
        "slug": slug,
        "title": title,
        "novel_path": str(novel),
        "manifest_dir": str(project_dir),
        "chapter_index_path": str(project_dir / f"{slug}_chapter_index.json"),
        "series_plan_path": str(project_dir / f"{slug}_comic_series_plan.json"),
        "legacy": slug == DEFAULT_PROJECT_SLUG,
        "updated": datetime.now().isoformat(timespec="seconds"),
    })
    current = config_snapshot()["config"]
    current["COMIC_PIPELINE_ACTIVE_PROJECT"] = slug
    current["COMIC_PIPELINE_NOVEL_PATH"] = str(novel)
    write_env(CONFIG_PATH, current, PIPELINE_KEYS)

    job_id = f"{int(time.time())}-process-novel"
    result_path = project_dir / f"{slug}_novel_process_result.json"
    cmd = [
        "python",
        str(PROCESS_NOVEL_SCRIPT),
        "--novel",
        str(novel),
        "--project-slug",
        slug,
        "--project-title",
        title,
        "--output-dir",
        str(project_dir),
        "--encoding",
        str(payload.get("encoding") or current.get("COMIC_PIPELINE_ENCODING") or DEFAULTS["COMIC_PIPELINE_ENCODING"]),
        "--pages-per-chapter",
        str(int(payload.get("pages_per_chapter") or current.get("COMIC_PIPELINE_DEFAULT_PAGES") or 8)),
        "--panels-per-page",
        str(int(payload.get("panels_per_page") or 4)),
        "--skeleton-count",
        "0" if import_strategy == "refresh_chapters" else str(int(payload.get("skeleton_count") or 3)),
    ]
    if payload.get("force"):
        cmd.append("--force")
    if payload.get("skip_text_model") or import_strategy == "refresh_chapters":
        cmd.append("--skip-text-model")
    job = {
        "id": job_id,
        "stage": "process_novel",
        "label": "处理小说",
        "project_slug": slug,
        "project_title": title,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": cmd,
        "result_path": str(result_path),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "project": project,
        "progress": job_progress_state(current="处理小说"),
        "retry_payload": {
            "project_title": title,
            "project_slug": slug,
            "novel_path": str(novel),
            "encoding": str(payload.get("encoding") or current.get("COMIC_PIPELINE_ENCODING") or DEFAULTS["COMIC_PIPELINE_ENCODING"]),
            "pages_per_chapter": int(payload.get("pages_per_chapter") or current.get("COMIC_PIPELINE_DEFAULT_PAGES") or 8),
            "panels_per_page": int(payload.get("panels_per_page") or 4),
            "skeleton_count": int(payload.get("skeleton_count") or 3),
            "import_strategy": import_strategy or "create",
            "force": bool(payload.get("force")),
            "skip_text_model": bool(payload.get("skip_text_model")),
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), slug, job)
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def start_job(payload: dict) -> dict:
    stage = str(payload.get("stage", "")).strip()
    if stage not in STAGE_MAP:
        raise ValueError(f"Unknown stage: {stage}")
    episode_number = int(payload.get("episode_number") or 3)
    assert_stage_allowed(stage, episode_number)
    project = active_project()
    episode_plan_path = project_episode_plan_path(episode_number, project)
    novel_path = project.get("novel_path") or config_snapshot()["config"].get("COMIC_PIPELINE_NOVEL_PATH", "")
    pages = int(payload.get("pages") or 8)
    max_panels = int(payload.get("max_panels") or 1)
    max_pages = int(payload.get("max_pages") or payload.get("max_batches") or 1)
    if stage == "close_reading":
        max_pages = max(1, int(payload.get("max_pages") or 2))
    force = bool(payload.get("force"))
    dry_run = bool(payload.get("dry_run"))
    allow_draft_warnings = bool(payload.get("allow_draft_warnings", True))
    skeleton = None
    if stage in {"breakdown", "draft_review", "generate", "review"} and not episode_plan_path.is_file():
        skeleton = create_episode_skeleton_plan(project, episode_number, episode_plan_path, pages)
    if stage == "close_reading":
        hydrate_episode_plan_source_excerpts(project, episode_number, episode_plan_path)

    job_id = f"{int(time.time())}-{stage}"
    result_path = project_manifest_dir(project) / f"console_{stage}_episode{episode_number:02d}_{int(time.time())}.json"
    generation_context = build_generation_context_snapshot(project, episode_number) if stage in {"generate", "close_reading"} else {}
    if stage == "close_reading":
        generation_context = add_close_reading_protection_context(project, episode_number, generation_context)
    if stage == "generate":
        hydrate_episode_asset_aliases(project, episode_number, generation_context)
    generation_context_path = write_generation_context_file(generation_context, job_id) if stage in {"generate", "close_reading"} else ""
    if STAGE_MAP[stage].get("custom") == "close_reading":
        cmd = [
            sys.executable,
            str(CLOSE_READING_SCRIPT),
            "--episode-plan",
            str(episode_plan_path),
            "--output",
            str(result_path),
            "--only-missing",
        ]
        if generation_context_path:
            cmd += ["--generation-context", generation_context_path]
        if max_pages > 0:
            cmd += ["--max-pages", str(max_pages)]
    else:
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUN_SCRIPT),
            "-EpisodeNumber",
            str(episode_number),
            "-EpisodePlanPath",
            str(episode_plan_path),
            "-NovelPath",
            str(novel_path),
            "-Pages",
            str(pages),
            "-RunLabel",
            f"console_{stage}",
            "-ResultPath",
            str(result_path),
        ]

        cmd += list(STAGE_MAP[stage].get("args", []))
        if dry_run and "-DryRun" not in cmd:
            cmd.append("-DryRun")
        if force:
            cmd.append("-Force")
        if allow_draft_warnings and "-AllowDraftWarnings" not in cmd:
            cmd.append("-AllowDraftWarnings")
        if STAGE_MAP[stage].get("needs_generation"):
            cmd += ["-MaxPanels", str(max_panels), "-MaxPages", str(max_pages)]
        elif max_panels > 0:
            cmd += ["-MaxPanels", str(max_panels)]
        if generation_context_path:
            cmd += ["-GenerationContextPath", generation_context_path]

    job = {
        "id": job_id,
        "stage": stage,
        "label": STAGE_MAP[stage]["label"],
        "project_slug": project["slug"],
        "episode_number": episode_number,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "command": cmd,
        "result_path": str(result_path),
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "generation_context": generation_context,
        "generation_context_path": generation_context_path,
        "progress": job_progress_state(current=STAGE_MAP[stage]["label"]),
        "retry_payload": {
            "stage": stage,
            "episode_number": episode_number,
            "pages": pages,
            "max_panels": max_panels,
            "max_pages": max_pages,
            "dry_run": dry_run,
            "force": force,
            "allow_draft_warnings": allow_draft_warnings,
        },
        "retried_from": str(payload.get("retried_from") or ""),
    }
    if skeleton:
        job["skeleton"] = skeleton
    with JOB_LOCK:
        JOBS[job_id] = job
    db.save_job(database_url(), project["slug"], job)
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def run_job(job_id: str) -> None:
    with JOB_LOCK:
        job = dict(JOBS[job_id])
    env = os.environ.copy()
    project = project_by_slug(job.get("project_slug", "")) if job.get("project_slug") else active_project()
    config = effective_config(project)
    global_config = runtime_config()
    env.update({
        "COMIC_PIPELINE_WORKSPACE": str(ROOT),
        "COMIC_PIPELINE_MANIFEST_DIR": str(project_manifest_dir(project)),
        "COMIC_PIPELINE_COMFY_ROOT": config.get("COMIC_PIPELINE_COMFY_ROOT", ""),
        "COMIC_PIPELINE_COMFY_URL": config.get("COMIC_PIPELINE_COMFY_URL", ""),
        "COMIC_PIPELINE_COMFY_OUTPUT_ROOT": config.get("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", ""),
        "COMIC_PIPELINE_OUTPUT_ROOT": config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
        "COMIC_PIPELINE_NOVEL_PATH": project.get("novel_path") or config.get("COMIC_PIPELINE_NOVEL_PATH", ""),
        "COMIC_PIPELINE_TEXT_ENV_PATH": config.get("COMIC_PIPELINE_TEXT_ENV_PATH", ""),
        "COMIC_PIPELINE_IMAGE_ENV_PATH": config.get("COMIC_PIPELINE_IMAGE_ENV_PATH", ""),
        "COMIC_PIPELINE_IMAGE_BACKEND": config.get("COMIC_PIPELINE_IMAGE_BACKEND", "direct_api"),
        "COMIC_PIPELINE_TEXT_MODEL": config.get("COMIC_PIPELINE_TEXT_MODEL", ""),
        "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT": config.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", ""),
        "COMIC_PIPELINE_TEXT_MODEL_STREAM": config.get("COMIC_PIPELINE_TEXT_MODEL_STREAM", ""),
        "COMIC_PIPELINE_IMAGE_MODEL": config.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
        "COMIC_PIPELINE_PYTHON_PATH": config.get("COMIC_PIPELINE_PYTHON_PATH", ""),
        "COMIC_PIPELINE_DEFAULT_PAGES": config.get("COMIC_PIPELINE_DEFAULT_PAGES", ""),
        "COMIC_PIPELINE_ENCODING": config.get("COMIC_PIPELINE_ENCODING", ""),
        "COMIC_PIPELINE_GLOBAL_OUTPUT_ROOT": global_config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
        "COMIC_PIPELINE_GLOBAL_TEXT_MODEL": global_config.get("COMIC_PIPELINE_TEXT_MODEL", ""),
        "COMIC_PIPELINE_GLOBAL_TEXT_MODEL_TIMEOUT": global_config.get("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT", ""),
        "COMIC_PIPELINE_GLOBAL_TEXT_MODEL_STREAM": global_config.get("COMIC_PIPELINE_TEXT_MODEL_STREAM", ""),
        "COMIC_PIPELINE_GLOBAL_IMAGE_MODEL": global_config.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
        "PYTHONIOENCODING": "utf-8",
    })
    with JOB_LOCK:
        live = JOBS.get(job_id)
        if live is not None:
            live["effective_config"] = {
                "project_slug": project.get("slug", ""),
                "sources": effective_config_sources(project),
                "text_model": config.get("COMIC_PIPELINE_TEXT_MODEL", ""),
                "image_model": config.get("COMIC_PIPELINE_IMAGE_MODEL", ""),
                "output_root": config.get("COMIC_PIPELINE_OUTPUT_ROOT", ""),
            }
    with JOB_LOCK:
        live = JOBS.get(job_id)
        if live:
            current = live.get("progress", {}).get("current") if isinstance(live.get("progress"), dict) else ""
            live["progress"] = job_progress_state(current=current or f"{live.get('label') or '任务'}运行中")
    try:
        completed = run_job_process(job_id, job["command"], env)
    except Exception as exc:
        stderr = f"任务启动失败：{exc}"
        result = {
            "ok": False,
            "error": str(exc),
            "error_type": "process_start_failed",
            "command": job.get("command", []),
        }
        with JOB_LOCK:
            live = JOBS[job_id]
            live["status"] = "failed"
            live["finished"] = datetime.now().isoformat(timespec="seconds")
            live["exit_code"] = 127
            live["stdout_tail"] = ""
            live["stderr_tail"] = stderr
            live["result"] = result
            live["diagnostics"] = {
                "domain": "job_process",
                "title": "任务进程启动失败",
                "issues": [{
                    "type": "process_start_failed",
                    "severity": "error",
                    "message": stderr,
                    "action": "检查运行环境是否包含该命令，或改为当前部署方式支持的执行器。",
                    "retry_hint": "修复运行环境后可重试",
                }],
            }
            live["progress"] = job_progress_state(failed=1, current="任务启动失败")
            try:
                live["restored_output_path"] = restore_job_backup(live)
                db.save_job(database_url(), live.get("project_slug") or active_project_slug(), live)
            except Exception as db_exc:
                live["database_warning"] = str(db_exc)
        return
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    result = read_optional_json(Path(job["result_path"]))
    if was_job_cancelled(job_id):
        cancelled_result = {"ok": False, "cancelled": True, "message": "任务已取消"}
        if result:
            cancelled_result["process_result"] = result
        with JOB_LOCK:
            job = JOBS[job_id]
            job["status"] = "cancelled"
            job["finished"] = job.get("finished") or datetime.now().isoformat(timespec="seconds")
            job["exit_code"] = -1
            job["stdout_tail"] = "任务已由用户取消。"
            job["stderr_tail"] = "\n".join(stderr.splitlines()[-80:])
            job["result"] = cancelled_result
            job["restored_output_path"] = restore_job_backup(job)
            current = job.get("progress", {}).get("current") if isinstance(job.get("progress"), dict) else ""
            job["progress"] = job_progress_state(
                job.get("progress", {}).get("total", 1) if isinstance(job.get("progress"), dict) else 1,
                job.get("progress", {}).get("completed", 0) if isinstance(job.get("progress"), dict) else 0,
                job.get("progress", {}).get("failed", 0) if isinstance(job.get("progress"), dict) else 0,
                current or "任务已取消",
                cancelled=True,
            )
            db.save_job(database_url(), job.get("project_slug") or active_project_slug(), job)
        return
    post_process = None
    result_waiting = bool(result and result.get("waiting"))
    result_partial = bool(result and result.get("partial"))
    result_completed = bool(result and result.get("completed"))
    diagnostics = job_diagnostics(job, result, stderr)
    asset_post_process_error = ""
    if (completed.returncode == 0 or result_completed) and job.get("stage") == "asset_regenerate":
        try:
            post_process = complete_asset_regeneration(project, job)
        except Exception as exc:
            asset_post_process_error = str(exc)
            restore_job_backup(job)
            result = {
                "ok": False,
                "error": asset_post_process_error,
                "error_type": "asset_output_sync_failed",
                "process_result": result or {},
            }
            diagnostics = {
                "domain": "asset_regenerate",
                "title": "素材生成结果未正确入库",
                "issues": [{
                    "type": "asset_output_sync_failed",
                    "severity": "error",
                    "message": asset_post_process_error,
                    "action": "检查工作流保存路径和素材数据库记录后重试。",
                    "retry_hint": "修复输出路径后可重试",
                }],
            }
    if (completed.returncode == 0 or result_completed) and job.get("stage") == "regenerate" and job.get("page_id"):
        post_process = assemble_page_for_panel(str(job.get("page_id")))
        try:
            job["sync_result"] = sync_and_record_job_output_versions(project, int(job.get("episode_number") or 0), job)
        except Exception as exc:
            job["sync_warning"] = str(exc)
    if (completed.returncode == 0 or result_completed) and job.get("stage") == "process_novel":
        sync_processed_novel_result(job, result)
    if (completed.returncode == 0 or result_completed) and job.get("stage") in {"breakdown", "draft_review", "close_reading"} and job.get("episode_number"):
        post_process = sync_episode_breakdown_from_plan(project, int(job.get("episode_number") or 0), job)
        if job.get("stage") == "close_reading":
            episode_number = int(job.get("episode_number") or 0)
            breakdown = post_process.get("breakdown") or {}
            if breakdown.get("id"):
                breakdown = db.update_chapter_breakdown(database_url(), int(breakdown["id"]), {
                    "pages": breakdown.get("pages") or [],
                    "panels": breakdown.get("panels") or [],
                    "referenced_setting_ids": infer_referenced_setting_ids(
                        episode_number,
                        breakdown.get("pages") or [],
                        db.list_setting_items(database_url(), project["slug"]),
                        breakdown.get("referenced_setting_ids") or [],
                    ),
                    "prompt_version": "close_reading.v1",
                    "model_name": (result or {}).get("model", ""),
                    "status": "close_reading_refined_needs_review",
                    "review_status": "pending_review",
                    "raw": {
                        "close_reading_result": result or {},
                        "editor_note": (breakdown.get("raw") or {}).get("editor_note", ""),
                    },
                })
                post_process["breakdown"] = breakdown
            approvals = get_episode_approvals(episode_number)
            approvals.update({
                "draft": False,
                "assets": False,
                "generation": False,
                "qa": False,
                "next_episode": False,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "close_reading_required_review": True,
            })
            db.save_approvals(database_url(), project["slug"], episode_number, approvals)
            if breakdown.get("id"):
                db.add_review(database_url(), project["slug"], {
                    "target_type": "chapter_breakdown",
                    "target_id": breakdown["id"],
                    "action": "close_reading",
                    "comment": "细读拆解已更新页面计划，请重新审核拆解后再继续生成。",
                    "before_data": {},
                    "after_data": result or {},
                })
    if (completed.returncode == 0 or result_completed) and job.get("stage") == "generate" and job.get("episode_number"):
        try:
            job["sync_result"] = sync_and_record_job_output_versions(project, int(job.get("episode_number") or 0), job)
        except Exception as exc:
            job["sync_warning"] = str(exc)
    with JOB_LOCK:
        job = JOBS[job_id]
        if result_waiting:
            job["status"] = "waiting"
        elif result_partial:
            job["status"] = "partial"
        elif (completed.returncode == 0 or result_completed) and not asset_post_process_error:
            job["status"] = "passed"
        else:
            job["status"] = "failed"
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        job["exit_code"] = completed.returncode
        job["stdout_tail"] = "\n".join(stdout.splitlines()[-80:])
        job["stderr_tail"] = "\n".join(stderr.splitlines()[-80:])
        job["result"] = result
        if result_waiting:
            job["progress"] = job_progress_state(current="等待继续处理", waiting=True)
        elif result_partial:
            job["progress"] = job_progress_state(completed=0, failed=1, current="部分完成", partial=True)
        elif (completed.returncode == 0 or result_completed) and not asset_post_process_error:
            job["progress"] = job_progress_state(completed=1, current="已完成")
        else:
            job["progress"] = job_progress_state(failed=1, current="执行失败")
            job["restored_output_path"] = restore_job_backup(job)
        if diagnostics:
            job["diagnostics"] = diagnostics
        if post_process:
            job["post_process"] = post_process
        try:
            db.save_job(database_url(), job.get("project_slug") or active_project_slug(), job)
        except Exception as exc:
            job["database_warning"] = str(exc)


def sync_processed_novel_result(job: dict, result: dict | None) -> None:
    if not result:
        return
    slug = job.get("project_slug") or result.get("project_slug") or ""
    if not slug:
        return
    project = db.get_project(database_url(), slug)
    if not project:
        return
    chapter_index = read_optional_json(Path(project["chapter_index_path"])) or []
    chapters = [item for item in chapter_index if isinstance(item, dict) and item.get("type") == "chapter"]
    series = read_optional_json(Path(project["series_plan_path"])) or {}
    episodes = series.get("episodes", []) if isinstance(series, dict) else []
    for item in episodes:
        number = episode_number_from_id(item.get("episode_id", ""))
        if number and not item.get("episode_plan_path"):
            item["episode_plan_path"] = str(project_episode_plan_path(number, project))
    db.replace_project_chapters(database_url(), slug, chapters)
    db.replace_project_episodes(database_url(), slug, episodes)


def import_result_summary(job: dict) -> dict:
    if job.get("stage") != "process_novel":
        return {}
    result = job.get("result")
    if not isinstance(result, dict) or not result:
        result = read_optional_json(Path(job.get("result_path") or ""))
    if not isinstance(result, dict) or not result:
        return {}
    text_model = result.get("text_model") if isinstance(result.get("text_model"), dict) else {}
    skeletons = result.get("skeletons") if isinstance(result.get("skeletons"), list) else []
    created = [item for item in skeletons if isinstance(item, dict) and item.get("status") in {"created", "written"}]
    kept = [item for item in skeletons if isinstance(item, dict) and item.get("status") not in {"created", "written"}]
    return {
        "project_slug": result.get("project_slug") or job.get("project_slug") or "",
        "project_title": result.get("project_title") or job.get("project_title") or "",
        "novel_path": result.get("novel_path") or "",
        "chapters": int(result.get("chapters") or 0),
        "episodes": int(result.get("episodes") or 0),
        "chapter_index_path": result.get("chapter_index_path") or "",
        "series_plan_path": result.get("series_plan_path") or "",
        "skeleton_total": len(skeletons),
        "skeleton_created": len(created),
        "skeleton_kept": len(kept),
        "text_model_configured": bool(text_model.get("configured")),
        "text_model_used": bool(text_model.get("used")),
        "text_model_name": text_model.get("model") or "",
        "text_model_error": text_model.get("error") or "",
        "updated": result.get("updated") or job.get("finished") or "",
    }


def import_result_for_project(slug: str = "") -> dict:
    try:
        project = project_by_slug(slug)
    except Exception:
        summary = {
            "project_slug": "",
            "project_title": "",
            "novel_path": "",
            "chapters": 0,
            "episodes": 0,
            "chapter_index_path": "",
            "series_plan_path": "",
            "skeleton_total": 0,
            "skeleton_created": 0,
            "skeleton_kept": 0,
            "text_model_configured": False,
            "text_model_used": False,
            "text_model_name": "",
            "text_model_error": "",
            "updated": "",
        }
        return {
            "ok": True,
            "project": {"slug": "", "title": ""},
            "result_path": "",
            "exists": False,
            "summary": summary,
        }
    result_path = Path(project_manifest_dir(project)) / f"{project['slug']}_novel_process_result.json"
    result = read_optional_json(result_path) or {}
    if result:
        summary = import_result_summary({
            "stage": "process_novel",
            "status": "passed" if result.get("ok") else "failed",
            "project_slug": project.get("slug", ""),
            "project_title": project.get("title", ""),
            "result_path": str(result_path),
            "result": result,
        })
    else:
        summary = {
            "project_slug": project.get("slug", ""),
            "project_title": project.get("title", ""),
            "novel_path": project.get("novel_path", ""),
            "chapters": int(project.get("chapters") or 0),
            "episodes": int(project.get("episodes") or 0),
            "chapter_index_path": project.get("chapter_index_path", ""),
            "series_plan_path": project.get("series_plan_path", ""),
            "skeleton_total": 0,
            "skeleton_created": 0,
            "skeleton_kept": 0,
            "text_model_configured": False,
            "text_model_used": False,
            "text_model_name": "",
            "text_model_error": "",
            "updated": project.get("updated") or "",
        }
    return {
        "ok": True,
        "project": {
            "slug": project.get("slug", ""),
            "title": project.get("title", ""),
        },
        "result_path": str(result_path),
        "exists": result_path.is_file(),
        "summary": summary,
    }


def attach_import_summary(job: dict) -> dict:
    if job.get("stage") == "process_novel":
        summary = import_result_summary(job)
        if summary:
            job["import_summary"] = summary
    return job


def recent_jobs() -> list[dict]:
    with JOB_LOCK:
        jobs = list(JOBS.values())
    for job in jobs:
        attach_import_summary(job)
        if job.get("stage") in {"generate", "regenerate", "regenerate_page", "close_reading"} and not job.get("diagnostics"):
            diagnostics = job_diagnostics(job)
            if diagnostics:
                job["diagnostics"] = diagnostics
    seen = {str(job.get("id") or job.get("job_id") or "") for job in jobs}
    try:
        for row in db.recent_work(database_url(), limit=20):
            raw = row.get("raw") or {}
            job = dict(raw) if isinstance(raw, dict) else {}
            job.setdefault("id", row.get("job_id", ""))
            job.setdefault("stage", row.get("stage", ""))
            job.setdefault("label", row.get("label", ""))
            job.setdefault("status", row.get("status", ""))
            job.setdefault("result_path", row.get("result_path", ""))
            job.setdefault("started", row.get("started_at", ""))
            job.setdefault("finished", row.get("finished_at", ""))
            job_id = str(job.get("id") or job.get("job_id") or "")
            attach_import_summary(job)
            if job.get("stage") in {"generate", "regenerate", "regenerate_page", "close_reading"} and not job.get("diagnostics"):
                diagnostics = job_diagnostics(job)
                if diagnostics:
                    job["diagnostics"] = diagnostics
            if job_id and job_id not in seen:
                jobs.append(job)
                seen.add(job_id)
    except Exception:
        pass
    return sorted(jobs, key=lambda item: item.get("started", ""), reverse=True)[:20]


class Handler(BaseHTTPRequestHandler):
    server_version = "ComicPipelineConsole/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/").strip("/")
            return self.serve_static(rel)
        if parsed.path.startswith("/backup-files/"):
            rel = unquote(parsed.path.removeprefix("/backup-files/").strip("/"))
            return self.serve_backup(rel)
        if parsed.path.startswith("/media/"):
            rel = unquote(parsed.path.removeprefix("/media/").strip("/"))
            return self.serve_media(rel)
        if parsed.path == "/api/config":
            return self.send_json(config_snapshot())
        if parsed.path == "/api/health":
            return self.send_json(comfy_health())
        if parsed.path == "/api/generation-backend":
            return self.send_json(comfy_runtime_diagnostics())
        if parsed.path == "/api/dashboard":
            return self.send_json(dashboard())
        if parsed.path == "/api/review-center":
            return self.send_json(review_center_api(parse_qs(parsed.query)))
        if parsed.path == "/api/novels":
            return self.send_json(list_novels_api())
        if parsed.path.startswith("/api/novels/"):
            parts = [unquote(item) for item in parsed.path.removeprefix("/api/novels/").strip("/").split("/") if item]
            if len(parts) == 2 and parts[1] == "scan-settings-preview":
                return self.send_json(scan_settings_preview_api(parts[0], parse_qs(parsed.query)))
            if len(parts) == 2 and parts[1] == "settings":
                return self.send_json(setting_library_api(parts[0], parse_qs(parsed.query)))
            if len(parts) == 1 and parts[0]:
                return self.send_json(novel_detail_api(parts[0]))
        if parsed.path == "/api/settings":
            return self.send_json({"ok": True, "settings": settings_summary()})
        if parsed.path == "/api/projects":
            return self.send_json(list_projects())
        if parsed.path.startswith("/api/projects/"):
            parts = [unquote(item) for item in parsed.path.removeprefix("/api/projects/").strip("/").split("/") if item]
            if len(parts) == 1:
                project = db.get_project(database_url(), parts[0])
                if not project:
                    return self.not_found()
                return self.send_json({"ok": True, "project": project})
        if parsed.path == "/api/import-result":
            query = parse_qs(parsed.query)
            slug = (query.get("project") or [""])[0]
            return self.send_json(import_result_for_project(slug))
        if parsed.path == "/api/episodes":
            return self.send_json(list_episodes())
        if parsed.path == "/api/jobs":
            return self.send_json({"jobs": recent_jobs()})
        if parsed.path == "/api/status":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(status_snapshot(episode))
        if parsed.path == "/api/episode-detail":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(episode_detail(episode))
        if parsed.path == "/api/assets":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            project = active_project()
            return self.send_json(attach_asset_db_state(project, episode_assets(episode)))
        if parsed.path == "/api/media":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(attach_output_db_state(active_project(), episode_media(episode)))
        if parsed.path == "/api/preview":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(preview_paths(episode))
        if parsed.path == "/api/agent/inspect":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(agent_inspect(episode))
        if parsed.path == "/api/agent/simulate":
            query = parse_qs(parsed.query)
            episode = int((query.get("episode") or ["3"])[0])
            return self.send_json(agent_simulate(episode))
        return self.not_found()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/config":
                return self.send_json(save_config(payload))
            if parsed.path == "/api/settings":
                return self.send_json(save_config(payload))
            if parsed.path == "/api/settings/health-check":
                return self.send_json(health_check_summary())
            if parsed.path == "/api/settings/test-model":
                return self.send_json(test_model_api(payload))
            if parsed.path == "/api/generation-backend/start":
                return self.send_json(start_generation_backend_api(payload), status=202)
            if parsed.path == "/api/file-action":
                return self.send_json(file_action_api(payload))
            if parsed.path == "/api/file-preview":
                return self.send_json(file_preview_api(payload))
            if parsed.path.startswith("/api/jobs/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/jobs/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "cancel":
                    return self.send_json(cancel_job_api(parts[0]))
                if len(parts) == 2 and parts[1] == "retry":
                    return self.send_json(retry_job_api(parts[0]), status=202)
            if parsed.path == "/api/novel-file":
                return self.send_json(save_uploaded_novel(payload), status=201)
            if parsed.path == "/api/import-preview":
                return self.send_json(preview_novel_import(payload))
            if parsed.path == "/api/assets/sync":
                return self.send_json(sync_assets_api(payload), status=201)
            if parsed.path == "/api/assets/generate-batch":
                return self.send_json(start_asset_batch_job(payload), status=202)
            if parsed.path == "/api/outputs/sync":
                return self.send_json(sync_outputs_api(payload), status=201)
            if parsed.path == "/api/outputs/review-batch":
                return self.send_json(review_outputs_batch_api(payload))
            if parsed.path.startswith("/api/assets/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/assets/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "review":
                    return self.send_json(review_asset_api(int(parts[0]), payload))
                if len(parts) == 2 and parts[1] == "lock":
                    return self.send_json(lock_asset_api(int(parts[0]), payload))
                if len(parts) == 2 and parts[1] == "setting":
                    return self.send_json(bind_asset_setting_api(int(parts[0]), payload))
            if parsed.path.startswith("/api/outputs/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/outputs/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "review":
                    return self.send_json(review_output_api(int(parts[0]), payload))
            if parsed.path.startswith("/api/novels/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/novels/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "scan-settings":
                    return self.send_json(start_setting_scan_job(parts[0], payload), status=202)
                if len(parts) == 2 and parts[1] == "suggest-settings":
                    return self.send_json(suggest_settings_api(parts[0], payload))
                if len(parts) == 2 and parts[1] == "settings":
                    return self.send_json(create_setting_api(parts[0], payload), status=201)
            if parsed.path.startswith("/api/settings/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/settings/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "refresh-prompt":
                    return self.send_json(refresh_setting_prompt_api(int(parts[0]), payload))
                if len(parts) == 2 and parts[1] == "review":
                    return self.send_json(review_setting_api(int(parts[0]), payload))
                if len(parts) == 2 and parts[1] == "lock":
                    return self.send_json(lock_setting_api(int(parts[0]), payload))
            if parsed.path.startswith("/api/breakdowns/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/breakdowns/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "review":
                    return self.send_json(review_breakdown_api(int(parts[0]), payload))
            if parsed.path == "/api/projects/active":
                return self.send_json(set_active_project(payload))
            if parsed.path == "/api/projects/import-backup":
                return self.send_json(import_project_backup_api(payload), status=201)
            if parsed.path.startswith("/api/projects/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/projects/").strip("/").split("/") if item]
                if len(parts) == 2 and parts[1] == "archive":
                    return self.send_json(archive_project_api(parts[0], payload))
                if len(parts) == 2 and parts[1] == "backup":
                    return self.send_json(export_project_backup_api(parts[0], payload), status=201)
            if parsed.path == "/api/process-novel":
                return self.send_json(start_process_novel_job(payload), status=202)
            if parsed.path == "/api/run":
                return self.send_json(start_job(payload), status=202)
            if parsed.path == "/api/regenerate-page":
                return self.send_json(start_regenerate_page_job(payload), status=202)
            if parsed.path == "/api/regenerate":
                return self.send_json(start_regenerate_job(payload), status=202)
            if parsed.path == "/api/agent/approval":
                return self.send_json(update_episode_approval(payload))
        except Exception as exc:
            return self.send_json({"error": str(exc)}, status=400)
        return self.not_found()

    def do_PATCH(self):
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path.startswith("/api/settings/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/settings/").strip("/").split("/") if item]
                if len(parts) == 1:
                    return self.send_json(update_setting_api(int(parts[0]), payload))
            if parsed.path.startswith("/api/breakdowns/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/breakdowns/").strip("/").split("/") if item]
                if len(parts) == 1:
                    return self.send_json(update_breakdown_api(int(parts[0]), payload))
            if parsed.path.startswith("/api/projects/"):
                parts = [unquote(item) for item in parsed.path.removeprefix("/api/projects/").strip("/").split("/") if item]
                if len(parts) == 1:
                    return self.send_json(update_project_api(parts[0], payload))
        except Exception as exc:
            return self.send_json({"error": str(exc)}, status=400)
        return self.not_found()

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8-sig"))

    def serve_static(self, rel: str):
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self.not_found()
        content_type = "application/octet-stream"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        return self.serve_file(target, content_type)

    def serve_backup(self, rel: str):
        target = (BACKUPS_DIR / rel).resolve()
        try:
            target.relative_to(BACKUPS_DIR.resolve())
        except ValueError:
            return self.not_found()
        if target.suffix.lower() != ".zip":
            return self.not_found()
        return self.serve_file(target, "application/zip")

    def serve_media(self, rel: str):
        root = comfy_output_root().resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return self.not_found()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return self.serve_file(target, content_type)

    def serve_file(self, path: Path, content_type: str):
        if not path.is_file():
            return self.not_found()
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def not_found(self):
        self.send_json({"error": "not_found"}, status=404)

    def log_message(self, format, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.address_string()} {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8199)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Comic Pipeline Console: http://{args.host}:{args.port}")
    print(f"Package root: {ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
