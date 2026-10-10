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
};
