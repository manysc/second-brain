// @vitest-environment node
// Presentation plumbing that is not a component: wording helpers, the page-level 404 translation, and the
// controllers checked against stubbed use cases (the full stack is covered in server-actions.test.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { revalidatePath } from "next/cache";
import { notFound } from "next/navigation";
import { NotFoundError, ValidationError } from "@/Application/Errors";

const useCases = vi.hoisted(() => ({
  getAskSession: vi.fn(),
  deleteAskSession: vi.fn(),
  loadTopicImage: vi.fn(),
  addItemTag: vi.fn(),
  fileItemsUnderNewTopic: vi.fn(),
  fileSuggestedItems: vi.fn(),
  createTopic: vi.fn(),
}));
vi.mock("@/composition", () => ({ useCases }));

import { deleteAskSession, getAskSession } from "@/Presentation/Controllers/askController";
import { addItemTagAction, createTopicAndMoveItemsAction, moveSuggestedItemsAction } from "@/Presentation/Controllers/itemActions";
import { field, redirectWithError, topicPath } from "@/Presentation/Controllers/support";
import { createTopicAction } from "@/Presentation/Controllers/topicActions";
import { getTopicImage } from "@/Presentation/Controllers/topicImageController";
import { formatNoteDate, percent, plural, timeAgo } from "@/Presentation/format";
import { orNotFound } from "@/Presentation/pageSupport";
import { form, redirectOf } from "./support/backend";

const revalidated = () => vi.mocked(revalidatePath).mock.calls.map((args) => args.join("|"));
const params = <T,>(value: T) => ({ params: Promise.resolve(value) });

beforeEach(() => vi.mocked(revalidatePath).mockClear());
afterEach(() => vi.useRealTimers());

describe("wording helpers", () => {
  it("formats scores, counts, ages and note dates", () => {
    expect(percent(0.456)).toBe(46);
    expect(plural(1, "item")).toBe("1 item");
    expect(plural(0, "item")).toBe("0 items");
    expect(formatNoteDate("2026-03-04T10:11:12Z")).toBe("2026-03-04");
    expect(formatNoteDate("yesterday")).toBe("yesterday");
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-09T12:00:00Z"));
    expect(timeAgo(Date.now() - 59 * 60_000)).toBe("59m ago");
    expect(timeAgo(Date.now() - 23 * 3_600_000)).toBe("23h ago");
  });
});

describe("orNotFound", () => {
  it("returns what loaded", async () => {
    await expect(orNotFound(Promise.resolve("topic"))).resolves.toBe("topic");
    expect(notFound).not.toHaveBeenCalled();
  });

  it("turns NotFoundError into the 404 page and lets other failures surface", async () => {
    await expect(orNotFound(Promise.reject(new NotFoundError("Topic not found")))).rejects.toMatchObject({ notFound: true });
    expect(notFound).toHaveBeenCalledOnce();
    await expect(orNotFound(Promise.reject(new Error("Backend request failed")))).rejects.toThrow("Backend request failed");
    expect(notFound).toHaveBeenCalledOnce();
  });
});

describe("controller support", () => {
  it("reads form fields as text and builds topic paths", () => {
    expect(field(form({ name: " x " }), "name")).toBe(" x ");
    expect(field(form({}), "name")).toBe("");
    expect(topicPath("a b/c")).toBe("/topics/a%20b%2Fc");
  });

  it("redirects with the failure message, or a fallback for a non-error", async () => {
    expect(await redirectOf(async () => redirectWithError("/topics", new Error("Name taken & used")))).toBe(
      "/topics?error=Name%20taken%20%26%20used",
    );
    expect(await redirectOf(async () => redirectWithError("/topics", "boom"))).toBe("/topics?error=Something%20went%20wrong");
  });
});

describe("controllers over use cases", () => {
  it("shows a use-case validation error on the page the form came from", async () => {
    useCases.createTopic.mockRejectedValue(new ValidationError("Topic name is required"));
    expect(await redirectOf(() => createTopicAction(form({ name: " " })))).toBe("/topics?error=Topic%20name%20is%20required");
    expect(useCases.createTopic).toHaveBeenCalledWith(" ");
    expect(revalidated()).toEqual([]);
  });

  it("ignores invalid input where the form has nowhere to show it, but not real failures", async () => {
    useCases.addItemTag.mockRejectedValue(new ValidationError("Tag cannot be empty"));
    await expect(addItemTagAction(form({ itemId: "i1", tag: "" }))).resolves.toBeUndefined();
    expect(revalidated()).toEqual([]);

    useCases.addItemTag.mockRejectedValue(new Error("Backend request failed"));
    await expect(addItemTagAction(form({ itemId: "i1", tag: "x" }))).rejects.toThrow("Backend request failed");
  });

  it("maps each filing outcome to what the suggestions panel expects", async () => {
    const run = () => createTopicAndMoveItemsAction("Pricing", ["a"], "/topics/unc");
    useCases.fileItemsUnderNewTopic.mockResolvedValue({ status: "invalid", error: "Topic name is required" });
    expect(await run()).toEqual({ error: "Topic name is required" });
    useCases.fileItemsUnderNewTopic.mockResolvedValue({ status: "nothing_to_file" });
    expect(await run()).toEqual({});
    useCases.fileItemsUnderNewTopic.mockResolvedValue({ status: "topic_not_created", error: "Topic name already exists" });
    expect(await run()).toEqual({ error: "Topic name already exists" });
    expect(revalidated()).toEqual([]);

    useCases.fileItemsUnderNewTopic.mockResolvedValue({ status: "items_not_moved", error: "could not move", topicId: "new" });
    expect(await run()).toEqual({ error: "could not move", topicId: "new" });
    expect(revalidated()).toEqual(["/topics"]);

    vi.mocked(revalidatePath).mockClear();
    useCases.fileItemsUnderNewTopic.mockResolvedValue({ status: "filed", topicId: "new" });
    expect(await run()).toEqual({ topicId: "new" });
    expect(revalidated()).toEqual(["/topics", "/topics/unc", "/topics/new"]);
  });

  it("revalidates only the topics that actually received items", async () => {
    useCases.fileSuggestedItems.mockResolvedValue({ error: "Topic not found", failedItemIds: ["a"], movedTopicIds: ["t2"] });
    expect(await moveSuggestedItemsAction([], "/topics/unc")).toEqual({ error: "Topic not found", failedItemIds: ["a"] });
    expect(revalidated()).toEqual(["/topics", "/topics/unc", "/topics/t2"]);

    vi.mocked(revalidatePath).mockClear();
    useCases.fileSuggestedItems.mockResolvedValue({ error: "down", failedItemIds: ["a"], movedTopicIds: [] });
    await moveSuggestedItemsAction([], "/topics/unc");
    expect(revalidated()).toEqual([]);
  });

  it("answers 404 for a conversation the use case does not know and 500 for other failures", async () => {
    useCases.getAskSession.mockRejectedValue(new NotFoundError("Conversation not found."));
    const missing = await getAskSession(new Request("http://x"), params({ id: "s1" }));
    expect(missing.status).toBe(404);
    expect(await missing.json()).toEqual({ error: "Conversation not found." });

    useCases.deleteAskSession.mockRejectedValue("disk on fire");
    const failed = await deleteAskSession(new Request("http://x"), params({ id: "s1" }));
    expect(failed.status).toBe(500);
    expect(await failed.json()).toEqual({ error: "Could not delete conversation." });
  });

  it("serves a topic image from whatever the use case loaded", async () => {
    useCases.loadTopicImage.mockResolvedValue({ kind: "ok", body: null, contentType: null });
    const served = await getTopicImage(new Request("http://x"), params({ id: "t1", imageId: "img" }));
    expect(served.headers.get("Content-Type")).toBe("application/octet-stream");
    expect(useCases.loadTopicImage).toHaveBeenCalledWith("t1", "img");

    useCases.loadTopicImage.mockResolvedValue({ kind: "missing" });
    expect((await getTopicImage(new Request("http://x"), params({ id: "t1", imageId: "img" }))).status).toBe(404);
  });
});
