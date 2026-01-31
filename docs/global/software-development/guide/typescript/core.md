---
description: TypeScript strict typing, discriminated unions, type guards, property
  checks. No any, no enum, no default exports.
id: software-development/guide/typescript/core
scope: domain
type: guide
---

# Core — Guide

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Goal

- **Strict mode always** - Enable all strict compiler options
- **No `any`** - Use `unknown` when type is truly unknown
- **Explicit return types** - Every function has declared return type
- **Use type guards** - Narrow types with proper guards (`typeof`, `instanceof`, `in`)
- **Strict null checks** - Handle `null` and `undefined` explicitly

- **Interfaces for shapes** - Use `interface` for object shapes
- **Types for unions/aliases** - Use `type` for unions, intersections, mapped types
- **Discriminated unions for state** - Tagged unions with literal discriminant
- **Const assertions for literals** - Use `as const` for readonly literal types

```typescript
// Discriminated union example
type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: string }
  | { status: 'error'; error: Error };

// Const assertion example
const config = {
  timeout: 5000,
  retries: 3,
} as const;
```

- ❌ **enum** - Use const objects or string literal unions instead
- ❌ **any** - Use `unknown` or proper types
- ❌ **Default exports** - Use named exports for better refactoring
- ❌ **Class-based namespacing** - Use modules/objects instead
- ❌ **Non-null assertions (!.)** - Handle null explicitly

- **Use `'prop' in obj`** for type guards and narrowing (TypeScript needs this for type inference)
- **Use `obj.prop`** for simple truthy checks where type narrowing isn't needed

```typescript
// Type guard - TypeScript narrows the type
if ('data' in response) {
  console.log(response.data); // TypeScript knows data exists
}

// Truthy check - no type narrowing needed
if (user.name) {
  console.log(user.name); // Simple existence check
}
```

- Use `Promise.all()` for concurrent operations
- Use `Promise.allSettled()` when failures shouldn't block
- Properly type async function returns: `Promise<T>`

- Follow project's tsconfig.json strictly
- Match existing import patterns (absolute vs relative)
- Conform to project's type organization

## Context

- Applies to all TypeScript code in the repository.
- These rules keep types explicit and refactors safe.

## Approach

1. Type every public function and exported value.
2. Use type guards to narrow before access.
3. Prefer immutable data and pure functions where feasible.
4. Use Promise utilities intentionally (`all` vs `allSettled`).
5. Follow project tsconfig and import conventions.

## Pitfalls

- Implicit `any` and default exports reduce type safety and refactorability.
- If type errors appear, narrow types or refactor until the change is type-safe.
