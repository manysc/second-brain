"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createTopic, deleteTopic, mergeTopics, moveItemTopic, updateReviewStatus, updateTopic } from "./api";

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

export async function mergeTopicsAction(sourceTopicId: string, targetTopicId: string): Promise<void> {
  try {
    await mergeTopics(sourceTopicId, targetTopicId);
  } catch (err) {
    redirect(`/topics?error=${encodeURIComponent(errorMessage(err))}`);
  }
  revalidatePath("/topics");
}

async function decideReviewCandidate(formData: FormData, status: "ACCEPTED" | "REJECTED"): Promise<void> {
  const candidateId = String(formData.get("candidateId") ?? "");

  try {
    await updateReviewStatus(candidateId, status);
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
