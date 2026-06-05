from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from fastapi_app.workspace_utils import resolve_workspace_path

PROJECT_DOCS_RELATIVE_PATH = ".supercode/project-docs.md"
PROJECT_DOCS_DIR_RELATIVE_PATH = ".supercode/project-docs"
PROJECT_DOCS_INDEX_RELATIVE_PATH = ".supercode/project-docs/index.json"
DEFAULT_PROJECT_DOCS_MARKDOWN = "# 项目文档\n\n"
DEFAULT_PROJECT_DOC_ID = "main"
_DOCUMENT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def _workspace_child_path(workspace: str, relative_path: str) -> Path:
    workspace_root = resolve_workspace_path(workspace)
    target = (workspace_root / relative_path).resolve()
    if workspace_root != target and workspace_root not in target.parents:
        raise HTTPException(status_code=400, detail="项目文档路径越界")
    return target


def project_docs_path(workspace: str) -> Path:
    return _workspace_child_path(workspace, PROJECT_DOCS_RELATIVE_PATH)


def _project_docs_index_path(workspace: str) -> Path:
    return _workspace_child_path(workspace, PROJECT_DOCS_INDEX_RELATIVE_PATH)


def _document_file_relative_path(document_id: str) -> str:
    if document_id == DEFAULT_PROJECT_DOC_ID:
        return PROJECT_DOCS_RELATIVE_PATH
    return f"{PROJECT_DOCS_DIR_RELATIVE_PATH}/{document_id}.md"


def _validate_document_id(document_id: str) -> str:
    normalized = document_id.strip()
    if not _DOCUMENT_ID_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="项目文档 ID 无效")
    return normalized


def _default_document_entry() -> dict[str, str]:
    return {
        "id": DEFAULT_PROJECT_DOC_ID,
        "title": "项目文档",
        "relativePath": PROJECT_DOCS_RELATIVE_PATH,
    }


def _read_index(workspace: str) -> dict[str, Any]:
    target = _project_docs_index_path(workspace)
    if not target.exists():
        return {
            "version": 1,
            "activeId": DEFAULT_PROJECT_DOC_ID,
            "documents": [_default_document_entry()],
        }
    if not target.is_file():
        raise HTTPException(status_code=400, detail="项目文档索引不是文件")
    payload = json.loads(target.read_text(encoding="utf-8") or "{}")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        documents = [_default_document_entry()]

    normalized_documents: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in documents:
        if not isinstance(item, dict):
            continue
        document_id = str(item.get("id") or "").strip()
        if not document_id or not _DOCUMENT_ID_RE.fullmatch(document_id) or document_id in seen_ids:
            continue
        title = str(item.get("title") or "").strip() or "未命名文档"
        relative_path = str(item.get("relativePath") or "").strip() or _document_file_relative_path(document_id)
        normalized_documents.append({
            "id": document_id,
            "title": title,
            "relativePath": relative_path,
        })
        seen_ids.add(document_id)

    if DEFAULT_PROJECT_DOC_ID not in seen_ids:
        normalized_documents.insert(0, _default_document_entry())

    active_id = str(payload.get("activeId") or "").strip()
    if active_id not in {item["id"] for item in normalized_documents}:
        active_id = normalized_documents[0]["id"]

    return {
        "version": 1,
        "activeId": active_id,
        "documents": normalized_documents,
    }


def _write_index(workspace: str, payload: dict[str, Any]) -> None:
    target = _project_docs_index_path(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _entry_path(workspace: str, entry: dict[str, str]) -> Path:
    return _workspace_child_path(workspace, entry["relativePath"])


def _entry_payload(workspace: str, entry: dict[str, str], markdown: str | None = None) -> dict[str, Any]:
    target = _entry_path(workspace, entry)
    exists = target.exists() and target.is_file()
    payload: dict[str, Any] = {
        "id": entry["id"],
        "title": entry["title"],
        "path": str(target),
        "relativePath": entry["relativePath"],
        "exists": exists,
    }
    if markdown is not None:
        payload["markdown"] = markdown
    return payload


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if heading_match:
            return heading_match.group(1).strip()[:80] or fallback
        return stripped[:80]
    return fallback


def _get_document_entry(index_payload: dict[str, Any], document_id: str | None = None) -> dict[str, str]:
    target_id = document_id or str(index_payload.get("activeId") or DEFAULT_PROJECT_DOC_ID)
    target_id = _validate_document_id(target_id)
    for entry in index_payload["documents"]:
        if entry["id"] == target_id:
            return entry
    raise HTTPException(status_code=404, detail="项目文档不存在")


def list_project_docs(workspace: str) -> dict[str, Any]:
    index_payload = _read_index(workspace)
    return {
        "activeId": index_payload["activeId"],
        "documents": [
            _entry_payload(workspace, entry)
            for entry in index_payload["documents"]
        ],
    }


def read_project_docs(workspace: str, document_id: str | None = None) -> dict[str, Any]:
    index_payload = _read_index(workspace)
    entry = _get_document_entry(index_payload, document_id)
    if document_id is not None and index_payload.get("activeId") != entry["id"]:
        index_payload["activeId"] = entry["id"]
        _write_index(workspace, index_payload)

    target = _entry_path(workspace, entry)
    if not target.exists():
        return {
            "id": entry["id"],
            "title": entry["title"],
            "path": str(target),
            "relativePath": entry["relativePath"],
            "markdown": DEFAULT_PROJECT_DOCS_MARKDOWN,
            "exists": False,
        }
    if not target.is_file():
        raise HTTPException(status_code=400, detail="项目文档路径不是文件")
    markdown = target.read_text(encoding="utf-8")
    return {
        "id": entry["id"],
        "title": entry["title"],
        "path": str(target),
        "relativePath": entry["relativePath"],
        "markdown": markdown,
        "exists": True,
    }


def write_project_docs(workspace: str, markdown: str, document_id: str | None = None) -> dict[str, Any]:
    index_payload = _read_index(workspace)
    entry = _get_document_entry(index_payload, document_id)
    entry["title"] = _extract_title(markdown, entry["title"])
    index_payload["activeId"] = entry["id"]
    _write_index(workspace, index_payload)

    target = _entry_path(workspace, entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return {
        "id": entry["id"],
        "title": entry["title"],
        "path": str(target),
        "relativePath": entry["relativePath"],
        "markdown": markdown,
        "exists": True,
    }


def create_project_doc(workspace: str, title: str | None = None) -> dict[str, Any]:
    index_payload = _read_index(workspace)
    document_id = uuid.uuid4().hex[:12]
    document_title = (title or "").strip() or f"新文档 {len(index_payload['documents']) + 1}"
    entry = {
        "id": document_id,
        "title": document_title,
        "relativePath": _document_file_relative_path(document_id),
    }
    markdown = f"# {document_title}\n\n"
    target = _entry_path(workspace, entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    index_payload["documents"].append(entry)
    index_payload["activeId"] = document_id
    _write_index(workspace, index_payload)
    return _entry_payload(workspace, entry, markdown)
