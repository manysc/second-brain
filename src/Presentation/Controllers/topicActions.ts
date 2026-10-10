"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import type { OpenClosed } from "@/Domain";
import { useCases } from "@/composition";
import { field, redirectWithError, revalidate, revalidateTopicPriorityPages, topicPath } from "./support";

export async function createTopicAction(formData: FormData): Promise<void> {
  try {
    await useCases.createTopic(field(formData, "name"));
  } catch (error) {
    redirectWithError("/topics", error);
  }
  revalidatePath("/topics");
  redirect("/topics");
}

export async function updateTopicAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.renameTopic(topicId, field(formData, "name"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function deleteTopicAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.deleteTopic(topicId);
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidatePath("/topics");
  redirect("/topics");
}

export async function mergeTopicsAction(sourceTopicId: string, targetTopicId: string): Promise<void> {
  try {
    await useCases.mergeTopics(sourceTopicId, targetTopicId);
  } catch (error) {
    redirectWithError("/topics", error);
  }
  revalidatePath("/topics");
}

export async function setTopicStatusAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.setTopicStatus(topicId, field(formData, "status") as OpenClosed);
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateTopicPriorityPages(topicId);
  redirect(topicPath(topicId));
}

export async function addTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.addTopicNote(topicId, field(formData, "body"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function updateTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.editTopicNote(topicId, field(formData, "noteId"), field(formData, "body"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function deleteTopicNoteAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.deleteTopicNote(topicId, field(formData, "noteId"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function addTopicTagAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.addTopicTag(topicId, field(formData, "tag"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function removeTopicTagAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.removeTopicTag(topicId, field(formData, "tag"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidate("/topics", `/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function addTopicImageAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.addTopicImage(topicId, formData.get("image"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidatePath(`/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function deleteTopicImageAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.deleteTopicImage(topicId, field(formData, "imageId"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidatePath(`/topics/${topicId}`);
  redirect(topicPath(topicId));
}

export async function setPriorityOverrideAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.setTopicPriorityOverride(topicId, field(formData, "priority"), field(formData, "reason"));
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateTopicPriorityPages(topicId);
  redirect(topicPath(topicId));
}

export async function clearPriorityOverrideAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.setTopicPriorityOverride(topicId, "", "");
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateTopicPriorityPages(topicId);
  redirect(topicPath(topicId));
}

export async function recalculatePriorityAction(formData: FormData): Promise<void> {
  const topicId = field(formData, "topicId");
  try {
    await useCases.recalculateTopicPriority(topicId);
  } catch (error) {
    redirectWithError(topicPath(topicId), error);
  }
  revalidateTopicPriorityPages(topicId);
  redirect(topicPath(topicId));
}
