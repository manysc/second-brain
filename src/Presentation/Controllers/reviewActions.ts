"use server";

import { revalidatePath } from "next/cache";
import type { IngestResult } from "@/Application/DTOs/Knowledge";
import { errorMessage } from "@/Application/Errors";
import type { ReviewDecision } from "@/Domain";
import { useCases } from "@/composition";
import { revalidate, revalidateReviewPages } from "./support";

// These return instead of redirecting, so the review components can hide what was just decided optimistically
// (and restore it with the error) instead of waiting for a full page re-render.

// topicId (accept only): "" = Uncategorized.
export async function decideReviewCandidateAction(
  candidateId: string,
  status: ReviewDecision,
  topicId?: string,
): Promise<{ error?: string }> {
  try {
    await useCases.decideReviewCandidate(candidateId, status, topicId);
  } catch (error) {
    return { error: errorMessage(error) };
  }
  revalidateReviewPages();
  return {};
}

// existingTopicId wins over topicName; topicName null = the suggested name.
export async function acceptTopicProposalAction(
  suggestedName: string,
  topicName: string | null,
  existingTopicId: string | null,
): Promise<{ error?: string }> {
  try {
    await useCases.acceptTopicProposal(suggestedName, topicName, existingTopicId);
  } catch (error) {
    return { error: errorMessage(error) };
  }
  revalidateReviewPages();
  return {};
}

export async function rejectTopicProposalAction(suggestedName: string): Promise<{ error?: string }> {
  try {
    await useCases.rejectTopicProposal(suggestedName);
  } catch (error) {
    return { error: errorMessage(error) };
  }
  revalidateReviewPages();
  return {};
}

// Ingestion can add meetings, items, review candidates and topic proposals, and recalculates priorities, so
// most pages go stale.
export async function ingestMeetingsAction(): Promise<{ error?: string; result?: IngestResult }> {
  let result: IngestResult;
  try {
    result = await useCases.ingestMeetings();
  } catch (error) {
    return { error: errorMessage(error) };
  }
  revalidate(
    "/meetings", "/dashboard", "/items", "/actions", "/questions", "/decisions", "/topics", "/review", "/briefing",
    "/graph",
  );
  revalidatePath("/meetings/[id]", "page");
  revalidatePath("/topics/[id]", "page");
  return { result };
}
