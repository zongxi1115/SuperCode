from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fastapi_app.memory_store import remember_preference as save_memory_preference
from fastapi_app.settings_store import load_settings
from zonix.tools import ToolContext

from .tool_common import (
    IMAGE_GENERATION_ALLOWED_QUALITIES,
    IMAGE_GENERATION_EXTENSIONS_BY_MIME,
    IMAGE_GENERATION_OUTPUT_DIR,
    _relative_posix_path,
)


def _resolve_workspace_path(raw_path: str, ctx: ToolContext) -> Path:
    workspace = Path(ctx.workspace or ".").resolve()
    candidate = (workspace / raw_path).resolve()
    if workspace != candidate and workspace not in candidate.parents:
        raise ValueError(f"路径越界，不允许访问工作区外部: {raw_path}")
    return candidate


def remember_preference(ctx: ToolContext, content: str, scope: str = "global") -> dict[str, object]:
    """记录用户明确表达的长期偏好、工作流约束、交互风格或当前项目约定。"""

    normalized_content = content.strip()
    normalized_scope = scope.strip().lower() or "global"
    app_data_root = Path(
        ctx.metadata.get("app_data_root")
        or ctx.metadata.get("project_root")
        or "."
    )
    session_id = ctx.metadata.get("session_id")
    result = save_memory_preference(
        app_data_root,
        ctx.workspace,
        normalized_content,
        scope=normalized_scope,
        source_session_id=str(session_id) if session_id is not None else None,
        source_preview="",
    )
    if not result.get("saved"):
        reason = str(result.get("reason") or "unknown")
        if reason == "memory_disabled":
            return {"saved": False, "message": "长期记忆已关闭，未记录。"}
        if reason == "auto_learn_disabled":
            return {"saved": False, "message": "自动学习已关闭，未记录。"}
        return {"saved": False, "message": f"未记录：{reason}"}
    return {
        "saved": True,
        "created": bool(result.get("created")),
        "scope": result.get("scope"),
        "workspaceKey": result.get("workspaceKey"),
        "item": result.get("item"),
    }


class ImageGenerator:
    """按 OpenAI Images API 协议生成图片，并保存到本地工作区。"""

    def generate(
        self,
        ctx: ToolContext,
        prompt: str,
        filename: str = "",
        size: str = "",
        quality: str = "",
        background: str = "",
        output_format: str = "",
    ) -> dict[str, object]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        config = self._load_image_generation_config(ctx)
        resolved_size = self._normalize_size(
            size or config.get("size") or "1024x1024"
        )
        resolved_quality = self._normalize_option(
            quality or config.get("quality") or "auto",
            IMAGE_GENERATION_ALLOWED_QUALITIES,
            "quality",
        )
        resolved_output_format = output_format.strip().lower()
        if resolved_output_format and resolved_output_format not in {"png", "jpeg", "webp"}:
            raise ValueError("output_format 只支持 png、jpeg、webp。")

        request_payload: dict[str, object] = {
            "model": str(config["model"]),
            "prompt": prompt,
            "n": 1,
            "size": resolved_size,
        }
        if resolved_quality:
            request_payload["quality"] = resolved_quality
        resolved_background = background.strip().lower()
        if resolved_background:
            request_payload["background"] = resolved_background
        if resolved_output_format:
            request_payload["output_format"] = resolved_output_format

        response_payload = self._request_image_generation(config, request_payload)
        final_size = str(request_payload.get("size") or resolved_size)
        image_bytes, mime_type, source_kind = self._extract_image_bytes(response_payload)
        extension = self._choose_extension(
            mime_type=mime_type,
            output_format=resolved_output_format,
        )
        target = self._resolve_output_target(
            raw_filename=filename.strip(),
            extension=extension,
            prompt=prompt,
            context=ctx,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)

        relative_path = _relative_posix_path(target, Path(ctx.workspace or ".").resolve())
        return {
            "summary": f"已生成图片并保存到 {relative_path}",
            "file": relative_path,
            "absolute_path": str(target),
            "mime_type": mime_type,
            "bytes": len(image_bytes),
            "model": str(config["model"]),
            "size": final_size,
            "quality": resolved_quality,
            "source": source_kind,
        }

    def _load_image_generation_config(self, context: ToolContext) -> dict[str, object]:
        app_data_root = Path(
            context.metadata.get("app_data_root")
            or context.metadata.get("project_root")
            or "."
        )
        raw_config = load_settings(app_data_root).get("imageGeneration")
        config = raw_config if isinstance(raw_config, dict) else {}

        if not bool(config.get("enabled")):
            raise RuntimeError("图片生成工具未启用，请先在设置中启用并配置图片生成 API。")

        base_url = str(config.get("baseUrl") or "").strip().rstrip("/")
        api_key = str(config.get("apiKey") or "").strip()
        model = str(config.get("model") or "").strip()
        missing = [
            label
            for label, value in (
                ("Base URL", base_url),
                ("API Key", api_key),
                ("Model", model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"图片生成配置缺少 {', '.join(missing)}。")

        return {
            **config,
            "baseUrl": base_url,
            "apiKey": api_key,
            "model": model,
        }

    def _normalize_option(
        self,
        value: object,
        allowed_values: set[str],
        field_name: str,
    ) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in allowed_values:
            allowed = ", ".join(sorted(allowed_values))
            raise ValueError(f"{field_name} 只支持：{allowed}")
        return normalized

    def _normalize_size(self, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return "1024x1024"
        return normalized

    def _request_image_generation(
        self,
        config: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        try:
            return self._send_image_generation_request(config, payload)
        except RuntimeError as exc:
            supported_sizes = self._extract_supported_sizes(str(exc))
            fallback_size = self._pick_fallback_size(
                supported_sizes,
                requested_size=str(payload.get("size") or ""),
            )
            if not fallback_size:
                raise
            payload["size"] = fallback_size
            return self._send_image_generation_request(config, payload)

    def _send_image_generation_request(
        self,
        config: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._image_generation_endpoint(str(config["baseUrl"])),
            data=body,
            headers={
                "Authorization": f"Bearer {config['apiKey']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "SuperCode/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"图片生成请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"图片生成请求失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("图片生成请求超时。") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"图片生成接口返回了无法解析的 JSON：{raw_body[:300]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("图片生成接口返回格式不正确。")
        return parsed

    def _extract_supported_sizes(self, error_detail: str) -> list[str]:
        if "size" not in error_detail.lower():
            return []
        return re.findall(r"\b\d{3,5}x\d{3,5}\b", error_detail.lower())

    def _pick_fallback_size(
        self,
        supported_sizes: list[str],
        *,
        requested_size: str,
    ) -> str | None:
        unique_sizes = list(dict.fromkeys(size for size in supported_sizes if "x" in size))
        if not unique_sizes:
            return None
        if requested_size in unique_sizes:
            return None

        requested_dimensions = self._parse_size_dimensions(requested_size)
        if requested_dimensions is None:
            return unique_sizes[0]
        requested_width, requested_height = requested_dimensions
        requested_ratio = requested_width / max(requested_height, 1)
        requested_area = requested_width * requested_height

        ranked_sizes: list[tuple[float, int, str]] = []
        for size in unique_sizes:
            dimensions = self._parse_size_dimensions(size)
            if dimensions is None:
                continue
            width, height = dimensions
            ratio_distance = abs((width / max(height, 1)) - requested_ratio)
            area_distance = abs((width * height) - requested_area)
            ranked_sizes.append((ratio_distance, area_distance, size))

        if not ranked_sizes:
            return unique_sizes[0]
        ranked_sizes.sort(key=lambda item: (item[0], item[1]))
        return ranked_sizes[0][2]

    def _parse_size_dimensions(self, size: str) -> tuple[int, int] | None:
        match = re.fullmatch(r"(\d{3,5})x(\d{3,5})", size.strip().lower())
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    def _image_generation_endpoint(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/images/generations"):
            return normalized
        return f"{normalized}/images/generations"

    def _extract_image_bytes(
        self,
        payload: dict[str, object],
    ) -> tuple[bytes, str, str]:
        image_item = self._first_image_item(payload)
        image_url = str(image_item.get("url") or "").strip()
        if image_url:
            image_bytes, mime_type = self._download_image(image_url)
            return image_bytes, mime_type, "url"

        b64_json = str(image_item.get("b64_json") or "").strip()
        if b64_json:
            try:
                image_bytes = base64.b64decode(b64_json, validate=True)
            except binascii.Error as exc:
                raise RuntimeError("图片生成接口返回了无效的 b64_json。") from exc
            return image_bytes, self._sniff_mime_type(image_bytes, ""), "b64_json"

        raise RuntimeError("图片生成接口未返回 url 或 b64_json。")

    def _first_image_item(self, payload: dict[str, object]) -> dict[str, object]:
        data = payload.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first

        if isinstance(payload.get("url"), str) or isinstance(payload.get("b64_json"), str):
            return payload

        raise RuntimeError("图片生成接口未返回 data[0]。")

    def _download_image(self, image_url: str) -> tuple[bytes, str]:
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("图片生成接口返回了不支持下载的 URL。")

        request = Request(
            image_url,
            headers={
                "Accept": "image/*,*/*;q=0.8",
                "User-Agent": "SuperCode/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=120) as response:
                image_bytes = response.read()
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as exc:
            raise RuntimeError(f"下载生成图片失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"下载生成图片失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("下载生成图片超时。") from exc

        if not image_bytes:
            raise RuntimeError("下载生成图片为空。")
        return image_bytes, self._sniff_mime_type(image_bytes, content_type)

    def _sniff_mime_type(self, image_bytes: bytes, content_type: str) -> str:
        mime_type = content_type.split(";", 1)[0].strip().lower()
        if mime_type.startswith("image/"):
            return mime_type
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
            return "image/gif"
        return "image/png"

    def _choose_extension(self, *, mime_type: str, output_format: str) -> str:
        if output_format == "jpeg":
            return ".jpg"
        if output_format:
            return f".{output_format}"
        return IMAGE_GENERATION_EXTENSIONS_BY_MIME.get(
            mime_type,
            mimetypes.guess_extension(mime_type) or ".png",
        )

    def _resolve_output_target(
        self,
        *,
        raw_filename: str,
        extension: str,
        prompt: str,
        context: ToolContext,
    ) -> Path:
        if raw_filename:
            target = _resolve_workspace_path(raw_filename, context)
            allowed_extensions = set(IMAGE_GENERATION_EXTENSIONS_BY_MIME.values())
            if target.suffix.lower() not in allowed_extensions:
                target = target.with_suffix(extension)
            return target

        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        return _resolve_workspace_path(
            f"{IMAGE_GENERATION_OUTPUT_DIR}/image-{timestamp}-{digest}{extension}",
            context,
        )


def generate_image(
    ctx: ToolContext,
    prompt: str,
    filename: str = "",
    size: str = "",
    quality: str = "",
    background: str = "",
    output_format: str = "",
) -> dict[str, object]:
    """生成图片并保存到本地文件，返回工作区内路径。"""

    return _IMAGE_GENERATOR.generate(
        ctx,
        prompt=prompt,
        filename=filename,
        size=size,
        quality=quality,
        background=background,
        output_format=output_format,
    )


def get_docs(ctx: ToolContext, type: str) -> dict[str, object]:  # noqa: A002
    """按文档类型获取内置教程/流程文档。"""

    doc_type = type.strip()
    if doc_type != "environment_setup":
        raise ValueError("未知文档类型。可选值：environment_setup。")

    return {
        "type": "environment_setup",
        "title": "用户缺少环境时的渐进式处理流程",
        "content": "\n".join(
            [
                "适用场景：用户机器缺少命令、运行时、SDK、系统包，命令未加入 PATH，或当前任务需要先找到并安装本机依赖。",
                "",
                "核心原则：少量、分层、可执行。先告诉用户当前卡在哪里，再只暴露下一步必要操作；不要一开始把安装、配置、验证和故障排查全部倒给用户。",
                "",
                "1. 说明阻塞",
                "- 用一句话说明缺少什么，以及它为什么阻止当前任务继续。",
                "- 示例：当前缺少 ffmpeg，所以不能继续处理视频转码。",
                "",
                "2. 先确认缺失",
                "- 优先检查命令是否存在和版本是否可用，例如 `<command> --version`。",
                "- Windows 上如果怀疑 PATH 未生效，可提示用户重新打开终端，或检查 `where <command>`。",
                "- 不要仅凭一次报错就直接安装；先区分未安装、PATH 未配置、当前 shell 未刷新三种情况。",
                "",
                "3. 搜索安装候选",
                "- Windows 系统包优先使用 winget 搜索：`winget search \"<包名>\"`。",
                "- 向用户解释搜索结果里的 Name、Id、Version、Source，重点确认 Id 和 Source。",
                "- 包名不确定时先搜索宽泛关键词；拿到结果后优先选择官方或可信发布者的精确 Id。",
                "",
                "4. 安装前确认",
                "- 安装会改变用户机器环境，除非用户已经明确要求安装，否则先展示将执行的命令并等待确认。",
                "- winget 安装优先使用精确 Id：`winget install --id <Package.Id> --exact --source winget`。",
                "- 不要安装来源不明的包，不要用未经审查的 curl pipe shell。",
                "",
                "5. 安装后验证",
                "- 安装完成后重新打开终端或刷新 PATH，再运行版本命令验证。",
                "- 如果仍不可用，再检查 PATH、安装位置、shell 环境和权限。",
                "",
                "交互风格：用户只问下一步时只给下一步；用户要求你操作时再调用命令工具。需要搜索包时，先执行 winget search，把候选说清楚，再决定安装命令。",
            ]
        ),
    }


class BrowserPreview:
    """为前端内置浏览器生成可访问的预览地址。"""

    def open(self, ctx: ToolContext, url: str = "", path: str = "", target: str = "") -> dict[str, str]:
        raw_path = path.strip()
        raw_url = url.strip()
        raw_target = target.strip()

        if raw_path and raw_url:
            raise ValueError(
                "path 和 url 只能传一个。path 用于本地文件，url 用于网络地址。"
            )
        if raw_url:
            selected_kind = "url"
            selected_target = raw_url
        elif raw_path:
            selected_kind = "path"
            selected_target = raw_path
        elif raw_target:
            selected_kind = "url" if self._looks_like_url(raw_target) else "path"
            selected_target = raw_target
        else:
            raise ValueError(
                "必须提供 url 或 path。url 用于网络地址，path 用于本地文件或目录。"
            )

        backend_base_url = str(
            ctx.metadata.get("backend_base_url", "http://localhost:3001")
        ).rstrip("/")
        if selected_kind == "url":
            resolved_url = self._normalize_url(selected_target)
            return {
                "target": selected_target,
                "resolved_url": resolved_url,
                "source_type": "network_url",
            }

        session_id = str(ctx.metadata.get("session_id", "")).strip()
        if not session_id:
            raise RuntimeError("当前会话缺少 session_id，无法生成预览地址。")

        resolved_path = _resolve_workspace_path(selected_target, ctx)
        preview_target = self._resolve_preview_target(resolved_path)
        workspace = Path(ctx.workspace or ".").resolve()
        try:
            relative_preview_path = preview_target.relative_to(workspace).as_posix()
        except ValueError as exc:
            raise ValueError(f"预览路径不在工作区内: {selected_target}") from exc

        encoded_preview_path = quote(relative_preview_path, safe="/")
        return {
            "target": selected_target,
            "absolute_path": str(preview_target),
            "resolved_url": f"{backend_base_url}/api/sessions/{session_id}/preview/{encoded_preview_path}",
            "source_type": "local_file",
        }

    def _looks_like_url(self, value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https", "file"}:
            return True
        if value.startswith(("localhost:", "127.0.0.1:", "0.0.0.0:", "[::1]:")):
            return True
        return bool(re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(:\d+)?([/?#].*)?$", value))

    def _normalize_url(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https", "file"}:
            return value
        return f"http://{value}"

    def _resolve_preview_target(self, target: Path) -> Path:
        if target.is_dir():
            for entry_name in ("index.html", "index.htm"):
                candidate = target / entry_name
                if candidate.exists() and candidate.is_file():
                    return candidate
            raise FileNotFoundError(f"目录下未找到可预览入口文件: {target}")
        if not target.exists():
            raise FileNotFoundError(f"预览目标不存在: {target}")
        if not target.is_file():
            raise ValueError(f"预览目标不是文件: {target}")
        return target


_IMAGE_GENERATOR = ImageGenerator()
_BROWSER_PREVIEW = BrowserPreview()


def open_browser(
    ctx: ToolContext,
    url: str = "",
    path: str = "",
    target: str = "",
) -> dict[str, object]:
    """打开内置浏览器预览；url 用于网络地址，path/target 用于本地文件或目录。"""

    return _BROWSER_PREVIEW.open(ctx, url=url, path=path, target=target)

