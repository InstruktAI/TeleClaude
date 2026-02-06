---
description: 'TypeScript strict typing, discriminated unions, type guards, property checks. No any, no enum, no default exports.'
id: 'software-development/policy/typescript/core'
scope: 'domain'
type: 'policy'
---

# Core — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

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

## Scope

- Applies to all TypeScript code in the repository.
- These rules keep types explicit and refactors safe.

## Rationale

Use strict typing to keep behavior explicit and refactors safe.

## Enforcement

- Implicit `any` and default exports reduce type safety and refactorability.
- If type errors appear, narrow types or refactor until the change is type-safe.

## Exceptions

- None. If a deviation is required, document the rationale and get explicit approval.
