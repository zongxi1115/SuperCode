---
name: systematic-debugging
description: Systematic bug diagnosis for debug, broken, failing, error, regression, flaky, performance, 复现, 调试, 报错, 失败, 回归.
---

# Systematic Debugging

Use this skill when the user reports a bug, failed behavior, regression, flaky issue, slow path, crash, or unclear error.

## Workflow

1. Build the smallest reliable feedback loop first.
   Prefer an existing test, focused regression test, CLI repro, HTTP request, browser script, fixture replay, or minimal harness. If the bug is flaky, raise the reproduction rate with repeated runs, controlled timing, or stress inputs.

2. Confirm the symptom.
   Verify the loop reproduces the user's actual problem, capture the observed output, and state the expected behavior.

3. List ranked hypotheses.
   Generate 3 to 5 falsifiable causes before editing. Each hypothesis should predict what evidence would confirm or reject it.

4. Instrument narrowly.
   Probe one hypothesis at a time. Add temporary logs only at decision boundaries and tag them with a unique prefix such as `[DEBUG-1234]` so cleanup is easy.

5. Fix the cause, not the symptom.
   Keep the patch minimal. Add or update a regression test at the highest public interface that exercises the real failure path.

6. Verify and clean up.
   Re-run the original repro, the new regression test, and any relevant existing checks. Remove temporary instrumentation and throwaway harnesses before finishing.

## Guardrails

- Do not guess-fix before reproducing unless reproduction is impossible.
- If no good test seam exists, document that architecture gap.
- For performance bugs, measure a baseline before changing code.
