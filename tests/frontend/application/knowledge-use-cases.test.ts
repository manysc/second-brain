// @vitest-environment node
// The application rules for reading and changing the knowledge base, against an in-memory repository:
// no HTTP, no Next.js.
import { describe, expect, it } from "vitest";
import { ValidationError } from "@/Application/Errors";
import { itemUseCases } from "@/Application/UseCases/items";
import { knowledgeUseCases } from "@/Application/UseCases/knowledge";
import { topicUseCases } from "@/Application/UseCases/topics";
import { type Answers, fakeKnowledge } from "../support/fakeKnowledge";
import { item } from "../support/factories";

const png = new File([new Uint8Array([1])], "a.png", { type: "image/png" });

describe("topic use cases", () => {
  it("trims a topic name and refuses a blank one before reaching the repository", async () => {
    const knowledge = fakeKnowledge();
    const topics = topicUseCases(knowledge);
    await topics.createTopic("  Roadmap ");
    await topics.renameTopic("t1", " New ");
    expect(knowledge.createTopic).toHaveBeenCalledWith("Roadmap");
    expect(knowledge.updateTopic).toHaveBeenCalledWith("t1", "New");

    await expect(topics.createTopic("   ")).rejects.toThrow(new ValidationError("Topic name is required"));
    await expect(topics.renameTopic("t1", "")).rejects.toBeInstanceOf(ValidationError);
    expect(knowledge.createTopic).toHaveBeenCalledTimes(1);
    expect(knowledge.updateTopic).toHaveBeenCalledTimes(1);
  });

  it("refuses empty notes, bad tags and missing uploads", async () => {
    const knowledge = fakeKnowledge();
    const topics = topicUseCases(knowledge);
    await expect(topics.addTopicNote("t1", " ")).rejects.toThrow("Note cannot be empty");
    await expect(topics.editTopicNote("t1", "n1", "")).rejects.toThrow("Note cannot be empty");
    await expect(topics.addTopicTag("t1", "  ")).rejects.toThrow("Tag cannot be empty");
    await expect(topics.addTopicTag("t1", "x".repeat(41))).rejects.toThrow("Tag cannot be longer than 40 characters");
    await expect(topics.addTopicImage("t1", "not a file")).rejects.toThrow("Choose an image to upload");
    await expect(topics.addTopicImage("t1", new File([], "empty.png"))).rejects.toThrow("Choose an image to upload");
    expect(knowledge.addTopicNote).not.toHaveBeenCalled();
    expect(knowledge.addTopicTag).not.toHaveBeenCalled();
    expect(knowledge.addTopicImage).not.toHaveBeenCalled();

    await topics.addTopicNote("t1", " hi ");
    await topics.addTopicTag("t1", " urgent ");
    await topics.addTopicImage("t1", png);
    expect(knowledge.addTopicNote).toHaveBeenCalledWith("t1", "hi");
    expect(knowledge.addTopicTag).toHaveBeenCalledWith("t1", "urgent");
    expect(knowledge.addTopicImage).toHaveBeenCalledWith("t1", png);
  });

  it("clears a priority override when no level is chosen", async () => {
    const knowledge = fakeKnowledge();
    const topics = topicUseCases(knowledge);
    await topics.setTopicPriorityOverride("t1", "MAJOR", " because ");
    await topics.setTopicPriorityOverride("t1", "", "  ");
    expect(knowledge.setTopicPriorityOverride.mock.calls).toEqual([["t1", "MAJOR", "because"], ["t1", null, null]]);
  });

  it("trims item suggestions down to rows for the panel", async () => {
    const full = item({ id: "i1", description: "Ship", type: "ACTION", stakeholders: ["Ana", "Ben", "Cy"] });
    const knowledge = fakeKnowledge({ getSuggestedItemTopics: [{ item: full, candidates: [], score: 0.3, confidence: "LOW" }] });
    expect(await topicUseCases(knowledge).suggestItemTopics()).toEqual([
      { id: "i1", description: "Ship", type: "ACTION", candidates: [], score: 0.3, confidence: "LOW" },
    ]);
  });
});

describe("item use cases", () => {
  it("creates a manual item from form input, treating blanks as nothing", async () => {
    const knowledge = fakeKnowledge();
    const items = itemUseCases(knowledge);
    await items.createItem("t1", { type: "ACTION", description: " Ship ", owner: " ", dueDate: "2026-01-02" });
    expect(knowledge.createItem).toHaveBeenCalledWith("t1", { type: "ACTION", description: "Ship", owner: null, dueDate: "2026-01-02" });

    await expect(items.createItem("t1", { type: "TASK", description: "x", owner: "", dueDate: "" })).rejects.toThrow("Invalid item type");
    await expect(items.createItem("t1", { type: "IDEA", description: " ", owner: "", dueDate: "" })).rejects.toThrow("Description is required");
    expect(knowledge.createItem).toHaveBeenCalledTimes(1);
  });

  it("edits an item, changing its type only when the form offered one", async () => {
    const knowledge = fakeKnowledge();
    const items = itemUseCases(knowledge);
    await items.updateItem("i1", { description: " d ", owner: "Ana", dueDate: "", rationale: " ", type: null });
    await items.updateItem("i1", { description: "d", owner: "", dueDate: "", rationale: "why", type: "IDEA" });
    expect(knowledge.updateItem.mock.calls).toEqual([
      ["i1", { description: "d", owner: "Ana", dueDate: null, rationale: null }],
      ["i1", { description: "d", owner: null, dueDate: null, rationale: "why", type: "IDEA" }],
    ]);
    await expect(items.updateItem("i1", { description: "d", owner: "", dueDate: "", rationale: "", type: "nope" })).rejects.toThrow("Invalid item type");
    await expect(items.updateItem("i1", { description: "", owner: "", dueDate: "", rationale: "", type: null })).rejects.toThrow("Description is required");
  });

  it("does not call the repository to move nothing", async () => {
    const knowledge = fakeKnowledge();
    const items = itemUseCases(knowledge);
    expect(await items.moveItems([], "t1")).toBe(false);
    expect(await items.moveItems(["a"], null)).toBe(true);
    expect(knowledge.moveItemsTopic.mock.calls).toEqual([[["a"], null]]);
  });

  it("files suggested moves independently and reports the first failure with every failed item", async () => {
    const knowledge = fakeKnowledge({
      moveItemsTopic: (_ids: string[], topicId: string) => {
        if (topicId.startsWith("bad")) throw new Error(`${topicId} not found`);
        return [];
      },
    });
    const result = await itemUseCases(knowledge).fileSuggestedItems([
      { itemIds: ["a"], topicId: "bad1" },
      { itemIds: [], topicId: "skipped" },
      { itemIds: ["b", "c"], topicId: "good" },
      { itemIds: ["d"], topicId: "bad2" },
    ]);
    expect(result).toEqual({ error: "bad1 not found", failedItemIds: ["a", "d"], movedTopicIds: ["good"] });
    expect(knowledge.moveItemsTopic).toHaveBeenCalledTimes(3);
  });

  it("files items under a new topic and says how far it got", async () => {
    const filing = (answers: Answers) => itemUseCases(fakeKnowledge(answers));

    expect(await filing({}).fileItemsUnderNewTopic("  ", ["a"])).toEqual({ status: "invalid", error: "Topic name is required" });
    expect(await filing({}).fileItemsUnderNewTopic("Pricing", [])).toEqual({ status: "nothing_to_file" });
    expect(await filing({ createTopic: new Error("Topic name already exists") }).fileItemsUnderNewTopic("Pricing", ["a"])).toEqual({
      status: "topic_not_created",
      error: "Topic name already exists",
    });
    expect(
      await filing({ createTopic: { id: "new" }, moveItemsTopic: new Error("Item not found") }).fileItemsUnderNewTopic(" Pricing ", ["a"]),
    ).toEqual({ status: "items_not_moved", error: 'Created "Pricing" but could not move the items: Item not found', topicId: "new" });

    const knowledge = fakeKnowledge({ createTopic: { id: "new" } });
    expect(await itemUseCases(knowledge).fileItemsUnderNewTopic(" Pricing ", ["a", "b"])).toEqual({ status: "filed", topicId: "new" });
    expect(knowledge.createTopic).toHaveBeenCalledWith("Pricing");
    expect(knowledge.moveItemsTopic).toHaveBeenCalledWith(["a", "b"], "new");
  });

  it("validates notes and tags on items", async () => {
    const knowledge = fakeKnowledge();
    const items = itemUseCases(knowledge);
    await expect(items.addItemNote("i1", " ")).rejects.toBeInstanceOf(ValidationError);
    await expect(items.editItemNote("i1", "n1", "")).rejects.toBeInstanceOf(ValidationError);
    await expect(items.addItemTag("i1", "")).rejects.toBeInstanceOf(ValidationError);
    await expect(items.removeItemTag("i1", "")).rejects.toBeInstanceOf(ValidationError);
    await items.addItemNote("i1", " hi ");
    await items.addItemTag("i1", " x ");
    await items.setItemPriorityOverride("i1", "", "");
    expect(knowledge.addItemNote).toHaveBeenCalledWith("i1", "hi");
    expect(knowledge.addItemTag).toHaveBeenCalledWith("i1", "x");
    expect(knowledge.setItemPriorityOverride).toHaveBeenCalledWith("i1", null, null);
  });
});

describe("review use cases", () => {
  it("passes a topic only when accepting a candidate", async () => {
    const knowledge = fakeKnowledge();
    const review = knowledgeUseCases(knowledge);
    await review.decideReviewCandidate("c1", "ACCEPTED", "");
    await review.decideReviewCandidate("c2", "ACCEPTED");
    await review.decideReviewCandidate("c3", "REJECTED", "t1");
    expect(knowledge.updateReviewStatus.mock.calls).toEqual([
      ["c1", "ACCEPTED", ""],
      ["c2", "ACCEPTED", undefined],
      ["c3", "REJECTED", undefined],
    ]);
  });

  it("lets repository failures through unchanged", async () => {
    const knowledge = fakeKnowledge({ ingestMeetings: new Error("Ingestion already running") });
    await expect(knowledgeUseCases(knowledge).ingestMeetings()).rejects.toThrow("Ingestion already running");
  });
});
