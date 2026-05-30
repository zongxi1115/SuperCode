from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent.config import read_dotenv_values
from agent.tools import BaseTool, ToolContext
from coding_agent.tools import (
    GlobFileTool,
    GrepFileTool,
    ListFileTool,
    ReadFileTool,
    RememberPreferenceTool,
)

DEFAULT_TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
DEFAULT_TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"
DEFAULT_TINYFISH_TIMEOUT_SECONDS = 30
MAX_SEARCH_RESULTS = 8
MAX_FETCH_DOCUMENT_CHARS = 4_000


def _normalize_string_list(raw_values: object) -> list[str]:
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        value = raw_values.strip()
        return [value] if value else []
    if not isinstance(raw_values, list):
        raise ValueError("字段必须是字符串数组。")

    values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            raise ValueError("数组里的每一项都必须是字符串。")
        normalized = item.strip()
        if normalized:
            values.append(normalized)
    return values


def _slugify(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return normalized or fallback


class PlanBaseTool(BaseTool):
    def _load_tinyfish_settings(self, context: ToolContext) -> dict[str, Any]:
        project_root = context.metadata.get("project_root")
        env_values = (
            read_dotenv_values(Path(project_root) / ".env")
            if isinstance(project_root, (str, Path))
            else {}
        )
        api_key = env_values.get("SC_TINYFISH_API_KEY", os.getenv("SC_TINYFISH_API_KEY", "")).strip()
        search_url = env_values.get(
            "SC_TINYFISH_SEARCH_URL",
            os.getenv("SC_TINYFISH_SEARCH_URL", DEFAULT_TINYFISH_SEARCH_URL),
        ).strip() or DEFAULT_TINYFISH_SEARCH_URL
        fetch_url = env_values.get(
            "SC_TINYFISH_FETCH_URL",
            os.getenv("SC_TINYFISH_FETCH_URL", DEFAULT_TINYFISH_FETCH_URL),
        ).strip() or DEFAULT_TINYFISH_FETCH_URL
        timeout_raw = env_values.get(
            "SC_TINYFISH_TIMEOUT",
            os.getenv("SC_TINYFISH_TIMEOUT", str(DEFAULT_TINYFISH_TIMEOUT_SECONDS)),
        ).strip()
        try:
            timeout = max(5, int(timeout_raw))
        except ValueError:
            timeout = DEFAULT_TINYFISH_TIMEOUT_SECONDS

        if not api_key:
            raise RuntimeError("缺少 SC_TINYFISH_API_KEY，请先在 .env 里配置 Tinyfish API Key。")

        return {
            "api_key": api_key,
            "search_url": search_url.rstrip("/"),
            "fetch_url": fetch_url.rstrip("/"),
            "timeout": timeout,
        }

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        api_key: str,
        timeout: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            method=method,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "SuperCode/1.0",
                "X-API-Key": api_key,
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"Tinyfish 请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Tinyfish 请求失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Tinyfish 请求超时。") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Tinyfish 返回了无法解析的 JSON：{raw_body[:300]}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("Tinyfish 返回格式不正确。")
        return parsed


class SearchWebTool(PlanBaseTool):
    name = "search_web"
    description = (
        "使用 Tinyfish 搜索互联网资料。参数：query（必填），可选 country、language、page、"
        "from_date、to_date、include_images、include_image_descriptions、max_results。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "country": {"type": "string"},
            "language": {"type": "string"},
            "page": {"type": "integer"},
            "from_date": {"type": "string"},
            "to_date": {"type": "string"},
            "include_images": {"type": "boolean"},
            "include_image_descriptions": {"type": "boolean"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query 不能为空。")

        settings = self._load_tinyfish_settings(context)
        page = max(0, int(arguments.get("page") or 0))
        max_results = min(MAX_SEARCH_RESULTS, max(1, int(arguments.get("max_results") or 5)))
        query_params: dict[str, Any] = {
            "query": query,
            "page": page,
        }
        country = str(arguments.get("country") or "").strip()
        if country:
            query_params["location"] = country
        for key in ("language",):
            value = str(arguments.get(key) or "").strip()
            if value:
                query_params[key] = value
        for key in ("include_images", "include_image_descriptions"):
            value = arguments.get(key)
            if isinstance(value, bool):
                query_params[key] = "true" if value else "false"

        url = f"{settings['search_url']}?{urlencode(query_params)}"
        payload = self._request_json(
            method="GET",
            url=url,
            api_key=str(settings["api_key"]),
            timeout=int(settings["timeout"]),
        )
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raw_results = payload.get("data") if isinstance(payload.get("data"), list) else []

        results: list[dict[str, Any]] = []
        for index, item in enumerate(raw_results[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "rank": index,
                    "title": str(item.get("title") or item.get("name") or "").strip(),
                    "url": str(item.get("url") or item.get("link") or "").strip(),
                    "snippet": str(
                        item.get("snippet")
                        or item.get("description")
                        or item.get("content")
                        or ""
                    ).strip(),
                    "source": str(item.get("source") or item.get("domain") or "").strip(),
                    "publishedAt": str(item.get("published_at") or item.get("date") or "").strip(),
                }
            )

        return {
            "query": query,
            "page": page,
            "count": len(results),
            "results": results,
        }


class FetchUrlContentTool(PlanBaseTool):
    name = "fetch_url_content"
    description = (
        "使用 Tinyfish 抓取指定网页正文。参数：urls（必填，字符串数组）。"
        "返回正文摘要，适合对搜索命中的页面做精读。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["urls"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        urls = _normalize_string_list(arguments.get("urls"))
        if not urls:
            raise ValueError("urls 不能为空。")

        settings = self._load_tinyfish_settings(context)
        payload = self._request_json(
            method="POST",
            url=str(settings["fetch_url"]),
            api_key=str(settings["api_key"]),
            timeout=int(settings["timeout"]),
            payload={"urls": urls, "format": "markdown"},
        )
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raw_results = payload.get("data") if isinstance(payload.get("data"), list) else []

        documents: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            content = str(
                item.get("content")
                or item.get("markdown")
                or item.get("text")
                or item.get("excerpt")
                or ""
            ).strip()
            if len(content) > MAX_FETCH_DOCUMENT_CHARS:
                content = f"{content[:MAX_FETCH_DOCUMENT_CHARS].rstrip()}... [truncated]"
            documents.append(
                {
                    "url": str(item.get("url") or "").strip(),
                    "title": str(item.get("title") or "").strip(),
                    "content": content,
                }
            )

        return {
            "count": len(documents),
            "documents": documents,
        }


class AskPlanQuestionsTool(PlanBaseTool):
    name = "ask_plan_questions"
    description = (
        "向用户发起需求澄清问题。支持 single_choice、multi_choice、short_text 三种题型。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "prompt": {"type": "string"},
                        "required": {"type": "boolean"},
                        "placeholder": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["label"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["type", "prompt"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["questions"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        del context
        raw_questions = arguments.get("questions")
        if not isinstance(raw_questions, list) or not raw_questions:
            raise ValueError("questions 不能为空。")

        title = str(arguments.get("title") or "需要确认一些需求细节").strip()
        message = str(
            arguments.get("message") or "请先回答下面几个关键问题，我会据此完善计划。"
        ).strip()

        normalized_questions: list[dict[str, Any]] = []
        for index, raw_question in enumerate(raw_questions, start=1):
            if not isinstance(raw_question, dict):
                raise ValueError("questions 里的每一项都必须是对象。")
            question_type = str(raw_question.get("type") or "").strip()
            if question_type not in {"single_choice", "multi_choice", "short_text"}:
                raise ValueError("问题类型只支持 single_choice、multi_choice、short_text。")
            prompt = str(raw_question.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("每个问题都必须提供 prompt。")

            question_id = str(raw_question.get("id") or "").strip() or f"question_{index}"
            normalized_question: dict[str, Any] = {
                "id": _slugify(question_id, f"question_{index}"),
                "type": question_type,
                "prompt": prompt,
                "required": bool(raw_question.get("required", True)),
            }
            placeholder = str(raw_question.get("placeholder") or "").strip()
            if placeholder:
                normalized_question["placeholder"] = placeholder

            if question_type in {"single_choice", "multi_choice"}:
                raw_options = raw_question.get("options")
                if not isinstance(raw_options, list) or len(raw_options) < 2:
                    raise ValueError("选择题至少需要提供 2 个 options。")
                normalized_options: list[dict[str, Any]] = []
                for option_index, raw_option in enumerate(raw_options, start=1):
                    if not isinstance(raw_option, dict):
                        raise ValueError("options 里的每一项都必须是对象。")
                    label = str(raw_option.get("label") or "").strip()
                    if not label:
                        raise ValueError("每个 option 都必须提供 label。")
                    option_id = str(raw_option.get("id") or "").strip()
                    normalized_option = {
                        "id": _slugify(option_id or label, f"option_{index}_{option_index}"),
                        "label": label,
                    }
                    description = str(raw_option.get("description") or "").strip()
                    if description:
                        normalized_option["description"] = description
                    normalized_options.append(normalized_option)
                normalized_question["options"] = normalized_options[:5]

            normalized_questions.append(normalized_question)

        return {
            "requires_user_input": True,
            "input_kind": "plan_questions",
            "title": title,
            "message": message,
            "questions": normalized_questions,
            "data_parts": [
                {
                    "type": "data-plan-questions",
                    "data": {
                        "title": title,
                        "message": message,
                        "questions": normalized_questions,
                    },
                }
            ],
        }


class SavePlanTool(PlanBaseTool):
    name = "save_plan"
    description = (
        "保存当前计划草案到后端。参数：title、summary、overview、key_steps（必填），"
        "markdown（可选，缺省时自动生成）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "overview": {"type": "string"},
            "key_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "markdown": {"type": "string"},
        },
        "required": ["title", "summary", "overview", "key_steps"],
        "additionalProperties": False,
    }

    def _build_markdown(
        self,
        *,
        title: str,
        summary: str,
        overview: str,
        key_steps: list[str],
    ) -> str:
        sections = [f"# {title}", "", summary, "", "## 总览", "", overview]
        if key_steps:
            sections.extend(
                [
                    "",
                    "## 关键步骤",
                    "",
                    *[f"{index + 1}. {step}" for index, step in enumerate(key_steps)],
                ]
            )
        return "\n".join(section for section in sections if section is not None).strip()

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        del context
        title = str(arguments.get("title") or "").strip()
        summary = str(arguments.get("summary") or "").strip()
        overview = str(arguments.get("overview") or "").strip()
        key_steps = _normalize_string_list(arguments.get("key_steps"))
        markdown = str(arguments.get("markdown") or "").strip()
        if not title:
            raise ValueError("title 不能为空。")
        if not summary:
            raise ValueError("summary 不能为空。")
        if not overview:
            raise ValueError("overview 不能为空。")
        if not key_steps:
            raise ValueError("key_steps 不能为空。")
        if not markdown:
            markdown = self._build_markdown(
                title=title,
                summary=summary,
                overview=overview,
                key_steps=key_steps,
            )

        plan = {
            "title": title,
            "summary": summary,
            "overview": overview,
            "keySteps": key_steps,
            "markdown": markdown,
        }
        return {
            "message": "计划草案已保存，可继续修改或提交进入编码模式。",
            "plan": plan,
            "data_parts": [
                {
                    "type": "data-plan-draft",
                    "data": plan,
                }
            ],
        }


class ReadCurrentPlanTool(PlanBaseTool):
    name = "read_current_plan"
    description = (
        "读取当前会话里最新的计划草案/当前计划正文。"
        "当用户在前端手动编辑过计划后，用它获取最新 markdown 和结构化内容。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        del arguments
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip("/")
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError("缺少 backend_base_url 或 session_id，无法读取当前计划。")

        payload = self._request_json(
            method="GET",
            url=f"{backend_base_url}/api/sessions/{session_id}/plan-draft/current",
            api_key="local-session",
            timeout=10,
        )
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise RuntimeError("当前会话没有可读取的计划草案。")
        return {
            "plan": plan,
            "planState": payload.get("planState"),
        }


class CreateTaskTool(PlanBaseTool):
    name = "create_task"
    description = (
        "创建一个结构化 task。参数：title、summary、steps。"
        "steps 是数组，每项都需要 title 和 summary。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["title", "summary"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "summary", "steps"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip("/")
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError("缺少 backend_base_url 或 session_id，无法创建 task。")

        title = str(arguments.get("title") or "").strip()
        summary = str(arguments.get("summary") or "").strip()
        raw_steps = arguments.get("steps")
        if not title:
            raise ValueError("title 不能为空。")
        if not summary:
            raise ValueError("summary 不能为空。")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("steps 不能为空。")

        steps: list[dict[str, str]] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                raise ValueError("steps 里的每一项都必须是对象。")
            step_title = str(raw_step.get("title") or "").strip()
            step_summary = str(raw_step.get("summary") or "").strip()
            if not step_title or not step_summary:
                raise ValueError("每个 step 都必须包含 title 和 summary。")
            steps.append({"title": step_title, "summary": step_summary})

        payload = self._request_json(
            method="POST",
            url=f"{backend_base_url}/api/sessions/{session_id}/tasks",
            api_key="local-session",
            timeout=10,
            payload={"title": title, "summary": summary, "steps": steps},
        )
        return {
            "task_id": payload.get("task_id"),
            "step_ids": payload.get("step_ids"),
            "task": payload.get("task"),
            "planState": payload.get("planState"),
            "planSteps": payload.get("planSteps"),
        }


class GetTaskStatusTool(PlanBaseTool):
    name = "get_task_status"
    description = "获取当前会话里的 task 状态。参数：task_id 可选。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip("/")
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError("缺少 backend_base_url 或 session_id，无法读取 task 状态。")

        task_id = str(arguments.get("task_id") or "").strip()
        query = f"?{urlencode({'task_id': task_id})}" if task_id else ""
        payload = self._request_json(
            method="GET",
            url=f"{backend_base_url}/api/sessions/{session_id}/tasks/status{query}",
            api_key="local-session",
            timeout=10,
        )
        return {
            "active_task_id": payload.get("active_task_id"),
            "active_step_id": payload.get("active_step_id"),
            "active_task": payload.get("active_task"),
            "tasks": payload.get("tasks"),
            "planState": payload.get("planState"),
            "planSteps": payload.get("planSteps"),
        }


def build_plan_tools() -> list[BaseTool]:
    return [
        ListFileTool(),
        RememberPreferenceTool(),
        GlobFileTool(),
        ReadFileTool(),
        GrepFileTool(),
        SearchWebTool(),
        FetchUrlContentTool(),
        AskPlanQuestionsTool(),
        SavePlanTool(),
        ReadCurrentPlanTool(),
        CreateTaskTool(),
        GetTaskStatusTool(),
    ]
