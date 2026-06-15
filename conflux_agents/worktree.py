from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


SHARED_DEPENDENCY_DIRS = (
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
)


class ConfluxWorktreeManager:
    """为 Conflux 子智能体创建隔离 worktree，并共享主仓依赖产物目录。"""

    def __init__(self, main_repo_path: Path, session_id: str) -> None:
        self.main_repo_path = Path(main_repo_path).expanduser().resolve()
        self.session_id = session_id.strip()
        if not self.session_id:
            raise ValueError("session_id 不能为空")
        self.worktrees_root = (
            self.main_repo_path
            / ".supercode"
            / "conflux_worktrees"
            / self.session_id
        )

    def create_specialist_worktree(self, specialist_name: str, base_branch: str = "main") -> Path:
        specialist_segment = self._normalize_specialist_name(specialist_name)
        branch_name = self._branch_name(specialist_segment)
        worktree_path = self.worktrees_root / specialist_segment

        print(f"[conflux-worktree] 准备创建子智能体 worktree: {worktree_path}")
        self._ensure_git_repo()
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

        if worktree_path.exists():
            print(f"[conflux-worktree] 发现已有 worktree 目录，先清理后重建: {worktree_path}")
            self.cleanup_specialist_worktree(worktree_path)

        if self._branch_exists(branch_name):
            print(f"[conflux-worktree] 发现已有分支，先删除后重建: {branch_name}")
            self._run_git(["branch", "-D", branch_name])

        print(f"[conflux-worktree] git worktree add -b {branch_name} {worktree_path} {base_branch}")
        self._run_git(["worktree", "add", "-b", branch_name, str(worktree_path), base_branch])

        print(f"[conflux-worktree] 为 worktree 链接主仓依赖产物目录: {worktree_path}")
        self._link_shared_dependency_dirs(worktree_path)
        return worktree_path.resolve()

    def cleanup_specialist_worktree(self, worktree_path: Path) -> None:
        resolved_worktree_path = Path(worktree_path).expanduser().resolve()
        self._ensure_managed_worktree_path(resolved_worktree_path)
        specialist_segment = resolved_worktree_path.name
        branch_name = self._branch_name(specialist_segment)

        print(f"[conflux-worktree] 开始清理子智能体 worktree: {resolved_worktree_path}")
        self._unlink_shared_dependency_dirs(resolved_worktree_path)

        if resolved_worktree_path.exists():
            print(f"[conflux-worktree] git worktree remove --force {resolved_worktree_path}")
            self._run_git(["worktree", "remove", "--force", str(resolved_worktree_path)])

        if self._branch_exists(branch_name):
            print(f"[conflux-worktree] git branch -D {branch_name}")
            self._run_git(["branch", "-D", branch_name])

    def list_active_worktrees(self) -> list[Path]:
        if not self.worktrees_root.exists():
            return []
        return sorted(
            path.resolve()
            for path in self.worktrees_root.iterdir()
            if path.is_dir()
        )

    def cleanup_all(self) -> None:
        print(f"[conflux-worktree] 清理当前 Conflux session 的全部 worktree: {self.worktrees_root}")
        errors: list[str] = []
        for worktree_path in self.list_active_worktrees():
            try:
                self.cleanup_specialist_worktree(worktree_path)
            except Exception as exc:
                errors.append(f"{worktree_path}: {exc}")
        if errors:
            raise RuntimeError("清理 Conflux worktree 时出现错误：\n" + "\n".join(errors))

    def _ensure_git_repo(self) -> None:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0 or result.stdout.strip().lower() != "true":
            detail = (result.stderr or result.stdout or "当前目录不是 git worktree").strip()
            raise RuntimeError(f"Conflux worktree 需要一个已有 git 仓库：{detail}")

    def _run_git(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.main_repo_path,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 git 命令，无法管理 Conflux worktree") from exc

        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "git 命令执行失败").strip()
            raise RuntimeError(f"git {' '.join(args)} 失败：{detail}")
        return result

    def _branch_exists(self, branch_name: str) -> bool:
        result = self._run_git(
            ["rev-parse", "--verify", f"refs/heads/{branch_name}"],
            check=False,
        )
        return result.returncode == 0

    def _branch_name(self, specialist_name: str) -> str:
        return f"conflux/{self.session_id}/{specialist_name}"

    def _normalize_specialist_name(self, specialist_name: str) -> str:
        normalized = specialist_name.strip()
        if not normalized:
            raise ValueError("specialist_name 不能为空")
        if normalized in {".", ".."}:
            raise ValueError("specialist_name 不能是 . 或 ..")
        if any(separator and separator in normalized for separator in (os.sep, os.altsep)):
            raise ValueError("specialist_name 不能包含路径分隔符")
        return normalized

    def _ensure_managed_worktree_path(self, worktree_path: Path) -> None:
        root = self.worktrees_root.resolve()
        try:
            worktree_path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"拒绝清理非 Conflux 管理目录：{worktree_path}") from exc

    def _link_shared_dependency_dirs(self, worktree_path: Path) -> None:
        for dirname in SHARED_DEPENDENCY_DIRS:
            source_path = self.main_repo_path / dirname
            link_path = worktree_path / dirname
            if not source_path.exists() or not source_path.is_dir():
                continue
            if link_path.exists() or link_path.is_symlink():
                if self._is_dependency_link(link_path):
                    print(f"[conflux-worktree] 已存在依赖链接，跳过: {link_path}")
                    continue
                print(f"[conflux-worktree] 目标已存在且不是链接，跳过共享: {link_path}")
                continue
            print(f"[conflux-worktree] 链接共享依赖目录: {link_path} -> {source_path}")
            self._create_directory_link(source_path, link_path)

    def _create_directory_link(self, source_path: Path, link_path: Path) -> None:
        if platform.system().lower() != "windows":
            os.symlink(source_path, link_path, target_is_directory=True)
            return

        try:
            os.symlink(source_path, link_path, target_is_directory=True)
            return
        except OSError as exc:
            print(f"[conflux-worktree] Windows 目录符号链接失败，退化为 junction: {exc}")

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(source_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "mklink /J 失败").strip()
            raise RuntimeError(f"创建 Windows junction 失败：{detail}")

    def _unlink_shared_dependency_dirs(self, worktree_path: Path) -> None:
        for dirname in SHARED_DEPENDENCY_DIRS:
            source_path = self.main_repo_path / dirname
            link_path = worktree_path / dirname
            if not link_path.exists() and not link_path.is_symlink():
                continue
            if link_path.is_symlink():
                print(f"[conflux-worktree] 解除依赖符号链接: {link_path}")
                os.unlink(link_path)
                continue
            if self._is_junction(link_path):
                print(f"[conflux-worktree] 解除依赖 junction: {link_path}")
                os.rmdir(link_path)
                continue

            if not source_path.exists():
                print(f"[conflux-worktree] {dirname} 不是主仓共享目录，交给 git worktree remove 清理: {link_path}")
                continue

            warning = (
                f"[conflux-worktree] 警告：{link_path} 不是符号链接或 junction，"
                "停止清理，避免误删真实依赖目录。"
            )
            print(warning)
            raise RuntimeError(warning)

    def _is_dependency_link(self, path: Path) -> bool:
        return path.is_symlink() or self._is_junction(path)

    def _is_junction(self, path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction):
            return bool(is_junction())
        return False
