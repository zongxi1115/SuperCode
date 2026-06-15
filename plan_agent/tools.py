from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from agent.config import read_dotenv_values
from agent.http_transport import open_url
from fastapi_app.settings_store import load_settings
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from zonix.models.base import ModelRequest
from zonix.tools import ToolContext
from zonix.types import Message

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


def _unwrap_tool_list(value: object) -> object:
    current = value
    for _ in range(3):
        if isinstance(current, dict):
            for key in ("items", "item", "values", "options", "questions"):
                nested = current.get(key)
                if nested is not None:
                    current = nested
                    break
            else:
                return current
            continue
        return current
    return current


def _normalize_object_list(raw_values: object, *, field_name: str) -> list[dict[str, Any]]:
    unwrapped = _unwrap_tool_list(raw_values)
    if not isinstance(unwrapped, list):
        raise ValueError(f"{field_name} 必须是对象数组。")

    values: list[dict[str, Any]] = []
    for item in unwrapped:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} 里的每一项都必须是对象。")
        values.append(item)
    return values


def _is_super_autopilot_enabled(ctx: ToolContext) -> bool:
    data = getattr(getattr(ctx, "state", None), "data", None)
    if not isinstance(data, dict):
        return False
    runtime_state = data.get("runtime_state")
    if not isinstance(runtime_state, dict):
        runtime_state = {}
    return bool(
        data.get("super_autopilot")
        or (
            runtime_state.get("agent_type") == "super"
            and runtime_state.get("super_autopilot")
        )
    )


def _fallback_question_answer(question: dict[str, Any]) -> dict[str, Any]:
    question_id = str(question.get("id") or "").strip()
    question_type = str(question.get("type") or "").strip()
    prompt = str(question.get("prompt") or question_id).strip()
    if question_type == "short_text":
        text = str(question.get("placeholder") or "").strip() or "由 AI 自主选择默认值"
        return {
            "questionId": question_id,
            "type": question_type,
            "prompt": prompt,
            "text": text,
            "otherText": None,
            "autopilot": True,
            "fallback": True,
        }

    options = question.get("options") if isinstance(question.get("options"), list) else []
    selected_options = options[:1]
    return {
        "questionId": question_id,
        "type": question_type,
        "prompt": prompt,
        "selectedOptionIds": [
            str(option.get("id") or "").strip()
            for option in selected_options
            if isinstance(option, dict) and str(option.get("id") or "").strip()
        ],
        "selectedOptions": [
            {
                "id": str(option.get("id") or "").strip(),
                "label": str(option.get("label") or "").strip(),
                "description": str(option.get("description") or "").strip(),
            }
            for option in selected_options
            if isinstance(option, dict)
        ],
        "otherText": None,
        "text": None,
        "autopilot": True,
        "fallback": True,
    }


def _build_fallback_question_answers(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_fallback_question_answer(question) for question in questions]


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("托管答题模型返回的 JSON 必须是对象。")
    return parsed


def _normalize_autopilot_answers(
    questions: list[dict[str, Any]],
    raw_answers: object,
) -> list[dict[str, Any]]:
    answer_items = raw_answers if isinstance(raw_answers, list) else []
    answers_by_id = {
        str(item.get("questionId") or item.get("question_id") or item.get("id") or "").strip(): item
        for item in answer_items
        if isinstance(item, dict)
    }
    normalized_answers: list[dict[str, Any]] = []

    for question in questions:
        question_id = str(question.get("id") or "").strip()
        question_type = str(question.get("type") or "").strip()
        prompt = str(question.get("prompt") or question_id).strip()
        raw_answer = answers_by_id.get(question_id)
        if not isinstance(raw_answer, dict):
            normalized_answers.append(_fallback_question_answer(question))
            continue

        if question_type == "short_text":
            text = str(raw_answer.get("text") or raw_answer.get("value") or "").strip()
            if not text:
                normalized_answers.append(_fallback_question_answer(question))
                continue
            normalized_answers.append(
                {
                    "questionId": question_id,
                    "type": question_type,
                    "prompt": prompt,
                    "text": text,
                    "otherText": str(raw_answer.get("otherText") or raw_answer.get("other_text") or "").strip() or None,
                    "autopilot": True,
                }
            )
            continue

        options = question.get("options") if isinstance(question.get("options"), list) else []
        options_by_id = {
            str(option.get("id") or "").strip(): option
            for option in options
            if isinstance(option, dict) and str(option.get("id") or "").strip()
        }
        raw_selected = (
            raw_answer.get("selectedOptionIds")
            or raw_answer.get("selected_option_ids")
            or raw_answer.get("value")
            or raw_answer.get("selected")
        )
        if isinstance(raw_selected, str):
            selected_ids = [raw_selected.strip()] if raw_selected.strip() else []
        elif isinstance(raw_selected, list):
            selected_ids = [
                str(option_id).strip()
                for option_id in raw_selected
                if str(option_id).strip()
            ]
        else:
            selected_ids = []
        selected_ids = [option_id for option_id in selected_ids if option_id in options_by_id]
        if question_type == "single_choice":
            selected_ids = selected_ids[:1]
        if not selected_ids:
            normalized_answers.append(_fallback_question_answer(question))
            continue

        normalized_answers.append(
            {
                "questionId": question_id,
                "type": question_type,
                "prompt": prompt,
                "selectedOptionIds": selected_ids,
                "selectedOptions": [
                    {
                        "id": option_id,
                        "label": str(options_by_id[option_id].get("label") or "").strip(),
                        "description": str(options_by_id[option_id].get("description") or "").strip(),
                    }
                    for option_id in selected_ids
                ],
                "otherText": str(raw_answer.get("otherText") or raw_answer.get("other_text") or "").strip() or None,
                "text": str(raw_answer.get("text") or "").strip() or None,
                "autopilot": True,
            }
        )
    return normalized_answers


async def _build_model_autopilot_question_answers(
    ctx: ToolContext,
    questions: list[dict[str, Any]],
    *,
    title: str,
    message: str,
) -> tuple[list[dict[str, Any]], str]:
    state = getattr(getattr(ctx, "deps", None), "state", None)
    current_input = str(getattr(state, "current_input", "") or "").strip()
    runtime_state = {}
    data = getattr(state, "data", None)
    if isinstance(data, dict) and isinstance(data.get("runtime_state"), dict):
        runtime_state = data["runtime_state"]
    prompt_payload = {
        "task": current_input,
        "title": title,
        "message": message,
        "questions": questions,
        "runtime_state": runtime_state,
    }
    system_prompt = (
        "你正在为 SuperCode 的一键托管模式自动回答澄清问题。"
        "请站在用户任务目标和交付质量的角度选择最有利于继续推进的答案。"
        "必须只输出 JSON 对象，不要 Markdown。格式："
        '{"answers":[{"questionId":"问题 ID","selectedOptionIds":["选项 ID"],"text":"短文本答案","otherText":""}],"reason":"一句话说明"}。'
        "single_choice 只能选一个选项；multi_choice 可以选一个或多个；short_text 填写简短、可执行的默认答案。"
        "如果无法判断，选择题选第一个可用选项。"
    )
    request = ModelRequest(
        messages=[
            Message(role="system", content=system_prompt),
            Message(role="user", content=json.dumps(prompt_payload, ensure_ascii=False)),
        ],
        tools=[],
        ctx=ctx.deps,
        state=ctx.state,
        task="自动回答澄清问题",
    )
    response = await ctx.agent.model.complete(request)
    ctx.usage.add(response.usage)
    payload = _extract_json_object(response.text or "")
    return _normalize_autopilot_answers(questions, payload.get("answers")), str(payload.get("reason") or "").strip()


async def _build_autopilot_question_answers(
    ctx: ToolContext,
    questions: list[dict[str, Any]],
    *,
    title: str,
    message: str,
) -> tuple[list[dict[str, Any]], str]:
    try:
        answers, reason = await _build_model_autopilot_question_answers(
            ctx,
            questions,
            title=title,
            message=message,
        )
        return answers, reason or "已由当前模型根据上下文自动回答。"
    except Exception as exc:  # noqa: BLE001 - 托管兜底不能中断主任务
        return _build_fallback_question_answers(questions), f"模型自动回答失败，已使用首选项兜底：{exc}"


def _build_autopilot_summary(answers: list[dict[str, Any]]) -> str:
    lines = ["一键托管已自动回答澄清问题："]
    for answer in answers:
        prompt = str(answer.get("prompt") or answer.get("questionId") or "未命名问题").strip()
        if answer.get("type") == "short_text":
            value = str(answer.get("text") or answer.get("otherText") or "").strip() or "(未填写)"
        else:
            labels = [
                str(option.get("label") or "").strip()
                for option in answer.get("selectedOptions", [])
                if isinstance(option, dict) and str(option.get("label") or "").strip()
            ]
            value = "；".join(labels) if labels else "(未选择)"
        lines.append(f"- {prompt}: {value}")
    return "\n".join(lines)


class QuestionOption(BaseModel):
    """用户澄清选择题的单个选项。"""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="选项稳定 ID，可省略。")
    label: str = Field(description="展示给用户的选项标题。")
    description: str | None = Field(default=None, description="选项补充说明。")


QuestionOptions = Annotated[list[QuestionOption], BeforeValidator(_unwrap_tool_list)]


class PlanQuestion(BaseModel):
    """向用户发起的单个澄清问题。"""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="问题稳定 ID，可省略。")
    type: Literal["single_choice", "multi_choice", "short_text"] = Field(
        description="问题类型，只支持 single_choice、multi_choice、short_text。"
    )
    prompt: str = Field(description="展示给用户的问题文案。")
    required: bool = Field(default=True, description="用户是否必须回答。")
    placeholder: str | None = Field(default=None, description="短文本输入占位提示。")
    options: QuestionOptions | None = Field(
        default=None,
        description="选择题选项数组；single_choice/multi_choice 至少需要 2 项。",
    )


PlanQuestions = Annotated[list[PlanQuestion], BeforeValidator(_unwrap_tool_list)]


def _slugify(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return normalized or fallback


def _load_tinyfish_settings(ctx: ToolContext) -> dict[str, Any]:
    app_data_root = ctx.metadata.get("app_data_root")
    ui_settings: dict[str, Any] = {}
    if isinstance(app_data_root, (str, Path)):
        raw_settings = load_settings(Path(app_data_root)).get("tinyfish")
        ui_settings = raw_settings if isinstance(raw_settings, dict) else {}

    if bool(ui_settings.get("enabled")):
        api_key = str(ui_settings.get("apiKey") or "").strip()
        search_url = str(ui_settings.get("searchUrl") or DEFAULT_TINYFISH_SEARCH_URL).strip()
        fetch_url = str(ui_settings.get("fetchUrl") or DEFAULT_TINYFISH_FETCH_URL).strip()
        timeout_raw = str(ui_settings.get("timeout") or DEFAULT_TINYFISH_TIMEOUT_SECONDS).strip()
        try:
            timeout = max(5, int(timeout_raw))
        except ValueError:
            timeout = DEFAULT_TINYFISH_TIMEOUT_SECONDS
        if not api_key:
            raise RuntimeError("缺少 Tinyfish API Key，请先在设置里配置 Tinyfish。")
        return {
            "api_key": api_key,
            "search_url": search_url.rstrip("/") or DEFAULT_TINYFISH_SEARCH_URL,
            "fetch_url": fetch_url.rstrip("/") or DEFAULT_TINYFISH_FETCH_URL,
            "timeout": timeout,
        }

    project_root = ctx.metadata.get("project_root")
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
        raise RuntimeError("缺少 Tinyfish API Key，请先在设置或 .env 里配置 Tinyfish。")

    return {
        "api_key": api_key,
        "search_url": search_url.rstrip("/"),
        "fetch_url": fetch_url.rstrip("/"),
        "timeout": timeout,
    }


def _request_json(
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
        with open_url(request, timeout=timeout) as response:
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


def search_web(
    ctx: ToolContext,
    query: str,
    country: str = "",
    language: str = "",
    page: int = 0,
    from_date: str = "",
    to_date: str = "",
    include_images: bool = False,
    include_image_descriptions: bool = False,
    max_results: int = 5,
) -> dict[str, Any]:
    """使用 Tinyfish 搜索互联网资料。"""

    del from_date, to_date
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空。")

    settings = _load_tinyfish_settings(ctx)
    page = max(0, int(page or 0))
    max_results = min(MAX_SEARCH_RESULTS, max(1, int(max_results or 5)))
    query_params: dict[str, Any] = {
        "query": query,
        "page": page,
    }
    country = country.strip()
    if country:
        query_params["location"] = country
    language = language.strip()
    if language:
        query_params["language"] = language
    if isinstance(include_images, bool):
        query_params["include_images"] = "true" if include_images else "false"
    if isinstance(include_image_descriptions, bool):
        query_params["include_image_descriptions"] = (
            "true" if include_image_descriptions else "false"
        )

    url = f"{settings['search_url']}?{urlencode(query_params)}"
    payload = _request_json(
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


def fetch_url_content(ctx: ToolContext, urls: list[str]) -> dict[str, Any]:
    """使用 Tinyfish 抓取指定网页正文，适合对搜索命中的页面做精读。"""

    urls = _normalize_string_list(urls)
    if not urls:
        raise ValueError("urls 不能为空。")

    settings = _load_tinyfish_settings(ctx)
    payload = _request_json(
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


async def ask_plan_questions(
    ctx: ToolContext,
    questions: PlanQuestions,
    title: str = "需要确认一些需求细节",
    message: str = "请先回答下面几个关键问题，我会据此完善计划。",
) -> dict[str, Any]:
    """向用户发起需求澄清问题，支持 single_choice、multi_choice、short_text 三种题型。"""

    if not questions:
        raise ValueError("questions 不能为空。")

    normalized_questions: list[dict[str, Any]] = []
    raw_questions = _unwrap_tool_list(questions)
    if not isinstance(raw_questions, list):
        raise ValueError("questions 必须是对象数组。")

    for index, raw_question in enumerate(raw_questions, start=1):
        if isinstance(raw_question, BaseModel):
            raw_question = raw_question.model_dump(mode="python", exclude_none=True)
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
            normalized_raw_options = _normalize_object_list(raw_options, field_name="options")
            if len(normalized_raw_options) < 2:
                raise ValueError("选择题至少需要提供 2 个 options。")
            normalized_options: list[dict[str, Any]] = []
            for option_index, raw_option in enumerate(normalized_raw_options, start=1):
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

    if _is_super_autopilot_enabled(ctx):
        answers, autopilot_reason = await _build_autopilot_question_answers(
            ctx,
            normalized_questions,
            title=title.strip(),
            message=message.strip(),
        )
        return {
            "requires_user_input": False,
            "input_kind": "plan_questions",
            "kind": "plan_questions",
            "title": title.strip(),
            "message": _build_autopilot_summary(answers),
            "questions": normalized_questions,
            "answers": answers,
            "autopilot": True,
            "autopilot_reason": autopilot_reason,
        }

    payload = {
        "requires_user_input": True,
        "input_kind": "plan_questions",
        "title": title.strip(),
        "message": message.strip(),
        "questions": normalized_questions,
        "data_parts": [
            {
                "type": "data-plan-questions",
                "data": {
                    "title": title.strip(),
                    "message": message.strip(),
                    "questions": normalized_questions,
                },
            }
        ],
    }
    ctx.state.request_stop("")
    return payload


def _build_plan_markdown(
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


def save_plan(
    ctx: ToolContext,
    title: str,
    summary: str,
    overview: str,
    key_steps: list[str],
    markdown: str = "",
) -> dict[str, Any]:
    """保存当前计划草案到后端。"""

    del ctx
    title = title.strip()
    summary = summary.strip()
    overview = overview.strip()
    key_steps = _normalize_string_list(key_steps)
    markdown = markdown.strip()
    if not title:
        raise ValueError("title 不能为空。")
    if not summary:
        raise ValueError("summary 不能为空。")
    if not overview:
        raise ValueError("overview 不能为空。")
    if not key_steps:
        raise ValueError("key_steps 不能为空。")
    if not markdown:
        markdown = _build_plan_markdown(
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


def read_current_plan(ctx: ToolContext) -> dict[str, Any]:
    """读取当前会话里最新的计划草案/当前计划正文。"""

    backend_base_url = str(ctx.metadata.get("backend_base_url") or "").rstrip("/")
    session_id = str(ctx.metadata.get("session_id") or "").strip()
    if not backend_base_url or not session_id:
        raise RuntimeError("缺少 backend_base_url 或 session_id，无法读取当前计划。")

    payload = _request_json(
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


def create_task(
    ctx: ToolContext,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
) -> dict[str, Any]:
    """创建一个结构化 task。"""

    backend_base_url = str(ctx.metadata.get("backend_base_url") or "").rstrip("/")
    session_id = str(ctx.metadata.get("session_id") or "").strip()
    if not backend_base_url or not session_id:
        raise RuntimeError("缺少 backend_base_url 或 session_id，无法创建 task。")

    title = title.strip()
    summary = summary.strip()
    if not title:
        raise ValueError("title 不能为空。")
    if not summary:
        raise ValueError("summary 不能为空。")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps 不能为空。")

    normalized_steps: list[dict[str, str]] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            raise ValueError("steps 里的每一项都必须是对象。")
        step_title = str(raw_step.get("title") or "").strip()
        step_summary = str(raw_step.get("summary") or "").strip()
        if not step_title or not step_summary:
            raise ValueError("每个 step 都必须包含 title 和 summary。")
        normalized_steps.append({"title": step_title, "summary": step_summary})

    payload = _request_json(
        method="POST",
        url=f"{backend_base_url}/api/sessions/{session_id}/tasks",
        api_key="local-session",
        timeout=10,
        payload={"title": title, "summary": summary, "steps": normalized_steps},
    )
    return {
        "task_id": payload.get("task_id"),
        "step_ids": payload.get("step_ids"),
        "task": payload.get("task"),
        "planState": payload.get("planState"),
        "planSteps": payload.get("planSteps"),
    }


def get_task_status(ctx: ToolContext, task_id: str = "") -> dict[str, Any]:
    """获取当前会话里的 task 状态。"""

    backend_base_url = str(ctx.metadata.get("backend_base_url") or "").rstrip("/")
    session_id = str(ctx.metadata.get("session_id") or "").strip()
    if not backend_base_url or not session_id:
        raise RuntimeError("缺少 backend_base_url 或 session_id，无法读取 task 状态。")

    task_id = task_id.strip()
    query = f"?{urlencode({'task_id': task_id})}" if task_id else ""
    payload = _request_json(
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


search_web.supports_parallel = True
fetch_url_content.supports_parallel = True
