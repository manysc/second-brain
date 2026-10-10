import type { ItemType } from "@/Domain";

// counts distinct meetings; meetings = new + updated + unchanged
export type IngestResult = { meetings: number; new: number; updated: number; unchanged: number };

export type NewItem = {
  type: ItemType;
  description: string;
  owner?: string | null;
  dueDate?: string | null;
};

/** A partial edit: omitted fields are left alone; null clears owner, due date or rationale. */
export type ItemPatch = Partial<NewItem> & { rationale?: string | null };

export type ItemsMove = { itemIds: string[]; topicId: string };

/** What the image store answered: the bytes, or why there are none. */
export type TopicImageContent =
  | { kind: "ok"; body: ReadableStream<Uint8Array> | null; contentType: string | null }
  | { kind: "missing" }
  | { kind: "failed" }
  | { kind: "unreachable" };
