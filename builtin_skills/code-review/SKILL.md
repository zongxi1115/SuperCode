---
name: code-review
description: Review code, diffs, PRs, changes, bugs, regressions, tests, risk, 代码审查, 评审, 找问题, 看风险.
---

# Code Review

Use this skill when the user asks for a review, PR check, diff analysis, risk scan, or second opinion on a change.

## Review Stance

Lead with findings. Prioritize correctness bugs, data loss, security issues, regressions, edge cases, missing tests, and maintainability risks that can cause real failures.

## Process

1. Understand the intended behavior and changed files.
2. Inspect the diff and nearby call sites, not just the edited lines.
3. Trace data flow through boundaries such as API inputs, persistence, async work, UI state, and error handling.
4. Check whether tests cover the changed behavior and failure modes.
5. Report issues in severity order with file and line references.

## Output Shape

- Findings first.
- Include severity when useful: P0 data loss/security, P1 likely breakage, P2 edge case or missing coverage, P3 polish.
- Keep summaries brief and secondary.
- If no issues are found, say so clearly and mention remaining residual risk.
