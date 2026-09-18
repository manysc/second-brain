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

export type TopicPriorityLevel = "CRITICAL" | "MAJOR" | "MINOR";
export type PriorityConfidence = "HIGH" | "MEDIUM" | "LOW";

// higher = more urgent; used to sort/compare priorities consistently across pages
export const PRIORITY_RANK: Record<TopicPriorityLevel, number> = { MINOR: 0, MAJOR: 1, CRITICAL: 2 };

export type TopicPrioritySignal = {
  type: string;
  rawValue: number | string | boolean | null;
  normalizedScore: number;
  weightedScore: number;
  maxScore: number;
  explanation: string;
  sourceKnowledgeItemIds: string[];
};

export type HardEscalation = {
  ruleId: string;
  reason: string;
  sourceKnowledgeItemIds: string[];
};

export type SemanticContribution = {
  provider: string;
  model: string;
  scores: { critical: number; major: number; minor: number };
  contribution: number;
  disagreement: boolean;
};

export type ManualPriorityOverride = {
  priority: TopicPriorityLevel;
  reason: string | null;
  overriddenAt: string;
};

export type TopicPriorityInfo = {
  calculatedPriority: TopicPriorityLevel;
  calculatedScore: number;
  effectivePriority: TopicPriorityLevel;
  confidence: PriorityConfidence;
  signals: TopicPrioritySignal[];
  hardEscalations: HardEscalation[];
  explanation: string;
  calculatedAt: string;
  algorithmVersion: string;
  semanticContribution: SemanticContribution | null;
  manualOverride: ManualPriorityOverride | null;
};

export type TopicPriorityHistoryEntry = {
  id: string;
  topicId: string;
  previousPriority: TopicPriorityLevel | null;
  newPriority: TopicPriorityLevel;
  previousScore: number | null;
  newScore: number;
  changedAt: string;
  algorithmVersion: string;
  primaryDrivers: string[];
  trigger: string;
  sourceKnowledgeItemIds: string[];
};

export type Topic = {
  id: string;
  name: string;
  items: KnowledgeItem[];
  stakeholders: string[];
  priority: TopicPriorityInfo | null;
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
  priority: TopicPriorityLevel | null;
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
