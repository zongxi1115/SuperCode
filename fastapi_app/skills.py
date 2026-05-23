from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi_app.workspace_utils import resolve_workspace_path


SKILL_MENTION_RE = re.compile(r"@\[((?:\\.|[^\]])*)\]")
BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "builtin_skills"
SEARCH_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{1,}|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
MAX_AUTO_SELECTED_SKILLS = 3


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    id: str
    name: str
    description: str
    scope: str
    skill_dir: Path
    skill_file: Path
    content: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "sourcePath": str(self.skill_file),
        }

    def to_activation_payload(self, source: str = "manual") -> dict[str, Any]:
        payload = self.to_summary()
        payload["activationSource"] = source
        payload["content"] = self.content
        return payload


def list_available_skills(workspace: str | Path) -> list[SkillDefinition]:
    skills_by_id: dict[str, SkillDefinition] = {}

    for skill in _scan_skill_root(BUILTIN_SKILLS_ROOT, scope="builtin"):
        skills_by_id[skill.id] = skill

    workspace_root = resolve_workspace_path(workspace)
    for skill in _scan_skill_root(workspace_root / ".agents" / "skills", scope="workspace"):
        skills_by_id[skill.id] = skill

    return sorted(
        skills_by_id.values(),
        key=lambda item: (0 if item.scope == "workspace" else 1, item.name.lower(), item.id),
    )


def list_available_skill_summaries(workspace: str | Path) -> list[dict[str, Any]]:
    return [skill.to_summary() for skill in list_available_skills(workspace)]


def resolve_message_skills(
    workspace: str | Path,
    message: str,
    requested_skill_ids: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    available_skills = list_available_skills(workspace)
    skill_map = {skill.id: skill for skill in available_skills}

    resolved_skills: list[dict[str, Any]] = []
    seen_skill_ids: set[str] = set()
    for reference in [*(requested_skill_ids or []), *extract_skill_references_from_message(message)]:
        normalized_reference = normalize_skill_reference(reference)
        if not normalized_reference or normalized_reference in seen_skill_ids:
            continue
        skill = skill_map.get(normalized_reference)
        if skill is None:
            continue
        resolved_skills.append(skill.to_activation_payload(source="manual"))
        seen_skill_ids.add(normalized_reference)

    cleaned_message = strip_skill_mentions(message)
    if not seen_skill_ids:
        resolved_skills.extend(
            select_relevant_skills_from_catalog(
                available_skills,
                cleaned_message,
                excluded_skill_ids=seen_skill_ids,
            )
        )

    return cleaned_message, resolved_skills


def extract_skill_references_from_message(message: str) -> list[str]:
    references: list[str] = []
    for match in SKILL_MENTION_RE.finditer(message):
        decoded = decode_mention_token_value(match.group(1) or "")
        if decoded.lower().startswith("skill:"):
            references.append(decoded.split(":", 1)[1].strip())
    return references


def strip_skill_mentions(message: str) -> str:
    if "@[" not in message:
        return message.strip()

    parts: list[str] = []
    last_index = 0
    for match in SKILL_MENTION_RE.finditer(message):
        parts.append(message[last_index:match.start()])
        decoded = decode_mention_token_value(match.group(1) or "")
        if not decoded.lower().startswith("skill:"):
            parts.append(match.group(0))
        last_index = match.end()
    parts.append(message[last_index:])

    cleaned = "".join(parts)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def decode_mention_token_value(value: str) -> str:
    return value.replace(r"\]", "]")


def normalize_skill_reference(reference: str) -> str:
    decoded = decode_mention_token_value(reference.strip())
    if decoded.lower().startswith("skill:"):
        decoded = decoded.split(":", 1)[1].strip()
    return slugify_skill_id(decoded)


def slugify_skill_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "skill"


def select_relevant_skills(
    workspace: str | Path,
    message: str,
    excluded_skill_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    return select_relevant_skills_from_catalog(
        list_available_skills(workspace),
        message,
        excluded_skill_ids=excluded_skill_ids,
    )


def select_relevant_skills_from_catalog(
    available_skills: list[SkillDefinition],
    message: str,
    excluded_skill_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_message = normalize_search_text(message)
    if not normalized_message:
        return []

    excluded_ids = excluded_skill_ids or set()
    message_terms = extract_search_terms(normalized_message)
    if not message_terms:
        return []

    scored_matches: list[tuple[float, SkillDefinition, str]] = []
    for skill in available_skills:
        if skill.id in excluded_ids:
            continue
        score, reason = _score_skill_match(skill, normalized_message, message_terms)
        if score <= 0:
            continue
        scored_matches.append((score, skill, reason))

    scored_matches.sort(key=lambda item: (-item[0], item[1].name.lower(), item[1].id))

    selected: list[dict[str, Any]] = []
    for score, skill, reason in scored_matches[:MAX_AUTO_SELECTED_SKILLS]:
        payload = skill.to_activation_payload(source="auto")
        payload["matchScore"] = round(score, 2)
        payload["matchReason"] = reason
        selected.append(payload)
    return selected


def normalize_search_text(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def extract_search_terms(value: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in SEARCH_TERM_RE.finditer(value):
        term = match.group(0).strip("._:/-")
        for candidate in _expand_search_term(term):
            if len(candidate) < 2 or candidate in seen:
                continue
            seen.add(candidate)
            terms.append(candidate)
    return terms


def _expand_search_term(term: str) -> list[str]:
    if not term:
        return []
    if re.fullmatch(r"[\u4e00-\u9fff]{2,}", term):
        candidates = [term]
        if len(term) <= 24:
            for index in range(len(term) - 1):
                candidates.append(term[index : index + 2])
        return candidates
    return [term]


def _score_skill_match(
    skill: SkillDefinition,
    normalized_message: str,
    message_terms: list[str],
) -> tuple[float, str]:
    id_text = normalize_search_text(skill.id)
    name_text = normalize_search_text(skill.name)
    description_text = normalize_search_text(skill.description)
    summary_text = " ".join(part for part in [id_text, name_text, description_text] if part)
    if not summary_text:
        return 0.0, ""

    score = 0.0
    reasons: list[str] = []

    if id_text and id_text in normalized_message:
        score += 8.0
        reasons.append(f"id:{skill.id}")
    if name_text and name_text in normalized_message and name_text != id_text:
        score += 6.0
        reasons.append(f"name:{skill.name}")

    matched_terms: list[str] = []
    for term in message_terms:
        if term not in summary_text:
            continue
        matched_terms.append(term)
        if term in description_text:
            score += 2.5
        elif term in name_text or term in id_text:
            score += 2.0
        else:
            score += 1.0

    if matched_terms:
        reasons.append("terms:" + ",".join(matched_terms[:5]))

    if not reasons or score < 2.5:
        return 0.0, ""
    return score, "; ".join(reasons)


def _scan_skill_root(skill_root: Path, scope: str) -> list[SkillDefinition]:
    if not skill_root.exists() or not skill_root.is_dir():
        return []

    skills: list[SkillDefinition] = []
    for entry in sorted(skill_root.iterdir(), key=lambda path: path.name.lower()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        skill = _load_skill_definition(skill_file, scope=scope)
        if skill is not None:
            skills.append(skill)
    return skills


def _load_skill_definition(skill_file: Path, scope: str) -> SkillDefinition | None:
    raw_text = skill_file.read_text(encoding="utf-8").strip()
    if not raw_text:
        return None

    metadata, body = _split_frontmatter(raw_text)
    name = str(metadata.get("name") or skill_file.parent.name).strip() or skill_file.parent.name
    description = str(metadata.get("description") or "").strip()
    content = body.strip() or raw_text

    return SkillDefinition(
        id=slugify_skill_id(name),
        name=name,
        description=description,
        scope=scope,
        skill_dir=skill_file.parent.resolve(),
        skill_file=skill_file.resolve(),
        content=content,
    )


def _split_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw_text

    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        frontmatter_text = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :])
        return _parse_simple_frontmatter(frontmatter_text), body

    return {}, raw_text


def _parse_simple_frontmatter(frontmatter_text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in frontmatter_text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key:
            current_value = metadata.get(current_list_key)
            if isinstance(current_value, list):
                current_value.append(_parse_frontmatter_scalar(stripped[2:]))
            continue

        current_list_key = None
        if ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        normalized_key = key.strip()
        value = raw_value.strip()
        if not value:
            metadata[normalized_key] = []
            current_list_key = normalized_key
            continue
        metadata[normalized_key] = _parse_frontmatter_scalar(value)

    return metadata


def _parse_frontmatter_scalar(value: str) -> Any:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]

    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [_parse_frontmatter_scalar(part) for part in inner.split(",")]

    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return stripped
