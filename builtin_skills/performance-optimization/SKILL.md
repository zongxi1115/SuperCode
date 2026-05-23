---
name: performance-optimization
description: Performance profiling and optimization for slow code, rendering, database, bundle, latency, memory, 性能, 慢, 卡顿, 优化.
---

# Performance Optimization

Use this skill when the user reports slowness, lag, high latency, memory growth, heavy bundles, expensive queries, or rendering jank.

## Workflow

1. Define the performance budget or user-visible symptom.
2. Measure a baseline with the closest realistic workload.
3. Identify the bottleneck before changing code.
4. Make one optimization at a time.
5. Re-measure with the same scenario.
6. Keep the optimization only if it improves the target without harming correctness or maintainability.

## Common Checks

- Frontend: unnecessary re-renders, layout thrash, large images, heavy client bundles, blocking work on the main thread.
- Backend: N+1 queries, missing indexes, synchronous I/O, unbounded scans, repeated expensive computation.
- Tooling: oversized dependencies, duplicate packages, slow test setup, uncached transforms.

## Guardrails

- Do not optimize based only on intuition.
- Prefer algorithmic and data-flow fixes over clever micro-optimizations.
- Document the before and after numbers when possible.
