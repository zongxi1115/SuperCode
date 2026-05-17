from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

FILE_TREE_IGNORED_DIR_NAMES = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
FILE_TREE_MAX_DEPTH = 4
FILE_TREE_MAX_ENTRIES_PER_DIR = 200

FILE_TREE_ALLOWED_SUFFIXES = {
    ".ts",
    ".tsx",
    ".css",
    ".json",
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".html",
    ".sql",
    ".rs",
    ".go",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".cmd",
    ".ps1",
    ".env",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc",
    ".babelrc",
    ".svelte",
    ".vue",
    ".prisma",
    ".graphql",
    ".gql",
    ".proto",
    ".xml",
    ".ini",
    ".cfg",
    ".conf",
    ".config",
    ".lock",
    ".sum",
    ".mod",
    ".txt",
    ".log",
    ".diff",
    ".patch",
    ".svg",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}


def normalize_workspace(raw_workspace: str | None, default_workspace: str | Path) -> str:
    if raw_workspace is None or not raw_workspace.strip():
        return str(Path(default_workspace).expanduser().resolve())
    candidate = Path(raw_workspace.strip()).expanduser().resolve()
    if not candidate.exists():
        raise HTTPException(status_code=400, detail="工作区不存在")
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="工作区必须是目录")
    return str(candidate)


def resolve_workspace_path(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def normalize_relative_path(raw_path: str, workspace: str) -> str:
    workspace_path = resolve_workspace_path(workspace)
    candidate_path = Path(raw_path)
    workspace_candidate = (
        candidate_path.expanduser().resolve()
        if candidate_path.is_absolute()
        else (workspace_path / candidate_path).resolve()
    )
    if workspace_path != workspace_candidate and workspace_path not in workspace_candidate.parents:
        raise HTTPException(status_code=400, detail="路径越界")
    return str(workspace_candidate)


def resolve_preview_path(raw_path: str, workspace: str) -> Path:
    workspace_root = resolve_workspace_path(workspace)
    normalized = raw_path.strip().strip("/")
    candidate = workspace_root if not normalized else (workspace_root / normalized).resolve()
    if workspace_root != candidate and workspace_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="预览路径越界")

    if candidate.is_dir():
        for entry_name in ("index.html", "index.htm"):
            entry = candidate / entry_name
            if entry.exists() and entry.is_file():
                return entry
        raise HTTPException(status_code=404, detail="目录下未找到 index.html")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail="预览目标不存在")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="预览目标不是文件")
    return candidate


def build_file_tree(root: Path, max_depth: int = FILE_TREE_MAX_DEPTH) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    def walk(target: Path, depth: int) -> list[dict[str, Any]]:
        if depth > max_depth:
            return []
        items: list[dict[str, Any]] = []
        count = 0
        for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if count >= FILE_TREE_MAX_ENTRIES_PER_DIR:
                items.append({"path": str(target.resolve()), "name": "... (too many entries)", "type": "file"})
                break
            absolute = str(child.resolve())
            if child.is_dir():
                if child.name in FILE_TREE_IGNORED_DIR_NAMES:
                    continue
                items.append(
                    {
                        "path": absolute,
                        "name": child.name,
                        "type": "folder",
                        "children": walk(child, depth + 1),
                    }
                )
            elif child.suffix in FILE_TREE_ALLOWED_SUFFIXES:
                items.append(
                    {
                        "path": absolute,
                        "name": child.name,
                        "type": "file",
                    }
                )
            count += 1
        return items

    return [
        {
            "path": str(root.resolve()),
            "name": root.name,
            "type": "folder",
            "children": walk(root, 1),
        }
    ]


def read_text_file(relative_path: str | None, workspace: str) -> str:
    if relative_path is None or not str(relative_path).strip():
        return ""
    target = Path(relative_path).expanduser().resolve()
    workspace_root = resolve_workspace_path(workspace)
    if workspace_root != target and workspace_root not in target.parents:
        return ""
    if not target.exists() or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8")


def list_workspace_options(default_workspace: str | Path) -> list[dict[str, str]]:
    seen: set[str] = set()
    options: list[dict[str, str]] = []
    default_workspace_path = Path(default_workspace).expanduser().resolve()

    def add(path: Path, label: str) -> None:
        resolved = str(path.expanduser().resolve())
        if resolved in seen or not Path(resolved).exists() or not Path(resolved).is_dir():
            return
        seen.add(resolved)
        options.append({"value": resolved, "label": label})

    add(default_workspace_path, "当前项目")
    add(default_workspace_path.parent, "当前项目的上级目录")
    home = Path.home()
    add(home, "用户目录")
    add(home / "Desktop", "桌面")
    add(home / "Documents", "文档")

    for drive in ("C:/", "D:/", "E:/", "F:/"):
        add(Path(drive), drive.rstrip("/"))

    return options


def list_child_directories(path: str | Path) -> list[dict[str, str]]:
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    children: list[dict[str, str]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        children.append(
            {
                "value": str(child.resolve()),
                "label": child.name,
            }
        )
    return children


def build_default_open_files(workspace: str) -> list[str]:
    default_file = pick_default_file(workspace)
    if default_file is None:
        return []
    return [Path(default_file).name]


def pick_default_file(workspace: str) -> str | None:
    workspace_root = resolve_workspace_path(workspace)
    preferred_names = ["main.py", "App.tsx", "README.md", "index.tsx", "index.ts", "__init__.py"]
    for name in preferred_names:
        for match in _shallow_glob(workspace_root, name, max_depth=2):
            return str(match.resolve())

    for match in _shallow_glob_all(workspace_root, max_depth=2):
        if match.is_file() and match.suffix in {".py", ".ts", ".tsx", ".md", ".json"}:
            return str(match.resolve())
    return None


def _shallow_glob(root: Path, name: str, max_depth: int) -> list[Path]:
    results: list[Path] = []
    _walk_shallow(root, max_depth, lambda path: results.append(path) if path.name == name else None)
    return results[:5]


def _shallow_glob_all(root: Path, max_depth: int) -> list[Path]:
    results: list[Path] = []
    _walk_shallow(root, max_depth, lambda path: results.append(path))
    return results[:50]


def _walk_shallow(root: Path, max_depth: int, visitor: Any) -> None:
    if max_depth <= 0:
        return
    try:
        for child in root.iterdir():
            if child.name in FILE_TREE_IGNORED_DIR_NAMES:
                continue
            visitor(child)
            if child.is_dir():
                _walk_shallow(child, max_depth - 1, visitor)
    except PermissionError:
        pass


def pick_demo_file(workspace: str) -> str | None:
    return pick_default_file(workspace)


def render_demo_list_output(workspace: str) -> str:
    workspace_root = resolve_workspace_path(workspace)
    rendered = [f"# Path: {workspace_root}"]
    for child in sorted(workspace_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if child.is_dir() and child.name in FILE_TREE_IGNORED_DIR_NAMES:
            continue
        rendered.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(rendered[:25])
