---
name: webapp-testing
description: Browser and Playwright validation for local web apps, UI flows, console errors, screenshots, e2e, 浏览器测试, 截图, 端到端.
---

# Webapp Testing

Use this skill when the user asks to test a web UI, verify a local app, inspect screenshots, reproduce a browser bug, or validate an end-to-end flow.

## Workflow

1. Find the app entry point and preferred dev command.
2. Reuse an already running dev server when available. If a server must be started, use the repo's package manager and avoid production builds unless the user has allowed them.
3. Open the target page in a browser automation tool.
4. Check console errors, failed network requests, visible layout, and the specific user flow.
5. Exercise the interaction, not just page load.
6. Capture screenshots for visual issues and test both desktop and mobile widths for responsive changes.

## Assertions

- Verify expected text, controls, disabled states, navigation, and persistence.
- Check that dynamic content does not overlap or resize surrounding layout unexpectedly.
- For forms, test validation, submission, loading, success, and failure states.

## Reporting

State the exact URL, viewport, action sequence, and observed failure or success.
