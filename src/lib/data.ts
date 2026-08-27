import { readFileSync } from "node:fs";
import path from "node:path";
import { z } from "zod";
import type { Confidence, Evidence, ItemType, KnowledgeItem, Meeting, ReviewCandidate, Topic } from "./domain";

const evidenceSchema = z.object({
  speaker: z.string().nullable().optional(),
  timestamp: z.string().nullable().optional(),
  quote: z.string().default(""),
  context: z.string().nullable().optional(),
});
const candidateSchema = z.object({
  candidate_id: z.string(), type: z.string(), description: z.string(), theme: z.string().nullable().optional(),
  status: z.string().default("Open"), owner: z.string().nullable().optional(), proposed_by: z.string().nullable().optional(),
  decision_owner: z.string().nullable().optional(), due_date: z.string().nullable().optional(), due_date_source_text: z.string().nullable().optional(),
  priority: z.string().nullable().optional(), confidence: z.string().default("Medium"), rationale: z.string().nullable().optional(), resolution: z.string().nullable().optional(),
  evidence: evidenceSchema, related_candidate_ids: z.array(z.string()).default([]),
});
const extractionSchema = z.object({
  schema_version: z.string(), meeting: z.object({ meeting_id: z.string(), title: z.string(), date: z.string(), source_url: z.string() }),
  ideas: z.array(candidateSchema), decisions: z.array(candidateSchema), actions: z.array(candidateSchema), questions: z.array(candidateSchema),
  review_candidates: z.array(z.object({ candidate_type: z.string(), description: z.string(), reason_for_review: z.string(), confidence: z.string(), evidence: evidenceSchema })),
});

type Candidate = z.infer<typeof candidateSchema>;
const normalizeConfidence = (value: string): Confidence => {
  const normalized = value.toUpperCase();
  return normalized === "HIGH" || normalized === "LOW" ? normalized : "MEDIUM";
};
const normalizeEvidence = (value: z.infer<typeof evidenceSchema>): Evidence => ({ speaker: value.speaker ?? null, timestamp: value.timestamp ?? null, quote: value.quote, context: value.context ?? null });
const normalize = (candidate: Candidate, type: ItemType, meetingId: string): KnowledgeItem => ({
  id: `${meetingId}:${candidate.candidate_id}`, type, description: candidate.description, theme: candidate.theme ?? null, status: candidate.status,
  confidence: normalizeConfidence(candidate.confidence), owner: candidate.owner ?? candidate.proposed_by ?? candidate.decision_owner ?? null,
  dueDate: candidate.due_date ?? null, dueDateSourceText: candidate.due_date_source_text ?? null, rationale: candidate.rationale ?? null, resolution: candidate.resolution ?? null,
  evidence: normalizeEvidence(candidate.evidence), relatedIds: candidate.related_candidate_ids, meetingId,
});

export function loadMeeting(): Meeting {
  const file = path.join(process.cwd(), "data", "meeting-extract.json");
  const original = readFileSync(file, "utf8").trim();
  const repaired = original.startsWith("{") ? original : `{${original}}`;
  const parsed = extractionSchema.parse(JSON.parse(repaired));
  const meetingId = parsed.meeting.meeting_id;
  const items = [
    ...parsed.ideas.map((item) => normalize(item, "IDEA", meetingId)),
    ...parsed.decisions.map((item) => normalize(item, "DECISION", meetingId)),
    ...parsed.actions.map((item) => normalize(item, "ACTION", meetingId)),
    ...parsed.questions.map((item) => normalize(item, "QUESTION", meetingId)),
  ];
  const reviewCandidates: ReviewCandidate[] = parsed.review_candidates.map((candidate, index) => ({
    id: `${meetingId}:review-${index + 1}`, type: candidate.candidate_type, description: candidate.description, reason: candidate.reason_for_review,
    confidence: normalizeConfidence(candidate.confidence), evidence: normalizeEvidence(candidate.evidence), status: "PENDING",
  }));
  const topicMap = new Map<string, KnowledgeItem[]>();
  for (const item of items) {
    const topic = item.theme ?? "Uncategorized";
    topicMap.set(topic, [...(topicMap.get(topic) ?? []), item]);
  }
  const topics: Topic[] = [...topicMap.entries()].map(([name, topicItems]) => ({ id: `${meetingId}:${name}`, name, items: topicItems }));
  return { id: meetingId, title: parsed.meeting.title, date: parsed.meeting.date, sourceUrl: parsed.meeting.source_url, items, reviewCandidates, topics };
}

export function relatedItems(item: KnowledgeItem, meeting: Meeting): KnowledgeItem[] {
  const ids = new Set(item.relatedIds);
  return meeting.items.filter((candidate) => ids.has(candidate.id.split(":")[1]) || ids.has(candidate.id));
}
