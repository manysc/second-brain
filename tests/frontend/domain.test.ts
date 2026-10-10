// @vitest-environment node
// The rules the UI applies to the knowledge base, with no React, Next.js or network in sight.
import { describe, expect, it } from "vitest";
import {
  MAX_TAG_LENGTH,
  byPriorityDesc,
  canDeleteTopic,
  classifyRecordId,
  countItemsOfType,
  groupByTopSuggestion,
  isItemType,
  isManualItem,
  isPriorityLevel,
  isUncategorized,
  otherStakeholders,
  sortByMeetingDateDesc,
  tagProblem,
  toSuggestionRow,
  type TopicPriorityInfo,
} from "@/Domain";
import { item, suggestion, topic } from "./support/factories";

const priority = (effectivePriority: "CRITICAL" | "MAJOR" | "MINOR", calculatedScore: number) =>
  ({ effectivePriority, calculatedScore }) as TopicPriorityInfo;

describe("knowledge items", () => {
  it("knows which items a person added by hand", () => {
    expect(isManualItem(item({ meetingId: "manual" }))).toBe(true);
    expect(isManualItem(item({ meetingId: "2026-01-02-sync" }))).toBe(false);
  });

  it("lists stakeholders other than the owner", () => {
    expect(otherStakeholders(item({ owner: "Ana", stakeholders: ["Ana", "Ben", "Cy"] }))).toEqual(["Ben", "Cy"]);
    expect(otherStakeholders(item({ owner: null, stakeholders: ["Ana"] }))).toEqual(["Ana"]);
    expect(otherStakeholders(item({ owner: "Ana", stakeholders: ["Ana"] }))).toEqual([]);
  });

  it("orders items by meeting date, newest first, with undated meetings last", () => {
    const dates = new Map([["old", "2026-01-01"], ["new", "2026-03-01"]]);
    const items = [item({ id: "a", meetingId: "old" }), item({ id: "b", meetingId: "manual" }), item({ id: "c", meetingId: "new" })];
    expect(sortByMeetingDateDesc(items, dates).map((i) => i.id)).toEqual(["c", "a", "b"]);
    expect(items.map((i) => i.id)).toEqual(["a", "b", "c"]); // the input is left as it was
  });

  it("recognizes item types and priority levels", () => {
    expect(["IDEA", "DECISION", "ACTION", "QUESTION"].every(isItemType)).toBe(true);
    expect(isItemType("action")).toBe(false);
    expect(isItemType(undefined)).toBe(false);
    expect(["CRITICAL", "MAJOR", "MINOR"].every(isPriorityLevel)).toBe(true);
    expect(isPriorityLevel("")).toBe(false);
  });
});

describe("topics", () => {
  it("treats the Uncategorized topic specially by name", () => {
    expect(isUncategorized(topic({ name: "Uncategorized" }))).toBe(true);
    expect(isUncategorized(topic({ name: "uncategorized" }))).toBe(false);
  });

  it("allows deleting only a topic with no items", () => {
    expect(canDeleteTopic(topic({ items: [] }))).toBe(true);
    expect(canDeleteTopic(topic({ items: [item()] }))).toBe(false);
  });

  it("ranks by priority level, then score, with unscored topics last", () => {
    const topics = [
      topic({ id: "none", priority: null }),
      topic({ id: "minor", priority: priority("MINOR", 90) }),
      topic({ id: "critical-low", priority: priority("CRITICAL", 10) }),
      topic({ id: "major", priority: priority("MAJOR", 50) }),
      topic({ id: "critical-high", priority: priority("CRITICAL", 80) }),
    ];
    expect([...topics].sort(byPriorityDesc).map((t) => t.id)).toEqual([
      "critical-high", "critical-low", "major", "minor", "none",
    ]);
  });
});

describe("topic suggestions", () => {
  it("keeps only what the suggestions panel shows of an item", () => {
    const row = toSuggestionRow({ item: item({ id: "i1", description: "Ship", type: "ACTION" }), candidates: [], score: 0.4, confidence: "LOW" });
    expect(row).toEqual({ id: "i1", description: "Ship", type: "ACTION", candidates: [], score: 0.4, confidence: "LOW" });
  });

  it("groups items under their best topic, most confident groups first and best matches first within a group", () => {
    const groups = groupByTopSuggestion([
      suggestion("i1", "MEDIUM", 0.5, [["t1", "Launch"], ["t2", "Infra"]]),
      suggestion("i2", "HIGH", 0.9, [["t2", "Infra"]]),
      suggestion("i3", "LOW", 0.7, [["t1", "Launch"]]),
      suggestion("i4", "LOW", 0.1, []), // nothing to suggest: left out
    ]);
    expect(groups.map((g) => [g.topicId, g.highCount, g.suggestions.map((s) => s.id)])).toEqual([
      ["t2", 1, ["i2"]],
      ["t1", 0, ["i3", "i1"]],
    ]);
    expect(groups[1].meanScore).toBeCloseTo(0.6);
    expect(groups[0]).toMatchObject({ topicName: "Infra", itemCount: 4 });
  });

  it("breaks ties between equally confident groups by mean score", () => {
    const groups = groupByTopSuggestion([
      suggestion("i1", "LOW", 0.2, [["weak", "Weak"]]),
      suggestion("i2", "LOW", 0.6, [["strong", "Strong"]]),
    ]);
    expect(groups.map((g) => g.topicId)).toEqual(["strong", "weak"]);
  });
});

describe("meetings, tags and record ids", () => {
  it("counts the items of one type in a meeting", () => {
    const meeting = { items: [item({ type: "ACTION" }), item({ type: "IDEA" }), item({ type: "ACTION" })] };
    expect(countItemsOfType(meeting, "ACTION")).toBe(2);
    expect(countItemsOfType(meeting, "QUESTION")).toBe(0);
  });

  it("explains why a tag cannot be added", () => {
    expect(tagProblem("")).toBe("Tag cannot be empty");
    expect(tagProblem("x".repeat(MAX_TAG_LENGTH))).toBeNull();
    expect(tagProblem("x".repeat(MAX_TAG_LENGTH + 1))).toBe("Tag cannot be longer than 40 characters");
  });

  it("tells topic ids from item ids", () => {
    const uuid = "0F8FAD5B-d9cb-469f-a165-70867728950e";
    expect(classifyRecordId(uuid)).toEqual({ kind: "topic", topicId: uuid });
    expect(classifyRecordId("2026-01-02 sync:item-3")).toEqual({ kind: "item", meetingId: "2026-01-02 sync" });
    expect(classifyRecordId("manual:abc:def")).toEqual({ kind: "item", meetingId: "manual" });
    expect(classifyRecordId("plain")).toBeNull();
    expect(classifyRecordId(":orphan")).toBeNull();
  });
});
