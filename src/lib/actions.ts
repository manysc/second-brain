"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  acceptTopicProposal,
  addItemNote,
  addItemTag,
  addTopicNote,
  addTopicTag,
  createItem,
  createTopic,
  deleteItem,
  deleteItemNote,
  deleteTopic,
  deleteTopicNote,
  mergeTopics,
  moveItemsTopic,
  moveItemTopic,
  recalculateTopicPriority,
  rejectTopicProposal,
  removeItemTag,
  removeTopicTag,
  setItemPriorityOverride,
  setItemStatus,
  setTopicPriorityOverride,
  setTopicStatus,
  updateItem,
  updateItemNote,
  updateReviewStatus,
  updateTopic,
  updateTopicNote,
} from "./api";
import type { ItemPatch } from "./api";
import { MAX_TAG_LENGTH } from "./domain";
import type { ItemType, OpenClosed, TopicPriorityLevel } from "./domain";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong";
}

export async function createTopicAction(formData: FormData): Promise<void> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) redirect(`/topics?error=${encodeURIComponent("Topic name is required")}`);

  try {
    await createTopic(name);
  } catch (err) {
    redirect(`/topics?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  redirect("/topics");
}

export async function updateTopicAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  if (!name) redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent("Topic name is required")}`);

  try {
    await updateTopic(topicId, name);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function deleteTopicAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");

  try {
    await deleteTopic(topicId);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  redirect("/topics");
}

export async function moveItemTopicAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const currentTopicId = String(formData.get("currentTopicId") ?? "");
  const rawTopicId = String(formData.get("topicId") ?? "");
  const topicId = rawTopicId === "" ? null : rawTopicId;

  try {
    await moveItemTopic(itemId, topicId);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(currentTopicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${currentTopicId}`);
  if (topicId) revalidatePath(`/topics/${topicId}`);
  redirect(`/topics/${encodeURIComponent(currentTopicId)}`);
}

export async function moveItemsTopicAction(itemIds: string[], topicId: string | null, returnTo: string): Promise<void> {
  if (itemIds.length === 0) return;

  try {
    await moveItemsTopic(itemIds, topicId);
  } catch (err) {
    redirect(`${returnTo}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/items");
  revalidatePath("/topics");
  revalidatePath(returnTo);
  if (topicId) revalidatePath(`/topics/${topicId}`);
  redirect(returnTo);
}

export async function mergeTopicsAction(sourceTopicId: string, targetTopicId: string): Promise<void> {
  try {
    await mergeTopics(sourceTopicId, targetTopicId);
  } catch (err) {
    redirect(`/topics?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
}

export async function assignItemTopicAction(itemId: string, topicId: string): Promise<void> {
  try {
    await moveItemTopic(itemId, topicId);
  } catch (err) {
    redirect(`/topics?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
}

async function decideReviewCandidate(formData: FormData, status: "ACCEPTED" | "REJECTED"): Promise<void> {
  const candidateId = String(formData.get("candidateId") ?? "");
  // only the accept form has a topic picker; "" there means the reviewer chose Uncategorized
  const topicId = status === "ACCEPTED" && formData.has("topicId") ? String(formData.get("topicId")) : undefined;

  try {
    await updateReviewStatus(candidateId, status, topicId);
  } catch (err) {
    redirect(`/review?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/review");
  revalidatePath("/dashboard");
  revalidatePath("/items");
  revalidatePath("/topics");
  revalidatePath("/meetings");
  redirect("/review");
}

export async function acceptReviewAction(formData: FormData): Promise<void> {
  await decideReviewCandidate(formData, "ACCEPTED");
}

export async function rejectReviewAction(formData: FormData): Promise<void> {
  await decideReviewCandidate(formData, "REJECTED");
}

function revalidateAfterTopicProposal(): void {
  revalidatePath("/review");
  revalidatePath("/dashboard");
  revalidatePath("/items");
  revalidatePath("/topics");
  revalidatePath("/meetings");
}

export async function acceptTopicProposalAction(formData: FormData): Promise<void> {
  const suggestedName = String(formData.get("suggestedName") ?? "");
  const topicName = String(formData.get("topicName") ?? "").trim();
  const existingTopicId = String(formData.get("existingTopicId") ?? "");

  try {
    await acceptTopicProposal(suggestedName, topicName || null, existingTopicId || null);
  } catch (err) {
    redirect(`/review?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidateAfterTopicProposal();
  redirect("/review");
}

export async function rejectTopicProposalAction(formData: FormData): Promise<void> {
  const suggestedName = String(formData.get("suggestedName") ?? "");

  try {
    await rejectTopicProposal(suggestedName);
  } catch (err) {
    redirect(`/review?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidateAfterTopicProposal();
  redirect("/review");
}

function revalidatePriorityAffectedPaths(topicId: string): void {
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  revalidatePath("/dashboard");
  revalidatePath("/briefing");
  revalidatePath("/graph");
}

export async function setPriorityOverrideAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const rawPriority = String(formData.get("priority") ?? "");
  const priority = rawPriority === "" ? null : (rawPriority as TopicPriorityLevel);
  const reason = String(formData.get("reason") ?? "").trim() || null;

  try {
    await setTopicPriorityOverride(topicId, priority, reason);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePriorityAffectedPaths(topicId);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function clearPriorityOverrideAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");

  try {
    await setTopicPriorityOverride(topicId, null, null);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePriorityAffectedPaths(topicId);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function recalculatePriorityAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");

  try {
    await recalculateTopicPriority(topicId);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePriorityAffectedPaths(topicId);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

// KnowledgeCard renders on many pages with no single "return to" route, so these intentionally
// don't redirect - revalidating lets Next re-render whichever page the form was submitted from.
function revalidateItemPriorityAffectedPaths(): void {
  revalidatePath("/items");
  revalidatePath("/actions");
  revalidatePath("/questions");
  revalidatePath("/decisions");
  revalidatePath("/ask");
  revalidatePath("/dashboard");
  revalidatePath("/topics");
}

export async function setItemPriorityOverrideAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const rawPriority = String(formData.get("priority") ?? "");
  const priority = rawPriority === "" ? null : (rawPriority as TopicPriorityLevel);
  const reason = String(formData.get("reason") ?? "").trim() || null;

  await setItemPriorityOverride(itemId, priority, reason);
  revalidateItemPriorityAffectedPaths();
}

export async function clearItemPriorityOverrideAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");

  await setItemPriorityOverride(itemId, null, null);
  revalidateItemPriorityAffectedPaths();
}

export async function setItemStatusAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const status = String(formData.get("status") ?? "") as OpenClosed;

  await setItemStatus(itemId, status);
  revalidateItemPriorityAffectedPaths();
  revalidatePath("/briefing");
}

export async function setTopicStatusAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const status = String(formData.get("status") ?? "") as OpenClosed;

  try {
    await setTopicStatus(topicId, status);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePriorityAffectedPaths(topicId);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function addItemNoteAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const body = String(formData.get("body") ?? "").trim();
  if (!body) return;

  await addItemNote(itemId, body);
  revalidateItemPriorityAffectedPaths();
}

export async function deleteItemNoteAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const noteId = String(formData.get("noteId") ?? "");

  await deleteItemNote(itemId, noteId);
  revalidateItemPriorityAffectedPaths();
}

export async function addTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const body = String(formData.get("body") ?? "").trim();
  if (!body) redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent("Note cannot be empty")}`);

  try {
    await addTopicNote(topicId, body);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function addTopicTagAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const topicPath = `/topics/${encodeURIComponent(topicId)}`;
  const tag = String(formData.get("tag") ?? "").trim();
  if (!tag) redirect(`${topicPath}?error=${encodeURIComponent("Tag cannot be empty")}`);
  if (tag.length > MAX_TAG_LENGTH) {
    redirect(`${topicPath}?error=${encodeURIComponent(`Tag cannot be longer than ${MAX_TAG_LENGTH} characters`)}`);
  }

  try {
    await addTopicTag(topicId, tag);
  } catch (err) {
    redirect(`${topicPath}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(topicPath);
}

export async function removeTopicTagAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const topicPath = `/topics/${encodeURIComponent(topicId)}`;
  const tag = String(formData.get("tag") ?? "");

  try {
    await removeTopicTag(topicId, tag);
  } catch (err) {
    redirect(`${topicPath}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(topicPath);
}

// the item tag forms live on KnowledgeCard, which renders on many pages, so (like the other item actions)
// these don't redirect; the topic and meeting detail pages need explicit revalidation on top of the shared set
function revalidateItemTagPaths(): void {
  revalidateItemPriorityAffectedPaths();
  revalidatePath("/topics/[id]", "page");
  revalidatePath("/meetings/[id]", "page");
}

export async function addItemTagAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const tag = String(formData.get("tag") ?? "").trim();
  if (!tag || tag.length > MAX_TAG_LENGTH) return;

  await addItemTag(itemId, tag);
  revalidateItemTagPaths();
}

export async function removeItemTagAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const tag = String(formData.get("tag") ?? "");
  if (!tag) return;

  await removeItemTag(itemId, tag);
  revalidateItemTagPaths();
}

const ITEM_TYPES: ItemType[] = ["IDEA", "QUESTION", "DECISION", "ACTION"];

export async function createItemAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const topicPath = `/topics/${encodeURIComponent(topicId)}`;
  const type = String(formData.get("type") ?? "") as ItemType;
  const description = String(formData.get("description") ?? "").trim();
  const owner = String(formData.get("owner") ?? "").trim() || null;
  const dueDate = String(formData.get("dueDate") ?? "").trim() || null;
  if (!ITEM_TYPES.includes(type)) redirect(`${topicPath}?error=${encodeURIComponent("Invalid item type")}`);
  if (!description) redirect(`${topicPath}?error=${encodeURIComponent("Description is required")}`);

  try {
    await createItem(topicId, { type, description, owner, dueDate });
  } catch (err) {
    redirect(`${topicPath}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidateItemMutationPaths(topicId);
  redirect(topicPath);
}

function revalidateItemMutationPaths(topicId: string): void {
  revalidateItemPriorityAffectedPaths();
  revalidatePath(`/topics/${topicId}`);
  revalidatePath("/briefing");
  revalidatePath("/graph");
  revalidatePath("/meetings");
}

export async function updateItemAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const topicId = String(formData.get("topicId") ?? "");
  const topicPath = `/topics/${encodeURIComponent(topicId)}`;
  const description = String(formData.get("description") ?? "").trim();
  if (!description) redirect(`${topicPath}?error=${encodeURIComponent("Description is required")}`);

  // blank owner/due date/rationale clear the field; type is only sent for manual items
  const patch: ItemPatch = {
    description,
    owner: String(formData.get("owner") ?? "").trim() || null,
    dueDate: String(formData.get("dueDate") ?? "").trim() || null,
    rationale: String(formData.get("rationale") ?? "").trim() || null,
  };
  const type = formData.get("type");
  if (type !== null) {
    if (!ITEM_TYPES.includes(String(type) as ItemType)) {
      redirect(`${topicPath}?error=${encodeURIComponent("Invalid item type")}`);
    }
    patch.type = String(type) as ItemType;
  }

  try {
    await updateItem(itemId, patch);
  } catch (err) {
    redirect(`${topicPath}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidateItemMutationPaths(topicId);
  redirect(topicPath);
}

export async function deleteItemAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const topicId = String(formData.get("topicId") ?? "");
  const topicPath = `/topics/${encodeURIComponent(topicId)}`;

  try {
    await deleteItem(itemId);
  } catch (err) {
    redirect(`${topicPath}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidateItemMutationPaths(topicId);
  redirect(topicPath);
}

export async function deleteTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const noteId = String(formData.get("noteId") ?? "");

  try {
    await deleteTopicNote(topicId, noteId);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}

export async function updateItemNoteAction(formData: FormData): Promise<void> {
  const itemId = String(formData.get("itemId") ?? "");
  const noteId = String(formData.get("noteId") ?? "");
  const body = String(formData.get("body") ?? "").trim();
  if (!body) return;

  await updateItemNote(itemId, noteId, body);
  revalidateItemPriorityAffectedPaths();
}

export async function updateTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = String(formData.get("topicId") ?? "");
  const noteId = String(formData.get("noteId") ?? "");
  const body = String(formData.get("body") ?? "").trim();
  if (!body) redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent("Note cannot be empty")}`);

  try {
    await updateTopicNote(topicId, noteId, body);
  } catch (err) {
    redirect(`/topics/${encodeURIComponent(topicId)}?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
  revalidatePath(`/topics/${topicId}`);
  redirect(`/topics/${encodeURIComponent(topicId)}`);
}
