import type { IngestResult, ItemPatch, NewItem, TopicImageContent } from "@/Application/DTOs/Knowledge";
import { NotFoundError } from "@/Application/Errors";
import type { KnowledgeRepository } from "@/Application/Interfaces/KnowledgeRepository";
import type {
  FollowUpResponse,
  GraphData,
  ItemTopicSuggestion,
  ItemType,
  KnowledgeItem,
  Meeting,
  OpenClosed,
  RelatedTopic,
  ReviewCandidate,
  ReviewDecision,
  SearchResult,
  Topic,
  TopicMergeSuggestion,
  TopicPriorityHistoryEntry,
  TopicPriorityLevel,
  TopicProposal,
} from "@/Domain";

export const DEFAULT_API_BASE_URL = "http://localhost:8000";

const id = encodeURIComponent;

/**
 * The knowledge base as served by the FastAPI backend. Every request is uncached (`no-store`): pages always show
 * what the backend has now. Failures become Errors carrying the backend's own explanation when it gave one.
 */
export class BackendApiClient implements KnowledgeRepository {
  constructor(private readonly baseUrl: string = process.env.API_BASE_URL ?? DEFAULT_API_BASE_URL) {}

  private async read<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`Backend request failed: ${path} (${res.status})`);
    return res.json() as Promise<T>;
  }

  private async mutate<T>(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
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

  // multipart upload: the Content-Type header is left unset so fetch adds the boundary itself
  private async upload<T>(path: string, form: FormData): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, { method: "POST", body: form, cache: "no-store" });
    if (!res.ok) {
      const payload = await res.json().catch(() => null);
      throw new Error(payload?.detail ?? `Backend request failed: ${path} (${res.status})`);
    }
    return res.json() as Promise<T>;
  }

  // -- meetings and ingestion ---------------------------------------------------------------------------

  getMeeting(): Promise<Meeting> {
    return this.read("/api/meeting");
  }

  getMeetings(): Promise<Meeting[]> {
    return this.read("/api/meetings");
  }

  getMeetingById(meetingId: string): Promise<Meeting> {
    return this.read(`/api/meetings/${id(meetingId)}`);
  }

  ingestMeetings(): Promise<IngestResult> {
    return this.mutate("/api/ingest", "POST");
  }

  // -- items --------------------------------------------------------------------------------------------

  getItems(type?: ItemType, priority?: TopicPriorityLevel): Promise<KnowledgeItem[]> {
    const params = new URLSearchParams();
    if (type) params.set("type", type);
    if (priority) params.set("priority", priority);
    const qs = params.toString();
    return this.read(qs ? `/api/items?${qs}` : "/api/items");
  }

  getItem(itemId: string): Promise<{ item: KnowledgeItem; related: KnowledgeItem[] }> {
    return this.read(`/api/items/${id(itemId)}`);
  }

  searchItems(query: string): Promise<SearchResult> {
    return this.read(`/api/search?q=${id(query)}`);
  }

  createItem(topicId: string, item: NewItem): Promise<KnowledgeItem> {
    return this.mutate(`/api/topics/${id(topicId)}/items`, "POST", item);
  }

  updateItem(itemId: string, patch: ItemPatch): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}`, "PATCH", patch);
  }

  deleteItem(itemId: string): Promise<void> {
    return this.mutate(`/api/items/${id(itemId)}`, "DELETE");
  }

  moveItemTopic(itemId: string, topicId: string | null): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/topic`, "PATCH", { topicId });
  }

  moveItemsTopic(itemIds: string[], topicId: string | null): Promise<KnowledgeItem[]> {
    return this.mutate("/api/items/topic", "PATCH", { itemIds, topicId });
  }

  setItemStatus(itemId: string, status: OpenClosed): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/status`, "PATCH", { status });
  }

  setItemPriorityOverride(
    itemId: string,
    priority: TopicPriorityLevel | null,
    reason: string | null,
  ): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/priority-override`, "PATCH", { priority, reason });
  }

  addItemNote(itemId: string, body: string): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/notes`, "POST", { body });
  }

  updateItemNote(itemId: string, noteId: string, body: string): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/notes/${id(noteId)}`, "PATCH", { body });
  }

  deleteItemNote(itemId: string, noteId: string): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/notes/${id(noteId)}`, "DELETE");
  }

  addItemTag(itemId: string, tag: string): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/tags`, "POST", { tag });
  }

  // the tag travels as a query param, not a path segment: tags are free text and may contain "/"
  removeItemTag(itemId: string, tag: string): Promise<KnowledgeItem> {
    return this.mutate(`/api/items/${id(itemId)}/tags?tag=${id(tag)}`, "DELETE");
  }

  // -- topics -------------------------------------------------------------------------------------------

  getTopics(): Promise<Topic[]> {
    return this.read("/api/topics");
  }

  async getTopicById(topicId: string): Promise<Topic> {
    const res = await fetch(`${this.baseUrl}/api/topics/${id(topicId)}`, { cache: "no-store" });
    if (res.status === 404) throw new NotFoundError("Topic not found");
    if (!res.ok) throw new Error(`Backend request failed: /api/topics/${topicId} (${res.status})`);
    return res.json() as Promise<Topic>;
  }

  getRelatedTopics(topicId: string): Promise<RelatedTopic[]> {
    return this.read(`/api/topics/${id(topicId)}/related`);
  }

  getSuggestedTopicMerges(): Promise<TopicMergeSuggestion[]> {
    return this.read("/api/topics/suggested-merges");
  }

  getSuggestedItemTopics(): Promise<ItemTopicSuggestion[]> {
    return this.read("/api/topics/suggested-item-topics");
  }

  createTopic(name: string): Promise<Topic> {
    return this.mutate("/api/topics", "POST", { name });
  }

  updateTopic(topicId: string, name: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}`, "PATCH", { name });
  }

  deleteTopic(topicId: string): Promise<void> {
    return this.mutate(`/api/topics/${id(topicId)}`, "DELETE");
  }

  mergeTopics(sourceId: string, targetId: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(sourceId)}/merge`, "POST", { targetTopicId: targetId });
  }

  setTopicStatus(topicId: string, status: OpenClosed): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/status`, "PATCH", { status });
  }

  addTopicNote(topicId: string, body: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/notes`, "POST", { body });
  }

  updateTopicNote(topicId: string, noteId: string, body: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/notes/${id(noteId)}`, "PATCH", { body });
  }

  deleteTopicNote(topicId: string, noteId: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/notes/${id(noteId)}`, "DELETE");
  }

  addTopicTag(topicId: string, tag: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/tags`, "POST", { tag });
  }

  removeTopicTag(topicId: string, tag: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/tags?tag=${id(tag)}`, "DELETE");
  }

  addTopicImage(topicId: string, file: File): Promise<Topic> {
    const form = new FormData();
    form.append("file", file);
    return this.upload(`/api/topics/${id(topicId)}/images`, form);
  }

  deleteTopicImage(topicId: string, imageId: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/images/${id(imageId)}`, "DELETE");
  }

  // The bucket behind the backend is private, so the browser gets image bytes through the app.
  async loadTopicImage(topicId: string, imageId: string): Promise<TopicImageContent> {
    const res = await fetch(`${this.baseUrl}/api/topics/${id(topicId)}/images/${id(imageId)}`, {
      cache: "no-store",
    }).catch(() => null);
    if (!res) return { kind: "unreachable" };
    if (!res.ok) return res.status === 404 ? { kind: "missing" } : { kind: "failed" };
    return { kind: "ok", body: res.body, contentType: res.headers.get("Content-Type") };
  }

  // -- priority -----------------------------------------------------------------------------------------

  recalculateTopicPriority(topicId: string): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/recalculate-priority`, "POST");
  }

  recalculateAllTopicPriorities(): Promise<{ recalculated: number }> {
    return this.mutate("/api/topics/recalculate-priority", "POST");
  }

  setTopicPriorityOverride(
    topicId: string,
    priority: TopicPriorityLevel | null,
    reason: string | null,
  ): Promise<Topic> {
    return this.mutate(`/api/topics/${id(topicId)}/priority-override`, "PATCH", { priority, reason });
  }

  getTopicPriorityHistory(topicId: string): Promise<TopicPriorityHistoryEntry[]> {
    return this.read(`/api/topics/${id(topicId)}/priority-history`);
  }

  getRecentPriorityEscalations(days?: number): Promise<TopicPriorityHistoryEntry[]> {
    return this.read(days !== undefined ? `/api/priority-history/recent?days=${days}` : "/api/priority-history/recent");
  }

  // -- review -------------------------------------------------------------------------------------------

  getReview(): Promise<ReviewCandidate[]> {
    return this.read("/api/review");
  }

  updateReviewStatus(candidateId: string, status: ReviewDecision, topicId?: string): Promise<ReviewCandidate> {
    return this.mutate(`/api/review/${id(candidateId)}`, "PATCH", { status, topicId });
  }

  getTopicProposals(): Promise<TopicProposal[]> {
    return this.read("/api/review/topic-proposals");
  }

  acceptTopicProposal(
    suggestedName: string,
    topicName: string | null,
    existingTopicId: string | null,
  ): Promise<KnowledgeItem[]> {
    return this.mutate("/api/review/topic-proposals/accept", "POST", { suggestedName, topicName, existingTopicId });
  }

  rejectTopicProposal(suggestedName: string): Promise<void> {
    return this.mutate("/api/review/topic-proposals/reject", "POST", { suggestedName });
  }

  // -- whole-knowledge-base views -----------------------------------------------------------------------

  getGraph(minSimilarity?: number): Promise<GraphData> {
    return this.read(minSimilarity !== undefined ? `/api/graph?minSimilarity=${minSimilarity}` : "/api/graph");
  }

  getFollowUp(limit?: number, dueSoonDays?: number): Promise<FollowUpResponse> {
    const params = new URLSearchParams();
    if (limit !== undefined) params.set("limit", String(limit));
    if (dueSoonDays !== undefined) params.set("dueSoonDays", String(dueSoonDays));
    const query = params.toString();
    return this.read(query ? `/api/follow-up?${query}` : "/api/follow-up");
  }
}
