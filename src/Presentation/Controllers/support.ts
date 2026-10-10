// Shared plumbing for the server-action controllers. Not a "use server" module: nothing here is callable from
// the browser.
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { errorMessage } from "@/Application/Errors";

/** A form field as the person typed it ("" when the form did not send it). */
export function field(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "");
}

export function topicPath(topicId: string): string {
  return `/topics/${encodeURIComponent(topicId)}`;
}

/** Sends the person back to `path` with the failure shown in its error banner. Never returns. */
export function redirectWithError(path: string, error: unknown): never {
  redirect(`${path}?error=${encodeURIComponent(errorMessage(error))}`);
}

export function revalidate(...paths: string[]): void {
  for (const path of paths) revalidatePath(path);
}

// KnowledgeCard renders on many pages with no single "return to" route, so item actions don't redirect -
// revalidating lets Next re-render whichever page the form was submitted from.
export const ITEM_PAGES = ["/items", "/actions", "/questions", "/decisions", "/ask", "/dashboard", "/topics"];

export function revalidateItemPages(): void {
  revalidate(...ITEM_PAGES);
}

export function revalidateTopicPriorityPages(topicId: string): void {
  revalidate("/topics", `/topics/${topicId}`, "/dashboard", "/briefing", "/graph");
}

export function revalidateAfterItemChange(topicId: string): void {
  revalidateItemPages();
  revalidate(`/topics/${topicId}`, "/briefing", "/graph", "/meetings");
}

export function revalidateReviewPages(): void {
  revalidate("/review", "/dashboard", "/items", "/topics", "/meetings");
}
