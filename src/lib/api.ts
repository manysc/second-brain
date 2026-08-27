import type { ItemType, KnowledgeItem, Meeting, ReviewCandidate, Topic } from "./domain";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend request failed: ${path} (${res.status})`);
  return res.json() as Promise<T>;
}

export function getMeeting(): Promise<Meeting> {
  return apiFetch<Meeting>("/api/meeting");
}

export function getItems(type?: ItemType): Promise<KnowledgeItem[]> {
  return apiFetch<KnowledgeItem[]>(type ? `/api/items?type=${type}` : "/api/items");
}

export function getItem(id: string): Promise<{ item: KnowledgeItem; related: KnowledgeItem[] }> {
  return apiFetch(`/api/items/${encodeURIComponent(id)}`);
}

export function getTopics(): Promise<Topic[]> {
  return apiFetch<Topic[]>("/api/topics");
}

export function getTopic(name: string): Promise<Topic> {
  return apiFetch<Topic>(`/api/topics/${encodeURIComponent(name)}`);
}

export function getReview(): Promise<ReviewCandidate[]> {
  return apiFetch<ReviewCandidate[]>("/api/review");
}
