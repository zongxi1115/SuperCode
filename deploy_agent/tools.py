from __future__ import annotations

import posixpath
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shlex
from typing import Any

from agent.tools import BaseTool, ToolContext
from coding_agent.tools import (
    DEFAULT_IGNORED_DIR_NAMES,
    READ_FILE_MAX_OUTPUT_CHARS,
    _build_powershell_utf8_command,
    _kill_process_tree,
)

try:
    import paramiko
except ImportError:  # pragma: no cover - optional dependency until environment installs it
    paramiko = None

LIST_FILES_MAX_ENTRIES = 400


@dataclass(slots=True)
class DeployConnection:
    session_id: str
    root_path: Path | PurePosixPath
    display_name: str
    description: str
    extra_info: str
    created_at: int
    host: str = ""
    username: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "root_path": str(self.root_path),
            "display_name": self.display_name,
            "description": self.description,
            "extra_info": self.extra_info,
            "created_at": self.created_at,
            "host": self.host,
            "username": self.username,
        }


class DeployConnectionManager:
    """管理部署目标连接。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._connections: dict[str, DeployConnection] = {}
        self._passwords: dict[str, str] = {}
        self._lock = threading.RLock()

    def create_connection(
        self,
        root_path: str,
        display_name: str = "",
        description: str = "",
        extra_info: str = "",
        host: str = "",
        username: str = "",
        password: str = "",
    ) -> dict[str, Any]:
        is_remote = bool(host.strip())
        if is_remote:
            if not username.strip():
                raise ValueError("远程连接必须提供 username。")
            if not password:
                raise ValueError("远程连接必须提供 password。")
        resolved_root = self._resolve_root_path(root_path) if not is_remote else self._normalize_remote_root(root_path)
        connection = DeployConnection(
            session_id=uuid.uuid4().hex,
            root_path=resolved_root,
            display_name=display_name.strip() or (host.strip() or resolved_root.name),
            description=description.strip(),
            extra_info=extra_info.strip(),
            created_at=int(time.time() * 1000),
            host=host.strip(),
            username=username.strip(),
        )
        with self._lock:
            self._connections[connection.session_id] = connection
            if is_remote:
                self._passwords[connection.session_id] = password
        return connection.to_payload()

    def register_connection(self, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("session_id") or "").strip()
        root_path = str(payload.get("root_path") or "").strip()
        if not session_id or not root_path:
            return

        host = str(payload.get("host") or "").strip()
        is_remote = bool(host)
        resolved_root = self._normalize_remote_root(root_path) if is_remote else Path(root_path).resolve()

        connection = DeployConnection(
            session_id=session_id,
            root_path=resolved_root,
            display_name=str(payload.get("display_name") or Path(root_path).name),
            description=str(payload.get("description") or ""),
            extra_info=str(payload.get("extra_info") or ""),
            created_at=int(payload.get("created_at") or int(time.time() * 1000)),
            host=host,
            username=str(payload.get("username") or ""),
        )
        with self._lock:
            self._connections[session_id] = connection

    def export_state(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                session_id: connection.to_payload()
                for session_id, connection in self._connections.items()
            }

    def list_connections(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [connection.to_payload() for connection in self._connections.values()]
        rows.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
        return rows

    def get_connection(self, session_id: str) -> DeployConnection:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id 不能为空。")
        with self._lock:
            connection = self._connections.get(normalized)
        if connection is None:
            raise KeyError(f"未找到 deploy session_id: {session_id}")
        return connection

    def has_password(self, session_id: str) -> bool:
        normalized = session_id.strip()
        if not normalized:
            return False
        with self._lock:
            connection = self._connections.get(normalized)
            if connection is None:
                return False
            if not connection.host:
                return True
            return normalized in self._passwords

    def get_password(self, session_id: str) -> str:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id 不能为空。")
        with self._lock:
            password = self._passwords.get(normalized)
        if password is None:
            raise KeyError(f"deploy session {session_id} 缺少远程凭据，请重新 connect。")
        return password

    def _resolve_root_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (self.workspace / raw_path).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"部署目录不存在: {raw_path}")
        if not candidate.is_dir():
            raise NotADirectoryError(f"部署目录不是文件夹: {raw_path}")
        return candidate

    def _normalize_remote_root(self, raw_path: str) -> PurePosixPath:
        candidate = (raw_path or "").strip()
        if not candidate:
            raise ValueError("远程连接必须提供 root_path。")
        if "\\" in candidate or (len(candidate) >= 2 and candidate[1] == ":"):
            raise ValueError(
                "远程 root_path 必须是 Linux 服务器上的绝对路径，例如 /home/ubuntu/app，"
                "不能填写本地 Windows 路径。"
            )
        if not candidate.startswith("/"):
            raise ValueError("远程 root_path 必须是以 / 开头的 Linux 绝对路径。")
        normalized = posixpath.normpath(candidate)
        return PurePosixPath(normalized)


class DeployBaseTool(BaseTool):
    """部署场景工具基类。"""

    def _get_connection_manager(self, context: ToolContext) -> DeployConnectionManager:
        manager = context.metadata.get("deploy_connection_manager")
        if not isinstance(manager, DeployConnectionManager):
            raise RuntimeError("当前会话缺少 deploy connection manager。")
        return manager

    def _get_connection(self, context: ToolContext, session_id: str) -> DeployConnection:
        manager = self._get_connection_manager(context)
        try:
            return manager.get_connection(session_id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

    def _is_remote_connection(self, connection: DeployConnection) -> bool:
        return bool(connection.host.strip())

    def _resolve_connection_path(
        self,
        connection: DeployConnection,
        raw_path: str,
    ) -> Path | str:
        if self._is_remote_connection(connection):
            root_path = self._remote_root_path(connection)
            normalized_raw = str(raw_path or ".").strip() or "."
            if posixpath.isabs(normalized_raw):
                candidate = posixpath.normpath(normalized_raw)
            else:
                candidate = posixpath.normpath(posixpath.join(root_path, normalized_raw))
            root_prefix = root_path.rstrip("/")
            if candidate != root_path and not candidate.startswith(f"{root_prefix}/"):
                raise ValueError(f"路径越界，不允许访问 deploy session 外部: {raw_path}")
            return candidate

        root_path = Path(connection.root_path).resolve()
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (root_path / raw_path).resolve()
        else:
            candidate = candidate.resolve()
        if candidate != root_path and root_path not in candidate.parents:
            raise ValueError(f"路径越界，不允许访问 deploy session 外部: {raw_path}")
        return candidate

    def _format_numbered_text(
        self,
        file_path: str,
        content: str,
        start_line: int = 1,
        metadata_lines: list[str] | None = None,
    ) -> str:
        lines = content.splitlines()
        rendered = [f"# File: {file_path}"]
        if metadata_lines:
            rendered.extend(metadata_lines)
        if not lines:
            rendered.append(f"{start_line} | ")
            return "\n".join(rendered)

        for index, line in enumerate(lines, start=start_line):
            rendered.append(f"{index} | {line}")
        return "\n".join(rendered)

    def _parse_timeout(self, arguments: dict[str, object]) -> int:
        raw_timeout = arguments.get("timeout")
        if raw_timeout is None:
            raise ValueError("timeout 为必填参数，单位秒。")
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout 必须是正整数秒数。") from exc
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0。")
        return timeout

    def _validate_command(self, command: str) -> None:
        normalized = command.lower()
        blocked_fragments = [
            "rm -rf",
            "rmdir /s",
            "del /s",
            "git push --force",
            "format ",
            "mkfs",
            "shutdown",
            "reboot",
            "poweroff",
            "| bash",
        ]
        for fragment in blocked_fragments:
            if fragment in normalized:
                raise ValueError(f"命令存在风险，已拒绝执行: {command}")

    def _build_shell_command(self, command: str) -> list[str]:
        if sys.platform == "win32":
            return _build_powershell_utf8_command(command)
        return ["/bin/bash", "-lc", command]

    def _remote_root_path(self, connection: DeployConnection) -> str:
        root = str(connection.root_path).strip() or "/"
        normalized = posixpath.normpath(root)
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _relative_remote_path(self, root_path: str, candidate: str) -> str:
        if candidate == root_path:
            return "."
        return posixpath.relpath(candidate, root_path)

    def _require_paramiko(self) -> Any:
        if paramiko is None:
            raise RuntimeError("当前环境缺少 paramiko，无法执行远程 SSH/SFTP 操作。")
        return paramiko

    def _connect_ssh_client(
        self,
        context: ToolContext,
        session_id: str,
        connection: DeployConnection,
    ) -> Any:
        paramiko_module = self._require_paramiko()
        manager = self._get_connection_manager(context)
        if not self._is_remote_connection(connection):
            raise RuntimeError("当前连接不是远程连接。")
        try:
            password = manager.get_password(session_id)
        except KeyError as exc:
            raise RuntimeError(str(exc)) from exc

        client = paramiko_module.SSHClient()
        client.set_missing_host_key_policy(paramiko_module.AutoAddPolicy())
        try:
            client.connect(
                hostname=connection.host,
                username=connection.username,
                password=password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10,
                look_for_keys=False,
                allow_agent=False,
            )
        except Exception as exc:  # noqa: BLE001 - needs to surface SSH errors cleanly
            try:
                client.close()
            except Exception:
                pass
            raise RuntimeError(f"SSH 连接失败: {exc}") from exc
        return client

    def _ensure_remote_directory(self, sftp: Any, remote_dir: str) -> None:
        normalized = posixpath.normpath(remote_dir)
        if normalized in {"", "/"}:
            return
        parent = posixpath.dirname(normalized)
        if parent and parent != normalized:
            self._ensure_remote_directory(sftp, parent)
        try:
            sftp.stat(normalized)
        except Exception:
            try:
                sftp.mkdir(normalized)
            except Exception as exc:
                try:
                    sftp.stat(normalized)
                except Exception:
                    raise RuntimeError(f"创建远程目录失败: {normalized} ({exc})") from exc

    def _decode_remote_bytes(self, value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _resolve_workspace_source_path(
        self,
        raw_path: str,
        context: ToolContext,
    ) -> Path:
        workspace = context.workspace.resolve()
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (workspace / raw_path).resolve()
        else:
            candidate = candidate.resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise ValueError(f"路径越界，不允许访问工作区外部: {raw_path}")
        return candidate

    def _normalize_string_list_argument(
        self,
        arguments: dict[str, object],
        *keys: str,
    ) -> list[str]:
        values: list[str] = []
        for key in keys:
            raw_value = arguments.get(key)
            if raw_value is None:
                continue
            if isinstance(raw_value, str):
                normalized = raw_value.strip()
                if normalized:
                    values.append(normalized)
                continue
            if isinstance(raw_value, list):
                for item in raw_value:
                    if not isinstance(item, str):
                        raise ValueError(f"{key} 数组里的每一项都必须是字符串。")
                    normalized = item.strip()
                    if normalized:
                        values.append(normalized)
                continue
            raise ValueError(f"{key} 只能是字符串或字符串数组。")
        return values


class ConnectTool(DeployBaseTool):
    name = "connect"
    description = "请求用户填写部署目标信息并建立 deploy session，成功后会返回 session_id。"
    parameters_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, object]:
        return {
            "requires_user_input": True,
            "input_kind": "deploy_connect",
            "title": "连接部署目标",
            "message": (
                "请填写部署目标信息。"
                "如果填写了服务器地址，root_path 必须是远程 Linux 服务器上的绝对路径，"
                "例如 /home/ubuntu/app 或 /var/www/myapp；不要填写本地 Windows 路径。"
            ),
            "fields": [
                {
                    "name": "host",
                    "label": "服务器地址",
                    "type": "text",
                    "required": False,
                    "placeholder": "远程示例: 192.168.1.100 或 example.com；留空表示本地部署目录",
                },
                {
                    "name": "username",
                    "label": "用户名",
                    "type": "text",
                    "required": False,
                    "placeholder": "远程示例: root 或 ubuntu",
                },
                {
                    "name": "password",
                    "label": "密码",
                    "type": "password",
                    "required": False,
                    "placeholder": "••••••••",
                    "sensitive": True,
                    "do_not_echo": True,
                },
                {
                    "name": "root_path",
                    "label": "访问根路径",
                    "type": "path",
                    "required": True,
                    "placeholder": (
                        "远程 Linux 示例: /home/ubuntu/app、/var/www/app、/etc/nginx、/"
                        "；本地示例: D:/project/dist"
                    ),
                },
                {
                    "name": "display_name",
                    "label": "会话名称",
                    "type": "text",
                    "required": False,
                    "placeholder": "production-web",
                },
                {
                    "name": "description",
                    "label": "备注",
                    "type": "textarea",
                    "required": False,
                    "placeholder": "例如 Vercel 项目根目录或服务器发布目录",
                },
                {
                    "name": "extra_info",
                    "label": "附加信息",
                    "type": "textarea",
                    "required": False,
                    "placeholder": (
                        "可填写站点域名、Nginx 配置位置、systemd 服务名、部署方式、"
                        "需要改的目录等上下文"
                    ),
                },
            ],
        }


class DeployListFilesTool(DeployBaseTool):
    name = "list_files"
    description = "列出 deploy session 下的目录结构，参数：session_id、path。path 相对 deploy session 根目录。"
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["session_id"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        session_id = str(arguments.get("session_id") or "").strip()
        relative_path = str(arguments.get("path") or ".")
        connection = self._get_connection(context, session_id)
        if self._is_remote_connection(connection):
            return self._run_remote(arguments, context, session_id, relative_path, connection)
        target = self._resolve_connection_path(connection, relative_path)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {relative_path}")

        rendered = [
            f"# Session: {session_id}",
            f"# Root: {connection.root_path}",
            f"# Path: {relative_path}",
        ]
        entries: list[str] = []
        self._render_tree(target, connection.root_path, entries)
        if not entries:
            rendered.append("(empty)")
        else:
            rendered.extend(entries[:LIST_FILES_MAX_ENTRIES])
            if len(entries) > LIST_FILES_MAX_ENTRIES:
                rendered.append("... [truncated]")
        return "\n".join(rendered)

    def _render_tree(self, target: Path, root_path: Path, rendered: list[str]) -> None:
        for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if child.is_dir() and child.name in DEFAULT_IGNORED_DIR_NAMES:
                continue
            relative = str(child.relative_to(root_path)).replace("\\", "/")
            rendered.append(f"{relative}/" if child.is_dir() else relative)
            if child.is_dir() and len(rendered) < LIST_FILES_MAX_ENTRIES:
                self._render_tree(child, root_path, rendered)

    def _run_remote(
        self,
        arguments: dict[str, object],
        context: ToolContext,
        session_id: str,
        relative_path: str,
        connection: DeployConnection,
    ) -> str:
        target = str(self._resolve_connection_path(connection, relative_path))
        client = self._connect_ssh_client(context, session_id, connection)
        try:
            sftp = client.open_sftp()
            try:
                attrs = sftp.stat(target)
                if not stat.S_ISDIR(attrs.st_mode):
                    raise NotADirectoryError(f"目标不是目录: {relative_path}")
                rendered = [
                    f"# Session: {session_id}",
                    f"# Root: {self._remote_root_path(connection)}",
                    f"# Path: {relative_path}",
                ]
                entries: list[str] = []
                self._render_remote_tree(sftp, target, self._remote_root_path(connection), entries)
                if not entries:
                    rendered.append("(empty)")
                else:
                    rendered.extend(entries[:LIST_FILES_MAX_ENTRIES])
                    if len(entries) > LIST_FILES_MAX_ENTRIES:
                        rendered.append("... [truncated]")
                return "\n".join(rendered)
            finally:
                sftp.close()
        finally:
            client.close()

    def _render_remote_tree(
        self,
        sftp: Any,
        target: str,
        root_path: str,
        rendered: list[str],
    ) -> None:
        children = sorted(
            sftp.listdir_attr(target),
            key=lambda item: (not stat.S_ISDIR(item.st_mode), item.filename.lower()),
        )
        for child in children:
            child_path = posixpath.join(target, child.filename)
            if stat.S_ISDIR(child.st_mode) and child.filename in DEFAULT_IGNORED_DIR_NAMES:
                continue
            relative = self._relative_remote_path(root_path, child_path)
            rendered.append(f"{relative}/" if stat.S_ISDIR(child.st_mode) else relative)
            if stat.S_ISDIR(child.st_mode) and len(rendered) < LIST_FILES_MAX_ENTRIES:
                self._render_remote_tree(sftp, child_path, root_path, rendered)


class DeployReadFileTool(DeployBaseTool):
    name = "read_file"
    description = (
        "读取 deploy session 下的文件内容，参数：session_id、path，可选 start_line、end_line。"
        "返回带行号内容；大文件应分段读取。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["session_id", "path"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        session_id = str(arguments.get("session_id") or "").strip()
        relative_path = str(arguments.get("path") or "").strip()
        if not relative_path:
            raise ValueError("path 不能为空。")

        connection = self._get_connection(context, session_id)
        if self._is_remote_connection(connection):
            return self._run_remote(arguments, context, session_id, relative_path, connection)
        target = self._resolve_connection_path(connection, relative_path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {relative_path}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {relative_path}")

        start_line = max(1, int(arguments.get("start_line") or 1))
        raw_end_line = arguments.get("end_line")
        end_line = int(raw_end_line) if raw_end_line is not None else None
        if end_line is not None and end_line < start_line:
            raise ValueError("end_line 不能小于 start_line。")

        content = target.read_text(encoding="utf-8")
        lines = content.splitlines()
        total_lines = len(lines)
        actual_start = start_line if start_line <= total_lines else total_lines + 1
        actual_end = total_lines if end_line is None else min(end_line, total_lines)
        selected_lines = lines[start_line - 1 : actual_end] if total_lines else []
        eof = total_lines == 0 or actual_end >= total_lines or start_line > total_lines
        selected_content = "\n".join(selected_lines)

        metadata_lines = [
            f"# Session: {session_id}",
            f"# Requested lines: {start_line}-{end_line if end_line is not None else 'EOF'}",
            f"# Actual lines: {actual_start}-{actual_end}",
            f"# Total lines: {total_lines}",
            f"# EOF: {'true' if eof else 'false'}",
        ]
        if start_line > total_lines and total_lines > 0:
            metadata_lines.append("# Note: requested range starts beyond end of file.")

        rendered = self._format_numbered_text(
            file_path=relative_path,
            content=selected_content,
            start_line=actual_start,
            metadata_lines=metadata_lines,
        )
        if len(rendered) > READ_FILE_MAX_OUTPUT_CHARS:
            raise ValueError(
                f"读取结果超过 {READ_FILE_MAX_OUTPUT_CHARS} 个字符，请缩小范围后重试。"
            )
        return rendered

    def _run_remote(
        self,
        arguments: dict[str, object],
        context: ToolContext,
        session_id: str,
        relative_path: str,
        connection: DeployConnection,
    ) -> str:
        target = str(self._resolve_connection_path(connection, relative_path))
        client = self._connect_ssh_client(context, session_id, connection)
        try:
            sftp = client.open_sftp()
            try:
                attrs = sftp.stat(target)
                if not stat.S_ISREG(attrs.st_mode):
                    raise IsADirectoryError(f"目标不是文件: {relative_path}")

                start_line = max(1, int(arguments.get("start_line") or 1))
                raw_end_line = arguments.get("end_line")
                end_line = int(raw_end_line) if raw_end_line is not None else None
                if end_line is not None and end_line < start_line:
                    raise ValueError("end_line 不能小于 start_line。")

                with sftp.open(target, "r") as remote_file:
                    content = self._decode_remote_bytes(remote_file.read())

                lines = content.splitlines()
                total_lines = len(lines)
                actual_start = start_line if start_line <= total_lines else total_lines + 1
                actual_end = total_lines if end_line is None else min(end_line, total_lines)
                selected_lines = lines[start_line - 1 : actual_end] if total_lines else []
                eof = total_lines == 0 or actual_end >= total_lines or start_line > total_lines
                selected_content = "\n".join(selected_lines)

                metadata_lines = [
                    f"# Session: {session_id}",
                    f"# Requested lines: {start_line}-{end_line if end_line is not None else 'EOF'}",
                    f"# Actual lines: {actual_start}-{actual_end}",
                    f"# Total lines: {total_lines}",
                    f"# EOF: {'true' if eof else 'false'}",
                ]
                if start_line > total_lines and total_lines > 0:
                    metadata_lines.append("# Note: requested range starts beyond end of file.")

                rendered = self._format_numbered_text(
                    file_path=relative_path,
                    content=selected_content,
                    start_line=actual_start,
                    metadata_lines=metadata_lines,
                )
                if len(rendered) > READ_FILE_MAX_OUTPUT_CHARS:
                    raise ValueError(
                        f"读取结果超过 {READ_FILE_MAX_OUTPUT_CHARS} 个字符，请缩小范围后重试。"
                    )
                return rendered
            finally:
                sftp.close()
        finally:
            client.close()


class DeployExecuteTool(DeployBaseTool):
    name = "execute"
    description = (
        "在 deploy session 下执行命令，参数：session_id、cwd、command、timeout（秒）。"
        "cwd 相对 deploy session 根目录。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "cwd": {"type": "string"},
            "command": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["session_id", "command", "timeout"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        session_id = str(arguments.get("session_id") or "").strip()
        cwd = str(arguments.get("cwd") or ".").strip() or "."
        command = str(arguments.get("command") or "").strip()
        timeout = self._parse_timeout(arguments)
        if not command:
            raise ValueError("command 不能为空。")
        self._validate_command(command)

        connection = self._get_connection(context, session_id)
        if self._is_remote_connection(connection):
            return self._run_remote(context, session_id, cwd, command, timeout, connection)
        working_directory = self._resolve_connection_path(connection, cwd)
        if not working_directory.exists():
            raise FileNotFoundError(f"cwd 不存在: {cwd}")
        if not working_directory.is_dir():
            raise NotADirectoryError(f"cwd 不是目录: {cwd}")

        process = subprocess.Popen(
            self._build_shell_command(command),
            cwd=working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise TimeoutError(f"命令执行超时（>{timeout} 秒）: {command}") from exc

        stdout = stdout.strip()
        stderr = stderr.strip()
        return "\n".join(
            [
                f"session_id: {session_id}",
                f"cwd: {working_directory}",
                f"exit_code: {process.returncode}",
                "stdout:",
                stdout or "(empty)",
                "stderr:",
                stderr or "(empty)",
            ]
        )

    def _run_remote(
        self,
        context: ToolContext,
        session_id: str,
        cwd: str,
        command: str,
        timeout: int,
        connection: DeployConnection,
    ) -> str:
        working_directory = str(self._resolve_connection_path(connection, cwd))
        client = self._connect_ssh_client(context, session_id, connection)
        try:
            transport = client.get_transport()
            if transport is None:
                raise RuntimeError("SSH transport 不可用。")
            channel = transport.open_session()
            try:
                channel.settimeout(timeout)
                remote_command = f"cd {shlex.quote(working_directory)} && {command}"
                channel.exec_command(remote_command)
                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []
                deadline = time.monotonic() + timeout

                while True:
                    if channel.recv_ready():
                        stdout_chunks.append(channel.recv(4096).decode("utf-8", errors="replace"))
                    if channel.recv_stderr_ready():
                        stderr_chunks.append(channel.recv_stderr(4096).decode("utf-8", errors="replace"))
                    if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"命令执行超时（>{timeout} 秒）: {command}")
                    time.sleep(0.05)

                exit_code = channel.recv_exit_status()
                stdout = "".join(stdout_chunks).strip()
                stderr = "".join(stderr_chunks).strip()
                return "\n".join(
                    [
                        f"session_id: {session_id}",
                        f"remote_host: {connection.host}",
                        f"cwd: {working_directory}",
                        f"exit_code: {exit_code}",
                        "stdout:",
                        stdout or "(empty)",
                        "stderr:",
                        stderr or "(empty)",
                    ]
                )
            except socket.timeout as exc:
                raise TimeoutError(f"命令执行超时（>{timeout} 秒）: {command}") from exc
            finally:
                try:
                    channel.close()
                except Exception:
                    pass
        finally:
            client.close()


class DeployTransferFilesTool(DeployBaseTool):
    name = "transfer_files"
    description = (
        "把当前工作区里的文件或目录复制到 deploy session 下。参数：session_id、"
        "path / file（都支持字符串或字符串数组，也兼容 paths / files）、"
        "target_dir（可选，默认 deploy 根目录）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "path": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
            },
            "file": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "target_dir": {"type": "string"},
        },
        "required": ["session_id"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, object]:
        session_id = str(arguments.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id 不能为空。")

        connection = self._get_connection(context, session_id)
        if self._is_remote_connection(connection):
            return self._run_remote(arguments, context, session_id, connection)

        target_dir = str(arguments.get("target_dir") or ".").strip() or "."
        target_root = self._resolve_connection_path(connection, target_dir)
        target_root.mkdir(parents=True, exist_ok=True)
        if not target_root.is_dir():
            raise NotADirectoryError(f"target_dir 不是目录: {target_dir}")

        path_inputs = self._normalize_string_list_argument(arguments, "path", "paths")
        file_inputs = self._normalize_string_list_argument(arguments, "file", "files")
        raw_sources = [("path", value) for value in path_inputs] + [("file", value) for value in file_inputs]
        if not raw_sources:
            raise ValueError("至少要提供 path 或 file。")

        workspace = context.workspace.resolve()
        transferred: list[dict[str, str]] = []
        seen_sources: set[str] = set()
        for source_kind, raw_source in raw_sources:
            source = self._resolve_workspace_source_path(raw_source, context)
            source_key = str(source)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)

            if not source.exists():
                raise FileNotFoundError(f"源路径不存在: {raw_source}")
            if source_kind == "file" and not source.is_file():
                raise IsADirectoryError(f"file 参数只能传文件: {raw_source}")

            relative_source = source.relative_to(workspace)
            destination = (target_root / relative_source).resolve()
            if destination != target_root and target_root not in destination.parents:
                raise ValueError(f"目标路径越界: {relative_source}")
            if source.is_dir() and (target_root == source or source in target_root.parents):
                raise ValueError(f"不能把目录复制到它自身或其子目录内: {raw_source}")
            if source == destination:
                raise ValueError(f"源路径和目标路径相同，拒绝重复复制: {raw_source}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
                transferred_type = "directory"
            else:
                shutil.copy2(source, destination)
                transferred_type = "file"

            transferred.append(
                {
                    "source": str(relative_source).replace("\\", "/"),
                    "destination": str(destination.relative_to(connection.root_path)).replace("\\", "/"),
                    "type": transferred_type,
                }
            )

        return {
            "session_id": session_id,
            "target_dir": str(target_root.relative_to(connection.root_path)).replace("\\", "/")
            if target_root != connection.root_path
            else ".",
            "count": len(transferred),
            "transferred": transferred,
        }

    def _run_remote(
        self,
        arguments: dict[str, object],
        context: ToolContext,
        session_id: str,
        connection: DeployConnection,
    ) -> dict[str, object]:
        target_dir = str(arguments.get("target_dir") or ".").strip() or "."
        target_root = str(self._resolve_connection_path(connection, target_dir))
        path_inputs = self._normalize_string_list_argument(arguments, "path", "paths")
        file_inputs = self._normalize_string_list_argument(arguments, "file", "files")
        raw_sources = [("path", value) for value in path_inputs] + [("file", value) for value in file_inputs]
        if not raw_sources:
            raise ValueError("至少要提供 path 或 file。")

        client = self._connect_ssh_client(context, session_id, connection)
        workspace = context.workspace.resolve()
        transferred: list[dict[str, str]] = []
        seen_sources: set[str] = set()

        try:
            sftp = client.open_sftp()
            try:
                self._ensure_remote_directory(sftp, target_root)
                for source_kind, raw_source in raw_sources:
                    source = self._resolve_workspace_source_path(raw_source, context)
                    source_key = str(source)
                    if source_key in seen_sources:
                        continue
                    seen_sources.add(source_key)

                    if not source.exists():
                        raise FileNotFoundError(f"源路径不存在: {raw_source}")
                    if source_kind == "file" and not source.is_file():
                        raise IsADirectoryError(f"file 参数只能传文件: {raw_source}")

                    relative_source = source.relative_to(workspace)
                    destination = posixpath.normpath(posixpath.join(target_root, relative_source.as_posix()))
                    if source.is_dir() and destination.startswith(f"{target_root.rstrip('/')}/") and destination == target_root:
                        raise ValueError(f"不能把目录复制到它自身路径上: {raw_source}")

                    if source.is_dir():
                        self._upload_directory_to_remote(sftp, source, destination)
                        transferred_type = "directory"
                    else:
                        self._ensure_remote_directory(sftp, posixpath.dirname(destination))
                        sftp.put(str(source), destination)
                        transferred_type = "file"

                    transferred.append(
                        {
                            "source": str(relative_source).replace("\\", "/"),
                            "destination": self._relative_remote_path(self._remote_root_path(connection), destination),
                            "type": transferred_type,
                        }
                    )
            finally:
                sftp.close()
        finally:
            client.close()

        return {
            "session_id": session_id,
            "target_dir": self._relative_remote_path(self._remote_root_path(connection), target_root),
            "count": len(transferred),
            "transferred": transferred,
        }

    def _upload_directory_to_remote(self, sftp: Any, source: Path, destination: str) -> None:
        self._ensure_remote_directory(sftp, destination)
        for child in source.iterdir():
            remote_child = posixpath.join(destination, child.name)
            if child.is_dir():
                self._upload_directory_to_remote(sftp, child, remote_child)
            else:
                self._ensure_remote_directory(sftp, posixpath.dirname(remote_child))
                sftp.put(str(child), remote_child)


def build_deploy_tools() -> list[BaseTool]:
    return [
        ConnectTool(),
        DeployListFilesTool(),
        DeployReadFileTool(),
        DeployTransferFilesTool(),
        DeployExecuteTool(),
    ]
