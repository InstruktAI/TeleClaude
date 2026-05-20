export const WORK_ITEM_SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export interface WorkItemSlugValidationResult {
  ok: boolean;
  slug: string;
  reason: 'invalid_slug' | null;
}

export function validateWorkItemSlug(slug: string): WorkItemSlugValidationResult {
  const normalizedSlug = slug.trim();
  const isValid = WORK_ITEM_SLUG_PATTERN.test(normalizedSlug);

  return {
    ok: isValid,
    slug: normalizedSlug,
    reason: isValid ? null : 'invalid_slug',
  };
}
