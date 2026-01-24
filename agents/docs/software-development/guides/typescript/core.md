---
description:
  TypeScript strict typing, discriminated unions, type guards, property
  checks. No any, no enum, no default exports.
id: software-development/guides/typescript/core
scope: domain
type: guide
---

# TypeScript Core Patterns

## Required reads

- @software-development/standards/code-quality

## Requirements

@~/.teleclaude/docs/software-development/standards/code-quality.md

## Typing

- **Strict mode always** - Enable all strict compiler options
- **No `any`** - Use `unknown` when type is truly unknown
- **Explicit return types** - Every function has declared return type
- **Use type guards** - Narrow types with proper guards (`typeof`, `instanceof`, `in`)
- **Strict null checks** - Handle `null` and `undefined` explicitly

## Type Declarations

- **Interfaces for shapes** - Use `interface` for object shapes
- **Types for unions/aliases** - Use `type` for unions, intersections, mapped types
- **Discriminated unions for state** - Tagged unions with literal discriminant
- **Const assertions for literals** - Use `as const` for readonly literal types

```typescript
// Discriminated union example
type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: string }
  | { status: "error"; error: Error };

// Const assertion example
const config = {
  timeout: 5000,
  retries: 3,
} as const;
```

## Patterns to Avoid

- ❌ **enum** - Use const objects or string literal unions instead
- ❌ **any** - Use `unknown` or proper types
- ❌ **Default exports** - Use named exports for better refactoring
- ❌ **Class-based namespacing** - Use modules/objects instead
- ❌ **Non-null assertions (!.)** - Handle null explicitly

## Property Checks

- **Use `'prop' in obj`** for type guards and narrowing (TypeScript needs this for type inference)
- **Use `obj.prop`** for simple truthy checks where type narrowing isn't needed

```typescript
// Type guard - TypeScript narrows the type
if ("data" in response) {
  console.log(response.data); // TypeScript knows data exists
}

// Truthy check - no type narrowing needed
if (user.name) {
  console.log(user.name); // Simple existence check
}
```

## Async Patterns

- Use `Promise.all()` for concurrent operations
- Use `Promise.allSettled()` when failures shouldn't block
- Properly type async function returns: `Promise<T>`

## Project Conformance

- Follow project's tsconfig.json strictly
- Match existing import patterns (absolute vs relative)
- Conform to project's type organization
