import type { KnowledgeItem } from "./KnowledgeItem";
import type { Topic } from "./Topic";

export type FollowUpRelatedItem = {
  item: KnowledgeItem;
  topicId: string;
  topicName: string;
  reason: string;
};

export type FollowUpTopic = {
  topic: Topic;
  followUpItems: KnowledgeItem[];
  escalatedRecently: boolean;
  escalationDrivers: string[];
  relatedFromOtherTopics: FollowUpRelatedItem[];
};

export type FollowUpResponse = {
  topics: FollowUpTopic[];
  generatedAt: string;
  /** items the age cut-off left out, inside the filters that were asked for */
  hiddenStaleCount: number;
  /** the cut-off that was applied; null when it was off */
  maxAgeDays: number | null;
  /** topics with something to raise before the limit cut the list */
  totalTopics: number;
};

// the backend's defaults (GET /api/follow-up `limit`, and FOLLOW_UP_MAX_AGE_DAYS in domain/policies.py)
export const DEFAULT_FOLLOW_UP_TOPICS = 5;
export const FOLLOW_UP_MAX_AGE_DAYS = 30;

/** What narrows a follow-up digest. Every field is optional; an empty list does not restrict. */
export type FollowUpQuery = {
  limit?: number;
  dueSoonDays?: number;
  /** items with no activity in this many days are left out; 0 turns the cut-off off */
  maxAgeDays?: number;
  stakeholders?: readonly string[];
  meetingIds?: readonly string[];
  topicIds?: readonly string[];
};

/** Every name on the topics' items, once each whatever its capitalization, in alphabetical order. */
export function stakeholderOptions(topics: readonly Pick<Topic, "stakeholders">[]): string[] {
  const nameByKey = new Map<string, string>();
  for (const topic of topics) {
    for (const stakeholder of topic.stakeholders) {
      const name = stakeholder.trim();
      const key = name.toLowerCase();
      if (name && !nameByKey.has(key)) nameByKey.set(key, name);
    }
  }
  return [...nameByKey.values()].sort((a, b) => a.localeCompare(b));
}
