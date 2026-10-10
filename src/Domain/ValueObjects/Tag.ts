// tag limits; keep in sync with backend/app/domain/value_objects/tag.py
export const MAX_TAG_LENGTH = 40;
export const MAX_TAGS = 20;

/** Why a tag cannot be added, or null when it is acceptable. The backend normalizes and enforces the count. */
export function tagProblem(tag: string): string | null {
  if (!tag) return "Tag cannot be empty";
  if (tag.length > MAX_TAG_LENGTH) return `Tag cannot be longer than ${MAX_TAG_LENGTH} characters`;
  return null;
}
