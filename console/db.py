import importlib.util
import json
import threading
from datetime import datetime


class DatabaseUnavailable(RuntimeError):
    pass


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS comic_projects (
        slug TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        novel_path TEXT NOT NULL,
        manifest_dir TEXT NOT NULL,
        chapter_index_path TEXT NOT NULL,
        series_plan_path TEXT NOT NULL,
        legacy BOOLEAN NOT NULL DEFAULT FALSE,
        status TEXT NOT NULL DEFAULT 'active',
        project_config JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_opened_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_chapters (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        chapter_number INTEGER NOT NULL,
        volume TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        line_number INTEGER NOT NULL DEFAULT 1,
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(project_slug, chapter_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_episodes (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        episode_number INTEGER NOT NULL,
        episode_code TEXT NOT NULL,
        chapter_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'needs_close_reading',
        planned_pages INTEGER NOT NULL DEFAULT 0,
        planned_panels INTEGER NOT NULL DEFAULT 0,
        episode_plan_path TEXT NOT NULL DEFAULT '',
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(project_slug, episode_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_episode_approvals (
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        episode_number INTEGER NOT NULL,
        draft BOOLEAN NOT NULL DEFAULT FALSE,
        assets BOOLEAN NOT NULL DEFAULT FALSE,
        generation BOOLEAN NOT NULL DEFAULT FALSE,
        qa BOOLEAN NOT NULL DEFAULT FALSE,
        next_episode BOOLEAN NOT NULL DEFAULT FALSE,
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(project_slug, episode_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_jobs (
        job_id TEXT PRIMARY KEY,
        project_slug TEXT NOT NULL DEFAULT '',
        stage TEXT NOT NULL,
        label TEXT NOT NULL,
        status TEXT NOT NULL,
        result_path TEXT NOT NULL DEFAULT '',
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_setting_items (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        item_type TEXT NOT NULL,
        name TEXT NOT NULL,
        aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
        description TEXT NOT NULL DEFAULT '',
        first_chapter_number INTEGER,
        chapter_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
        visual_prompt TEXT NOT NULL DEFAULT '',
        negative_prompt TEXT NOT NULL DEFAULT '',
        relations JSONB NOT NULL DEFAULT '{}'::jsonb,
        source_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        importance TEXT NOT NULL DEFAULT 'normal',
        review_status TEXT NOT NULL DEFAULT 'draft',
        locked BOOLEAN NOT NULL DEFAULT FALSE,
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(project_slug, item_type, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_visual_assets (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        setting_item_id BIGINT REFERENCES comic_setting_items(id) ON DELETE SET NULL,
        chapter_number INTEGER,
        asset_type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        file_path TEXT NOT NULL DEFAULT '',
        thumbnail_path TEXT NOT NULL DEFAULT '',
        prompt TEXT NOT NULL DEFAULT '',
        source_job_id TEXT NOT NULL DEFAULT '',
        usage JSONB NOT NULL DEFAULT '{}'::jsonb,
        review_status TEXT NOT NULL DEFAULT 'draft',
        locked BOOLEAN NOT NULL DEFAULT FALSE,
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_chapter_breakdowns (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        chapter_number INTEGER NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        pages JSONB NOT NULL DEFAULT '[]'::jsonb,
        panels JSONB NOT NULL DEFAULT '[]'::jsonb,
        referenced_setting_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        prompt_version TEXT NOT NULL DEFAULT '',
        model_name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        review_status TEXT NOT NULL DEFAULT 'draft',
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(project_slug, chapter_number, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_generated_outputs (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        chapter_number INTEGER,
        job_id TEXT NOT NULL DEFAULT '',
        output_type TEXT NOT NULL,
        page_index INTEGER,
        panel_index INTEGER,
        file_path TEXT NOT NULL DEFAULT '',
        thumbnail_path TEXT NOT NULL DEFAULT '',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        review_status TEXT NOT NULL DEFAULT 'draft',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_output_versions (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        output_id BIGINT REFERENCES comic_generated_outputs(id) ON DELETE SET NULL,
        chapter_number INTEGER,
        output_type TEXT NOT NULL DEFAULT '',
        page_index INTEGER,
        panel_index INTEGER,
        version_number INTEGER NOT NULL DEFAULT 1,
        file_path TEXT NOT NULL DEFAULT '',
        thumbnail_path TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'current',
        source_job_id TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS comic_output_versions_output_idx
    ON comic_output_versions(project_slug, output_id, version_number)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS comic_generated_outputs_project_file_idx
    ON comic_generated_outputs(project_slug, file_path)
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_reviews (
        id BIGSERIAL PRIMARY KEY,
        project_slug TEXT NOT NULL REFERENCES comic_projects(slug) ON DELETE CASCADE,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        action TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        before_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        after_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comic_app_settings (
        key TEXT PRIMARY KEY,
        value JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS comic_visual_assets_project_file_idx
    ON comic_visual_assets(project_slug, file_path)
    """,
    "ALTER TABLE comic_projects ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'",
    "ALTER TABLE comic_projects ADD COLUMN IF NOT EXISTS project_config JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE comic_projects ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ",
]

_LOCAL = threading.local()


def driver_status() -> dict:
    if importlib.util.find_spec("psycopg"):
        return {"available": True, "name": "psycopg"}
    if importlib.util.find_spec("psycopg2"):
        return {"available": True, "name": "psycopg2"}
    return {
        "available": False,
        "name": "",
        "error": "缺少 PostgreSQL Python 驱动。请安装 requirements.txt 中的 psycopg[binary]。",
    }


def connect(database_url: str):
    if not database_url:
        raise DatabaseUnavailable("COMIC_PIPELINE_DATABASE_URL 未配置")
    status = driver_status()
    if not status["available"]:
        raise DatabaseUnavailable(status["error"])
    if status["name"] == "psycopg":
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn


def get_connection(database_url: str):
    cached = getattr(_LOCAL, "connection", None)
    cached_url = getattr(_LOCAL, "database_url", "")
    if cached is not None and cached_url == database_url:
        try:
            with cached.cursor() as cur:
                cur.execute("SELECT 1")
            return cached
        except Exception:
            try:
                cached.close()
            except Exception:
                pass
    conn = connect(database_url)
    _LOCAL.connection = conn
    _LOCAL.database_url = database_url
    return conn


def execute(database_url: str, sql: str, params: tuple = (), fetch: str = ""):
    conn = get_connection(database_url)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        if fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        if fetch == "all":
            return [dict(row) for row in cur.fetchall()]
    return None


def init_schema(database_url: str) -> None:
    conn = get_connection(database_url)
    with conn.cursor() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


def status(database_url: str) -> dict:
    driver = driver_status()
    result = {
        "configured": bool(database_url),
        "driver": driver,
        "connected": False,
        "schema_ready": False,
        "error": "",
    }
    if not database_url or not driver["available"]:
        result["error"] = "" if database_url else "COMIC_PIPELINE_DATABASE_URL 未配置"
        if not driver["available"]:
            result["error"] = driver.get("error", "")
        return result
    try:
        init_schema(database_url)
        row = execute(database_url, "SELECT count(*) AS count FROM comic_projects", fetch="one")
        result["connected"] = True
        result["schema_ready"] = row is not None
    except Exception as exc:
        result["error"] = str(exc)
    return result


def upsert_project(database_url: str, project: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_projects
            (slug, title, novel_path, manifest_dir, chapter_index_path, series_plan_path, legacy,
             status, project_config, last_opened_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (slug) DO UPDATE SET
            title = EXCLUDED.title,
            novel_path = EXCLUDED.novel_path,
            manifest_dir = EXCLUDED.manifest_dir,
            chapter_index_path = EXCLUDED.chapter_index_path,
            series_plan_path = EXCLUDED.series_plan_path,
            legacy = EXCLUDED.legacy,
            status = CASE
                WHEN comic_projects.status = 'archived' THEN comic_projects.status
                ELSE EXCLUDED.status
            END,
            project_config = COALESCE(comic_projects.project_config, '{}'::jsonb) || EXCLUDED.project_config,
            updated_at = now()
        RETURNING slug, title, novel_path, manifest_dir, chapter_index_path, series_plan_path, legacy,
                  status, project_config, last_opened_at::text,
                  created_at::text, updated_at::text
        """,
        (
            project.get("slug", ""),
            project.get("title", ""),
            project.get("novel_path", ""),
            project.get("manifest_dir", ""),
            project.get("chapter_index_path", ""),
            project.get("series_plan_path", ""),
            bool(project.get("legacy")),
            project.get("status") or "active",
            json.dumps(project.get("project_config") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def list_projects(database_url: str) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT p.slug, p.title, p.novel_path, p.manifest_dir, p.chapter_index_path,
               p.series_plan_path, p.legacy, p.status, p.project_config,
               p.last_opened_at::text, p.created_at::text, p.updated_at::text,
               COALESCE(c.chapter_count, 0) AS chapters,
               COALESCE(e.episode_count, 0) AS episodes
        FROM comic_projects p
        LEFT JOIN (
            SELECT project_slug, count(*) AS chapter_count
            FROM comic_chapters
            GROUP BY project_slug
        ) c ON c.project_slug = p.slug
        LEFT JOIN (
            SELECT project_slug, count(*) AS episode_count
            FROM comic_episodes
            GROUP BY project_slug
        ) e ON e.project_slug = p.slug
        ORDER BY COALESCE(p.last_opened_at, p.updated_at) DESC, p.updated_at DESC, p.slug
        """,
        fetch="all",
    )


def dashboard_stats(database_url: str) -> dict:
    row = execute(
        database_url,
        """
        SELECT
          (SELECT count(*) FROM comic_projects) AS novels,
          (SELECT count(*) FROM comic_chapters) AS chapters,
          (SELECT count(*) FROM comic_setting_items WHERE review_status IN ('draft', 'pending_review')) AS pending_settings,
          (SELECT count(*) FROM comic_episode_approvals WHERE NOT (draft AND assets AND generation AND qa)) AS pending_reviews,
          (SELECT count(*) FROM comic_jobs WHERE status IN ('failed', 'error')) AS failed_jobs
        """,
        fetch="one",
    )
    return row or {}


def dashboard_pending_outputs(database_url: str, slug: str, limit: int = 5) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT chapter_number, output_type, review_status, count(*) AS count,
               min(id) AS first_output_id
        FROM comic_generated_outputs
        WHERE project_slug = %s AND review_status IN ('draft', 'pending_review', 'needs_work')
        GROUP BY chapter_number, output_type, review_status
        ORDER BY chapter_number NULLS LAST, output_type, review_status
        LIMIT %s
        """,
        (slug, limit),
        fetch="all",
    )


def dashboard_pending_settings(database_url: str, slug: str, limit: int = 5) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT id, item_type, name, review_status, locked, updated_at::text
        FROM comic_setting_items
        WHERE project_slug = %s AND review_status IN ('draft', 'pending_review', 'needs_work')
        ORDER BY locked DESC, updated_at DESC, id DESC
        LIMIT %s
        """,
        (slug, limit),
        fetch="all",
    )


def dashboard_active_approval(database_url: str, slug: str) -> dict | None:
    return execute(
        database_url,
        """
        SELECT episode_number, draft, assets, generation, qa, next_episode,
               updated_at::text AS updated
        FROM comic_episode_approvals
        WHERE project_slug = %s AND NOT (draft AND assets AND generation AND qa AND next_episode)
        ORDER BY updated_at DESC, episode_number DESC
        LIMIT 1
        """,
        (slug,),
        fetch="one",
    )


def recent_work(database_url: str, limit: int = 8) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT job_id, project_slug, stage, label, status, result_path,
               started_at::text AS started_at, finished_at::text AS finished_at, raw
        FROM comic_jobs
        ORDER BY COALESCE(finished_at, started_at) DESC
        LIMIT %s
        """,
        (limit,),
        fetch="all",
    )


def mark_interrupted_jobs(database_url: str, note: str, recovered_at: str) -> list[dict]:
    rows = execute(
        database_url,
        """
        SELECT job_id, project_slug, stage, label, status, result_path,
               started_at::text AS started_at, raw
        FROM comic_jobs
        WHERE status IN ('running', 'queued', 'starting')
        ORDER BY started_at DESC
        """,
        fetch="all",
    ) or []
    updated = []
    for row in rows:
        raw = dict(row.get("raw") or {})
        progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
        raw.update({
            "status": "interrupted",
            "finished": raw.get("finished") or recovered_at,
            "exit_code": -2,
            "stdout_tail": raw.get("stdout_tail") or "",
            "stderr_tail": raw.get("stderr_tail") or note,
            "progress": {
                "total": max(int(progress.get("total") or 1), 1),
                "completed": int(progress.get("completed") or 0),
                "failed": int(progress.get("failed") or 0),
                "current": "服务重启后任务已中断",
                "interrupted": True,
            },
            "result": {
                "ok": False,
                "interrupted": True,
                "message": note,
            },
            "diagnostics": {
                "domain": "task",
                "title": "任务已中断",
                "issues": [{
                    "type": "task_interrupted_by_restart",
                    "severity": "warning",
                    "message": note,
                    "action": "请从原流程入口重新启动任务；已生成文件不会自动删除。",
                    "retry_hint": "可重新启动",
                }],
                "waiting_reason": "task_interrupted_by_restart",
            },
        })
        execute(
            database_url,
            """
            UPDATE comic_jobs
            SET status = 'interrupted',
                raw = %s::jsonb,
                finished_at = now()
            WHERE job_id = %s
            """,
            (json.dumps(raw, ensure_ascii=False), row.get("job_id", "")),
        )
        updated.append({**row, "status": "interrupted", "raw": raw})
    return updated


def get_project(database_url: str, slug: str) -> dict | None:
    return execute(
        database_url,
        """
        SELECT slug, title, novel_path, manifest_dir, chapter_index_path, series_plan_path,
               legacy, status, project_config, last_opened_at::text,
               created_at::text, updated_at::text
        FROM comic_projects
        WHERE slug = %s
        """,
        (slug,),
        fetch="one",
    )


def update_project_metadata(database_url: str, slug: str, updates: dict) -> dict | None:
    current = get_project(database_url, slug)
    if not current:
        return None
    config = current.get("project_config") if isinstance(current.get("project_config"), dict) else {}
    incoming_config = updates.get("project_config") if isinstance(updates.get("project_config"), dict) else {}
    merged_config = {**config, **incoming_config}
    return execute(
        database_url,
        """
        UPDATE comic_projects
        SET title = %s,
            status = %s,
            project_config = %s::jsonb,
            updated_at = now()
        WHERE slug = %s
        RETURNING slug, title, novel_path, manifest_dir, chapter_index_path, series_plan_path,
                  legacy, status, project_config, last_opened_at::text,
                  created_at::text, updated_at::text
        """,
        (
            str(updates.get("title") or current.get("title") or slug).strip(),
            str(updates.get("status") or current.get("status") or "active").strip(),
            json.dumps(merged_config, ensure_ascii=False),
            slug,
        ),
        fetch="one",
    )


def touch_project_opened(database_url: str, slug: str) -> dict | None:
    return execute(
        database_url,
        """
        UPDATE comic_projects
        SET last_opened_at = now(),
            updated_at = now()
        WHERE slug = %s
        RETURNING slug, title, novel_path, manifest_dir, chapter_index_path, series_plan_path,
                  legacy, status, project_config, last_opened_at::text,
                  created_at::text, updated_at::text
        """,
        (slug,),
        fetch="one",
    )


def list_chapters(database_url: str, slug: str) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT id, project_slug, chapter_number, volume, title, line_number, raw,
               created_at::text, updated_at::text
        FROM comic_chapters
        WHERE project_slug = %s
        ORDER BY chapter_number
        """,
        (slug,),
        fetch="all",
    )


def project_counts(database_url: str, slug: str) -> dict:
    row = execute(
        database_url,
        """
        SELECT
          (SELECT count(*) FROM comic_chapters WHERE project_slug = %s) AS chapters,
          (SELECT count(*) FROM comic_episodes WHERE project_slug = %s) AS episodes,
          (SELECT count(*) FROM comic_setting_items WHERE project_slug = %s) AS setting_items,
          (SELECT count(*) FROM comic_visual_assets WHERE project_slug = %s) AS visual_assets,
          (SELECT count(*) FROM comic_chapter_breakdowns WHERE project_slug = %s) AS breakdowns,
          (SELECT count(*) FROM comic_generated_outputs WHERE project_slug = %s) AS outputs,
          (SELECT count(*) FROM comic_reviews WHERE project_slug = %s) AS reviews
        """,
        (slug, slug, slug, slug, slug, slug, slug),
        fetch="one",
    )
    return row or {}


def replace_project_chapters(database_url: str, slug: str, chapters: list[dict]) -> None:
    execute(database_url, "DELETE FROM comic_chapters WHERE project_slug = %s", (slug,))
    for index, chapter in enumerate(chapters, start=1):
        execute(
            database_url,
            """
            INSERT INTO comic_chapters
                (project_slug, chapter_number, volume, title, line_number, raw, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (project_slug, chapter_number) DO UPDATE SET
                volume = EXCLUDED.volume,
                title = EXCLUDED.title,
                line_number = EXCLUDED.line_number,
                raw = EXCLUDED.raw,
                updated_at = now()
            """,
            (
                slug,
                index,
                chapter.get("volume", ""),
                chapter.get("title", ""),
                int(chapter.get("line") or chapter.get("line_number") or 1),
                json.dumps(chapter, ensure_ascii=False),
            ),
        )


def replace_project_episodes(database_url: str, slug: str, episodes: list[dict]) -> None:
    execute(database_url, "DELETE FROM comic_episodes WHERE project_slug = %s", (slug,))
    for index, episode in enumerate(episodes, start=1):
        number = episode_number_from_id(episode.get("episode_id", "")) or index
        execute(
            database_url,
            """
            INSERT INTO comic_episodes
                (project_slug, episode_number, episode_code, chapter_number, title, status,
                 planned_pages, planned_panels, episode_plan_path, raw, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (project_slug, episode_number) DO UPDATE SET
                episode_code = EXCLUDED.episode_code,
                chapter_number = EXCLUDED.chapter_number,
                title = EXCLUDED.title,
                status = EXCLUDED.status,
                planned_pages = EXCLUDED.planned_pages,
                planned_panels = EXCLUDED.planned_panels,
                episode_plan_path = EXCLUDED.episode_plan_path,
                raw = EXCLUDED.raw,
                updated_at = now()
            """,
            (
                slug,
                number,
                episode.get("episode_id", f"EP{number:03d}"),
                index,
                episode.get("chapter_title", ""),
                episode.get("status", "needs_close_reading"),
                int(episode.get("planned_pages") or 0),
                int(episode.get("planned_panels") or 0),
                episode.get("episode_plan_path", ""),
                json.dumps(episode, ensure_ascii=False),
            ),
        )


def list_episodes(database_url: str, slug: str) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT episode_number, episode_code, chapter_number, title, status,
               planned_pages, planned_panels, episode_plan_path, raw
        FROM comic_episodes
        WHERE project_slug = %s
        ORDER BY episode_number
        """,
        (slug,),
        fetch="all",
    )


def get_approvals(database_url: str, slug: str, episode_number: int) -> dict | None:
    return execute(
        database_url,
        """
        SELECT draft, assets, generation, qa, next_episode, raw, updated_at::text AS updated
        FROM comic_episode_approvals
        WHERE project_slug = %s AND episode_number = %s
        """,
        (slug, episode_number),
        fetch="one",
    )


def save_approvals(database_url: str, slug: str, episode_number: int, approvals: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_episode_approvals
            (project_slug, episode_number, draft, assets, generation, qa, next_episode, raw, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (project_slug, episode_number) DO UPDATE SET
            draft = EXCLUDED.draft,
            assets = EXCLUDED.assets,
            generation = EXCLUDED.generation,
            qa = EXCLUDED.qa,
            next_episode = EXCLUDED.next_episode,
            raw = EXCLUDED.raw,
            updated_at = now()
        RETURNING draft, assets, generation, qa, next_episode, raw, updated_at::text AS updated
        """,
        (
            slug,
            episode_number,
            bool(approvals.get("draft")),
            bool(approvals.get("assets")),
            bool(approvals.get("generation")),
            bool(approvals.get("qa")),
            bool(approvals.get("next_episode")),
            json.dumps(approvals, ensure_ascii=False),
        ),
        fetch="one",
    )


def save_job(database_url: str, project_slug: str, job: dict) -> None:
    finished = job.get("finished") or None
    execute(
        database_url,
        """
        INSERT INTO comic_jobs
            (job_id, project_slug, stage, label, status, result_path, raw, started_at, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s::timestamptz, now()), %s::timestamptz)
        ON CONFLICT (job_id) DO UPDATE SET
            project_slug = EXCLUDED.project_slug,
            stage = EXCLUDED.stage,
            label = EXCLUDED.label,
            status = EXCLUDED.status,
            result_path = EXCLUDED.result_path,
            raw = EXCLUDED.raw,
            finished_at = EXCLUDED.finished_at
        """,
        (
            job.get("id", ""),
            project_slug,
            job.get("stage", ""),
            job.get("label", ""),
            job.get("status", ""),
            job.get("result_path", ""),
            json.dumps(job, ensure_ascii=False, default=str),
            job.get("started") or None,
            finished,
        ),
    )


def list_setting_items(database_url: str, slug: str, item_type: str = "", review_status: str = "") -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if item_type:
        filters.append("item_type = %s")
        params.append(item_type)
    if review_status:
        filters.append("review_status = %s")
        params.append(review_status)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, item_type, name, aliases, description, first_chapter_number,
               chapter_numbers, visual_prompt, negative_prompt, relations, source_evidence,
               importance, review_status, locked, raw, created_at::text, updated_at::text
        FROM comic_setting_items
        WHERE {' AND '.join(filters)}
        ORDER BY locked DESC, importance, item_type, name
        """,
        tuple(params),
        fetch="all",
    )


def get_setting_item(database_url: str, setting_id: int) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, item_type, name, aliases, description, first_chapter_number,
               chapter_numbers, visual_prompt, negative_prompt, relations, source_evidence,
               importance, review_status, locked, raw, created_at::text, updated_at::text
        FROM comic_setting_items
        WHERE id = %s
        """,
        (setting_id,),
        fetch="one",
    )


def upsert_setting_item(database_url: str, slug: str, item: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_setting_items
            (project_slug, item_type, name, aliases, description, first_chapter_number,
             chapter_numbers, visual_prompt, negative_prompt, relations, source_evidence,
             importance, review_status, locked, raw, updated_at)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s::jsonb,
                %s::jsonb, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (project_slug, item_type, name) DO UPDATE SET
            aliases = EXCLUDED.aliases,
            description = EXCLUDED.description,
            first_chapter_number = COALESCE(comic_setting_items.first_chapter_number, EXCLUDED.first_chapter_number),
            chapter_numbers = EXCLUDED.chapter_numbers,
            visual_prompt = EXCLUDED.visual_prompt,
            negative_prompt = EXCLUDED.negative_prompt,
            relations = EXCLUDED.relations,
            source_evidence = EXCLUDED.source_evidence,
            importance = EXCLUDED.importance,
            review_status = CASE
                WHEN comic_setting_items.locked THEN comic_setting_items.review_status
                ELSE EXCLUDED.review_status
            END,
            locked = comic_setting_items.locked OR EXCLUDED.locked,
            raw = EXCLUDED.raw,
            updated_at = now()
        RETURNING id, project_slug, item_type, name, aliases, description, first_chapter_number,
                  chapter_numbers, visual_prompt, negative_prompt, relations, source_evidence,
                  importance, review_status, locked, raw, created_at::text, updated_at::text
        """,
        (
            slug,
            item.get("item_type", "world_rule"),
            item.get("name", ""),
            json.dumps(item.get("aliases") or [], ensure_ascii=False),
            item.get("description", ""),
            item.get("first_chapter_number"),
            json.dumps(item.get("chapter_numbers") or [], ensure_ascii=False),
            item.get("visual_prompt", ""),
            item.get("negative_prompt", ""),
            json.dumps(item.get("relations") or {}, ensure_ascii=False),
            json.dumps(item.get("source_evidence") or [], ensure_ascii=False),
            item.get("importance", "normal"),
            item.get("review_status", "pending_review"),
            bool(item.get("locked")),
            json.dumps(item.get("raw") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def update_setting_item(database_url: str, setting_id: int, updates: dict) -> dict:
    current = get_setting_item(database_url, setting_id)
    if not current:
        raise DatabaseUnavailable(f"设定条目不存在：{setting_id}")
    merged = {**current, **updates}
    return execute(
        database_url,
        """
        UPDATE comic_setting_items SET
            item_type = %s,
            name = %s,
            aliases = %s::jsonb,
            description = %s,
            first_chapter_number = %s,
            chapter_numbers = %s::jsonb,
            visual_prompt = %s,
            negative_prompt = %s,
            relations = %s::jsonb,
            source_evidence = %s::jsonb,
            importance = %s,
            review_status = %s,
            locked = %s,
            raw = %s::jsonb,
            updated_at = now()
        WHERE id = %s
        RETURNING id, project_slug, item_type, name, aliases, description, first_chapter_number,
                  chapter_numbers, visual_prompt, negative_prompt, relations, source_evidence,
                  importance, review_status, locked, raw, created_at::text, updated_at::text
        """,
        (
            merged.get("item_type", "world_rule"),
            merged.get("name", ""),
            json.dumps(merged.get("aliases") or [], ensure_ascii=False),
            merged.get("description", ""),
            merged.get("first_chapter_number"),
            json.dumps(merged.get("chapter_numbers") or [], ensure_ascii=False),
            merged.get("visual_prompt", ""),
            merged.get("negative_prompt", ""),
            json.dumps(merged.get("relations") or {}, ensure_ascii=False),
            json.dumps(merged.get("source_evidence") or [], ensure_ascii=False),
            merged.get("importance", "normal"),
            merged.get("review_status", "pending_review"),
            bool(merged.get("locked")),
            json.dumps(merged.get("raw") or {}, ensure_ascii=False),
            setting_id,
        ),
        fetch="one",
    )


def add_review(database_url: str, slug: str, review: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_reviews
            (project_slug, target_type, target_id, action, comment, before_data, after_data)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id, project_slug, target_type, target_id, action, comment,
                  before_data, after_data, created_at::text
        """,
        (
            slug,
            review.get("target_type", ""),
            str(review.get("target_id", "")),
            review.get("action", ""),
            review.get("comment", ""),
            json.dumps(review.get("before_data") or {}, ensure_ascii=False),
            json.dumps(review.get("after_data") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def get_chapter_breakdown(database_url: str, slug: str, chapter_number: int, version: int = 1) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, chapter_number, version, pages, panels,
               referenced_setting_ids, prompt_version, model_name, status,
               review_status, raw, created_at::text, updated_at::text
        FROM comic_chapter_breakdowns
        WHERE project_slug = %s AND chapter_number = %s AND version = %s
        """,
        (slug, chapter_number, version),
        fetch="one",
    )


def get_chapter_breakdown_by_id(database_url: str, breakdown_id: int) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, chapter_number, version, pages, panels,
               referenced_setting_ids, prompt_version, model_name, status,
               review_status, raw, created_at::text, updated_at::text
        FROM comic_chapter_breakdowns
        WHERE id = %s
        """,
        (breakdown_id,),
        fetch="one",
    )


def list_chapter_breakdowns(database_url: str, slug: str, review_status: str = "") -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if review_status:
        filters.append("review_status = %s")
        params.append(review_status)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, chapter_number, version, pages, panels,
               referenced_setting_ids, prompt_version, model_name, status,
               review_status, raw, created_at::text, updated_at::text
        FROM comic_chapter_breakdowns
        WHERE {' AND '.join(filters)}
        ORDER BY chapter_number, version DESC
        """,
        tuple(params),
        fetch="all",
    )


def upsert_chapter_breakdown(database_url: str, slug: str, chapter_number: int, breakdown: dict) -> dict:
    version = int(breakdown.get("version") or 1)
    return execute(
        database_url,
        """
        INSERT INTO comic_chapter_breakdowns
            (project_slug, chapter_number, version, pages, panels, referenced_setting_ids,
             prompt_version, model_name, status, review_status, raw, updated_at)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (project_slug, chapter_number, version) DO UPDATE SET
            pages = EXCLUDED.pages,
            panels = EXCLUDED.panels,
            referenced_setting_ids = EXCLUDED.referenced_setting_ids,
            prompt_version = EXCLUDED.prompt_version,
            model_name = EXCLUDED.model_name,
            status = EXCLUDED.status,
            review_status = CASE
                WHEN comic_chapter_breakdowns.review_status = 'approved' THEN comic_chapter_breakdowns.review_status
                ELSE EXCLUDED.review_status
            END,
            raw = comic_chapter_breakdowns.raw || EXCLUDED.raw,
            updated_at = now()
        RETURNING id, project_slug, chapter_number, version, pages, panels,
                  referenced_setting_ids, prompt_version, model_name, status,
                  review_status, raw, created_at::text, updated_at::text
        """,
        (
            slug,
            chapter_number,
            version,
            json.dumps(breakdown.get("pages") or [], ensure_ascii=False),
            json.dumps(breakdown.get("panels") or [], ensure_ascii=False),
            json.dumps(breakdown.get("referenced_setting_ids") or [], ensure_ascii=False),
            breakdown.get("prompt_version", ""),
            breakdown.get("model_name", ""),
            breakdown.get("status", "draft_ready"),
            breakdown.get("review_status", "pending_review"),
            json.dumps(breakdown.get("raw") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def update_chapter_breakdown(database_url: str, breakdown_id: int, updates: dict) -> dict:
    current = get_chapter_breakdown_by_id(database_url, breakdown_id)
    if not current:
        raise ValueError("章节拆解不存在")
    raw = dict(current.get("raw") or {})
    raw.update(updates.get("raw") or {})
    return execute(
        database_url,
        """
        UPDATE comic_chapter_breakdowns SET
            pages = %s::jsonb,
            panels = %s::jsonb,
            referenced_setting_ids = %s::jsonb,
            prompt_version = %s,
            model_name = %s,
            status = %s,
            review_status = %s,
            raw = %s::jsonb,
            updated_at = now()
        WHERE id = %s
        RETURNING id, project_slug, chapter_number, version, pages, panels,
                  referenced_setting_ids, prompt_version, model_name, status,
                  review_status, raw, created_at::text, updated_at::text
        """,
        (
            json.dumps(updates.get("pages", current.get("pages") or []), ensure_ascii=False),
            json.dumps(updates.get("panels", current.get("panels") or []), ensure_ascii=False),
            json.dumps(updates.get("referenced_setting_ids", current.get("referenced_setting_ids") or []), ensure_ascii=False),
            updates.get("prompt_version", current.get("prompt_version", "")),
            updates.get("model_name", current.get("model_name", "")),
            updates.get("status", current.get("status", "draft")),
            updates.get("review_status", current.get("review_status", "draft")),
            json.dumps(raw, ensure_ascii=False),
            breakdown_id,
        ),
        fetch="one",
    )


def list_visual_assets(database_url: str, slug: str, asset_type: str = "", review_status: str = "") -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if asset_type:
        filters.append("asset_type = %s")
        params.append(asset_type)
    if review_status:
        filters.append("review_status = %s")
        params.append(review_status)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, setting_item_id, chapter_number, asset_type, title,
               description, file_path, thumbnail_path, prompt, source_job_id, usage,
               review_status, locked, raw, created_at::text, updated_at::text
        FROM comic_visual_assets
        WHERE {' AND '.join(filters)}
        ORDER BY locked DESC, asset_type, title
        """,
        tuple(params),
        fetch="all",
    )


def get_visual_asset(database_url: str, asset_id: int) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, setting_item_id, chapter_number, asset_type, title,
               description, file_path, thumbnail_path, prompt, source_job_id, usage,
               review_status, locked, raw, created_at::text, updated_at::text
        FROM comic_visual_assets
        WHERE id = %s
        """,
        (asset_id,),
        fetch="one",
    )


def get_visual_asset_by_path(database_url: str, slug: str, file_path: str) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, setting_item_id, chapter_number, asset_type, title,
               description, file_path, thumbnail_path, prompt, source_job_id, usage,
               review_status, locked, raw, created_at::text, updated_at::text
        FROM comic_visual_assets
        WHERE project_slug = %s AND file_path = %s
        """,
        (slug, file_path),
        fetch="one",
    )


def upsert_visual_asset(database_url: str, slug: str, asset: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_visual_assets
            (project_slug, setting_item_id, chapter_number, asset_type, title, description,
             file_path, thumbnail_path, prompt, source_job_id, usage, review_status,
             locked, raw, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, now())
        ON CONFLICT (project_slug, file_path) DO UPDATE SET
            setting_item_id = COALESCE(comic_visual_assets.setting_item_id, EXCLUDED.setting_item_id),
            chapter_number = COALESCE(comic_visual_assets.chapter_number, EXCLUDED.chapter_number),
            asset_type = EXCLUDED.asset_type,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            thumbnail_path = EXCLUDED.thumbnail_path,
            prompt = COALESCE(NULLIF(comic_visual_assets.prompt, ''), EXCLUDED.prompt),
            source_job_id = COALESCE(NULLIF(comic_visual_assets.source_job_id, ''), EXCLUDED.source_job_id),
            usage = EXCLUDED.usage,
            review_status = CASE
                WHEN comic_visual_assets.locked THEN comic_visual_assets.review_status
                WHEN comic_visual_assets.review_status = 'approved' THEN comic_visual_assets.review_status
                ELSE EXCLUDED.review_status
            END,
            locked = comic_visual_assets.locked OR EXCLUDED.locked,
            raw = comic_visual_assets.raw || EXCLUDED.raw,
            updated_at = now()
        RETURNING id, project_slug, setting_item_id, chapter_number, asset_type, title,
                  description, file_path, thumbnail_path, prompt, source_job_id, usage,
                  review_status, locked, raw, created_at::text, updated_at::text
        """,
        (
            slug,
            asset.get("setting_item_id"),
            asset.get("chapter_number"),
            asset.get("asset_type", "uncategorized"),
            asset.get("title", ""),
            asset.get("description", ""),
            asset.get("file_path", ""),
            asset.get("thumbnail_path", ""),
            asset.get("prompt", ""),
            asset.get("source_job_id", ""),
            json.dumps(asset.get("usage") or {}, ensure_ascii=False),
            asset.get("review_status", "pending_review"),
            bool(asset.get("locked")),
            json.dumps(asset.get("raw") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def update_visual_asset(database_url: str, asset_id: int, updates: dict) -> dict:
    current = get_visual_asset(database_url, asset_id)
    if not current:
        raise ValueError("视觉素材不存在")
    raw = dict(current.get("raw") or {})
    raw.update(updates.get("raw") or {})
    merged = {**current, **updates, "raw": raw}
    return execute(
        database_url,
        """
        UPDATE comic_visual_assets SET
            setting_item_id = %s,
            chapter_number = %s,
            asset_type = %s,
            title = %s,
            description = %s,
            file_path = %s,
            thumbnail_path = %s,
            prompt = %s,
            source_job_id = %s,
            usage = %s::jsonb,
            review_status = %s,
            locked = %s,
            raw = %s::jsonb,
            updated_at = now()
        WHERE id = %s
        RETURNING id, project_slug, setting_item_id, chapter_number, asset_type, title,
                  description, file_path, thumbnail_path, prompt, source_job_id, usage,
                  review_status, locked, raw, created_at::text, updated_at::text
        """,
        (
            merged.get("setting_item_id"),
            merged.get("chapter_number"),
            merged.get("asset_type", "uncategorized"),
            merged.get("title", ""),
            merged.get("description", ""),
            merged.get("file_path", ""),
            merged.get("thumbnail_path", ""),
            merged.get("prompt", ""),
            merged.get("source_job_id", ""),
            json.dumps(merged.get("usage") or {}, ensure_ascii=False),
            merged.get("review_status", "draft"),
            bool(merged.get("locked")),
            json.dumps(merged.get("raw") or {}, ensure_ascii=False),
            asset_id,
        ),
        fetch="one",
    )


def list_generated_outputs(database_url: str, slug: str, chapter_number: int | None = None, output_type: str = "") -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if chapter_number is not None:
        filters.append("chapter_number = %s")
        params.append(chapter_number)
    if output_type:
        filters.append("output_type = %s")
        params.append(output_type)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, chapter_number, job_id, output_type, page_index,
               panel_index, file_path, thumbnail_path, metadata, review_status,
               created_at::text
        FROM comic_generated_outputs
        WHERE {' AND '.join(filters)}
        ORDER BY chapter_number NULLS LAST, page_index NULLS LAST,
                 panel_index NULLS LAST, id
        """,
        tuple(params),
        fetch="all",
    )


def get_generated_output(database_url: str, output_id: int) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, chapter_number, job_id, output_type, page_index,
               panel_index, file_path, thumbnail_path, metadata, review_status,
               created_at::text
        FROM comic_generated_outputs
        WHERE id = %s
        """,
        (output_id,),
        fetch="one",
    )


def get_generated_output_by_path(database_url: str, slug: str, file_path: str) -> dict | None:
    return execute(
        database_url,
        """
        SELECT id, project_slug, chapter_number, job_id, output_type, page_index,
               panel_index, file_path, thumbnail_path, metadata, review_status,
               created_at::text
        FROM comic_generated_outputs
        WHERE project_slug = %s AND file_path = %s
        """,
        (slug, file_path),
        fetch="one",
    )


def delete_generated_output(database_url: str, output_id: int) -> dict | None:
    return execute(
        database_url,
        """
        DELETE FROM comic_generated_outputs
        WHERE id = %s
        RETURNING id, project_slug, chapter_number, job_id, output_type, page_index,
                  panel_index, file_path, thumbnail_path, metadata, review_status,
                  created_at::text
        """,
        (output_id,),
        fetch="one",
    )


def upsert_generated_output(database_url: str, slug: str, output: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_generated_outputs
            (project_slug, chapter_number, job_id, output_type, page_index,
             panel_index, file_path, thumbnail_path, metadata, review_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (project_slug, file_path) DO UPDATE SET
            chapter_number = COALESCE(EXCLUDED.chapter_number, comic_generated_outputs.chapter_number),
            job_id = COALESCE(NULLIF(EXCLUDED.job_id, ''), comic_generated_outputs.job_id),
            output_type = EXCLUDED.output_type,
            page_index = COALESCE(EXCLUDED.page_index, comic_generated_outputs.page_index),
            panel_index = COALESCE(EXCLUDED.panel_index, comic_generated_outputs.panel_index),
            thumbnail_path = COALESCE(NULLIF(EXCLUDED.thumbnail_path, ''), comic_generated_outputs.thumbnail_path),
            metadata = comic_generated_outputs.metadata || EXCLUDED.metadata,
            review_status = CASE
                WHEN comic_generated_outputs.review_status = 'approved' THEN comic_generated_outputs.review_status
                ELSE EXCLUDED.review_status
            END
        RETURNING id, project_slug, chapter_number, job_id, output_type, page_index,
                  panel_index, file_path, thumbnail_path, metadata, review_status,
                  created_at::text
        """,
        (
            slug,
            output.get("chapter_number"),
            output.get("job_id", ""),
            output.get("output_type", "panel"),
            output.get("page_index"),
            output.get("panel_index"),
            output.get("file_path", ""),
            output.get("thumbnail_path", ""),
            json.dumps(output.get("metadata") or {}, ensure_ascii=False),
            output.get("review_status", "pending_review"),
        ),
        fetch="one",
    )


def update_generated_output(database_url: str, output_id: int, updates: dict) -> dict:
    current = get_generated_output(database_url, output_id)
    if not current:
        raise ValueError("生成结果不存在")
    metadata = dict(current.get("metadata") or {})
    metadata.update(updates.get("metadata") or {})
    merged = {**current, **updates, "metadata": metadata}
    return execute(
        database_url,
        """
        UPDATE comic_generated_outputs SET
            job_id = %s,
            output_type = %s,
            page_index = %s,
            panel_index = %s,
            file_path = %s,
            thumbnail_path = %s,
            metadata = %s::jsonb,
            review_status = %s
        WHERE id = %s
        RETURNING id, project_slug, chapter_number, job_id, output_type, page_index,
                  panel_index, file_path, thumbnail_path, metadata, review_status,
                  created_at::text
        """,
        (
            merged.get("job_id", ""),
            merged.get("output_type", "panel"),
            merged.get("page_index"),
            merged.get("panel_index"),
            merged.get("file_path", ""),
            merged.get("thumbnail_path", ""),
            json.dumps(merged.get("metadata") or {}, ensure_ascii=False),
            merged.get("review_status", "draft"),
            output_id,
        ),
        fetch="one",
    )


def next_output_version_number(database_url: str, slug: str, output_id: int | None, file_path: str = "") -> int:
    if output_id:
        row = execute(
            database_url,
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS version_number
            FROM comic_output_versions
            WHERE project_slug = %s AND output_id = %s
            """,
            (slug, output_id),
            fetch="one",
        )
    else:
        row = execute(
            database_url,
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS version_number
            FROM comic_output_versions
            WHERE project_slug = %s AND file_path = %s
            """,
            (slug, file_path),
            fetch="one",
        )
    return int((row or {}).get("version_number") or 1)


def add_output_version(database_url: str, slug: str, version: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_output_versions
            (project_slug, output_id, chapter_number, output_type, page_index, panel_index,
             version_number, file_path, thumbnail_path, role, source_job_id, reason, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id, project_slug, output_id, chapter_number, output_type, page_index,
                  panel_index, version_number, file_path, thumbnail_path, role,
                  source_job_id, reason, metadata, created_at::text
        """,
        (
            slug,
            version.get("output_id"),
            version.get("chapter_number"),
            version.get("output_type", ""),
            version.get("page_index"),
            version.get("panel_index"),
            version.get("version_number") or next_output_version_number(database_url, slug, version.get("output_id"), version.get("file_path", "")),
            version.get("file_path", ""),
            version.get("thumbnail_path", ""),
            version.get("role", "current"),
            version.get("source_job_id", ""),
            version.get("reason", ""),
            json.dumps(version.get("metadata") or {}, ensure_ascii=False),
        ),
        fetch="one",
    )


def list_output_versions(database_url: str, slug: str, output_ids: list[int] | None = None, chapter_number: int | None = None) -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if output_ids:
        filters.append("output_id = ANY(%s)")
        params.append(output_ids)
    if chapter_number is not None:
        filters.append("chapter_number = %s")
        params.append(chapter_number)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, output_id, chapter_number, output_type, page_index,
               panel_index, version_number, file_path, thumbnail_path, role,
               source_job_id, reason, metadata, created_at::text
        FROM comic_output_versions
        WHERE {' AND '.join(filters)}
        ORDER BY COALESCE(output_id, 0), version_number DESC, id DESC
        """,
        tuple(params),
        fetch="all",
    )


def list_reviews(database_url: str, slug: str, target_type: str = "", limit: int = 50, days: int = 0) -> list[dict]:
    filters = ["project_slug = %s"]
    params: list = [slug]
    if target_type:
        filters.append("target_type = %s")
        params.append(target_type)
    if days > 0:
        filters.append("created_at >= now() - (%s * interval '1 day')")
        params.append(days)
    params.append(limit)
    return execute(
        database_url,
        f"""
        SELECT id, project_slug, target_type, target_id, action, comment,
               before_data, after_data, created_at::text
        FROM comic_reviews
        WHERE {' AND '.join(filters)}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        tuple(params),
        fetch="all",
    )


def list_app_settings(database_url: str) -> list[dict]:
    return execute(
        database_url,
        """
        SELECT key, value, updated_at::text
        FROM comic_app_settings
        ORDER BY key
        """,
        fetch="all",
    )


def upsert_app_setting(database_url: str, key: str, value: dict) -> dict:
    return execute(
        database_url,
        """
        INSERT INTO comic_app_settings (key, value, updated_at)
        VALUES (%s, %s::jsonb, now())
        ON CONFLICT (key) DO UPDATE SET
            value = EXCLUDED.value,
            updated_at = now()
        RETURNING key, value, updated_at::text
        """,
        (key, json.dumps(value, ensure_ascii=False)),
        fetch="one",
    )


def episode_number_from_id(value: str) -> int:
    import re

    match = re.search(r"EP0*(\d+)", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")
