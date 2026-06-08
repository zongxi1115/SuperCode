#!/usr/bin/env python3
"""SuperCode TUI — 直接读后端 SQLite, 接入真实数据

数据源: .supercode/state.sqlite3 (和后端同一个数据库)
SSE 流式: 仍走 HTTP (因为这是实时流, 必须走网络)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import datetime
from pathlib import Path
from dataclasses import dataclass, field

import httpx
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.text import Text
from rich.live import Live
from rich.prompt import Prompt
from rich.spinner import Spinner
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory

console = Console()
BASE = "http://localhost:3001"
ROOT = Path(__file__).resolve().parents[1]


def _db_path() -> Path:
    explicit = os.environ.get("SUPERCODE_STATE_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return ROOT / ".supercode" / "state.sqlite3"


DB_PATH = _db_path()


# ═══════════════════════════════════════════════════════════════
#  直接读 SQLite — 真实数据, 不走 HTTP
# ═══════════════════════════════════════════════════════════════

def db_query(sql: str, params=()) -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        console.print(f"[red]db err: {e}[/]")
        return []


def db_load_json(text, fallback=None):
    if not isinstance(text, str) or not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def load_session(session_id: str) -> dict | None:
    rows = db_query("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    if not rows:
        return None
    return rows[0]


def load_all_sessions() -> list[dict]:
    return db_query("SELECT * FROM sessions ORDER BY updated_at DESC")


# ═══════════════════════════════════════════════════════════════
#  HTTP — 只用于 SSE 流式和写操作
# ═══════════════════════════════════════════════════════════════

def api(endpoint: str, *, method="GET", json_body=None, params=None, timeout=30, silent=False):
    try:
        r = httpx.request(method, f"{BASE}{endpoint}", json=json_body, params=params, timeout=timeout)
        if r.status_code >= 400:
            if not silent:
                console.print(f"[red]HTTP {r.status_code}[/] {r.text[:200]}")
            return None
        return r.json()
    except httpx.ConnectError:
        if not silent:
            console.print("[red]连不上后端 localhost:3001[/]")
        return None
    except Exception as e:
        if not silent:
            console.print(f"[red]err:[/] {e}")
        return None


COMMANDS = {
    "/monitor":  "仪表盘: 实时刷新终端+token+进程+计划",
    "/chat":     "流式聊天: 逐字回显+工具调用+代码变更",
    "/twatch":   "终端实时跟踪",
    "/mwatch":   "消息实时流",
    "/status":   "后端整体状态 (读DB)",
    "/models":   "可用模型列表",
    "/sessions": "会话历史列表 (读DB)",
    "/new":      "创建新会话",
    "/context":  "token用量/上下文 (读DB)",
    "/tree":     "文件树",
    "/term":     "发送终端命令",
    "/code":     "代码变更记录 (读DB)",
    "/msg":      "查看消息 (读DB)",
    "/git":      "Git状态",
    "/stop":     "停止生成",
    "/delete":   "删除会话",
    "/set":      "绑定会话ID",
    "/help":     "显示帮助",
    "/quit":     "退出",
}


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        partial = text[1:]
        for cmd, desc in COMMANDS.items():
            name = cmd.lstrip("/")
            if name.startswith(partial) or partial == "":
                yield Completion(
                    "/" + name,
                    start_position=-len(text),
                    display=f"{cmd}  — {desc}",
                    display_meta=desc,
                )


def fmt_time(ts_ms):
    if not ts_ms:
        return "-"
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%m-%d %H:%M:%S")


def token_bar(est, mx, width=20):
    if not mx:
        return "[dim]?/?[/]"
    ratio = min(est / mx, 1.0)
    filled = int(ratio * width)
    color = "green" if ratio < 0.5 else "yellow" if ratio < 0.8 else "red"
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/] {est}/{mx} ({ratio:.0%})"


def _context_usage_tokens(usage):
    if not isinstance(usage, dict):
        return 0
    try:
        return max(int(usage.get("inputTokens", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _parse_usage(raw):
    if not isinstance(raw, str):
        return {}
    return db_load_json(raw, {})


# ═══════════════════════════════════════════════════════════════
#  DB 直接读取命令 — 零延迟, 真实数据
# ═══════════════════════════════════════════════════════════════

def cmd_status():
    sessions = load_all_sessions()
    models = api("/api/models", silent=True)
    workspaces = api("/api/workspaces", silent=True)

    t = Text()
    t.append(f"DB: {DB_PATH}\n", style="dim")
    t.append(f"后端: ", style="bold")
    t.append(BASE, style="cyan")
    t.append("\n")
    if models:
        t.append(f"模型: {len(models.get('models',[]))} 个  ", style="green")
    if workspaces:
        t.append(f"工作区: {len(workspaces.get('workspaces',[]))} 个  ", style="green")
    t.append(f"会话: {len(sessions)} 条\n", style="green")
    for s in sessions[:8]:
        sid = s.get("session_id", "?")
        ws = s.get("workspace", "?")
        mc = s.get("message_count", 0)
        tc = s.get("tool_call_count", 0)
        gen = bool(s.get("is_generating", 0))
        gen_mark = " [yellow]●[/]" if gen else ""
        phase = s.get("phase", "?")
        t.append(f"  {sid[:8]}  {ws[:30]}  msg={mc} tool={tc}  {phase}{gen_mark}\n")
    console.print(Panel(t, title="状态 (DB直读)", border_style="cyan"))


def cmd_sessions():
    sessions = load_all_sessions()
    if not sessions:
        console.print("[yellow]DB无会话记录[/]")
        return
    table = Table(title="会话历史 (DB直读)", header_style="bold blue")
    table.add_column("ID", style="cyan", width=10)
    table.add_column("工作区", width=30)
    table.add_column("模型", width=16)
    table.add_column("模式")
    table.add_column("Phase")
    table.add_column("msg", width=5)
    table.add_column("tool", width=5)
    table.add_column("生成", width=4)
    table.add_column("更新", width=16)
    for s in sessions:
        table.add_row(
            s.get("session_id", "?")[:8],
            (s.get("workspace", "?") or "")[:30],
            s.get("model", "?")[:16],
            s.get("mode", "?"),
            s.get("phase", "?"),
            str(s.get("message_count", 0)),
            str(s.get("tool_call_count", 0)),
            "[yellow]●[/]" if s.get("is_generating", 0) else "",
            fmt_time(s.get("updated_at", 0)),
        )
    console.print(table)


def cmd_context(session_id: str):
    row = load_session(session_id)
    if not row:
        console.print(f"[red]DB中找不到 {session_id[:8]}[/]")
        return
    t = Text()
    t.append(f"ID:       {row.get('session_id','?')}\n", style="bold cyan")
    t.append(f"工作区:   {row.get('workspace','?')}\n")
    t.append(f"模型:     {row.get('model','?')}\n")
    t.append(f"模式:     {row.get('mode','?')}\n")
    t.append(f"Agent:    {row.get('agent_type','?')}\n")
    t.append(f"Phase:    {row.get('phase','?')}\n")
    gen = bool(row.get("is_generating", 0))
    t.append(f"生成中:   {'是' if gen else '否'}\n")
    if row.get("startup_error"):
        t.append(f"错误:     {row['startup_error']}\n", style="red")

    usage = _parse_usage(row.get("token_usage", "{}"))
    cum = _parse_usage(row.get("cumulative_token_usage", "{}"))
    est = _context_usage_tokens(usage)
    mx = row.get("max_context_tokens") or 0

    t.append(f"\nToken: {token_bar(est, mx, 25)}\n")
    t.append(f"本次: in={usage.get('inputTokens',0)} out={usage.get('outputTokens',0)} total={usage.get('totalTokens',0)}\n")
    t.append(f"累计: in={cum.get('inputTokens',0)} out={cum.get('outputTokens',0)} total={cum.get('totalTokens',0)}\n")
    t.append(f"msg={row.get('message_count',0)} tool={row.get('tool_call_count',0)} change={len(db_load_json(row.get('code_changes','[]'),[]))}\n")

    steps = db_load_json(row.get("plan_steps", "[]"), [])
    if steps:
        t.append(f"\n计划 ({len(steps)}):\n")
        for s in steps:
            st = s.get("status", "?")
            c = "green" if st == "completed" else "yellow" if st == "running" else "dim"
            t.append(f"  [{c}]{'✓' if st=='completed' else '●'}[/] {s.get('title','?')}\n")

    console.print(Panel(t, title="上下文 (DB直读)", border_style="yellow"))


def cmd_messages(session_id: str):
    row = load_session(session_id)
    if not row:
        console.print(f"[red]DB中找不到 {session_id[:8]}[/]")
        return
    msgs = db_load_json(row.get("history_messages", "[]"), [])
    tools = db_load_json(row.get("history_tools", "[]"), [])
    thoughts = db_load_json(row.get("thoughts", "[]"), [])

    if not msgs:
        console.print("[yellow]无消息[/]")
        return

    console.print(f"[bold]消息 {len(msgs)} 条 | 工具 {len(tools)} | 思考 {len(thoughts)}[/]\n")
    for m in msgs[-20:]:
        role = m.get("role", "?")
        content = m.get("content", "")
        m_thoughts = m.get("thoughts", "")
        tcs = m.get("toolCalls", [])

        if role == "user":
            console.print(Panel(content[:400], title="用户", border_style="green", padding=(0, 1)))
        else:
            if m_thoughts:
                console.print(Panel(m_thoughts[:300], title="思考", border_style="dim", padding=(0, 1)))
            if content:
                console.print(Panel(content[:400], title="助手", border_style="magenta", padding=(0, 1)))
            for tc in tcs:
                n = tc.get("name", "?")
                s = tc.get("state", "?")
                c = "green" if s == "completed" else "red" if s == "error" else "yellow"
                args = json.dumps(tc.get("arguments", {}), ensure_ascii=False, default=str)[:120] if tc.get("arguments") else ""
                err = tc.get("errorMessage") or tc.get("error_message")
                out = str(tc.get("output", ""))[:150]
                tc_info = f"[{c}]{s}[/] {n}"
                if args:
                    tc_info += f"\n  参数: {args}"
                if err:
                    tc_info += f"\n  [red]错误: {err[:150]}[/]"
                elif out:
                    tc_info += f"\n  输出: {out}"
                console.print(Panel(tc_info, title=f"工具 {tc.get('id','?')[:8]}", border_style="blue", padding=(0, 1)))


def cmd_code_changes(session_id: str):
    row = load_session(session_id)
    if not row:
        console.print(f"[red]DB中找不到 {session_id[:8]}[/]")
        return
    changes = db_load_json(row.get("code_changes", "[]"), [])
    if not changes:
        console.print("[yellow]无变更[/]")
        return
    table = Table(title=f"代码变更 ({len(changes)})")
    table.add_column("操作", width=8)
    table.add_column("路径", width=40)
    table.add_column("+", width=5)
    table.add_column("-", width=5)
    table.add_column("摘要", width=30)
    for c in changes[-30:]:
        a = c.get("action", "?")
        s = "green" if a == "added" else "red" if a == "deleted" else "yellow"
        table.add_row(f"[{s}]{a}[/]", c.get("path", "?")[:40],
                       str(c.get("linesAdded", 0)), str(c.get("linesDeleted", 0)),
                       c.get("summary", "")[:30])
    console.print(table)


# ═══════════════════════════════════════════════════════════════
#  SSE 解析
# ═══════════════════════════════════════════════════════════════

def iter_sse_events(byte_stream):
    buffer = ""
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")()

    while True:
        try:
            chunk = next(byte_stream)
        except StopIteration:
            remaining = decoder.decode(b"", finalize=True)
            if remaining:
                buffer += remaining
            break

        buffer += decoder.decode(chunk)

        while "\n\n" in buffer:
            event_str, buffer = buffer.split("\n\n", 1)
            event_str = event_str.strip()
            if not event_str:
                continue

            data_lines = []
            for line in event_str.split("\n"):
                if line.startswith("data:"):
                    data_lines.append(line[5:].strip() if len(line) > 5 else "")
            if not data_lines:
                continue

            raw = "\n".join(data_lines)
            if raw == "[DONE]":
                return
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue

    if buffer.strip():
        event_str = buffer.strip()
        data_lines = []
        for line in event_str.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].strip() if len(line) > 5 else "")
        if data_lines:
            raw = "\n".join(data_lines)
            if raw and raw != "[DONE]":
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    pass


# ═══════════════════════════════════════════════════════════════
#  MONITOR — DB直读 + 实时轮询
# ═══════════════════════════════════════════════════════════════

class MonitorState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.row: dict = {}
        self.terminal_data: dict = {}
        self.processes: list = []
        self.poll_count = 0
        self.last_update = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def stop(self):
        self._stop.set()

    def poll(self):
        if self._stop.is_set():
            return
        self.poll_count += 1

        row = load_session(self.session_id)
        term = api(f"/api/sessions/{self.session_id}/terminal",
                   params={"include_processes": "true", "include_file_tree": "false"}, silent=True)

        with self._lock:
            if row:
                self.row = row
            if term:
                self.terminal_data = term
                self.processes = term.get("processes", [])
            self.last_update = time.time()

    def render(self) -> Panel:
        with self._lock:
            return self._render()

    def _render(self) -> Panel:
        row = self.row
        if not row:
            return Panel("等待数据...", border_style="dim")

        term_data = self.terminal_data
        procs = self.processes

        header = Text()
        header.append(f"{self.session_id[:8]}  ", style="bold cyan")
        header.append(f"{row.get('workspace','?')}  ")
        header.append(f"{row.get('model','?')[:20]}  ")
        header.append(f"{row.get('agent_type','?')}/{row.get('phase','?')}")
        gen = bool(row.get("is_generating", 0))
        if gen:
            header.append(" [yellow]● 生成中[/]")
        header.append("\n")

        usage = _parse_usage(row.get("token_usage", "{}"))
        cum = _parse_usage(row.get("cumulative_token_usage", "{}"))
        est = _context_usage_tokens(usage)
        mx = row.get("max_context_tokens") or 0
        header.append(f"Token: {token_bar(est, mx)}\n")
        header.append(f"累计: in={cum.get('inputTokens',0)} out={cum.get('outputTokens',0)}  ")
        header.append(f"msg={row.get('message_count',0)} tool={row.get('tool_call_count',0)} change={len(db_load_json(row.get('code_changes','[]'),[]))}\n")

        steps = db_load_json(row.get("plan_steps", "[]"), [])
        if steps:
            header.append("计划: ")
            for s in steps:
                st = s.get("status", "?")
                icon = "✓" if st == "completed" else "●" if st == "running" else "○"
                c = "green" if st == "completed" else "yellow" if st == "running" else "dim"
                header.append(f"[{c}]{icon} {s.get('title','?')}[/] ")
            header.append("\n")

        if procs:
            header.append(f"进程({len(procs)}): ")
            for p in procs[:3]:
                header.append(f"[yellow]{p.get('command','?')[:25]}[/]({p.get('status','?')}) ")
            header.append("\n")

        term_out = term_data.get("output", row.get("terminal_output", ""))
        cwd = term_data.get("cwd", "?")
        alive = term_data.get("isAlive", False)
        lines = term_out.split("\n")[-14:] if term_out else ["(空)"]
        term_title = f"终端 cwd={cwd} alive={'是' if alive else '否'}"

        recent_changes = db_load_json(row.get("code_changes", "[]"), [])
        change_lines = ""
        for c in recent_changes[-5:]:
            a = c.get("action", "?")
            change_lines += f"  {a}: {c.get('path','?')} (+{c.get('linesAdded',0)} -{c.get('linesDeleted',0)})\n"

        content_parts = [Panel("\n".join(lines), title=term_title, border_style="green")]
        if change_lines:
            content_parts.append(Panel(change_lines.strip(), title="代码变更", border_style="yellow"))

        elapsed = time.time() - self.last_update if self.last_update else 0
        subtitle = f"#{self.poll_count}  {elapsed:.0f}s前  DB直读"

        return Panel(Group(*content_parts), title=header.plain[:90],
                     subtitle=subtitle, border_style="cyan", padding=(0, 1))


def cmd_monitor(session_id: str):
    state = MonitorState(session_id)

    def poll_loop():
        while not state._stop.is_set():
            state.poll()
            time.sleep(1.5)

    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()

    try:
        with Live(state.render(), refresh_per_second=2, console=console) as live:
            while not state._stop.is_set():
                live.update(state.render())
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop()
        t.join(timeout=2)
    console.print("[dim]monitor 退出[/]")


# ═══════════════════════════════════════════════════════════════
#  CHAT — SSE 流式实时
# ═══════════════════════════════════════════════════════════════

def cmd_chat(session_id: str):
    msg = Prompt.ask("消息")
    agent_mode = Prompt.ask("mode", choices=["auto", "plan", "coding", "deploy"], default="auto")

    text_buf = ""
    think_buf = ""
    tools: list[dict] = []
    changes: list[str] = []
    errors: list[str] = []

    def build_output():
        parts = []
        if think_buf:
            parts.append(Panel(think_buf[-800:], title="思考", border_style="dim", padding=(0, 1)))
        if text_buf:
            parts.append(Panel(text_buf[-2000:], title="回复", border_style="magenta", padding=(0, 1)))
        if tools:
            tool_text = ""
            for tc in tools[-8:]:
                icon = "✓" if tc["state"] == "completed" else "✗" if tc["state"] == "error" else "▶"
                c = "green" if tc["state"] == "completed" else "red" if tc["state"] == "error" else "yellow"
                tool_text += f"[{c}]{icon} {tc['name']}[/]"
                if tc.get("preview"):
                    tool_text += f"  {tc['preview'][:80]}"
                tool_text += "\n"
            parts.append(Panel(tool_text.strip(), title=f"工具 ({len(tools)})", border_style="blue", padding=(0, 1)))
        if changes:
            parts.append(Panel("\n".join(changes[-6:]), title="代码变更", border_style="yellow", padding=(0, 1)))
        if errors:
            parts.append(Panel("\n".join(errors[-3:]), title="错误", border_style="red", padding=(0, 1)))
        if not parts:
            parts.append(Spinner("dots", text="等待响应..."))
        return Group(*parts)

    try:
        with Live(build_output(), refresh_per_second=8, console=console) as live:
            with httpx.stream("POST", f"{BASE}/api/chat/stream",
                              json={"session_id": session_id, "message": msg, "agent_mode": agent_mode},
                              timeout=180) as resp:
                for d in iter_sse_events(resp.iter_bytes()):
                    t = d.get("type", "")

                    if t == "text-delta":
                        text_buf += d.get("delta", "")
                    elif t == "reasoning-delta":
                        think_buf += d.get("delta", "")
                    elif t == "assistant_delta":
                        text_buf += d.get("payload", {}).get("delta", "")
                    elif t == "tool-input-available":
                        tools.append({"name": d.get("toolName", "?"), "state": "running",
                                      "preview": json.dumps(d.get("input", {}), ensure_ascii=False, default=str)[:120]})
                    elif t == "tool-input-start":
                        tools.append({"name": d.get("toolName", "?"), "state": "running", "preview": ""})
                    elif t == "tool-output-available":
                        for tc in reversed(tools):
                            if tc["state"] == "running":
                                tc["state"] = "completed"
                                tc["preview"] = str(d.get("output", ""))[:120]
                                break
                    elif t == "data-tool-result":
                        payload = d.get("data", {})
                        name = payload.get("name", "?")
                        success = payload.get("success")
                        err = payload.get("error_message") or payload.get("errorMessage")
                        tools.append({"name": name, "state": "completed" if success else "error",
                                      "preview": f"ERR: {err[:80]}" if err else str(payload.get("output", ""))[:80]})
                    elif t == "data-code-change":
                        p = d.get("data", {})
                        changes.append(f"{p.get('action','?')}: {p.get('path','?')} (+{p.get('linesAdded',0)} -{p.get('linesDeleted',0)})")
                    elif t == "error":
                        errors.append(d.get("errorText", "未知错误"))

                    live.update(build_output())
    except KeyboardInterrupt:
        console.print("\n[yellow]中断[/]")
    except httpx.ConnectError:
        console.print("[red]连不上后端[/]")

    console.print(f"[dim]回复 {len(text_buf)} 字 | 思考 {len(think_buf)} 字 | 工具 {len(tools)} | 变更 {len(changes)}[/]")


# ═══════════════════════════════════════════════════════════════
#  终端实时跟踪 / 消息流
# ═══════════════════════════════════════════════════════════════

def cmd_terminal_watch(session_id: str):
    try:
        with Live("连接中...", refresh_per_second=4, console=console) as live:
            while True:
                data = api(f"/api/sessions/{session_id}/terminal", params={"include_processes": "true"}, silent=True)
                row = load_session(session_id)
                if data:
                    output = data.get("output", "")
                    cwd = data.get("cwd", "?")
                    alive = data.get("isAlive", False)
                    procs = data.get("processes", [])
                    lines = output.split("\n")[-25:] if output else ["(空)"]
                    title = f"终端 cwd={cwd} alive={'是' if alive else '否'}"
                    proc_text = ""
                    if procs:
                        proc_text = "\n\n[dim]进程: " + " | ".join(f"{p.get('command','?')[:20]}({p.get('status','?')})" for p in procs[:3]) + "[/]"
                    live.update(Panel("\n".join(lines) + proc_text, title=title, border_style="green"))
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    console.print("[dim]终端跟踪退出[/]")


def cmd_messages_watch(session_id: str):
    try:
        with Live("加载中...", refresh_per_second=2, console=console) as live:
            while True:
                row = load_session(session_id)
                if row:
                    msgs = db_load_json(row.get("history_messages", "[]"), [])
                    gen = bool(row.get("is_generating", 0))
                    parts = []
                    header = f"消息 {len(msgs)} 条"
                    if gen:
                        header += " [yellow]● 生成中[/]"

                    for m in msgs[-15:]:
                        role = m.get("role", "?")
                        content = m.get("content", "")
                        m_thoughts = m.get("thoughts", "")
                        tcs = m.get("toolCalls", [])
                        if role == "user":
                            parts.append(Panel(content[:300].replace("\n", " "), title="用户", border_style="green", padding=(0, 1)))
                        else:
                            if m_thoughts:
                                parts.append(Panel(m_thoughts[:200].replace("\n", " "), title="思考", border_style="dim", padding=(0, 1)))
                            if content:
                                parts.append(Panel(content[:300].replace("\n", " "), title="助手", border_style="magenta", padding=(0, 1)))
                            for tc in tcs:
                                n = tc.get("name", "?")
                                s = tc.get("state", "?")
                                c = "green" if s == "completed" else "red" if s == "error" else "yellow"
                                parts.append(Panel(f"[{c}]{s}[/] {n}", border_style="blue", padding=(0, 1)))

                    live.update(Panel(Group(*parts) if parts else Text("(无)"), title=header, border_style="cyan"))
                time.sleep(1.5)
    except KeyboardInterrupt:
        pass
    console.print("[dim]消息流退出[/]")


# ═══════════════════════════════════════════════════════════════
#  其他静态命令
# ═══════════════════════════════════════════════════════════════

def cmd_models():
    data = api("/api/models")
    if not data:
        return
    table = Table(title="模型", header_style="bold magenta")
    table.add_column("ID", style="cyan")
    table.add_column("名称")
    table.add_column("供应商")
    for m in data.get("models", []):
        table.add_row(m.get("id", "?"), m.get("name", "?"), m.get("provider", "?"))
    console.print(table)


def cmd_create_session():
    workspaces = api("/api/workspaces")
    ws_list = workspaces.get("workspaces", []) if workspaces else []
    if ws_list:
        table = Table(header_style="bold")
        table.add_column("#", width=4)
        table.add_column("标签")
        table.add_column("路径", style="dim")
        for i, w in enumerate(ws_list):
            table.add_row(str(i), w.get("label", "?"), w.get("value", "?")[:50])
        console.print(table)
    console.print("[dim]直接输入路径 或 输入编号选择[/]")
    choice = Prompt.ask("路径/编号", default="0")
    try:
        idx = int(choice)
        workspace = ws_list[idx].get("value", "")
    except (ValueError, IndexError):
        workspace = choice

    agent = Prompt.ask("模式", choices=["auto", "plan", "coding", "deploy"], default="auto")
    data = api("/api/sessions", method="POST", json_body={"workspace": workspace, "agent_type": agent}, timeout=60)
    if not data:
        return None
    sid = data.get("sessionId", "?")
    console.print(f"[green]会话已创建[/] {sid}")
    return sid


def cmd_tree(session_id: str):
    data = api(f"/api/sessions/{session_id}/file-tree")
    if not data:
        return
    tree_data = data.get("fileTree", [])
    if not tree_data:
        console.print("[yellow]空[/]")
        return
    tree = Tree("📁", guide_style="dim")
    _build_tree(tree, tree_data)
    console.print(tree)

def _build_tree(parent, nodes, depth=0):
    if depth > 5:
        return
    for n in nodes[:40]:
        icon = "📁" if n.get("type") == "folder" else "📄"
        b = parent.add(f"{icon} {n.get('name','?')}")
        if n.get("children"):
            _build_tree(b, n["children"], depth + 1)


def cmd_send_terminal(session_id: str):
    cmd_text = Prompt.ask("命令")
    data = api(f"/api/sessions/{session_id}/terminal/input", method="POST",
               json_body={"command": cmd_text, "submit": True})
    if data:
        out = data.get("output", "")
        lines = out.split("\n")[-15:] if out else ["(无输出)"]
        console.print(Panel("\n".join(lines), title="终端", border_style="green"))


def cmd_git(session_id: str):
    data = api(f"/api/sessions/{session_id}/git/status")
    if not data or not data.get("isRepo"):
        console.print("[yellow]非Git仓库[/]")
        return
    console.print(f"[bold]分支: {data.get('branch','?')}[/]  变更: {len(data.get('changedFiles',[]))}")
    for f in data.get("changedFiles", []):
        console.print(f"  · {f}")


def cmd_stop(session_id: str):
    data = api(f"/api/sessions/{session_id}/stop", method="POST")
    if data:
        console.print("[green]已停止[/]")


def cmd_delete(session_id: str):
    if Prompt.ask(f"确认删除 {session_id[:8]}?", choices=["y", "n"], default="n") == "y":
        api(f"/api/sessions/{session_id}", method="DELETE")
        console.print("[green]已删除[/]")


# ═══════════════════════════════════════════════════════════════
#  命令分发
# ═══════════════════════════════════════════════════════════════

def _run_command(action: str, arg: str | None, current_session: str | None) -> str | None:
    sid = arg or current_session

    if action in ("quit", "exit", "q"):
        raise SystemExit(0)
    elif action == "help" or action == "?":
        rows = []
        for cmd, desc in COMMANDS.items():
            rows.append(f"  {cmd:<12} {desc}")
        console.print(Panel("\n".join(rows), title="命令列表", border_style="cyan"))
    elif action == "set":
        new_sid = arg or Prompt.ask("会话ID")
        console.print(f"[dim]绑定 {new_sid[:8]}[/]")
        return new_sid
    elif action == "monitor":
        if sid: cmd_monitor(sid)
        else: console.print("[red]先 /set <id>[/]")
    elif action == "chat":
        if sid: cmd_chat(sid)
        else: console.print("[red]先 /set <id>[/]")
    elif action == "twatch":
        if sid: cmd_terminal_watch(sid)
        else: console.print("[red]先 /set <id>[/]")
    elif action == "mwatch":
        if sid: cmd_messages_watch(sid)
        else: console.print("[red]先 /set <id>[/]")
    elif action == "status":
        cmd_status()
    elif action == "models":
        cmd_models()
    elif action == "sessions":
        cmd_sessions()
    elif action == "new":
        sid_new = cmd_create_session()
        if sid_new:
            return sid_new
    elif action == "context":
        if sid: cmd_context(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "msg":
        if sid: cmd_messages(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "tree":
        if sid: cmd_tree(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "term":
        if sid: cmd_send_terminal(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "code":
        if sid: cmd_code_changes(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "git":
        if sid: cmd_git(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "stop":
        if sid: cmd_stop(sid)
        else: console.print("[red]需要会话ID[/]")
    elif action == "delete":
        if sid:
            cmd_delete(sid)
            if current_session == sid:
                return ""
        else:
            console.print("[red]需要会话ID[/]")
    else:
        console.print(f"[yellow]未知: {action}[/]  输入 / 查看命令")
    return None


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    db_ok = DB_PATH.exists()
    db_hint = f"[green]DB: {DB_PATH}[/]" if db_ok else f"[red]DB不存在: {DB_PATH}[/]"

    console.print(Panel(
        f"[bold cyan]SuperCode TUI[/] [dim]实时调试 — DB直读[/]\n\n"
        f"{db_hint}\n\n"
        "输入 [bold yellow]/[/] 弹出命令列表, ↑↓ 切换\n\n"
        "[bold green]实时命令[/] (Ctrl+C 退出):\n"
        "  /monitor  仪表盘 DB+终端 一屏刷新\n"
        "  /chat     流式聊天 逐字回显\n"
        "  /twatch   终端实时跟踪\n"
        "  /mwatch   消息实时流 (DB直读)\n\n"
        "[bold]DB直读命令[/] (零延迟):\n"
        "  /sessions /context /msg /code\n\n"
        "[dim]/set <id> 绑定会话[/]",
        border_style="cyan", padding=(1, 3)))

    current_session: str | None = None
    completer = SlashCompleter()
    history = InMemoryHistory()

    session = PromptSession(
        completer=completer,
        complete_while_typing=True,
        history=history,
        complete_in_thread=True,
    )

    while True:
        try:
            sid_hint = current_session[:8] if current_session else ""
            prompt_text = FormattedText([
                ("bold green", "sc"),
                ("cyan", f":{sid_hint}" if sid_hint else ""),
                ("", "> "),
            ])

            raw = session.prompt(prompt_text).strip()
            if not raw:
                continue

            if not raw.startswith("/"):
                parts = raw.split(maxsplit=1)
                action = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else None
            else:
                no_slash = raw[1:]
                parts = no_slash.split(maxsplit=1)
                action = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else None

            result = _run_command(action, arg, current_session)
            if result is not None:
                current_session = result or None

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — 输入 /quit 退出[/]")
        except EOFError:
            break
        except SystemExit:
            break

    console.print("[dim]再见[/]")

if __name__ == "__main__":
    main()
