import type { Confidence } from "../ValueObjects/Confidence";
import type { ItemType } from "../ValueObjects/ItemType";
import type { KnowledgeItem } from "./KnowledgeItem";
import type { Topic } from "./Topic";

// Suggestions are advisory: nothing here moves an item or merges a topic without a human decision.

export type TopicMergeSuggestion = {
  topicA: Topic;
  topicB: Topic;
  similarity: number;
};

/** A new topic name the extractor proposed for a group of items; nothing is created until a human accepts it. */
export type TopicProposal = {
  name: string;
  items: KnowledgeItem[];
  suggestedExistingTopicId: string | null;
};

export type TopicCandidate = {
  topicId: string;
  topicName: string;
  itemCount: number;
  score: number;
  centroidSimilarity: number;
};

export type ItemTopicSuggestion = {
  item: KnowledgeItem;
  // best first, up to 3
  candidates: TopicCandidate[];
  score: number;
  confidence: Confidence;
};

// What the suggestions panel needs of an ItemTopicSuggestion - the full item (evidence, notes, ...)
// would otherwise be serialized to the browser once per row.
export type SuggestionRow = {
  id: string;
  description: string;
  type: ItemType;
  candidates: TopicCandidate[];
  score: number;
  confidence: Confidence;
};

export function toSuggestionRow({ item, candidates, score, confidence }: ItemTopicSuggestion): SuggestionRow {
  return { id: item.id, description: item.description, type: item.type, candidates, score, confidence };
}

export type SuggestionGroup = {
  topicId: string;
  topicName: string;
  itemCount: number;
  suggestions: SuggestionRow[];
  highCount: number;
  meanScore: number;
};

/** Groups items under their best-ranked topic; topics with the most confident matches come first. */
export function groupByTopSuggestion(suggestions: readonly SuggestionRow[]): SuggestionGroup[] {
  const groups = new Map<string, SuggestionGroup>();
  for (const suggestion of suggestions) {
    const top = suggestion.candidates[0];
    if (!top) continue;
    const group = groups.get(top.topicId) ?? {
      topicId: top.topicId,
      topicName: top.topicName,
      itemCount: top.itemCount,
      suggestions: [],
      highCount: 0,
      meanScore: 0,
    };
    group.suggestions.push(suggestion);
    if (suggestion.confidence === "HIGH") group.highCount += 1;
    groups.set(top.topicId, group);
  }
  for (const group of groups.values()) {
    group.suggestions.sort((a, b) => b.score - a.score);
    group.meanScore = group.suggestions.reduce((sum, s) => sum + s.score, 0) / group.suggestions.length;
  }
  return [...groups.values()].sort((a, b) => b.highCount - a.highCount || b.meanScore - a.meanScore);
}
