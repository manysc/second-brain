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
  stakeholders: string[];
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
  stakeholders: string[];
};

export type SearchResult = {
  items: KnowledgeItem[];
  // topics owning at least one matched item, each carrying its full item list
  topics: Topic[];
};

export type TopicMergeSuggestion = {
  topicA: Topic;
  topicB: Topic;
  similarity: number;
};

export type ItemTopicSuggestion = {
  item: KnowledgeItem;
  suggestedTopic: Topic;
  similarity: number;
};

export type GraphNode = {
  id: string;
  type: ItemType;
  description: string;
  confidence: Confidence;
  owner: string | null;
  topicId: string | null;
  topicName: string | null;
  meetingId: string;
};

export type GraphEdge = {
  source: string;
  target: string;
  kind: "related" | "topic" | "semantic";
  weight: number;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
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
