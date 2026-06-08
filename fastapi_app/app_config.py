from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_DATA_ROOT = Path(os.environ.get("SUPERCODE_STATE_DIR", str(ROOT))).expanduser().resolve()
DEFAULT_WORKSPACE = ROOT


def hidden_windows_process_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def is_desktop_mode() -> bool:
    return os.environ.get("SUPERCODE_DESKTOP", "").strip() == "1"


def _resolve_backend_base_url() -> str:
    explicit = os.environ.get("SUPERCODE_BACKEND_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("SUPERCODE_HOST", "localhost").strip() or "localhost"
    if host in {"0.0.0.0", "::"}:
        host = "localhost"
    port = os.environ.get("SUPERCODE_PORT", "3001").strip() or "3001"
    return f"http://{host}:{port}"


BACKEND_BASE_URL = _resolve_backend_base_url()
DEFAULT_BROWSER_PREVIEW_URL = "http://localhost:8888"
DEFAULT_SELECTED_FILE = None
DEFAULT_OPEN_FILES = (
    "ChatLayout.tsx",
    "MessageList.tsx",
    "TerminalPanel.tsx",
    "ToolPanel.tsx",
    "FilePreview.tsx",
)


def _resolve_state_db_path() -> Path:
    explicit = os.environ.get("SUPERCODE_STATE_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    state_dir = os.environ.get("SUPERCODE_STATE_DIR", "").strip()
    if state_dir:
        return Path(state_dir).expanduser().resolve() / "state.sqlite3"
    if "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"supercode-state-pytest-{os.getpid()}.sqlite3"
    return ROOT / ".supercode" / "state.sqlite3"


STATE_DB_PATH = _resolve_state_db_path()

ALLOWED_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}


def normalize_reasoning_effort(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized == "default":
        return None
    if normalized not in ALLOWED_REASONING_EFFORTS:
        raise ValueError("reasoning_effort 仅支持 none、minimal、low、medium、high、xhigh 或 default。")
    return normalized
