import type { KnowledgeItem, ReviewCandidate, SuggestionRow, Topic, TopicProposal } from "@/lib/domain";

export function item(overrides: Partial<KnowledgeItem> = {}): KnowledgeItem {
  return {
    id: "m1:item-1",
    type: "ACTION",
    description: "Ship the beta",
    theme: null,
    topicId: "t1",
    topicName: "Launch",
    status: "Open",
    confidence: "HIGH",
    owner: "Ana",
    stakeholders: ["Ana", "Ben"],
    dueDate: "2026-11-01",
    dueDateSourceText: null,
    rationale: null,
    resolution: null,
    evidence: { speaker: "Ana", timestamp: "00:01:02", quote: "Let's ship", context: "Planning" },
    relatedIds: [],
    meetingId: "m1",
    effectivePriority: null,
    manualOverride: null,
    notes: [],
    tags: [],
    ...overrides,
  };
}

export function topic(overrides: Partial<Topic> = {}): Topic {
  return {
    id: "t1",
    name: "Launch",
    status: "Open",
    items: [],
    stakeholders: [],
    priority: null,
    notes: [],
    tags: [],
    images: [],
    ...overrides,
  };
}

export function candidate(overrides: Partial<ReviewCandidate> = {}): ReviewCandidate {
  return {
    id: "c1",
    type: "DECISION",
    description: "Adopt pgvector",
    reason: "Explicit agreement",
    confidence: "MEDIUM",
    evidence: { speaker: null, timestamp: null, quote: "We agree", context: "Infra sync" },
    status: "PENDING",
    suggestedTopicId: null,
    ...overrides,
  };
}

export function proposal(overrides: Partial<TopicProposal> = {}): TopicProposal {
  return { name: "Infra", items: [item({ id: "a" }), item({ id: "b" })], suggestedExistingTopicId: null, ...overrides };
}

export function suggestion(
  id: string,
  confidence: SuggestionRow["confidence"],
  score: number,
  topics: [string, string][],
): SuggestionRow {
  return {
    id,
    description: `Item ${id}`,
    type: "IDEA",
    score,
    confidence,
    candidates: topics.map(([topicId, topicName], index) => ({
      topicId,
      topicName,
      itemCount: 4,
      score: score - index * 0.1,
      centroidSimilarity: score,
    })),
  };
}
