import type { Confidence } from "../ValueObjects/Confidence";
import type { Evidence } from "../ValueObjects/Evidence";
import type { ItemType } from "../ValueObjects/ItemType";
import type { KnowledgeItem } from "./KnowledgeItem";
import type { Topic } from "./Topic";

/** Something the extractor was unsure about; it stays pending until a person accepts or rejects it. */
export type ReviewCandidate = {
  id: string;
  type: string;
  description: string;
  reason: string;
  confidence: Confidence;
  evidence: Evidence;
  status: "PENDING" | "ACCEPTED" | "REJECTED";
  suggestedTopicId?: string | null;
};

export type ReviewDecision = "ACCEPTED" | "REJECTED";

export type Meeting = {
  id: string;
  title: string;
  date: string;
  sourceUrl: string;
  items: KnowledgeItem[];
  reviewCandidates: ReviewCandidate[];
  topics: Topic[];
};

export function countItemsOfType(meeting: Pick<Meeting, "items">, type: ItemType): number {
  return meeting.items.filter((item) => item.type === type).length;
}

export type SearchResult = {
  items: KnowledgeItem[];
  // topics owning at least one matched item, each carrying its full item list
  topics: Topic[];
};
