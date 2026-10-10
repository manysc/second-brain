// @vitest-environment node
// Characterizes every server action end to end at the network boundary: FormData parsing -> backend request ->
// cache revalidation -> redirect / return value. The refactor moves these into Presentation controllers backed by
// use cases; only the import below may change.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { revalidatePath } from "next/cache";
import * as actions from "@/lib/actions";
import { fakeBackend, form, redirectOf } from "./support/backend";

const revalidated = () => vi.mocked(revalidatePath).mock.calls.map((args) => args.join("|"));
const ok = { json: {} };

beforeEach(() => {
  vi.mocked(revalidatePath).mockClear();
});

describe("topic actions", () => {
  it("createTopicAction creates, revalidates and returns to /topics", async () => {
    const backend = fakeBackend({ "POST /api/topics": { status: 201, json: { id: "t1" } } });
    expect(await redirectOf(() => actions.createTopicAction(form({ name: "  Roadmap " })))).toBe("/topics");
    expect(backend.last().body).toEqual({ name: "Roadmap" });
    expect(revalidated()).toEqual(["/topics"]);
  });

  it("createTopicAction rejects a blank name without calling the backend", async () => {
    const backend = fakeBackend();
    expect(await redirectOf(() => actions.createTopicAction(form({ name: "  " })))).toBe(
      "/topics?error=Topic%20name%20is%20required",
    );
    expect(backend.calls).toHaveLength(0);
  });

  it("createTopicAction reports backend errors on /topics", async () => {
    fakeBackend({ "POST /api/topics": { status: 409, json: { detail: "Topic name already exists" } } });
    expect(await redirectOf(() => actions.createTopicAction(form({ name: "Dup" })))).toBe(
      "/topics?error=Topic%20name%20already%20exists",
    );
    expect(revalidated()).toEqual([]);
  });

  it("updateTopicAction renames and returns to the topic", async () => {
    const backend = fakeBackend({ "PATCH /api/topics/a%20b": ok });
    expect(await redirectOf(() => actions.updateTopicAction(form({ topicId: "a b", name: " New " })))).toBe("/topics/a%20b");
    expect(backend.last()).toMatchObject({ path: "/api/topics/a%20b", body: { name: "New" } });
    expect(revalidated()).toEqual(["/topics", "/topics/a b"]);
  });

  it("updateTopicAction requires a name", async () => {
    fakeBackend();
    expect(await redirectOf(() => actions.updateTopicAction(form({ topicId: "t1", name: "" })))).toBe(
      "/topics/t1?error=Topic%20name%20is%20required",
    );
  });

  it("deleteTopicAction deletes and returns to /topics, or reports the conflict on the topic page", async () => {
    fakeBackend({ "DELETE /api/topics/t1": { status: 204 } });
    expect(await redirectOf(() => actions.deleteTopicAction(form({ topicId: "t1" })))).toBe("/topics");
    expect(revalidated()).toEqual(["/topics"]);

    fakeBackend({ "DELETE /api/topics/t1": { status: 409, json: { detail: "Topic still has 2 items" } } });
    expect(await redirectOf(() => actions.deleteTopicAction(form({ topicId: "t1" })))).toBe(
      "/topics/t1?error=Topic%20still%20has%202%20items",
    );
  });

  it("mergeTopicsAction merges and revalidates without redirecting", async () => {
    const backend = fakeBackend({ "POST /api/topics/s/merge": ok });
    await expect(actions.mergeTopicsAction("s", "t")).resolves.toBeUndefined();
    expect(backend.last().body).toEqual({ targetTopicId: "t" });
    expect(revalidated()).toEqual(["/topics"]);

    fakeBackend({ "POST /api/topics/s/merge": { status: 400, json: { detail: "Cannot merge a topic into itself" } } });
    expect(await redirectOf(() => actions.mergeTopicsAction("s", "s"))).toBe(
      "/topics?error=Cannot%20merge%20a%20topic%20into%20itself",
    );
  });

  it("setTopicStatusAction updates and returns to the topic", async () => {
    const backend = fakeBackend({ "PATCH /api/topics/t1/status": ok });
    expect(await redirectOf(() => actions.setTopicStatusAction(form({ topicId: "t1", status: "Closed" })))).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ status: "Closed" });
    expect(revalidated()).toEqual(["/topics", "/topics/t1", "/dashboard", "/briefing", "/graph"]);
  });
});

describe("item filing actions", () => {
  it("moveItemTopicAction moves to a topic or to Unassigned", async () => {
    const backend = fakeBackend({ "PATCH /api/items/i1/topic": ok });
    expect(
      await redirectOf(() => actions.moveItemTopicAction(form({ itemId: "i1", currentTopicId: "t0", topicId: "t2" }))),
    ).toBe("/topics/t0");
    expect(backend.last().body).toEqual({ topicId: "t2" });
    expect(revalidated()).toEqual(["/topics", "/topics/t0", "/topics/t2"]);

    vi.mocked(revalidatePath).mockClear();
    await redirectOf(() => actions.moveItemTopicAction(form({ itemId: "i1", currentTopicId: "t0", topicId: "" })));
    expect(backend.last().body).toEqual({ topicId: null });
    expect(revalidated()).toEqual(["/topics", "/topics/t0"]);
  });

  it("moveItemsTopicAction ignores an empty selection", async () => {
    const backend = fakeBackend();
    await expect(actions.moveItemsTopicAction([], "t", "/items")).resolves.toBeUndefined();
    expect(backend.calls).toHaveLength(0);
  });

  it("moveItemsTopicAction moves the batch and returns to the caller's page", async () => {
    const backend = fakeBackend({ "PATCH /api/items/topic": ok });
    expect(await redirectOf(() => actions.moveItemsTopicAction(["a", "b"], "t9", "/items"))).toBe("/items");
    expect(backend.last().body).toEqual({ itemIds: ["a", "b"], topicId: "t9" });
    expect(revalidated()).toEqual(["/items", "/topics", "/items", "/topics/t9"]);

    fakeBackend({ "PATCH /api/items/topic": { status: 404, json: { detail: "Topic not found" } } });
    expect(await redirectOf(() => actions.moveItemsTopicAction(["a"], null, "/items"))).toBe("/items?error=Topic%20not%20found");
  });

  it("moveSuggestedItemsAction files every batch and reports failed items without throwing", async () => {
    const backend = fakeBackend({
      "PATCH /api/items/topic": (call) =>
        (call.body as { topicId: string }).topicId === "bad" ? { status: 404, json: { detail: "Topic not found" } } : ok,
    });
    const result = await actions.moveSuggestedItemsAction(
      [
        { itemIds: ["a"], topicId: "t1" },
        { itemIds: [], topicId: "t2" },
        { itemIds: ["b", "c"], topicId: "bad" },
      ],
      "/topics/unc",
    );
    expect(result).toEqual({ error: "Topic not found", failedItemIds: ["b", "c"] });
    expect(backend.calls).toHaveLength(2);
    expect(revalidated()).toEqual(["/topics", "/topics/unc", "/topics/t1"]);
  });

  it("moveSuggestedItemsAction returns {} when everything moved", async () => {
    fakeBackend({ "PATCH /api/items/topic": ok });
    await expect(actions.moveSuggestedItemsAction([{ itemIds: ["a"], topicId: "t1" }], "/r")).resolves.toEqual({});
  });

  it("createTopicAndMoveItemsAction creates the topic, then files the items", async () => {
    const backend = fakeBackend({ "POST /api/topics": { status: 201, json: { id: "new" } }, "PATCH /api/items/topic": ok });
    await expect(actions.createTopicAndMoveItemsAction(" Fresh ", ["a"], "/r")).resolves.toEqual({ topicId: "new" });
    expect(backend.calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["POST", "/api/topics", { name: "Fresh" }],
      ["PATCH", "/api/items/topic", { itemIds: ["a"], topicId: "new" }],
    ]);
    expect(revalidated()).toEqual(["/topics", "/r", "/topics/new"]);
  });

  it("createTopicAndMoveItemsAction validates and reports partial failure", async () => {
    fakeBackend();
    await expect(actions.createTopicAndMoveItemsAction("  ", ["a"], "/r")).resolves.toEqual({ error: "Topic name is required" });
    await expect(actions.createTopicAndMoveItemsAction("x", [], "/r")).resolves.toEqual({});

    fakeBackend({ "POST /api/topics": { status: 409, json: { detail: "Topic name already exists" } } });
    await expect(actions.createTopicAndMoveItemsAction("x", ["a"], "/r")).resolves.toEqual({ error: "Topic name already exists" });

    fakeBackend({
      "POST /api/topics": { status: 201, json: { id: "new" } },
      "PATCH /api/items/topic": { status: 500, json: { detail: "boom" } },
    });
    await expect(actions.createTopicAndMoveItemsAction("x", ["a"], "/r")).resolves.toEqual({
      error: 'Created "x" but could not move the items: boom',
      topicId: "new",
    });
  });
});

describe("review and ingestion actions", () => {
  const reviewPaths = ["/review", "/dashboard", "/items", "/topics", "/meetings"];

  it("decideReviewCandidateAction sends the topic only when accepting", async () => {
    const backend = fakeBackend({ "PATCH /api/review/c1": ok });
    await expect(actions.decideReviewCandidateAction("c1", "ACCEPTED", "")).resolves.toEqual({});
    expect(backend.last().body).toEqual({ status: "ACCEPTED", topicId: "" });
    await actions.decideReviewCandidateAction("c1", "REJECTED", "t1");
    expect(backend.last().body).toEqual({ status: "REJECTED" });
    expect(revalidated()).toEqual([...reviewPaths, ...reviewPaths]);
  });

  it("decideReviewCandidateAction returns the error instead of throwing", async () => {
    fakeBackend({ "PATCH /api/review/c1": { status: 409, json: { detail: "Review candidate already decided" } } });
    await expect(actions.decideReviewCandidateAction("c1", "ACCEPTED")).resolves.toEqual({
      error: "Review candidate already decided",
    });
    expect(revalidated()).toEqual([]);
  });

  it("topic proposal actions accept/reject and revalidate the review pages", async () => {
    const backend = fakeBackend({
      "POST /api/review/topic-proposals/accept": { json: [] },
      "POST /api/review/topic-proposals/reject": { status: 204 },
    });
    await expect(actions.acceptTopicProposalAction("Infra", "Infrastructure", null)).resolves.toEqual({});
    expect(backend.last().body).toEqual({ suggestedName: "Infra", topicName: "Infrastructure", existingTopicId: null });
    await expect(actions.rejectTopicProposalAction("Infra")).resolves.toEqual({});
    expect(backend.last().body).toEqual({ suggestedName: "Infra" });
    expect(revalidated()).toEqual([...reviewPaths, ...reviewPaths]);

    fakeBackend({ "POST /api/review/topic-proposals/reject": { status: 404, json: { detail: "No pending proposal" } } });
    await expect(actions.rejectTopicProposalAction("x")).resolves.toEqual({ error: "No pending proposal" });
  });

  it("ingestMeetingsAction returns the summary and revalidates every data page", async () => {
    const summary = { meetings: 3, new: 1, updated: 1, unchanged: 1 };
    fakeBackend({ "POST /api/ingest": { json: summary } });
    await expect(actions.ingestMeetingsAction()).resolves.toEqual({ result: summary });
    expect(revalidated()).toEqual([
      "/meetings", "/dashboard", "/items", "/actions", "/questions", "/decisions", "/topics", "/review", "/briefing",
      "/graph", "/meetings/[id]|page", "/topics/[id]|page",
    ]);

    fakeBackend({ "POST /api/ingest": { status: 409, json: { detail: "Ingestion is already running" } } });
    await expect(actions.ingestMeetingsAction()).resolves.toEqual({ error: "Ingestion is already running" });
  });
});

describe("priority actions", () => {
  const topicPriorityPaths = ["/topics", "/topics/t1", "/dashboard", "/briefing", "/graph"];
  const itemPaths = ["/items", "/actions", "/questions", "/decisions", "/ask", "/dashboard", "/topics"];

  it("setPriorityOverrideAction sends level and trimmed reason; blanks become null", async () => {
    const backend = fakeBackend({ "PATCH /api/topics/t1/priority-override": ok });
    expect(
      await redirectOf(() => actions.setPriorityOverrideAction(form({ topicId: "t1", priority: "CRITICAL", reason: " exec ask " }))),
    ).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ priority: "CRITICAL", reason: "exec ask" });
    await redirectOf(() => actions.setPriorityOverrideAction(form({ topicId: "t1", priority: "", reason: " " })));
    expect(backend.last().body).toEqual({ priority: null, reason: null });
    expect(revalidated()).toEqual([...topicPriorityPaths, ...topicPriorityPaths]);
  });

  it("clearPriorityOverrideAction and recalculatePriorityAction return to the topic", async () => {
    const backend = fakeBackend({ "PATCH /api/topics/t1/priority-override": ok, "POST /api/topics/t1/recalculate-priority": ok });
    expect(await redirectOf(() => actions.clearPriorityOverrideAction(form({ topicId: "t1" })))).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ priority: null, reason: null });
    expect(await redirectOf(() => actions.recalculatePriorityAction(form({ topicId: "t1" })))).toBe("/topics/t1");
    expect(backend.last().path).toBe("/api/topics/t1/recalculate-priority");

    fakeBackend({ "POST /api/topics/t1/recalculate-priority": { status: 404, json: { detail: "Topic not found" } } });
    expect(await redirectOf(() => actions.recalculatePriorityAction(form({ topicId: "t1" })))).toBe(
      "/topics/t1?error=Topic%20not%20found",
    );
  });

  it("item priority and status actions revalidate the item pages without redirecting", async () => {
    const backend = fakeBackend({ "PATCH /api/items/i1/priority-override": ok, "PATCH /api/items/i1/status": ok });
    await actions.setItemPriorityOverrideAction(form({ itemId: "i1", priority: "MINOR", reason: "" }));
    expect(backend.last().body).toEqual({ priority: "MINOR", reason: null });
    await actions.clearItemPriorityOverrideAction(form({ itemId: "i1" }));
    expect(backend.last().body).toEqual({ priority: null, reason: null });
    await actions.setItemStatusAction(form({ itemId: "i1", status: "Closed" }));
    expect(backend.last().body).toEqual({ status: "Closed" });
    expect(revalidated()).toEqual([...itemPaths, ...itemPaths, ...itemPaths, "/briefing"]);
  });

  it("item actions without a redirect let backend failures propagate", async () => {
    fakeBackend({ "PATCH /api/items/i1/status": { status: 404, json: { detail: "Item not found" } } });
    await expect(actions.setItemStatusAction(form({ itemId: "i1", status: "Open" }))).rejects.toThrow("Item not found");
  });
});

describe("note actions", () => {
  const itemPaths = ["/items", "/actions", "/questions", "/decisions", "/ask", "/dashboard", "/topics"];

  it("item note actions add, edit and delete; blank bodies are ignored", async () => {
    const backend = fakeBackend({
      "POST /api/items/i1/notes": ok,
      "PATCH /api/items/i1/notes/n1": ok,
      "DELETE /api/items/i1/notes/n1": ok,
    });
    await actions.addItemNoteAction(form({ itemId: "i1", body: "  " }));
    await actions.updateItemNoteAction(form({ itemId: "i1", noteId: "n1", body: "" }));
    expect(backend.calls).toHaveLength(0);

    await actions.addItemNoteAction(form({ itemId: "i1", body: " hello " }));
    expect(backend.last().body).toEqual({ body: "hello" });
    await actions.updateItemNoteAction(form({ itemId: "i1", noteId: "n1", body: "edited" }));
    expect(backend.last().body).toEqual({ body: "edited" });
    await actions.deleteItemNoteAction(form({ itemId: "i1", noteId: "n1" }));
    expect(backend.last().method).toBe("DELETE");
    expect(revalidated()).toEqual([...itemPaths, ...itemPaths, ...itemPaths]);
  });

  it("topic note actions validate, call the backend and return to the topic", async () => {
    const backend = fakeBackend({
      "POST /api/topics/t1/notes": ok,
      "PATCH /api/topics/t1/notes/n1": ok,
      "DELETE /api/topics/t1/notes/n1": ok,
    });
    expect(await redirectOf(() => actions.addTopicNoteAction(form({ topicId: "t1", body: " " })))).toBe(
      "/topics/t1?error=Note%20cannot%20be%20empty",
    );
    expect(await redirectOf(() => actions.updateTopicNoteAction(form({ topicId: "t1", noteId: "n1", body: "" })))).toBe(
      "/topics/t1?error=Note%20cannot%20be%20empty",
    );
    expect(backend.calls).toHaveLength(0);

    expect(await redirectOf(() => actions.addTopicNoteAction(form({ topicId: "t1", body: " hi " })))).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ body: "hi" });
    expect(await redirectOf(() => actions.updateTopicNoteAction(form({ topicId: "t1", noteId: "n1", body: "x" })))).toBe("/topics/t1");
    expect(await redirectOf(() => actions.deleteTopicNoteAction(form({ topicId: "t1", noteId: "n1" })))).toBe("/topics/t1");
    expect(revalidated()).toEqual(["/topics", "/topics/t1", "/topics", "/topics/t1", "/topics", "/topics/t1"]);
  });
});

describe("tag actions", () => {
  const itemTagPaths = [
    "/items", "/actions", "/questions", "/decisions", "/ask", "/dashboard", "/topics", "/topics/[id]|page", "/meetings/[id]|page",
  ];

  it("addTopicTagAction validates length and emptiness before calling the backend", async () => {
    const backend = fakeBackend({ "POST /api/topics/t1/tags": ok });
    expect(await redirectOf(() => actions.addTopicTagAction(form({ topicId: "t1", tag: " " })))).toBe(
      "/topics/t1?error=Tag%20cannot%20be%20empty",
    );
    expect(await redirectOf(() => actions.addTopicTagAction(form({ topicId: "t1", tag: "x".repeat(41) })))).toBe(
      "/topics/t1?error=Tag%20cannot%20be%20longer%20than%2040%20characters",
    );
    expect(backend.calls).toHaveLength(0);
    expect(await redirectOf(() => actions.addTopicTagAction(form({ topicId: "t1", tag: " infra " })))).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ tag: "infra" });
    expect(revalidated()).toEqual(["/topics", "/topics/t1"]);
  });

  it("addTopicTagAction reports the tag limit from the backend", async () => {
    fakeBackend({ "POST /api/topics/t1/tags": { status: 400, json: { detail: "A topic can have at most 20 tags" } } });
    expect(await redirectOf(() => actions.addTopicTagAction(form({ topicId: "t1", tag: "x" })))).toBe(
      "/topics/t1?error=A%20topic%20can%20have%20at%20most%2020%20tags",
    );
  });

  it("removeTopicTagAction removes by query string", async () => {
    const backend = fakeBackend({ "DELETE /api/topics/t1/tags": ok });
    expect(await redirectOf(() => actions.removeTopicTagAction(form({ topicId: "t1", tag: "a b" })))).toBe("/topics/t1");
    expect(backend.last().path).toBe("/api/topics/t1/tags?tag=a%20b");
  });

  it("item tag actions skip invalid tags and revalidate the item pages", async () => {
    const backend = fakeBackend({ "POST /api/items/i1/tags": ok, "DELETE /api/items/i1/tags": ok });
    await actions.addItemTagAction(form({ itemId: "i1", tag: " " }));
    await actions.addItemTagAction(form({ itemId: "i1", tag: "y".repeat(41) }));
    await actions.removeItemTagAction(form({ itemId: "i1", tag: "" }));
    expect(backend.calls).toHaveLength(0);

    await actions.addItemTagAction(form({ itemId: "i1", tag: " q3 " }));
    expect(backend.last().body).toEqual({ tag: "q3" });
    await actions.removeItemTagAction(form({ itemId: "i1", tag: "q3" }));
    expect(backend.last().path).toBe("/api/items/i1/tags?tag=q3");
    expect(revalidated()).toEqual([...itemTagPaths, ...itemTagPaths]);
  });
});

describe("item CRUD actions", () => {
  const mutationPaths = [
    "/items", "/actions", "/questions", "/decisions", "/ask", "/dashboard", "/topics", "/topics/t1", "/briefing", "/graph",
    "/meetings",
  ];

  it("createItemAction validates type and description, blanks become null", async () => {
    const backend = fakeBackend({ "POST /api/topics/t1/items": { status: 201, json: {} } });
    expect(await redirectOf(() => actions.createItemAction(form({ topicId: "t1", type: "TASK", description: "d" })))).toBe(
      "/topics/t1?error=Invalid%20item%20type",
    );
    expect(await redirectOf(() => actions.createItemAction(form({ topicId: "t1", type: "IDEA", description: " " })))).toBe(
      "/topics/t1?error=Description%20is%20required",
    );
    expect(backend.calls).toHaveLength(0);

    expect(
      await redirectOf(() =>
        actions.createItemAction(form({ topicId: "t1", type: "ACTION", description: " Ship it ", owner: " ", dueDate: "2026-11-01" })),
      ),
    ).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ type: "ACTION", description: "Ship it", owner: null, dueDate: "2026-11-01" });
    expect(revalidated()).toEqual(mutationPaths);
  });

  it("updateItemAction clears blank fields and only sends type when the form has one", async () => {
    const backend = fakeBackend({ "PATCH /api/items/i1": ok });
    expect(
      await redirectOf(() =>
        actions.updateItemAction(form({ itemId: "i1", topicId: "t1", description: " d ", owner: "Ana", dueDate: "", rationale: " " })),
      ),
    ).toBe("/topics/t1");
    expect(backend.last().body).toEqual({ description: "d", owner: "Ana", dueDate: null, rationale: null });

    await redirectOf(() => actions.updateItemAction(form({ itemId: "i1", topicId: "t1", description: "d", type: "QUESTION" })));
    expect(backend.last().body).toMatchObject({ type: "QUESTION" });

    expect(
      await redirectOf(() => actions.updateItemAction(form({ itemId: "i1", topicId: "t1", description: "d", type: "BOGUS" }))),
    ).toBe("/topics/t1?error=Invalid%20item%20type");
    expect(await redirectOf(() => actions.updateItemAction(form({ itemId: "i1", topicId: "t1", description: "" })))).toBe(
      "/topics/t1?error=Description%20is%20required",
    );
  });

  it("updateItemAction reports a non-editable item", async () => {
    fakeBackend({ "PATCH /api/items/i1": { status: 400, json: { detail: "Only manually added items can change type" } } });
    expect(
      await redirectOf(() => actions.updateItemAction(form({ itemId: "i1", topicId: "t1", description: "d", type: "IDEA" }))),
    ).toBe("/topics/t1?error=Only%20manually%20added%20items%20can%20change%20type");
  });

  it("deleteItemAction deletes and returns to the topic", async () => {
    const backend = fakeBackend({ "DELETE /api/items/i1": { status: 204 } });
    expect(await redirectOf(() => actions.deleteItemAction(form({ itemId: "i1", topicId: "t1" })))).toBe("/topics/t1");
    expect(backend.last().method).toBe("DELETE");
    expect(revalidated()).toEqual(mutationPaths);
  });
});

describe("topic image actions", () => {
  it("addTopicImageAction requires a non-empty file, then uploads it", async () => {
    const backend = fakeBackend({ "POST /api/topics/t1/images": { json: {} } });
    expect(await redirectOf(() => actions.addTopicImageAction(form({ topicId: "t1" })))).toBe(
      "/topics/t1?error=Choose%20an%20image%20to%20upload",
    );
    expect(
      await redirectOf(() => actions.addTopicImageAction(form({ topicId: "t1", image: new File([], "empty.png") }))),
    ).toBe("/topics/t1?error=Choose%20an%20image%20to%20upload");
    expect(backend.calls).toHaveLength(0);

    const image = new File([new Uint8Array([1, 2])], "a.png", { type: "image/png" });
    expect(await redirectOf(() => actions.addTopicImageAction(form({ topicId: "t1", image })))).toBe("/topics/t1");
    expect((backend.last().body as FormData).get("file")).toBeInstanceOf(File);
    expect(revalidated()).toEqual(["/topics/t1"]);
  });

  it("addTopicImageAction reports oversized and unsupported uploads", async () => {
    fakeBackend({ "POST /api/topics/t1/images": { status: 413, json: { detail: "Image is larger than 5 MB" } } });
    const image = new File([new Uint8Array([1])], "a.png");
    expect(await redirectOf(() => actions.addTopicImageAction(form({ topicId: "t1", image })))).toBe(
      "/topics/t1?error=Image%20is%20larger%20than%205%20MB",
    );
  });

  it("deleteTopicImageAction deletes and returns to the topic", async () => {
    const backend = fakeBackend({ "DELETE /api/topics/t1/images/img": { json: {} } });
    expect(await redirectOf(() => actions.deleteTopicImageAction(form({ topicId: "t1", imageId: "img" })))).toBe("/topics/t1");
    expect(backend.last().path).toBe("/api/topics/t1/images/img");
    expect(revalidated()).toEqual(["/topics/t1"]);
  });
});
