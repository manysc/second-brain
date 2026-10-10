import {
  type OpenClosed,
  type RelatedTopic,
  type SuggestionRow,
  type Topic,
  type TopicMergeSuggestion,
  type TopicPriorityHistoryEntry,
  type TopicPriorityLevel,
  tagProblem,
  toSuggestionRow,
} from "@/Domain";
import type { TopicImageContent } from "../DTOs/Knowledge";
import { ValidationError } from "../Errors";
import type { KnowledgeRepository } from "../Interfaces/KnowledgeRepository";

function required(text: string, message: string): string {
  const trimmed = text.trim();
  if (!trimmed) throw new ValidationError(message);
  return trimmed;
}

export function topicUseCases(knowledge: KnowledgeRepository) {
  return {
    listTopics: (): Promise<Topic[]> => knowledge.getTopics(),

    /** Rejects with NotFoundError when the topic does not exist. */
    getTopic: (topicId: string): Promise<Topic> => knowledge.getTopicById(topicId),

    listRelatedTopics: (topicId: string): Promise<RelatedTopic[]> => knowledge.getRelatedTopics(topicId),

    suggestTopicMerges: (): Promise<TopicMergeSuggestion[]> => knowledge.getSuggestedTopicMerges(),

    /** Ranked topics for each item still in Uncategorized, trimmed to what the suggestions panel shows. */
    async suggestItemTopics(): Promise<SuggestionRow[]> {
      return (await knowledge.getSuggestedItemTopics()).map(toSuggestionRow);
    },

    createTopic: async (name: string): Promise<Topic> => knowledge.createTopic(required(name, "Topic name is required")),

    renameTopic: async (topicId: string, name: string): Promise<Topic> =>
      knowledge.updateTopic(topicId, required(name, "Topic name is required")),

    deleteTopic: (topicId: string): Promise<void> => knowledge.deleteTopic(topicId),

    mergeTopics: (sourceTopicId: string, targetTopicId: string): Promise<Topic> =>
      knowledge.mergeTopics(sourceTopicId, targetTopicId),

    setTopicStatus: (topicId: string, status: OpenClosed): Promise<Topic> => knowledge.setTopicStatus(topicId, status),

    addTopicNote: async (topicId: string, body: string): Promise<Topic> =>
      knowledge.addTopicNote(topicId, required(body, "Note cannot be empty")),

    editTopicNote: async (topicId: string, noteId: string, body: string): Promise<Topic> =>
      knowledge.updateTopicNote(topicId, noteId, required(body, "Note cannot be empty")),

    deleteTopicNote: (topicId: string, noteId: string): Promise<Topic> => knowledge.deleteTopicNote(topicId, noteId),

    async addTopicTag(topicId: string, tag: string): Promise<Topic> {
      const text = tag.trim();
      const problem = tagProblem(text);
      if (problem) throw new ValidationError(problem);
      return knowledge.addTopicTag(topicId, text);
    },

    removeTopicTag: (topicId: string, tag: string): Promise<Topic> => knowledge.removeTopicTag(topicId, tag),

    /** `file` is whatever the upload form sent; anything but a non-empty file is refused. */
    async addTopicImage(topicId: string, file: unknown): Promise<Topic> {
      if (!(file instanceof File) || file.size === 0) throw new ValidationError("Choose an image to upload");
      return knowledge.addTopicImage(topicId, file);
    },

    deleteTopicImage: (topicId: string, imageId: string): Promise<Topic> =>
      knowledge.deleteTopicImage(topicId, imageId),

    loadTopicImage: (topicId: string, imageId: string): Promise<TopicImageContent> =>
      knowledge.loadTopicImage(topicId, imageId),

    /** An empty priority clears the override. */
    setTopicPriorityOverride(topicId: string, priority: string, reason: string): Promise<Topic> {
      const level = priority === "" ? null : (priority as TopicPriorityLevel);
      return knowledge.setTopicPriorityOverride(topicId, level, reason.trim() || null);
    },

    recalculateTopicPriority: (topicId: string): Promise<Topic> => knowledge.recalculateTopicPriority(topicId),

    listRecentEscalations: (days?: number): Promise<TopicPriorityHistoryEntry[]> =>
      knowledge.getRecentPriorityEscalations(days),

    getTopicPriorityHistory: (topicId: string): Promise<TopicPriorityHistoryEntry[]> =>
      knowledge.getTopicPriorityHistory(topicId),
  };
}
