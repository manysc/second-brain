"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import type { ItemsMove } from "@/Application/DTOs/Knowledge";
import { ValidationError } from "@/Application/Errors";
import type { OpenClosed } from "@/Domain";
import { useCases } from "@/composition";
import {
  field,
  redirectWithError,
  revalidate,
  revalidateAfterItemChange,
  revalidateItemPages,
  topicPath,
} from "./support";

// the item tag forms live on KnowledgeCard, which renders on many pages, so (like the other item actions)
// these don't redirect; the topic and meeting detail pages need explicit revalidation on top of the shared set
function revalidateItemTagPages(): void {
  revalidateItemPages();
  revalidatePath("/topics/[id]", "page");
  revalidatePath("/meetings/[id]", "page");
}

/** Runs an item action whose form has nowhere to show an error: invalid input is simply ignored. */
async function ignoringInvalidInput(run: () => Promise<unknown>): Promise<boolean> {
  try {
    await run();
    return true;
  } catch (error) {
    if (error instanceof ValidationError) return false;
    throw error;
  }
}

// -- filing under topics ----------------------------------------------------------------------------------

export async function moveItemTopicAction(formData: FormData): Promise<void> {
  const itemId = field(formData, "itemId");
  const currentTopicId = field(formData, "currentTopicId");
  const topicId = field(formData, "topicId") || null; // "" = unassigned
  try {
    await useCases.moveItem(itemId, topicId);
  } catch (error) {
    redirectWithError(topicPath(currentTopicId), error);
  }
  revalidate("/topics", `/topics/${currentTopicId}`);
  if (topicId) revalidatePath(`/topics/${topicId}`);
  redirect(topicPath(currentTopicId));
}

export async function moveItemsTopicAction(itemIds: string[], topicId: string | null, returnTo: string): Promise<void> {
  let moved: boolean;
  try {
    moved = await useCases.moveItems(itemIds, topicId);
  } catch (error) {
    redirectWithError(returnTo, error);
  }
  if (!moved) return;
  revalidate("/items", "/topics", returnTo);
  if (topicId) revalidatePath(`/topics/${topicId}`);
  redirect(returnTo);
}

// Like moveItemsTopicAction but returns instead of redirecting, so a client component can hide the
// moved items optimistically instead of waiting for a full page re-render. Takes a batch of moves
// (one per target topic) so filing every group at once costs a single revalidation.
export async function moveSuggestedItemsAction(
  moves: ItemsMove[],
  returnTo: string,
): Promise<{ error?: string; failedItemIds?: string[] }> {
  const { error, failedItemIds, movedTopicIds } = await useCases.fileSuggestedItems(moves);
  if (movedTopicIds.length) {
    revalidate("/topics", returnTo, ...movedTopicIds.map((topicId) => `/topics/${topicId}`));
  }
  return error ? { error, failedItemIds } : {};
}

// Creates a topic and files the items into it in one step, for when none of the suggested topics fit.
// Returns like moveSuggestedItemsAction; if the move fails the topic still exists (empty) and its id comes back.
export async function createTopicAndMoveItemsAction(
  name: string,
  itemIds: string[],
  returnTo: string,
): Promise<{ error?: string; topicId?: string }> {
  const result = await useCases.fileItemsUnderNewTopic(name, itemIds);
  switch (result.status) {
    case "invalid":
    case "topic_not_created":
      return { error: result.error };
    case "nothing_to_file":
      return {};
    case "items_not_moved":
      revalidatePath("/topics");
      return { error: result.error, topicId: result.topicId };
    case "filed":
      revalidate("/topics", returnTo, `/topics/${result.topicId}`);
      return { topicId: result.topicId };
  }
}

// -- adding, editing and deleting by hand -----------------------------------------------------------------

export async function createItemAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.createItem(topicId, {
      type: field(formData, "type"),
      description: field(formData, "description"),
      owner: field(formData, "owner"),
      dueDate: field(formData, "dueDate"),
    });
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateAfterItemChange(topicId);
  redirect(topicPath(topicId));
}

export async function updateItemAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  const type = formData.get("type"); // only present for manual items
  try {
    await useCases.updateItem(field(formData, "itemId"), {
      description: field(formData, "description"),
      owner: field(formData, "owner"),
      dueDate: field(formData, "dueDate"),
      rationale: field(formData, "rationale"),
      type: type === null ? null : String(type),
    });
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateAfterItemChange(topicId);
  redirect(topicPath(topicId));
}

export async function deleteItemAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.deleteItem(field(formData, "itemId"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateAfterItemChange(topicId);
  redirect(topicPath(topicId));
}

// -- status, priority, notes and tags (forms on KnowledgeCard: no redirect) -------------------------------

export async function setItemStatusAction(formData: FormData): Promise<void> {
  await useCases.setItemStatus(field(formData, "itemId"), field(formData, "status") as OpenClosed);
  revalidateItemPages();
  revalidatePath("/briefing");
}

export async function setItemPriorityOverrideAction(formData: FormData): Promise<void> {
  await useCases.setItemPriorityOverride(field(formData, "itemId"), field(formData, "priority"), field(formData, "reason"));
  revalidateItemPages();
}

export async function clearItemPriorityOverrideAction(formData: FormData): Promise<void> {
  await useCases.setItemPriorityOverride(field(formData, "itemId"), "", "");
  revalidateItemPages();
}

export async function addItemNoteAction(formData: FormData): Promise<void> {
  if (await ignoringInvalidInput(() => useCases.addItemNote(field(formData, "itemId"), field(formData, "body")))) {
    revalidateItemPages();
  }
}

export async function updateItemNoteAction(formData: FormData): Promise<void> {
  const edit = () => useCases.editItemNote(field(formData, "itemId"), field(formData, "noteId"), field(formData, "body"));
  if (await ignoringInvalidInput(edit)) revalidateItemPages();
}

export async function deleteItemNoteAction(formData: FormData): Promise<void> {
  await useCases.deleteItemNote(field(formData, "itemId"), field(formData, "noteId"));
  revalidateItemPages();
}

export async function addItemTagAction(formData: FormData): Promise<void> {
  if (await ignoringInvalidInput(() => useCases.addItemTag(field(formData, "itemId"), field(formData, "tag")))) {
    revalidateItemTagPages();
  }
}

export async function removeItemTagAction(formData: FormData): Promise<void> {
  if (await ignoringInvalidInput(() => useCases.removeItemTag(field(formData, "itemId"), field(formData, "tag")))) {
    revalidateItemTagPages();
  }
}
