"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  acceptTopicProposal,
  createTopic,
  deleteTopic,
  mergeTopics,
  moveItemsTopic,
  moveItemTopic,
  recalculateTopicPriority,
  rejectTopicProposal,
  setItemPriorityOverride,
  setTopicPriorityOverride,
  updateReviewStatus,
  updateTopic,
} from "./api";
import type { TopicPriorityLevel } from "./domain";

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
