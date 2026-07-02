import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def read_env(path: str | Path) -> dict:
    values = {}
    candidate = Path(path)
    if not candidate.is_file():
        return values
    for line in candidate.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def parse_int(value: str | int | None, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def text_model_config() -> dict:
    env_path = os.getenv("COMIC_PIPELINE_TEXT_ENV_PATH") or ""
    env_values = read_env(env_path) if env_path else {}
    return {
        "model": os.getenv("COMIC_PIPELINE_TEXT_MODEL", "").strip(),
        "base_url": (
            os.getenv("COMIC_PIPELINE_TEXT_BASE_URL")
            or env_values.get("OPENAI_BASE_URL", "")
        ).strip().rstrip("/"),
        "api_key": (
            os.getenv("COMIC_PIPELINE_TEXT_API_KEY")
            or env_values.get("OPENAI_API_KEY", "")
        ).strip(),
        "env_path": env_path,
        "timeout": parse_int(os.getenv("COMIC_PIPELINE_TEXT_MODEL_TIMEOUT"), 300),
        "stream": parse_bool(os.getenv("COMIC_PIPELINE_TEXT_MODEL_STREAM"), True),
    }


def is_configured(config: dict | None = None) -> bool:
    config = config or text_model_config()
    return bool(config.get("model") and config.get("base_url") and config.get("api_key"))


def stream_chat_content(response) -> str:
    parts = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        choice = (event.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            parts.append(str(delta["content"]))
        message = choice.get("message") or {}
        if message.get("content"):
            parts.append(str(message["content"]))
    return "".join(parts)


def chat_json(
    messages: list[dict],
    temperature: float = 0.2,
    timeout: int | None = None,
    stream: bool | None = None,
) -> dict:
    config = text_model_config()
    if not is_configured(config):
        raise RuntimeError("text model is not configured")
    timeout = parse_int(timeout, int(config.get("timeout") or 300))
    use_stream = parse_bool(stream, bool(config.get("stream")))

    base_url = config["base_url"]
    if base_url.endswith("/chat/completions"):
        url = base_url
    elif base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if use_stream:
        payload["stream"] = True
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if use_stream:
                content = stream_chat_content(response)
                raw = ""
            else:
                raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"text model request failed: HTTP {exc.code} {body[:600]}") from exc

    if not use_stream:
        data = json.loads(raw)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("text model returned empty content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"text model returned non-json content: {content[:600]}") from exc
    parsed.setdefault("_model", config["model"])
    return parsed
