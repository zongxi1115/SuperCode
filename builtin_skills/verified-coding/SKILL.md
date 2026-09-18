---
name: verified-coding
description: Evidence-based coding workflow for bug fixes, refactoring, and feature implementation. Use to locate relevant code, make scoped changes, and verify results before reporting completion.
---

# Verified Coding

Use this workflow for software changes. Scale investigation and verification to the task. Follow the user's scope and the host's tool and approval rules; this skill grants no additional permissions.

## Establish the Task

- Identify the observable outcome and an appropriate acceptance check. Separate user requirements from assumptions.
- Read repository instructions and inspect the current working-tree state before editing. Preserve existing changes, including untracked files.
- For a small change, proceed directly. Use the existing task tools for work with several dependent stages.
- Ask only about missing information that materially changes the implementation and cannot be resolved from the project.

## Find Evidence Efficiently

- Search exact paths, symbols, and error messages first using list_file, glob_file, and grep_file. Read relevant ranges with read_file.
- Inspect callers, configuration, and nearby tests before changing a shared contract. Confirm that an apparent extension point is actually loaded or called.
- Parallelize independent read-only searches. Delegate code exploration only when a distinct investigation justifies the extra model work.
- Treat retrieval results and subagent summaries as leads. Check the source before relying on a claim or modifying a file.
- Retain a compact working record of requirements, evidence paths, changed files, check results, and unresolved issues. Preserve these facts when summarizing context.

## Make Scoped Changes

- Reuse existing conventions and dependencies. Avoid unrelated cleanup, formatting, and configuration changes.
- Re-read the relevant content before applying an edit when another actor or command may have changed the file. Prefer replace_file with a unique old-content match; use line-based edits only against freshly read content.
- Sequence dependent writes. Inspect the resulting diff for unintended changes before continuing.
- If the user explicitly permits only new files, do not modify, rename, delete, or overwrite any pre-existing file, including manifests and lockfiles. Use a confirmed discovery mechanism or a standalone entry point. Explain when the requested behavior cannot become active without changing an existing file.
- Do not use terminal commands, formatters, installers, or generators to bypass a file-edit restriction. Avoid tools whose side effects would violate it.

## Verify the Outcome

- Choose checks from the repository's actual scripts and conventions. Start with the narrowest check that exercises the changed behavior.
- For a bug fix, use an existing reproducer when available and confirm its outcome after the change. Add a regression test only when authorized by the user and host rules.
- Use syntax, type, lint, test, or UI checks where they supply relevant evidence. A successful build alone does not prove the requested behavior works.
- Obtain any approval required by the host before builds, dependency changes, or other restricted actions. Never describe an unrun check as passed.
- Inspect the final working-tree state against the initial state. Distinguish your changes from pre-existing work. Do not revert another actor's changes to make the result look clean.

## Recover from Failure

- Classify a failed check as an implementation problem, an environment problem, or a pre-existing failure using observable evidence.
- Before another repair, state a new hypothesis and choose a check that can distinguish it. Do not repeat unchanged commands or failed edits without new information.
- If two repair attempts produce the same failure without new evidence, stop that loop and report the blocker or pursue a different evidence-based approach.
- Do not automatically repeat actions with external effects, such as publication or remote changes. First establish whether the previous attempt took effect and whether retrying is authorized.
- Keep useful partial work and explain unresolved limitations. Do not expand scope to conceal a failing check.

## Report Evidence

Give a concise final response containing the delivered behavior, affected files, checks actually run and their outcomes, and any remaining limitation. For new plugins or skills, distinguish file discovery from activation and from verified behavior. Never equate a successful tool call, a plausible answer, or the presence of a new file with successful task completion.

