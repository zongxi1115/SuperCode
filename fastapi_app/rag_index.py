from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi_app.settings_store import load_settings


IGNORED_DIR_NAMES = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".supercode",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}

TEXT_EXTENSIONS = {
    ".css",
    ".go",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".scss",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}

SKIPPED_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}

MAX_FILE_BYTES = 512_000
CHUNK_LINE_COUNT = 80
CHUNK_OVERLAP_LINES = 12
MAX_STRUCTURAL_CHUNK_LINES = 160
MAX_STRUCTURAL_CHUNK_CHARS = 12_000
EMBEDDING_BATCH_SIZE = 16
BACKGROUND_MAX_FILES_PER_RUN = 400
CHUNKER_VERSION = "tree-sitter-v1"

LANGUAGE_BY_EXTENSION = {
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".scss": "scss",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
}

DECLARATION_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:export|default|public|private|protected|static|async|abstract|final|pub|internal|external|declare|override)\s+
    )*
    (?P<kind>
        class|interface|type|enum|struct|trait|impl|function|func|def|fn|
        module|namespace|component|const|let|var|record|service|controller
    )
    \b
    (?:\s+(?P<symbol>[A-Za-z_$][\w$.-]*))?
    """,
    re.VERBOSE,
)
ASSIGNMENT_FUNCTION_RE = re.compile(
    r"^\s*(?P<symbol>[A-Za-z_$][\w$.-]*)\s*[:=]\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)
CALLABLE_SIGNATURE_RE = re.compile(
    r"^\s*(?P<symbol>[A-Za-z_$][\w$]*)\s*\([^;]*\)\s*(?:[{:]|=>)?\s*$"
)
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<symbol>.+?)\s*$")
CONTROL_FLOW_WORDS = {
    "catch",
    "elif",
    "else",
    "for",
    "foreach",
    "if",
    "return",
    "switch",
    "try",
    "while",
    "with",
}

_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_KEYS: set[str] = set()


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.model)


@dataclass(frozen=True, slots=True)
class RagSearchMatch:
    path: str
    start_line: int
    end_line: int
    score: float
    content: str
    kind: str = "text"
    symbol: str = ""
    language: str = ""


@dataclass(frozen=True, slots=True)
class CodeChunk:
    start_line: int
    end_line: int
    content: str
    kind: str
    symbol: str
    language: str


def load_embedding_config(app_root: Path) -> EmbeddingConfig:
    raw_embedding = load_settings(app_root).get("embedding")
    embedding = raw_embedding if isinstance(raw_embedding, dict) else {}
    return EmbeddingConfig(
        enabled=bool(embedding.get("enabled")),
        base_url=str(embedding.get("baseUrl") or "").strip().rstrip("/"),
        api_key=str(embedding.get("apiKey") or "").strip(),
        model=str(embedding.get("model") or "").strip(),
    )


def test_embedding_config(raw_config: dict[str, Any]) -> dict[str, Any]:
    config = EmbeddingConfig(
        enabled=True,
        base_url=str(raw_config.get("baseUrl") or "").strip().rstrip("/"),
        api_key=str(raw_config.get("apiKey") or "").strip(),
        model=str(raw_config.get("model") or "").strip(),
    )
    if not config.base_url:
        raise ValueError("Embedding Base URL 不能为空。")
    if not config.api_key:
        raise ValueError("Embedding API Key 不能为空。")
    if not config.model:
        raise ValueError("Embedding Model 不能为空。")

    index = RagCodeIndex(Path.cwd(), Path.cwd(), config)
    embeddings = index._embed_texts(["SuperCode embedding connectivity test"])
    if not embeddings:
        raise ValueError("Embedding 接口没有返回可用向量。")
    return {
        "ok": True,
        "model": config.model,
        "dimension": len(embeddings[0]),
    }


def schedule_workspace_rag_index(app_root: Path, workspace: str | Path) -> None:
    config = load_embedding_config(app_root)
    if not config.is_configured:
        return

    workspace_path = Path(workspace).resolve()
    key = _workspace_key(workspace_path)
    with _BACKGROUND_LOCK:
        if key in _BACKGROUND_KEYS:
            return
        _BACKGROUND_KEYS.add(key)

    def run() -> None:
        try:
            RagCodeIndex(app_root, workspace_path, config).ensure_index(
                max_changed_files=BACKGROUND_MAX_FILES_PER_RUN
            )
        finally:
            with _BACKGROUND_LOCK:
                _BACKGROUND_KEYS.discard(key)

    thread = threading.Thread(target=run, name=f"supercode-rag-{key[:8]}", daemon=True)
    thread.start()


def search_workspace_rag(
    app_root: Path,
    workspace: str | Path,
    query: str,
    *,
    search_path: str = ".",
    limit: int = 8,
) -> list[RagSearchMatch]:
    config = load_embedding_config(app_root)
    if not config.is_configured:
        return []

    index = RagCodeIndex(app_root, Path(workspace).resolve(), config)
    index.ensure_index(max_changed_files=24)
    return index.search(query, search_path=search_path, limit=limit)


class RagCodeIndex:
    def __init__(self, app_root: Path, workspace: Path, config: EmbeddingConfig) -> None:
        self.app_root = app_root.resolve()
        self.workspace = workspace.resolve()
        self.config = config
        self.db_path = self.app_root / ".supercode" / "rag-index" / f"{_workspace_key(self.workspace)}.sqlite"

    def ensure_index(self, *, max_changed_files: int | None = None) -> None:
        if not self.config.is_configured or not self.workspace.exists():
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._init_db(connection)
            known_files = self._load_known_files(connection)
            current_files = list(self._iter_indexable_files())
            current_paths = {path for path, _, _, _ in current_files}
            self._remove_deleted_files(connection, set(known_files) - current_paths)

            changed: list[tuple[str, Path, int, int, str]] = []
            for relative_path, absolute_path, mtime_ns, size, digest in current_files:
                known = known_files.get(relative_path)
                if known == (mtime_ns, size, digest, CHUNKER_VERSION):
                    continue
                changed.append((relative_path, absolute_path, mtime_ns, size, digest))
                if max_changed_files is not None and len(changed) >= max_changed_files:
                    break

            for relative_path, absolute_path, mtime_ns, size, digest in changed:
                self._index_file(connection, relative_path, absolute_path, mtime_ns, size, digest)

    def search(self, query: str, *, search_path: str = ".", limit: int = 8) -> list[RagSearchMatch]:
        query = query.strip()
        if not query:
            return []

        query_embedding = self._embed_texts([query])
        if not query_embedding:
            return []

        normalized_prefix = self._normalize_search_path(search_path)
        matches: list[RagSearchMatch] = []
        with self._connect() as connection:
            self._init_db(connection)
            for row in connection.execute(
                """
                SELECT path, start_line, end_line, content, embedding
                    , kind, symbol, language
                FROM chunks
                WHERE (? = '' OR path = ? OR path LIKE ?)
                """,
                (normalized_prefix, normalized_prefix, f"{normalized_prefix}/%"),
            ):
                embedding = _parse_embedding(row["embedding"])
                score = _cosine_similarity(query_embedding[0], embedding)
                if score <= 0:
                    continue
                matches.append(
                    RagSearchMatch(
                        path=str(row["path"]),
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        score=score,
                        content=str(row["content"]),
                        kind=str(row["kind"] or "text"),
                        symbol=str(row["symbol"] or ""),
                        language=str(row["language"] or ""),
                    )
                )

        matches.sort(key=lambda item: item.score, reverse=True)
        return _dedupe_matches(matches, limit=max(1, limit))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                indexed_at REAL NOT NULL,
                chunker_version TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._ensure_file_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'text',
                symbol TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._ensure_chunk_columns(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)")

    def _ensure_file_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(files)").fetchall()
        }
        if "chunker_version" not in existing_columns:
            connection.execute("ALTER TABLE files ADD COLUMN chunker_version TEXT NOT NULL DEFAULT ''")

    def _ensure_chunk_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
        }
        for name, definition in {
            "kind": "TEXT NOT NULL DEFAULT 'text'",
            "symbol": "TEXT NOT NULL DEFAULT ''",
            "language": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE chunks ADD COLUMN {name} {definition}")

    def _load_known_files(self, connection: sqlite3.Connection) -> dict[str, tuple[int, int, str, str]]:
        rows = connection.execute("SELECT path, mtime_ns, size, sha256, chunker_version FROM files").fetchall()
        return {
            str(row["path"]): (
                int(row["mtime_ns"]),
                int(row["size"]),
                str(row["sha256"]),
                str(row["chunker_version"] or ""),
            )
            for row in rows
        }

    def _remove_deleted_files(self, connection: sqlite3.Connection, deleted_paths: set[str]) -> None:
        for path in deleted_paths:
            connection.execute("DELETE FROM chunks WHERE path = ?", (path,))
            connection.execute("DELETE FROM files WHERE path = ?", (path,))

    def _iter_indexable_files(self) -> list[tuple[str, Path, int, int, str]]:
        files: list[tuple[str, Path, int, int, str]] = []
        for path in self.workspace.rglob("*"):
            if not path.is_file() or not _is_indexable_file(path):
                continue
            try:
                relative = path.relative_to(self.workspace).as_posix()
            except ValueError:
                continue
            if any(part in IGNORED_DIR_NAMES for part in Path(relative).parts):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES:
                continue
            digest = _sha256_file(path)
            files.append((relative, path, int(stat.st_mtime_ns), int(stat.st_size), digest))
        files.sort(key=lambda item: item[0])
        return files

    def _index_file(
        self,
        connection: sqlite3.Connection,
        relative_path: str,
        absolute_path: Path,
        mtime_ns: int,
        size: int,
        digest: str,
    ) -> None:
        text = _read_text_lossy(absolute_path)
        chunks = _chunk_code(relative_path, text)
        chunk_payloads = [
            {
                "id": f"{relative_path}:{chunk.start_line}:{chunk.end_line}:{_sha256_text(chunk.content)[:12]}",
                "path": relative_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "content_hash": _sha256_text(chunk.content),
                "kind": chunk.kind,
                "symbol": chunk.symbol,
                "language": chunk.language,
            }
            for chunk in chunks
            if chunk.content.strip()
        ]
        embeddings = self._embed_texts(
            [
                "\n".join(
                    part
                    for part in [
                        str(payload["path"]),
                        str(payload["language"]),
                        str(payload["kind"]),
                        str(payload["symbol"]),
                        str(payload["content"]),
                    ]
                    if part
                )
                for payload in chunk_payloads
            ]
        )
        if len(embeddings) != len(chunk_payloads):
            return

        connection.execute("DELETE FROM chunks WHERE path = ?", (relative_path,))
        for payload, embedding in zip(chunk_payloads, embeddings):
            connection.execute(
                """
                INSERT OR REPLACE INTO chunks
                    (id, path, start_line, end_line, content, content_hash, embedding, kind, symbol, language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["path"],
                    payload["start_line"],
                    payload["end_line"],
                    payload["content"],
                    payload["content_hash"],
                    json.dumps(embedding, separators=(",", ":")),
                    payload["kind"],
                    payload["symbol"],
                    payload["language"],
                ),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO files(path, mtime_ns, size, sha256, indexed_at, chunker_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (relative_path, mtime_ns, size, digest, time.time(), CHUNKER_VERSION),
        )

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            embeddings.extend(self._request_embeddings(batch))
        return embeddings

    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = json.dumps({"model": self.config.model, "input": texts}).encode("utf-8")
        endpoint = _embedding_endpoint(self.config.base_url)
        request = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "SuperCode/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

        data = payload.get("data")
        if not isinstance(data, list):
            return []
        ordered = sorted(
            [item for item in data if isinstance(item, dict)],
            key=lambda item: int(item.get("index", 0)),
        )
        embeddings: list[list[float]] = []
        for item in ordered:
            raw_embedding = item.get("embedding")
            if not isinstance(raw_embedding, list):
                continue
            vector = [float(value) for value in raw_embedding if isinstance(value, (int, float))]
            if vector:
                embeddings.append(vector)
        return embeddings

    def _normalize_search_path(self, search_path: str) -> str:
        raw = (search_path or ".").strip().replace("\\", "/")
        if raw in {"", "."}:
            return ""
        candidate = (self.workspace / raw).resolve()
        try:
            return candidate.relative_to(self.workspace).as_posix()
        except ValueError:
            return ""


def _workspace_key(workspace: Path) -> str:
    return hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()


def _embedding_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/embeddings"):
        return normalized
    return f"{normalized}/embeddings"


def _is_indexable_file(path: Path) -> bool:
    if path.name in SKIPPED_FILENAMES:
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _read_text_lossy(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunk_code(relative_path: str, text: str) -> list[CodeChunk]:
    lines = text.splitlines()
    language = _language_for_path(relative_path)
    if not lines:
        return []

    ast_chunks = _chunk_by_tree_sitter(text, language)
    if ast_chunks:
        return ast_chunks

    structural_chunks = _chunk_by_structure(lines, language)
    if structural_chunks:
        return structural_chunks
    return _chunk_by_line_windows(lines, language)


def _language_for_path(relative_path: str) -> str:
    return LANGUAGE_BY_EXTENSION.get(Path(relative_path).suffix.lower(), "text")


def _chunk_by_tree_sitter(text: str, language: str) -> list[CodeChunk]:
    parser = _get_tree_sitter_parser(language)
    if parser is None:
        return []

    source = text.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(text)
    except Exception:
        return []

    root_node = getattr(tree, "root_node", None)
    if callable(root_node):
        try:
            root_node = root_node()
        except Exception:
            return []
    if root_node is None:
        return []

    selected_nodes: list[Any] = []
    _collect_tree_sitter_nodes(root_node, source, selected_nodes)
    if not selected_nodes:
        return []

    lines = text.splitlines()
    chunks: list[CodeChunk] = []
    cursor_line = 0
    for node in sorted(selected_nodes, key=lambda item: (_node_start_row(item), _node_start_column(item))):
        start_line = _node_start_row(node)
        end_line = _node_end_row(node)
        if start_line > cursor_line:
            context_chunk = _build_code_chunk(
                lines,
                cursor_line,
                start_line - 1,
                kind="context",
                symbol="",
                language=language,
            )
            if context_chunk is not None:
                chunks.extend(_split_oversized_chunk(context_chunk))

        kind = _normalize_tree_sitter_kind(_node_kind(node))
        symbol = _extract_tree_sitter_symbol(node, source)
        node_chunk = _build_code_chunk(
            lines,
            start_line,
            end_line,
            kind=kind,
            symbol=symbol,
            language=language,
        )
        if node_chunk is not None:
            chunks.extend(_split_oversized_chunk(node_chunk))
        cursor_line = max(cursor_line, end_line + 1)

    if cursor_line < len(lines):
        tail_chunk = _build_code_chunk(
            lines,
            cursor_line,
            len(lines) - 1,
            kind="context",
            symbol="",
            language=language,
        )
        if tail_chunk is not None:
            chunks.extend(_split_oversized_chunk(tail_chunk))

    return chunks


@lru_cache(maxsize=64)
def _get_tree_sitter_parser(language: str) -> Any | None:
    if not language or language == "text":
        return None
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:
        return None
    try:
        return get_parser(language)
    except Exception:
        return None


def _collect_tree_sitter_nodes(node: Any, source: bytes, selected_nodes: list[Any]) -> bool:
    if _is_tree_sitter_chunk_node(node):
        node_line_count = _node_end_row(node) - _node_start_row(node) + 1
        node_size = _node_end_byte(node) - _node_start_byte(node)
        if node_line_count <= MAX_STRUCTURAL_CHUNK_LINES and node_size <= MAX_STRUCTURAL_CHUNK_CHARS:
            selected_nodes.append(node)
            return True

        child_added = False
        for child in _named_children(node):
            child_added = _collect_tree_sitter_nodes(child, source, selected_nodes) or child_added
        if not child_added:
            selected_nodes.append(node)
        return True

    child_added = False
    for child in _named_children(node):
        child_added = _collect_tree_sitter_nodes(child, source, selected_nodes) or child_added
    return child_added


def _is_tree_sitter_chunk_node(node: Any) -> bool:
    node_type = _node_kind(node).lower()
    if _node_parent(node) is None and node_type in {"module", "program", "source_file", "document"}:
        return False
    if not node_type or node_type in {
        "comment",
        "error",
        "identifier",
        "string",
        "number",
        "parameters",
        "arguments",
        "block",
        "body",
    }:
        return False
    structural_terms = (
        "function",
        "method",
        "class",
        "interface",
        "struct",
        "enum",
        "trait",
        "impl",
        "module",
        "namespace",
        "type_alias",
        "component",
        "declaration",
        "definition",
    )
    if not any(term in node_type for term in structural_terms):
        return False
    if "import" in node_type or "comment" in node_type:
        return False
    return True


def _point_row(point: Any) -> int:
    if point is None:
        return 0
    row = getattr(point, "row", None)
    if isinstance(row, int):
        return row
    try:
        return int(point[0])
    except Exception:
        return 0


def _point_column(point: Any) -> int:
    if point is None:
        return 0
    column = getattr(point, "column", None)
    if isinstance(column, int):
        return column
    try:
        return int(point[1])
    except Exception:
        return 0


def _node_kind(node: Any) -> str:
    value = getattr(node, "type", None)
    if value is None:
        value = getattr(node, "kind", None)
    if callable(value):
        try:
            value = value()
        except Exception:
            value = None
    return str(value or "")


def _node_parent(node: Any) -> Any | None:
    value = getattr(node, "parent", None)
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


def _node_start_byte(node: Any) -> int:
    return _call_int_attr(node, "start_byte")


def _node_end_byte(node: Any) -> int:
    return _call_int_attr(node, "end_byte")


def _node_start_row(node: Any) -> int:
    return _point_row(_node_point(node, "start_point", "start_position"))


def _node_end_row(node: Any) -> int:
    return _point_row(_node_point(node, "end_point", "end_position"))


def _node_start_column(node: Any) -> int:
    return _point_column(_node_point(node, "start_point", "start_position"))


def _node_point(node: Any, *names: str) -> Any:
    for name in names:
        value = getattr(node, name, None)
        if callable(value):
            try:
                return value()
            except Exception:
                continue
        if value is not None:
            return value
    return None


def _call_int_attr(node: Any, name: str) -> int:
    value = getattr(node, name, 0)
    if callable(value):
        try:
            value = value()
        except Exception:
            value = 0
    try:
        return int(value)
    except Exception:
        return 0


def _named_children(node: Any) -> list[Any]:
    raw_children = getattr(node, "named_children", None)
    if raw_children is not None:
        try:
            return list(raw_children() if callable(raw_children) else raw_children)
        except Exception:
            return []

    count = _call_int_attr(node, "named_child_count")
    if count <= 0:
        return []
    child_getter = getattr(node, "named_child", None)
    if not callable(child_getter):
        return []
    children: list[Any] = []
    for index in range(count):
        try:
            child = child_getter(index)
        except Exception:
            child = None
        if child is not None:
            children.append(child)
    return children


def _normalize_tree_sitter_kind(node_type: str) -> str:
    normalized = node_type.lower()
    for term in (
        "function",
        "method",
        "class",
        "interface",
        "struct",
        "enum",
        "trait",
        "impl",
        "module",
        "namespace",
        "type",
        "component",
        "declaration",
        "definition",
    ):
        if term in normalized:
            return term
    return normalized or "node"


def _extract_tree_sitter_symbol(node: Any, source: bytes) -> str:
    for field_name in ("name", "declarator", "type"):
        try:
            child = node.child_by_field_name(field_name)
        except Exception:
            child = None
        symbol = _node_text(child, source)
        if symbol:
            return _clean_symbol(symbol)

    for child in _named_children(node):
        child_type = _node_kind(child).lower()
        if "identifier" not in child_type and child_type not in {"name", "property_identifier", "type_identifier"}:
            continue
        symbol = _node_text(child, source)
        if symbol:
            return _clean_symbol(symbol)

    node_text = _node_text(node, source)
    first_line = node_text.splitlines()[0] if node_text else ""
    metadata = _extract_declaration_metadata(first_line)
    if metadata is not None and metadata[1]:
        return _clean_symbol(metadata[1])

    return ""


def _node_text(node: Any | None, source: bytes) -> str:
    if node is None:
        return ""
    try:
        raw = source[_node_start_byte(node) : _node_end_byte(node)]
    except Exception:
        return ""
    return raw.decode("utf-8", errors="ignore").strip()


def _clean_symbol(value: str) -> str:
    first_line = value.strip().splitlines()[0] if value.strip() else ""
    first_line = first_line.strip("`'\" ")
    if len(first_line) > 120:
        return first_line[:120].rstrip()
    return first_line


def _chunk_by_structure(lines: list[str], language: str) -> list[CodeChunk]:
    boundaries = [
        (index, metadata)
        for index, line in enumerate(lines)
        if (metadata := _extract_declaration_metadata(line)) is not None
    ]
    if not boundaries:
        return []

    chunks: list[CodeChunk] = []
    chunk_start = 0
    chunk_kind = "preamble"
    chunk_symbol = ""
    boundary_by_index = {index: metadata for index, metadata in boundaries}

    for index, line in enumerate(lines):
        metadata = boundary_by_index.get(index)
        if metadata is not None and index > chunk_start:
            chunk = _build_code_chunk(
                lines,
                chunk_start,
                index - 1,
                kind=chunk_kind,
                symbol=chunk_symbol,
                language=language,
            )
            if chunk is not None:
                chunks.extend(_split_oversized_chunk(chunk))
            chunk_start = index
            chunk_kind, chunk_symbol = metadata
        elif metadata is not None:
            chunk_kind, chunk_symbol = metadata

        current_line_count = index - chunk_start + 1
        current_chars = sum(len(item) + 1 for item in lines[chunk_start : index + 1])
        if (
            current_line_count >= MAX_STRUCTURAL_CHUNK_LINES
            or current_chars >= MAX_STRUCTURAL_CHUNK_CHARS
        ):
            chunk = _build_code_chunk(
                lines,
                chunk_start,
                index,
                kind=chunk_kind,
                symbol=chunk_symbol,
                language=language,
            )
            if chunk is not None:
                chunks.extend(_split_oversized_chunk(chunk))
            chunk_start = index + 1
            chunk_kind = "continuation"

    tail = _build_code_chunk(
        lines,
        chunk_start,
        len(lines) - 1,
        kind=chunk_kind,
        symbol=chunk_symbol,
        language=language,
    )
    if tail is not None:
        chunks.extend(_split_oversized_chunk(tail))

    return chunks


def _extract_declaration_metadata(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    heading_match = MARKDOWN_HEADING_RE.match(line)
    if heading_match is not None:
        return "section", heading_match.group("symbol").strip()

    assignment_match = ASSIGNMENT_FUNCTION_RE.match(line)
    if assignment_match is not None:
        return "function", assignment_match.group("symbol").strip()

    declaration_match = DECLARATION_RE.match(line)
    if declaration_match is not None:
        kind = declaration_match.group("kind").strip()
        symbol = str(declaration_match.group("symbol") or "").strip("=:({")
        if kind in {"const", "let", "var"} and not _looks_like_callable_assignment(line):
            return "value", symbol
        return kind, symbol

    callable_match = CALLABLE_SIGNATURE_RE.match(line)
    if callable_match is not None and _indent_width(line) <= 8:
        symbol = callable_match.group("symbol").strip()
        if symbol.lower() not in CONTROL_FLOW_WORDS:
            return "function", symbol

    return None


def _looks_like_callable_assignment(line: str) -> bool:
    return "=>" in line or "function" in line


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _build_code_chunk(
    lines: list[str],
    start_index: int,
    end_index: int,
    *,
    kind: str,
    symbol: str,
    language: str,
) -> CodeChunk | None:
    start = max(start_index, 0)
    end = min(end_index, len(lines) - 1)
    while start <= end and not lines[start].strip():
        start += 1
    while end >= start and not lines[end].strip():
        end -= 1
    if start > end:
        return None
    content = "\n".join(lines[start : end + 1]).strip()
    if not content:
        return None
    return CodeChunk(
        start_line=start + 1,
        end_line=end + 1,
        content=content,
        kind=kind or "text",
        symbol=symbol,
        language=language,
    )


def _split_oversized_chunk(chunk: CodeChunk) -> list[CodeChunk]:
    lines = chunk.content.splitlines()
    if len(lines) <= CHUNK_LINE_COUNT and len(chunk.content) <= MAX_STRUCTURAL_CHUNK_CHARS:
        return [chunk]
    split_chunks: list[CodeChunk] = []
    step = max(1, CHUNK_LINE_COUNT - CHUNK_OVERLAP_LINES)
    for offset in range(0, len(lines), step):
        segment = lines[offset : offset + CHUNK_LINE_COUNT]
        if not segment:
            continue
        split_chunks.append(
            CodeChunk(
                start_line=chunk.start_line + offset,
                end_line=chunk.start_line + offset + len(segment) - 1,
                content="\n".join(segment).strip(),
                kind=chunk.kind,
                symbol=chunk.symbol,
                language=chunk.language,
            )
        )
        if offset + CHUNK_LINE_COUNT >= len(lines):
            break
    return [item for item in split_chunks if item.content]


def _chunk_by_line_windows(lines: list[str], language: str) -> list[CodeChunk]:
    if not lines:
        return []
    chunks: list[CodeChunk] = []
    step = max(1, CHUNK_LINE_COUNT - CHUNK_OVERLAP_LINES)
    for start_index in range(0, len(lines), step):
        end_index = min(start_index + CHUNK_LINE_COUNT, len(lines))
        content = "\n".join(lines[start_index:end_index]).strip()
        if content:
            chunks.append(
                CodeChunk(
                    start_line=start_index + 1,
                    end_line=end_index,
                    content=content,
                    kind="window",
                    symbol="",
                    language=language,
                )
            )
        if end_index >= len(lines):
            break
    return chunks


def _parse_embedding(value: str) -> list[float]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [float(item) for item in raw if isinstance(item, (int, float))]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _dedupe_matches(matches: list[RagSearchMatch], *, limit: int) -> list[RagSearchMatch]:
    selected: list[RagSearchMatch] = []
    selected_ranges: set[tuple[str, int, int]] = set()
    chunks_per_path: dict[str, int] = {}
    for match in matches:
        range_key = (match.path, match.start_line, match.end_line)
        if range_key in selected_ranges:
            continue
        if chunks_per_path.get(match.path, 0) >= 2:
            continue
        selected.append(match)
        selected_ranges.add(range_key)
        chunks_per_path[match.path] = chunks_per_path.get(match.path, 0) + 1
        if len(selected) >= limit:
            break
    return selected
