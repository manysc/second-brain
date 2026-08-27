export type ItemType = "IDEA" | "DECISION" | "ACTION" | "QUESTION";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export type Evidence = {
  speaker: string | null;
  timestamp: string | null;
  quote: string;
  context: string | null;
};

export type KnowledgeItem = {
  id: string;
  type: ItemType;
  description: string;
  theme: string | null;
  status: string;
  confidence: Confidence;
  owner: string | null;
  dueDate: string | null;
  dueDateSourceText: string | null;
  rationale: string | null;
  resolution: string | null;
  evidence: Evidence;
  relatedIds: string[];
  meetingId: string;
};

export type ReviewCandidate = {
  id: string;
  type: string;
  description: string;
  reason: string;
  confidence: Confidence;
  evidence: Evidence;
  status: "PENDING" | "ACCEPTED" | "REJECTED";
};

export type Topic = {
  id: string;
  name: string;
  items: KnowledgeItem[];
};

export type Meeting = {
  id: string;
  title: string;
  date: string;
  sourceUrl: string;
  items: KnowledgeItem[];
  reviewCandidates: ReviewCandidate[];
  topics: Topic[];
};
