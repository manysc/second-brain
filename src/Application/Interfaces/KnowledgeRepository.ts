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
import type { IngestResult, ItemPatch, NewItem, TopicImageContent } from "../DTOs/Knowledge";

/**
 * Everything the app reads from and writes to the knowledge base. Implemented by the backend API client.
 * A failed call rejects with an Error whose message can be shown to the person; a missing topic rejects
 * with NotFoundError where noted.
 */
export interface KnowledgeRepository {
  // meetings and ingestion
  getMeeting(): Promise<Meeting>;
  getMeetings(): Promise<Meeting[]>;
  getMeetingById(id: string): Promise<Meeting>;
  ingestMeetings(): Promise<IngestResult>;

  // items
  getItems(type?: ItemType, priority?: TopicPriorityLevel): Promise<KnowledgeItem[]>;
  getItem(id: string): Promise<{ item: KnowledgeItem; related: KnowledgeItem[] }>;
  searchItems(query: string): Promise<SearchResult>;
  createItem(topicId: string, item: NewItem): Promise<KnowledgeItem>;
  updateItem(id: string, patch: ItemPatch): Promise<KnowledgeItem>;
  deleteItem(id: string): Promise<void>;
  moveItemTopic(itemId: string, topicId: string | null): Promise<KnowledgeItem>;
  moveItemsTopic(itemIds: string[], topicId: string | null): Promise<KnowledgeItem[]>;
  setItemStatus(id: string, status: OpenClosed): Promise<KnowledgeItem>;
  setItemPriorityOverride(id: string, priority: TopicPriorityLevel | null, reason: string | null): Promise<KnowledgeItem>;
  addItemNote(id: string, body: string): Promise<KnowledgeItem>;
  updateItemNote(id: string, noteId: string, body: string): Promise<KnowledgeItem>;
  deleteItemNote(id: string, noteId: string): Promise<KnowledgeItem>;
  addItemTag(id: string, tag: string): Promise<KnowledgeItem>;
  removeItemTag(id: string, tag: string): Promise<KnowledgeItem>;

  // topics
  getTopics(): Promise<Topic[]>;
  /** Rejects with NotFoundError when the topic does not exist. */
  getTopicById(id: string): Promise<Topic>;
  getRelatedTopics(id: string): Promise<RelatedTopic[]>;
  getSuggestedTopicMerges(): Promise<TopicMergeSuggestion[]>;
  getSuggestedItemTopics(): Promise<ItemTopicSuggestion[]>;
  createTopic(name: string): Promise<Topic>;
  updateTopic(id: string, name: string): Promise<Topic>;
  deleteTopic(id: string): Promise<void>;
  mergeTopics(sourceId: string, targetId: string): Promise<Topic>;
  setTopicStatus(id: string, status: OpenClosed): Promise<Topic>;
  addTopicNote(id: string, body: string): Promise<Topic>;
  updateTopicNote(id: string, noteId: string, body: string): Promise<Topic>;
  deleteTopicNote(id: string, noteId: string): Promise<Topic>;
  addTopicTag(id: string, tag: string): Promise<Topic>;
  removeTopicTag(id: string, tag: string): Promise<Topic>;
  addTopicImage(id: string, file: File): Promise<Topic>;
  deleteTopicImage(id: string, imageId: string): Promise<Topic>;
  loadTopicImage(id: string, imageId: string): Promise<TopicImageContent>;

  // priority
  recalculateTopicPriority(id: string): Promise<Topic>;
  recalculateAllTopicPriorities(): Promise<{ recalculated: number }>;
  setTopicPriorityOverride(id: string, priority: TopicPriorityLevel | null, reason: string | null): Promise<Topic>;
  getTopicPriorityHistory(id: string): Promise<TopicPriorityHistoryEntry[]>;
  getRecentPriorityEscalations(days?: number): Promise<TopicPriorityHistoryEntry[]>;

  // review
  getReview(): Promise<ReviewCandidate[]>;
  /** topicId (accept only): "" = Uncategorized, undefined = let the backend auto-match. */
  updateReviewStatus(id: string, status: ReviewDecision, topicId?: string): Promise<ReviewCandidate>;
  getTopicProposals(): Promise<TopicProposal[]>;
  acceptTopicProposal(suggestedName: string, topicName: string | null, existingTopicId: string | null): Promise<KnowledgeItem[]>;
  rejectTopicProposal(suggestedName: string): Promise<void>;

  // whole-knowledge-base views
  getGraph(minSimilarity?: number): Promise<GraphData>;
  getFollowUp(limit?: number, dueSoonDays?: number): Promise<FollowUpResponse>;
}
