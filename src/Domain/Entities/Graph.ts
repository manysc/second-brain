import type { Confidence } from "../ValueObjects/Confidence";
import type { ItemType } from "../ValueObjects/ItemType";
import type { TopicPriorityLevel } from "../ValueObjects/Priority";

export type GraphNode = {
  id: string;
  type: ItemType;
  description: string;
  confidence: Confidence;
  owner: string | null;
  topicId: string | null;
  topicName: string | null;
  meetingId: string;
  priority: TopicPriorityLevel | null;
};

// "related" is evidence-grounded, "topic" structural, "semantic" a possible link (never an assertion)
export type GraphEdge = {
  source: string;
  target: string;
  kind: "related" | "topic" | "semantic";
  weight: number;
};

export type GraphTopic = {
  id: string;
  name: string;
  itemCount: number;
};

// directed: `target` is among the topics most related to `source` (same data as RelatedTopic)
export type TopicLink = {
  source: string;
  target: string;
  similarity: number;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  topics: GraphTopic[];
  topicLinks: TopicLink[];
};
