from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import uvicorn


def _read_port() -> int:
    raw_port = os.environ.get("SUPERCODE_PORT", "3001").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"SUPERCODE_PORT must be an integer, got {raw_port!r}") from exc
    if port <= 0 or port > 65535:
        raise SystemExit(f"SUPERCODE_PORT must be between 1 and 65535, got {port}")
    return port


def _ensure_state_dir() -> None:
    raw_state_dir = os.environ.get("SUPERCODE_STATE_DIR", "").strip()
    if not raw_state_dir:
        return
    Path(raw_state_dir).expanduser().resolve().mkdir(parents=True, exist_ok=True)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            wintypes.DWORD(pid),
        )
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _start_parent_watchdog() -> None:
    raw_pid = os.environ.get("SUPERCODE_PARENT_PID", "").strip()
    if not raw_pid:
        return
    try:
        parent_pid = int(raw_pid)
    except ValueError:
        return

    def watch_parent() -> None:
        while True:
            time.sleep(2)
            if not _process_exists(parent_pid):
                os._exit(0)

    threading.Thread(target=watch_parent, daemon=True).start()


def main() -> None:
    host = os.environ.get("SUPERCODE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _read_port()
    _ensure_state_dir()
    _start_parent_watchdog()
    from fastapi_app.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
