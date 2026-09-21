import { notFound } from "next/navigation";
import type {
  FollowUpResponse,
  GraphData,
  ItemType,
  ItemTopicSuggestion,
  KnowledgeItem,
  Meeting,
  OpenClosed,
  RelatedTopic,
  ReviewCandidate,
  SearchResult,
  Topic,
  TopicMergeSuggestion,
  TopicPriorityHistoryEntry,
  TopicPriorityLevel,
  TopicProposal,
} from "./domain";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend request failed: ${path} (${res.status})`);
  return res.json() as Promise<T>;
}

async function apiMutate<T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new Error(payload?.detail ?? `Backend request failed: ${path} (${res.status})`);
  }
  return res.status === 204 ? (undefined as T) : (res.json() as Promise<T>);
}


export function getMeeting(): Promise<Meeting> {
  return apiFetch<Meeting>("/api/meeting");
}

export function getMeetings(): Promise<Meeting[]> {
  return apiFetch<Meeting[]>("/api/meetings");
}

export function getMeetingById(id: string): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/meetings/${encodeURIComponent(id)}`);
}

export function getItems(type?: ItemType, priority?: TopicPriorityLevel): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  if (priority) params.set("priority", priority);
  const qs = params.toString();
  return apiFetch<KnowledgeItem[]>(qs ? `/api/items?${qs}` : "/api/items");
}

export function getItem(id: string): Promise<{ item: KnowledgeItem; related: KnowledgeItem[] }> {
  return apiFetch(`/api/items/${encodeURIComponent(id)}`);
}

export function searchItems(query: string): Promise<SearchResult> {
  return apiFetch<SearchResult>(`/api/search?q=${encodeURIComponent(query)}`);
}

export function getTopics(): Promise<Topic[]> {
  return apiFetch<Topic[]>("/api/topics");
}

export function getGraph(minSimilarity?: number): Promise<GraphData> {
  return apiFetch<GraphData>(
    minSimilarity !== undefined ? `/api/graph?minSimilarity=${minSimilarity}` : "/api/graph"
  );
}

export function getSuggestedTopicMerges(): Promise<TopicMergeSuggestion[]> {
  return apiFetch<TopicMergeSuggestion[]>("/api/topics/suggested-merges");
}

export function getSuggestedItemTopics(): Promise<ItemTopicSuggestion[]> {
  return apiFetch<ItemTopicSuggestion[]>("/api/topics/suggested-item-topics");
}

export async function getTopicById(id: string): Promise<Topic> {
  const res = await fetch(`${API_BASE_URL}/api/topics/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error(`Backend request failed: /api/topics/${id} (${res.status})`);
  return res.json() as Promise<Topic>;
}

export function getRelatedTopics(id: string): Promise<RelatedTopic[]> {
  return apiFetch<RelatedTopic[]>(`/api/topics/${encodeURIComponent(id)}/related`);
}

export function createTopic(name: string): Promise<Topic> {
  return apiMutate<Topic>("/api/topics", "POST", { name });
}

export function updateTopic(id: string, name: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}`, "PATCH", { name });
}

export function mergeTopics(sourceId: string, targetId: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(sourceId)}/merge`, "POST", { targetTopicId: targetId });
}

export function deleteTopic(id: string): Promise<void> {
  return apiMutate<void>(`/api/topics/${encodeURIComponent(id)}`, "DELETE");
}

export function moveItemTopic(itemId: string, topicId: string | null): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(itemId)}/topic`, "PATCH", { topicId });
}

export function moveItemsTopic(itemIds: string[], topicId: string | null): Promise<KnowledgeItem[]> {
  return apiMutate<KnowledgeItem[]>("/api/items/topic", "PATCH", { itemIds, topicId });
}

export function getReview(): Promise<ReviewCandidate[]> {
  return apiFetch<ReviewCandidate[]>("/api/review");
}

// topicId (accept only): "" = Uncategorized, undefined = let the backend auto-match
export function updateReviewStatus(
  id: string,
  status: "ACCEPTED" | "REJECTED",
  topicId?: string
): Promise<ReviewCandidate> {
  return apiMutate<ReviewCandidate>(`/api/review/${encodeURIComponent(id)}`, "PATCH", { status, topicId });
}

export function getTopicProposals(): Promise<TopicProposal[]> {
  return apiFetch<TopicProposal[]>("/api/review/topic-proposals");
}

export function acceptTopicProposal(
  suggestedName: string,
  topicName: string | null,
  existingTopicId: string | null
): Promise<KnowledgeItem[]> {
  return apiMutate<KnowledgeItem[]>("/api/review/topic-proposals/accept", "POST", {
    suggestedName,
    topicName,
    existingTopicId,
  });
}

export function rejectTopicProposal(suggestedName: string): Promise<void> {
  return apiMutate<void>("/api/review/topic-proposals/reject", "POST", { suggestedName });
}

export function recalculateTopicPriority(id: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/recalculate-priority`, "POST");
}

export function recalculateAllTopicPriorities(): Promise<{ recalculated: number }> {
  return apiMutate<{ recalculated: number }>("/api/topics/recalculate-priority", "POST");
}

export function setTopicPriorityOverride(
  id: string,
  priority: TopicPriorityLevel | null,
  reason: string | null
): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/priority-override`, "PATCH", { priority, reason });
}

export function getTopicPriorityHistory(id: string): Promise<TopicPriorityHistoryEntry[]> {
  return apiFetch<TopicPriorityHistoryEntry[]>(`/api/topics/${encodeURIComponent(id)}/priority-history`);
}

export function setItemPriorityOverride(
  id: string,
  priority: TopicPriorityLevel | null,
  reason: string | null
): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}/priority-override`, "PATCH", { priority, reason });
}

export function setItemStatus(id: string, status: OpenClosed): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}/status`, "PATCH", { status });
}

export function setTopicStatus(id: string, status: OpenClosed): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/status`, "PATCH", { status });
}

export function addItemNote(id: string, body: string): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}/notes`, "POST", { body });
}

export function deleteItemNote(id: string, noteId: string): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, "DELETE");
}

export function addTopicNote(id: string, body: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/notes`, "POST", { body });
}

export type NewItem = {
  type: ItemType;
  description: string;
  owner?: string | null;
  dueDate?: string | null;
};

export function createItem(topicId: string, item: NewItem): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/topics/${encodeURIComponent(topicId)}/items`, "POST", item);
}

export type ItemPatch = Partial<NewItem> & { rationale?: string | null };

export function updateItem(id: string, patch: ItemPatch): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}`, "PATCH", patch);
}

export function deleteItem(id: string): Promise<void> {
  return apiMutate<void>(`/api/items/${encodeURIComponent(id)}`, "DELETE");
}

export function deleteTopicNote(id: string, noteId: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, "DELETE");
}

export function updateItemNote(id: string, noteId: string, body: string): Promise<KnowledgeItem> {
  return apiMutate<KnowledgeItem>(`/api/items/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, "PATCH", {
    body,
  });
}

export function updateTopicNote(id: string, noteId: string, body: string): Promise<Topic> {
  return apiMutate<Topic>(`/api/topics/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, "PATCH", { body });
}

export function getRecentPriorityEscalations(days?: number): Promise<TopicPriorityHistoryEntry[]> {
  return apiFetch<TopicPriorityHistoryEntry[]>(
    days !== undefined ? `/api/priority-history/recent?days=${days}` : "/api/priority-history/recent"
  );
}

export function getFollowUp(limit?: number, dueSoonDays?: number): Promise<FollowUpResponse> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (dueSoonDays !== undefined) params.set("dueSoonDays", String(dueSoonDays));
  const query = params.toString();
  return apiFetch<FollowUpResponse>(query ? `/api/follow-up?${query}` : "/api/follow-up");
}
