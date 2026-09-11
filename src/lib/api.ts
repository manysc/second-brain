import { notFound } from "next/navigation";
import type { GraphData, ItemType, ItemTopicSuggestion, KnowledgeItem, Meeting, ReviewCandidate, SearchResult, Topic, TopicMergeSuggestion } from "./domain";

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

export function getItems(type?: ItemType): Promise<KnowledgeItem[]> {
  return apiFetch<KnowledgeItem[]>(type ? `/api/items?type=${type}` : "/api/items");
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

export function getReview(): Promise<ReviewCandidate[]> {
  return apiFetch<ReviewCandidate[]>("/api/review");
}

export function updateReviewStatus(id: string, status: "ACCEPTED" | "REJECTED"): Promise<ReviewCandidate> {
  return apiMutate<ReviewCandidate>(`/api/review/${encodeURIComponent(id)}`, "PATCH", { status });
}
