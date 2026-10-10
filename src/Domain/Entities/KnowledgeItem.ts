import type { Confidence } from "../ValueObjects/Confidence";
import type { Evidence } from "../ValueObjects/Evidence";
import type { ItemType } from "../ValueObjects/ItemType";
import type { OpenClosed } from "../ValueObjects/OpenClosed";
import type { ManualPriorityOverride, TopicPriorityLevel } from "../ValueObjects/Priority";

export type Note = {
  id: string;
  body: string;
  createdAt: string;
};

export type KnowledgeItem = {
  id: string;
  type: ItemType;
  description: string;
  theme: string | null;
  topicId?: string | null;
  topicName?: string | null;
  status: OpenClosed;
  confidence: Confidence;
  owner: string | null;
  stakeholders: string[];
  dueDate: string | null;
  dueDateSourceText: string | null;
  rationale: string | null;
  resolution: string | null;
  evidence: Evidence;
  relatedIds: string[];
  meetingId: string;
  // items have no automatic scoring of their own - the override wins, else inherited from the topic
  effectivePriority: TopicPriorityLevel | null;
  manualOverride: ManualPriorityOverride | null;
  notes: Note[];
  tags: string[];
};

// Items added by hand live on a synthetic meeting (see backend MANUAL_MEETING_ID).
export const MANUAL_MEETING_ID = "manual";

/** Only manually added items can change type or be deleted; extracted ones would be re-created by the next ingest. */
export function isManualItem(item: Pick<KnowledgeItem, "meetingId">): boolean {
  return item.meetingId === MANUAL_MEETING_ID;
}

/** Stakeholders beyond the owner, who is shown separately. */
export function otherStakeholders(item: Pick<KnowledgeItem, "owner" | "stakeholders">): string[] {
  return item.stakeholders.filter((name) => name !== item.owner);
}

/** Items only carry a meetingId, so recency comes from the meeting's date; items of unknown meetings go last. */
export function sortByMeetingDateDesc<T extends Pick<KnowledgeItem, "meetingId">>(
  items: readonly T[],
  meetingDateById: ReadonlyMap<string, string>,
): T[] {
  return [...items].sort((a, b) => {
    const dateA = meetingDateById.get(a.meetingId);
    const dateB = meetingDateById.get(b.meetingId);
    if (!dateA && !dateB) return 0;
    if (!dateA) return 1;
    if (!dateB) return -1;
    return dateB.localeCompare(dateA);
  });
}
