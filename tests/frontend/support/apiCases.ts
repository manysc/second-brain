// The request every backend API client call must produce; shared by the client tests and the OpenAPI contract test.
import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";

const api = new BackendApiClient();

export type Case = { name: string; run: () => Promise<unknown>; method: string; path: string; body?: unknown };

export const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "shot.png", { type: "image/png" });

export const CASES: Case[] = [
  { name: "getMeeting", run: () => api.getMeeting(), method: "GET", path: "/api/meeting" },
  { name: "getMeetings", run: () => api.getMeetings(), method: "GET", path: "/api/meetings" },
  { name: "getMeetingById", run: () => api.getMeetingById("m 1/x"), method: "GET", path: "/api/meetings/m%201%2Fx" },
  { name: "ingestMeetings", run: () => api.ingestMeetings(), method: "POST", path: "/api/ingest" },
  { name: "getItems", run: () => api.getItems(), method: "GET", path: "/api/items" },
  { name: "getItems filtered", run: () => api.getItems("ACTION", "CRITICAL"), method: "GET", path: "/api/items?type=ACTION&priority=CRITICAL" },
  { name: "getItem", run: () => api.getItem("m:1"), method: "GET", path: "/api/items/m%3A1" },
  { name: "searchItems", run: () => api.searchItems("a b&c"), method: "GET", path: "/api/search?q=a%20b%26c" },
  { name: "getTopics", run: () => api.getTopics(), method: "GET", path: "/api/topics" },
  { name: "getGraph", run: () => api.getGraph(), method: "GET", path: "/api/graph" },
  { name: "getGraph threshold", run: () => api.getGraph(0.5), method: "GET", path: "/api/graph?minSimilarity=0.5" },
  { name: "getSuggestedTopicMerges", run: () => api.getSuggestedTopicMerges(), method: "GET", path: "/api/topics/suggested-merges" },
  { name: "getSuggestedItemTopics", run: () => api.getSuggestedItemTopics(), method: "GET", path: "/api/topics/suggested-item-topics" },
  { name: "getTopicById", run: () => api.getTopicById("t1"), method: "GET", path: "/api/topics/t1" },
  { name: "getRelatedTopics", run: () => api.getRelatedTopics("t1"), method: "GET", path: "/api/topics/t1/related" },
  { name: "createTopic", run: () => api.createTopic("Roadmap"), method: "POST", path: "/api/topics", body: { name: "Roadmap" } },
  { name: "updateTopic", run: () => api.updateTopic("t1", "New"), method: "PATCH", path: "/api/topics/t1", body: { name: "New" } },
  { name: "mergeTopics", run: () => api.mergeTopics("s", "t"), method: "POST", path: "/api/topics/s/merge", body: { targetTopicId: "t" } },
  { name: "deleteTopic", run: () => api.deleteTopic("t1"), method: "DELETE", path: "/api/topics/t1" },
  { name: "moveItemTopic", run: () => api.moveItemTopic("i1", null), method: "PATCH", path: "/api/items/i1/topic", body: { topicId: null } },
  {
    name: "moveItemsTopic", run: () => api.moveItemsTopic(["a", "b"], "t"), method: "PATCH", path: "/api/items/topic",
    body: { itemIds: ["a", "b"], topicId: "t" },
  },
  { name: "getReview", run: () => api.getReview(), method: "GET", path: "/api/review" },
  {
    name: "updateReviewStatus accept", run: () => api.updateReviewStatus("c1", "ACCEPTED", ""), method: "PATCH",
    path: "/api/review/c1", body: { status: "ACCEPTED", topicId: "" },
  },
  {
    name: "updateReviewStatus reject", run: () => api.updateReviewStatus("c1", "REJECTED"), method: "PATCH",
    path: "/api/review/c1", body: { status: "REJECTED" },
  },
  { name: "getTopicProposals", run: () => api.getTopicProposals(), method: "GET", path: "/api/review/topic-proposals" },
  {
    name: "acceptTopicProposal", run: () => api.acceptTopicProposal("Infra", null, "t9"), method: "POST",
    path: "/api/review/topic-proposals/accept", body: { suggestedName: "Infra", topicName: null, existingTopicId: "t9" },
  },
  {
    name: "rejectTopicProposal", run: () => api.rejectTopicProposal("Infra"), method: "POST",
    path: "/api/review/topic-proposals/reject", body: { suggestedName: "Infra" },
  },
  { name: "recalculateTopicPriority", run: () => api.recalculateTopicPriority("t1"), method: "POST", path: "/api/topics/t1/recalculate-priority" },
  { name: "recalculateAllTopicPriorities", run: () => api.recalculateAllTopicPriorities(), method: "POST", path: "/api/topics/recalculate-priority" },
  {
    name: "setTopicPriorityOverride", run: () => api.setTopicPriorityOverride("t1", "MAJOR", "why"), method: "PATCH",
    path: "/api/topics/t1/priority-override", body: { priority: "MAJOR", reason: "why" },
  },
  { name: "getTopicPriorityHistory", run: () => api.getTopicPriorityHistory("t1"), method: "GET", path: "/api/topics/t1/priority-history" },
  {
    name: "setItemPriorityOverride", run: () => api.setItemPriorityOverride("i1", null, null), method: "PATCH",
    path: "/api/items/i1/priority-override", body: { priority: null, reason: null },
  },
  { name: "setItemStatus", run: () => api.setItemStatus("i1", "Closed"), method: "PATCH", path: "/api/items/i1/status", body: { status: "Closed" } },
  { name: "setTopicStatus", run: () => api.setTopicStatus("t1", "Open"), method: "PATCH", path: "/api/topics/t1/status", body: { status: "Open" } },
  { name: "addItemNote", run: () => api.addItemNote("i1", "hi"), method: "POST", path: "/api/items/i1/notes", body: { body: "hi" } },
  { name: "deleteItemNote", run: () => api.deleteItemNote("i1", "n1"), method: "DELETE", path: "/api/items/i1/notes/n1" },
  { name: "addTopicNote", run: () => api.addTopicNote("t1", "hi"), method: "POST", path: "/api/topics/t1/notes", body: { body: "hi" } },
  { name: "deleteTopicImage", run: () => api.deleteTopicImage("t1", "img"), method: "DELETE", path: "/api/topics/t1/images/img" },
  { name: "addTopicTag", run: () => api.addTopicTag("t1", "x"), method: "POST", path: "/api/topics/t1/tags", body: { tag: "x" } },
  { name: "removeTopicTag", run: () => api.removeTopicTag("t1", "a b"), method: "DELETE", path: "/api/topics/t1/tags?tag=a%20b" },
  { name: "addItemTag", run: () => api.addItemTag("i1", "x"), method: "POST", path: "/api/items/i1/tags", body: { tag: "x" } },
  { name: "removeItemTag", run: () => api.removeItemTag("i1", "x"), method: "DELETE", path: "/api/items/i1/tags?tag=x" },
  {
    name: "createItem", run: () => api.createItem("t1", { type: "ACTION", description: "d", owner: null, dueDate: "2026-01-02" }),
    method: "POST", path: "/api/topics/t1/items", body: { type: "ACTION", description: "d", owner: null, dueDate: "2026-01-02" },
  },
  {
    name: "updateItem", run: () => api.updateItem("i1", { description: "d", rationale: null }), method: "PATCH",
    path: "/api/items/i1", body: { description: "d", rationale: null },
  },
  { name: "deleteItem", run: () => api.deleteItem("i1"), method: "DELETE", path: "/api/items/i1" },
  { name: "deleteTopicNote", run: () => api.deleteTopicNote("t1", "n1"), method: "DELETE", path: "/api/topics/t1/notes/n1" },
  { name: "updateItemNote", run: () => api.updateItemNote("i1", "n1", "b"), method: "PATCH", path: "/api/items/i1/notes/n1", body: { body: "b" } },
  { name: "updateTopicNote", run: () => api.updateTopicNote("t1", "n1", "b"), method: "PATCH", path: "/api/topics/t1/notes/n1", body: { body: "b" } },
  { name: "getRecentPriorityEscalations", run: () => api.getRecentPriorityEscalations(), method: "GET", path: "/api/priority-history/recent" },
  { name: "getRecentPriorityEscalations days", run: () => api.getRecentPriorityEscalations(7), method: "GET", path: "/api/priority-history/recent?days=7" },
  { name: "getFollowUp", run: () => api.getFollowUp(), method: "GET", path: "/api/follow-up" },
  { name: "getFollowUp params", run: () => api.getFollowUp(3, 10), method: "GET", path: "/api/follow-up?limit=3&dueSoonDays=10" },
];
