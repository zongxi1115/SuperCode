---
name: test-driven-development
description: TDD red-green-refactor workflow for tests, integration tests, specs, behavior, 红绿重构, 测试驱动, 先写测试.
---

# Test-Driven Development

Use this skill when the user asks for TDD, test-first work, regression tests, integration tests, or a careful behavior-driven implementation.

## Workflow

1. Identify the public behavior.
   Name the user-visible capability or contract being changed. Prefer tests through public APIs, routes, UI flows, CLI commands, or module exports rather than private helpers.

2. Write one failing test.
   Test one behavior only. Avoid writing a batch of speculative tests before implementation teaches you the shape of the solution.

3. Make it pass with the smallest useful change.
   Implement only what the current test requires. Keep the feedback loop fast and focused.

4. Repeat vertically.
   Add the next test only after the previous one passes. Let each new test respond to what was learned from the last cycle.

5. Refactor while green.
   Improve names, structure, duplication, and boundaries only after tests pass. Re-run the focused tests after each meaningful refactor.

## Test Quality

- Tests should describe behavior, not implementation details.
- Prefer realistic collaborators over mocking internals.
- Keep fixtures small and readable.
- Cover critical paths, edge cases with real risk, and regressions that already happened.
