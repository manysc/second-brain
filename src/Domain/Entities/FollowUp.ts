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

function nameWords(name: string): string[] {
  return name.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? [];
}

/** "Akshay / QA (reported)" -> Akshay, QA; "Akshay and Nando" -> Akshay, Nando. */
function peopleIn(stakeholder: string): string[] {
  return stakeholder
    .replace(/\([^)]*\)/g, " ")
    .split(/[/,;&+]|\band\b/i)
    .map((name) => name.trim())
    .filter((name) => nameWords(name).length > 0);
}

/**
 * Every person named on the topics' items, once each whatever its capitalization, in alphabetical order. Combined
 * entries are split into their people, and a name whose leading words are another listed name ("Akshay Chowdu"
 * next to "Akshay") is left out: the backend matches a name by its whole words, so the shorter one covers it.
 */
export function stakeholderOptions(topics: readonly Pick<Topic, "stakeholders">[]): string[] {
  const nameByKey = new Map<string, string>();
  for (const topic of topics) {
    for (const stakeholder of topic.stakeholders) {
      for (const name of peopleIn(stakeholder)) {
        const key = nameWords(name).join(" ");
        if (!nameByKey.has(key)) nameByKey.set(key, name);
      }
    }
  }
  const keys = [...nameByKey.keys()];
  return keys
    .filter((key) => !keys.some((other) => other !== key && key.startsWith(`${other} `)))
    .map((key) => nameByKey.get(key)!)
    .sort((a, b) => a.localeCompare(b));
}
