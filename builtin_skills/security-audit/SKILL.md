---
name: security-audit
description: Security review for auth, secrets, injection, XSS, SSRF, dependency risk, permissions, 安全, 漏洞, 密钥, 权限.
---

# Security Audit

Use this skill when reviewing security-sensitive code, authentication, authorization, secrets, dependency changes, file access, network calls, uploads, payments, or user-supplied input.

## Audit Areas

- Authentication and session handling.
- Authorization checks on every protected resource.
- Input validation, output encoding, XSS, SQL injection, command injection, path traversal, and SSRF.
- Secret handling, logs, environment variables, and accidental credential exposure.
- Dependency, build, CI, and GitHub Actions trust boundaries.
- File upload, archive extraction, and generated file paths.

## Process

1. Identify assets, trust boundaries, and attacker-controlled inputs.
2. Trace the input through validation, storage, execution, and output.
3. Check both intended workflows and direct API calls that bypass UI assumptions.
4. Look for missing tests around denied access and malicious input.
5. Recommend minimal fixes with concrete verification steps.

## Output

Separate confirmed vulnerabilities from hardening suggestions. Include exploitability, impact, and the file or route affected.
