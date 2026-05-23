---
name: react-next-best-practices
description: React and Next.js best practices for hooks, rendering, state, data fetching, forms, routing, Vite, React, Next, hooks, 组件.
---

# React And Next.js Best Practices

Use this skill when working on React, Next.js, Vite React, hooks, component state, data fetching, routing, forms, or rendering performance.

## Component Design

- Keep state as local as possible, but lift it when multiple components need the same source of truth.
- Derive values during render instead of mirroring props into state.
- Use effects for synchronization with external systems, not for ordinary data derivation.
- Keep component props small, explicit, and named around the domain.
- Prefer composition over boolean prop explosions.

## Rendering And Data

- Avoid unnecessary memoization. Measure or identify a real render problem before adding `memo`, `useMemo`, or `useCallback`.
- Keep list keys stable and domain-based.
- Handle loading, empty, error, and stale states deliberately.
- In Next.js, respect server/client boundaries and keep client components as small as practical.

## Forms And Accessibility

- Use semantic controls, labels, keyboard support, and focus states.
- Validate close to the user interaction and surface actionable errors.
- Do not break browser defaults unless replacing them with a complete accessible behavior.
