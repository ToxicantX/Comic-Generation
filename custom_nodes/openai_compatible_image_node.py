import base64
from io import BytesIO
import os
import re
import time
from pathlib import Path

import numpy as np
import requests
import torch
from PIL import Image


class OpenAICompatibleImageGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "model": ("STRING", {"default": "gpt-image-2"}),
                "size": (["1024x1024", "1024x1536", "1536x1024"], {"default": "1024x1536"}),
            },
            "optional": {
                "api_key": ("STRING", {"multiline": False, "default": ""}),
                "base_url": ("STRING", {"default": ""}),
                "api_key_env_path": ("STRING", {"multiline": False, "default": ""}),
                "quality": (["auto", "low", "medium", "high"], {"default": "auto"}),
                "reference_image_paths": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "generate"
    CATEGORY = "api/image"

    def generate(self, prompt, model, size, api_key="", base_url="", api_key_env_path="", quality="auto", reference_image_paths="", negative_prompt=""):
        resolved = _resolve_openai_compatible_config(api_key, base_url, api_key_env_path)
        api_key = resolved["api_key"]
        base_url = resolved["base_url"]
        if not api_key.strip():
            raise ValueError("api_key is required via input, OPENAI_API_KEY/API_KEYS, or api_key_env_path")

        final_prompt = prompt.strip()
        if negative_prompt.strip():
            final_prompt += "\n\nAvoid: " + negative_prompt.strip()

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
        }

        session = requests.Session()
        session.trust_env = False
        references = _reference_paths(reference_image_paths)
        attempts = []
        if references:
            endpoint = base_url.rstrip("/") + "/v1/images/edits"
            data = {
                "model": model.strip(),
                "prompt": final_prompt,
                "size": size,
                "quality": quality,
                "n": "1",
                "response_format": "b64_json",
            }
            files = []
            handles = []
            try:
                for path in references:
                    handle = path.open("rb")
                    handles.append(handle)
                    files.append(("image", (path.name, handle, _guess_content_type(path))))
                response = session.post(endpoint, data=data, files=files, headers=headers, timeout=600)
                attempts.append(("multipart_edits_b64_json", response))
            finally:
                for handle in handles:
                    handle.close()
            if _should_fallback_from_edits(response):
                endpoint = base_url.rstrip("/") + "/v1/images/generations"
                payload = {
                    "model": model.strip(),
                    "prompt": final_prompt,
                    "size": size,
                    "quality": quality,
                    "n": 1,
                    "response_format": "b64_json",
                }
                response = _post_json_with_rate_limit_retry(
                    session, endpoint, headers, payload, attempts, "json_generation_fallback"
                )
                if _should_retry_without_response_format(response):
                    payload.pop("response_format", None)
                    response = _post_json_with_rate_limit_retry(
                        session, endpoint, headers, payload, attempts, "json_generation_fallback_default"
                    )
        else:
            endpoint = base_url.rstrip("/") + "/v1/images/generations"
            payload = {
                "model": model.strip(),
                "prompt": final_prompt,
                "size": size,
                "quality": quality,
                "n": 1,
                "response_format": "b64_json",
            }
            response = _post_json_with_rate_limit_retry(
                session, endpoint, headers, payload, attempts, "json_b64_json"
            )
            if _should_retry_without_response_format(response):
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                response = _post_json_with_rate_limit_retry(
                    session, endpoint, headers, fallback_payload, attempts, "json_default_response"
                )
            if _should_retry_as_form(response) or _attempts_include_content_type_issue(attempts):
                form_payload = {
                    "model": model.strip(),
                    "prompt": final_prompt,
                    "size": size,
                    "quality": quality,
                    "n": "1",
                }
                response = session.post(endpoint, data=form_payload, headers=dict(headers), timeout=600)
                attempts.append(("form_default_response", response))
        if response.status_code >= 400:
            raise RuntimeError(f"Image API error {response.status_code}: {_safe_error_text(response)}; attempts={_attempt_summary(attempts)}")

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Image API response was not JSON: content_type={response.headers.get('content-type', '')}") from exc

        image_bytes = _extract_image_bytes(data, session)
        if not image_bytes:
            raise RuntimeError("Image API response did not include usable image data; " + _response_shape(data))

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        array = np.asarray(image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array)[None,]
        return (tensor,)


NODE_CLASS_MAPPINGS = {
    "OpenAICompatibleImageGenerate": OpenAICompatibleImageGenerate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenAICompatibleImageGenerate": "OpenAI Compatible Image Generate",
}


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _resolve_openai_compatible_config(api_key: str, base_url: str, api_key_env_path: str) -> dict:
    file_api_key = ""
    file_base_url = ""
    env_path = str(api_key_env_path or "").strip().strip('"')
    if env_path:
        path = _resolve_comfy_path(env_path)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            file_api_key = _first_match(
                text,
                [
                    r'"apiKey"\s*:\s*"([^"]+)"',
                    r"'apiKey'\s*:\s*'([^']+)'",
                    r"(?m)^\s*(?:OPENAI_API_KEY|API_KEY|API_KEYS)\s*=\s*([^\r\n,]+)",
                ],
            )
            file_base_url = _first_match(
                text,
                [
                    r'"baseURL"\s*:\s*"([^"]+)"',
                    r'"base_url"\s*:\s*"([^"]+)"',
                    r"'baseURL'\s*:\s*'([^']+)'",
                    r"(?m)^\s*(?:OPENAI_BASE_URL|BASE_URL)\s*=\s*([^\r\n]+)",
                ],
            )

    resolved_api_key = (
        str(api_key or "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("API_KEYS", "").split(",")[0].strip()
        or file_api_key.strip()
    )
    resolved_base_url = (
        str(base_url or "").strip()
        or os.getenv("OPENAI_BASE_URL", "").strip()
        or file_base_url.strip()
        or "https://api.openai.com"
    )
    return {"api_key": resolved_api_key, "base_url": resolved_base_url}


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return ""


def _reference_paths(reference_image_paths: str) -> list[Path]:
    if not reference_image_paths or not reference_image_paths.strip():
        return []
    paths = []
    seen = set()
    for line in reference_image_paths.replace(";", "\n").splitlines():
        raw = line.strip().strip('"')
        if not raw:
            continue
        path = _resolve_comfy_path(raw)
        normalized = str(path).lower()
        if normalized in seen:
            continue
        if not path.is_file():
            raise ValueError(f"reference image path does not exist: {raw}")
        seen.add(normalized)
        paths.append(path)
    if len(paths) > 16:
        raise ValueError("reference_image_paths supports at most 16 images")
    return paths


def _resolve_comfy_path(value: str) -> Path:
    path = Path(value)
    if path.is_file():
        return path

    comfy_root = Path(__file__).resolve().parents[1]
    normalized = value.replace("\\", "/")
    if normalized == "/comfyui" or normalized.startswith("/comfyui/"):
        relative = normalized.removeprefix("/comfyui").lstrip("/")
        return comfy_root / Path(relative)
    if not path.is_absolute():
        return comfy_root / path
    return path


def _extract_image_bytes(data, session: requests.Session) -> bytes:
    for candidate in _image_candidates(data):
        if not candidate:
            continue
        if isinstance(candidate, str):
            value = candidate.strip()
            if not value:
                continue
            if value.startswith("data:image/"):
                value = value.split(",", 1)[-1]
                decoded = _try_b64_decode(value)
                if decoded:
                    return decoded
            if value.startswith("http://") or value.startswith("https://"):
                downloaded = _download_image(value, session)
                if downloaded:
                    return downloaded
            decoded = _try_b64_decode(value)
            if decoded:
                return decoded
    return b""


def _post_json(session: requests.Session, endpoint: str, headers: dict, payload: dict) -> requests.Response:
    request_headers = dict(headers)
    request_headers["Content-Type"] = "application/json"
    request_headers["Accept"] = "application/json"
    return session.post(endpoint, json=payload, headers=request_headers, timeout=600)


def _post_json_with_rate_limit_retry(
    session: requests.Session,
    endpoint: str,
    headers: dict,
    payload: dict,
    attempts: list[tuple[str, requests.Response]],
    attempt_name: str,
) -> requests.Response:
    response = _post_json(session, endpoint, headers, payload)
    attempts.append((attempt_name, response))
    if response.status_code != 429:
        return response
    retry_after = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
    try:
        delay = max(1, min(300, int(float(retry_after)) + 1))
    except (TypeError, ValueError):
        delay = 65
    time.sleep(delay)
    response = _post_json(session, endpoint, headers, payload)
    attempts.append((f"{attempt_name}_rate_limit_retry", response))
    return response


def _should_retry_without_response_format(response: requests.Response) -> bool:
    if response.status_code not in {400, 415, 422}:
        return False
    text = _safe_error_text(response).lower()
    return (
        "unsupported content type" in text
        or "response_format" in text
        or "b64_json" in text
        or "invalid_request_error" in text
    )


def _should_fallback_from_edits(response: requests.Response) -> bool:
    if response.status_code in {404, 405}:
        return True
    if response.status_code not in {400, 415, 422}:
        return False
    text = _safe_error_text(response).lower()
    return "edit" in text and any(token in text for token in ("unsupported", "not supported", "unknown endpoint"))


def _should_retry_as_form(response: requests.Response) -> bool:
    if response.status_code not in {400, 415, 422}:
        return False
    text = _safe_error_text(response).lower()
    return "unsupported content type" in text or "content-type" in text or "content type" in text


def _attempts_include_content_type_issue(attempts: list[tuple[str, requests.Response]]) -> bool:
    for _, response in attempts:
        if response.status_code not in {400, 415, 422}:
            continue
        text = _safe_error_text(response).lower()
        if "unsupported content type" in text or "content-type" in text or "content type" in text:
            return True
    return False


def _attempt_summary(attempts: list[tuple[str, requests.Response]]) -> str:
    parts = []
    for name, response in attempts[-4:]:
        parts.append(f"{name}:{response.status_code}:{_safe_error_text(response)[:120]}")
    return " | ".join(parts)


def _image_candidates(data):
    if isinstance(data, dict):
        for key in ("b64_json", "base64", "b64", "image", "image_base64", "result", "url", "image_url"):
            yield data.get(key)
        items = data.get("data")
        if isinstance(items, list):
            for item in items:
                yield from _image_candidates(item)
        elif isinstance(items, dict):
            yield from _image_candidates(items)
        outputs = data.get("output") or data.get("outputs") or data.get("images")
        if isinstance(outputs, list):
            for item in outputs:
                yield from _image_candidates(item)
        elif isinstance(outputs, dict):
            yield from _image_candidates(outputs)
        content = data.get("content")
        if isinstance(content, list):
            for item in content:
                yield from _image_candidates(item)
        elif isinstance(content, dict):
            yield from _image_candidates(content)
    elif isinstance(data, list):
        for item in data:
            yield from _image_candidates(item)
    elif isinstance(data, str):
        yield data


def _try_b64_decode(value: str) -> bytes:
    text = value.strip()
    if len(text) < 64:
        return b""
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception:
        try:
            decoded = base64.b64decode(text + "=" * (-len(text) % 4), validate=False)
        except Exception:
            return b""
    if decoded.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8", b"BM")):
        return decoded
    return b""


def _download_image(url: str, session: requests.Session) -> bytes:
    try:
        response = session.get(url, timeout=300)
        response.raise_for_status()
    except Exception:
        return b""
    content_type = response.headers.get("content-type", "").lower()
    if "image/" in content_type or response.content.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8", b"BM")):
        return response.content
    return b""


def _safe_error_text(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        text = response.text or ""
        extracted = _extract_sse_error_text(text)
        return (extracted or text)[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("type") or error.get("code") or "")
            return message[:500] or _response_shape(data)
        if isinstance(error, str):
            return error[:500]
    return _response_shape(data)


def _extract_sse_error_text(text: str) -> str:
    chunks = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        payload = stripped.split(":", 1)[1].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = __import__("json").loads(payload)
        except Exception:
            chunks.append(payload)
            continue
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                chunks.append(str(error.get("message") or error.get("type") or error.get("code") or ""))
            elif isinstance(error, str):
                chunks.append(error)
            elif data.get("message"):
                chunks.append(str(data.get("message")))
    return " ".join(item for item in chunks if item)


def _response_shape(data) -> str:
    if isinstance(data, dict):
        parts = [f"top_keys={sorted(str(key) for key in data.keys())[:12]}"]
        if isinstance(data.get("data"), list):
            parts.append(f"data_len={len(data['data'])}")
            if data["data"] and isinstance(data["data"][0], dict):
                parts.append(f"data0_keys={sorted(str(key) for key in data['data'][0].keys())[:12]}")
        if isinstance(data.get("output"), list):
            parts.append(f"output_len={len(data['output'])}")
            if data["output"] and isinstance(data["output"][0], dict):
                parts.append(f"output0_keys={sorted(str(key) for key in data['output'][0].keys())[:12]}")
        error = data.get("error")
        if isinstance(error, dict):
            parts.append(f"error_keys={sorted(str(key) for key in error.keys())[:12]}")
            if error.get("message"):
                parts.append(f"error_message={str(error.get('message'))[:240]}")
        return "; ".join(parts)
    if isinstance(data, list):
        first_type = type(data[0]).__name__ if data else "empty"
        return f"list_len={len(data)}; first_type={first_type}"
    return f"type={type(data).__name__}"
