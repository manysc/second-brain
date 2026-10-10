import type { OpenClosed } from "../ValueObjects/OpenClosed";
import { PRIORITY_RANK, type TopicPriorityInfo } from "../ValueObjects/Priority";
import type { KnowledgeItem, Note } from "./KnowledgeItem";

export type TopicImage = {
  id: string;
  filename: string;
  contentType: string;
  size: number;
  createdAt: string;
};

export type Topic = {
  id: string;
  name: string;
  status: OpenClosed;
  items: KnowledgeItem[];
  stakeholders: string[];
  priority: TopicPriorityInfo | null;
  notes: Note[];
  tags: string[];
  images: TopicImage[];
};

export type RelatedTopic = {
  id: string;
  name: string;
  status: string;
  similarity: number;
  itemCount: number;
};

// catch-all topic for items nobody has filed yet; never offered as a destination or a suggestion
export const UNCATEGORIZED_TOPIC = "Uncategorized";

export function isUncategorized(topic: Pick<Topic, "name">): boolean {
  return topic.name === UNCATEGORIZED_TOPIC;
}

/** A topic can only be deleted once every item has been reassigned. */
export function canDeleteTopic(topic: Pick<Topic, "items">): boolean {
  return topic.items.length === 0;
}

/** Highest effective priority first, then the higher score; topics without a priority go last. */
export function byPriorityDesc(a: Pick<Topic, "priority">, b: Pick<Topic, "priority">): number {
  const rankA = a.priority ? PRIORITY_RANK[a.priority.effectivePriority] : -1;
  const rankB = b.priority ? PRIORITY_RANK[b.priority.effectivePriority] : -1;
  if (rankA !== rankB) return rankB - rankA;
  return (b.priority?.calculatedScore ?? 0) - (a.priority?.calculatedScore ?? 0);
}
