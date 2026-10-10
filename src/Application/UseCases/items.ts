import {
  type ItemType,
  type KnowledgeItem,
  type OpenClosed,
  type TopicPriorityLevel,
  isItemType,
  tagProblem,
} from "@/Domain";
import type { ItemPatch, ItemsMove } from "../DTOs/Knowledge";
import { ValidationError, errorMessage } from "../Errors";
import type { KnowledgeRepository } from "../Interfaces/KnowledgeRepository";

/** Text as a person typed it into a form: trimmed, and blank means "nothing". */
function optional(text: string): string | null {
  return text.trim() || null;
}

export type NewItemInput = { type: string; description: string; owner: string; dueDate: string };

/** `type` is null when the form did not offer it (only manually added items can change type). */
export type ItemEditInput = { description: string; owner: string; dueDate: string; rationale: string; type: string | null };

export type SuggestedMovesResult = { error?: string; failedItemIds: string[]; movedTopicIds: string[] };

export type NewTopicFilingResult =
  | { status: "invalid"; error: string }
  | { status: "nothing_to_file" }
  | { status: "topic_not_created"; error: string }
  | { status: "items_not_moved"; error: string; topicId: string }
  | { status: "filed"; topicId: string };

export function itemUseCases(knowledge: KnowledgeRepository) {
  return {
    listItems: (type?: ItemType, priority?: TopicPriorityLevel): Promise<KnowledgeItem[]> =>
      knowledge.getItems(type, priority),

    /** Adds an item a person wrote by hand under a topic. */
    async createItem(topicId: string, input: NewItemInput): Promise<KnowledgeItem> {
      if (!isItemType(input.type)) throw new ValidationError("Invalid item type");
      const description = input.description.trim();
      if (!description) throw new ValidationError("Description is required");
      return knowledge.createItem(topicId, {
        type: input.type,
        description,
        owner: optional(input.owner),
        dueDate: optional(input.dueDate),
      });
    },

    /** Blank owner, due date or rationale clears that field. */
    async updateItem(itemId: string, input: ItemEditInput): Promise<KnowledgeItem> {
      const description = input.description.trim();
      if (!description) throw new ValidationError("Description is required");
      const patch: ItemPatch = {
        description,
        owner: optional(input.owner),
        dueDate: optional(input.dueDate),
        rationale: optional(input.rationale),
      };
      if (input.type !== null) {
        if (!isItemType(input.type)) throw new ValidationError("Invalid item type");
        patch.type = input.type;
      }
      return knowledge.updateItem(itemId, patch);
    },

    deleteItem: (itemId: string): Promise<void> => knowledge.deleteItem(itemId),

    setItemStatus: (itemId: string, status: OpenClosed): Promise<KnowledgeItem> =>
      knowledge.setItemStatus(itemId, status),

    /** An empty priority clears the override. */
    setItemPriorityOverride(itemId: string, priority: string, reason: string): Promise<KnowledgeItem> {
      const level = priority === "" ? null : (priority as TopicPriorityLevel);
      return knowledge.setItemPriorityOverride(itemId, level, optional(reason));
    },

    /** topicId null = unassigned. */
    moveItem: (itemId: string, topicId: string | null): Promise<KnowledgeItem> =>
      knowledge.moveItemTopic(itemId, topicId),

    /** Returns false when there was nothing to move. */
    async moveItems(itemIds: string[], topicId: string | null): Promise<boolean> {
      if (itemIds.length === 0) return false;
      await knowledge.moveItemsTopic(itemIds, topicId);
      return true;
    },

    /**
     * Files a batch of suggestion moves (one per target topic). A failed move doesn't stop the rest; its items
     * come back in `failedItemIds` with the first error.
     */
    async fileSuggestedItems(moves: ItemsMove[]): Promise<SuggestedMovesResult> {
      const result: SuggestedMovesResult = { failedItemIds: [], movedTopicIds: [] };
      for (const { itemIds, topicId } of moves) {
        if (itemIds.length === 0) continue;
        try {
          await knowledge.moveItemsTopic(itemIds, topicId);
          result.movedTopicIds.push(topicId);
        } catch (error) {
          result.error ??= errorMessage(error);
          result.failedItemIds.push(...itemIds);
        }
      }
      return result;
    },

    /**
     * Creates a topic and files the items into it in one step, for when none of the suggested topics fit.
     * If the move fails the topic still exists (empty) and its id comes back.
     */
    async fileItemsUnderNewTopic(name: string, itemIds: string[]): Promise<NewTopicFilingResult> {
      const topicName = name.trim();
      if (!topicName) return { status: "invalid", error: "Topic name is required" };
      if (itemIds.length === 0) return { status: "nothing_to_file" };
      let topicId: string;
      try {
        topicId = (await knowledge.createTopic(topicName)).id;
      } catch (error) {
        return { status: "topic_not_created", error: errorMessage(error) };
      }
      try {
        await knowledge.moveItemsTopic(itemIds, topicId);
      } catch (error) {
        return {
          status: "items_not_moved",
          error: `Created "${topicName}" but could not move the items: ${errorMessage(error)}`,
          topicId,
        };
      }
      return { status: "filed", topicId };
    },

    async addItemNote(itemId: string, body: string): Promise<KnowledgeItem> {
      const text = body.trim();
      if (!text) throw new ValidationError("Note cannot be empty");
      return knowledge.addItemNote(itemId, text);
    },

    async editItemNote(itemId: string, noteId: string, body: string): Promise<KnowledgeItem> {
      const text = body.trim();
      if (!text) throw new ValidationError("Note cannot be empty");
      return knowledge.updateItemNote(itemId, noteId, text);
    },

    deleteItemNote: (itemId: string, noteId: string): Promise<KnowledgeItem> =>
      knowledge.deleteItemNote(itemId, noteId),

    async addItemTag(itemId: string, tag: string): Promise<KnowledgeItem> {
      const text = tag.trim();
      const problem = tagProblem(text);
      if (problem) throw new ValidationError(problem);
      return knowledge.addItemTag(itemId, text);
    },

    async removeItemTag(itemId: string, tag: string): Promise<KnowledgeItem> {
      if (!tag) throw new ValidationError("Tag cannot be empty");
      return knowledge.removeItemTag(itemId, tag);
    },
  };
}
