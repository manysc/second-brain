export type ItemType = "IDEA" | "DECISION" | "ACTION" | "QUESTION";

export const ITEM_TYPES: readonly ItemType[] = ["IDEA", "QUESTION", "DECISION", "ACTION"];

export function isItemType(value: unknown): value is ItemType {
  return typeof value === "string" && (ITEM_TYPES as readonly string[]).includes(value);
}
