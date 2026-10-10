export type TopicPriorityLevel = "CRITICAL" | "MAJOR" | "MINOR";
export type PriorityConfidence = "HIGH" | "MEDIUM" | "LOW";

export const PRIORITY_LEVELS: readonly TopicPriorityLevel[] = ["CRITICAL", "MAJOR", "MINOR"];

// higher = more urgent; used to sort/compare priorities consistently across pages
export const PRIORITY_RANK: Record<TopicPriorityLevel, number> = { MINOR: 0, MAJOR: 1, CRITICAL: 2 };

export function isPriorityLevel(value: unknown): value is TopicPriorityLevel {
  return typeof value === "string" && (PRIORITY_LEVELS as readonly string[]).includes(value);
}

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

/** A human decision that wins over the calculated priority and is never touched by recalculation. */
export type ManualPriorityOverride = {
  priority: TopicPriorityLevel;
  reason: string | null;
  overriddenAt: string;
};

// minimal shape shared by Topic and Item priority info, so one badge works for both
export type EffectivePriorityInfo = {
  effectivePriority: TopicPriorityLevel;
  manualOverride: ManualPriorityOverride | null;
  calculatedScore?: number;
  confidence?: PriorityConfidence;
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
