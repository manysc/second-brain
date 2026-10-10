// Characterizes the client components that call server actions optimistically: hide on click, restore with an error
// banner when the action fails.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  decideReviewCandidateAction: vi.fn(),
  acceptTopicProposalAction: vi.fn(),
  rejectTopicProposalAction: vi.fn(),
  ingestMeetingsAction: vi.fn(),
  moveItemsTopicAction: vi.fn(),
  moveSuggestedItemsAction: vi.fn(),
  createTopicAndMoveItemsAction: vi.fn(),
}));
vi.mock("@/Presentation/Controllers/itemActions", () => actions);
vi.mock("@/Presentation/Controllers/reviewActions", () => actions);
vi.mock("@/Presentation/Controllers/topicActions", () => actions);

import { BulkMoveProvider, SelectableItem } from "@/Presentation/Components/BulkTopicMove";
import { IngestMeetingsButton } from "@/Presentation/Components/IngestMeetingsButton";
import { ReviewCandidateList } from "@/Presentation/Components/ReviewCandidateList";
import { SuggestedItemTopics } from "@/Presentation/Components/SuggestedItemTopics";
import { TopicProposalList } from "@/Presentation/Components/TopicProposalList";
import { candidate, proposal, suggestion, topic } from "../support/factories";

const TOPICS = [
  { id: "t1", name: "Launch" },
  { id: "t2", name: "Infra" },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
});

describe("ReviewCandidateList", () => {
  it("accepts under the chosen topic and hides the card immediately", async () => {
    const pending = deferred<{ error?: string }>();
    actions.decideReviewCandidateAction.mockReturnValue(pending.promise);
    render(<ReviewCandidateList candidates={[candidate({ suggestedTopicId: "t2" })]} topics={TOPICS} />);

    expect((screen.getByLabelText("File under topic") as HTMLSelectElement).value).toBe("t2");
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(screen.queryByText("Adopt pgvector")).toBeNull();
    expect(actions.decideReviewCandidateAction).toHaveBeenCalledWith("c1", "ACCEPTED", "t2");
    await act(async () => pending.resolve({}));
    expect(screen.queryByText("Adopt pgvector")).toBeNull();
  });

  it("defaults to Uncategorized ('') and rejects without a topic", async () => {
    actions.decideReviewCandidateAction.mockResolvedValue({});
    render(<ReviewCandidateList candidates={[candidate(), candidate({ id: "c2", description: "Other" })]} topics={TOPICS} />);
    const [first, second] = screen.getAllByRole("article");
    await userEvent.click(within(first).getByRole("button", { name: "Accept" }));
    expect(actions.decideReviewCandidateAction).toHaveBeenLastCalledWith("c1", "ACCEPTED", "");
    await userEvent.click(within(second).getByRole("button", { name: "Reject" }));
    expect(actions.decideReviewCandidateAction).toHaveBeenLastCalledWith("c2", "REJECTED", undefined);
  });

  it("restores the card and shows the error when the decision fails", async () => {
    actions.decideReviewCandidateAction.mockResolvedValue({ error: "Review candidate already decided" });
    render(<ReviewCandidateList candidates={[candidate()]} topics={TOPICS} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Review candidate already decided")).toHaveProperty("className", "error-banner");
    expect(screen.getByText("Adopt pgvector")).toBeTruthy();
  });
});

describe("TopicProposalList", () => {
  it("accepts with the edited name, or files under an existing topic on select", async () => {
    actions.acceptTopicProposalAction.mockResolvedValue({});
    render(<TopicProposalList proposals={[proposal(), proposal({ name: "Hiring" })]} topics={TOPICS} />);
    expect(screen.getByText("Suggested new topics")).toBeTruthy();

    const [infra, hiring] = screen.getAllByRole("article");
    const name = within(infra).getByLabelText("Create topic as");
    await userEvent.clear(name);
    await userEvent.type(name, "Infrastructure ");
    await userEvent.click(within(infra).getByRole("button", { name: "Accept" }));
    expect(actions.acceptTopicProposalAction).toHaveBeenLastCalledWith("Infra", "Infrastructure", null);

    await userEvent.selectOptions(within(hiring).getByLabelText(/file under existing topic/), "t1");
    expect(actions.acceptTopicProposalAction).toHaveBeenLastCalledWith("Hiring", null, "t1");
    expect(screen.queryByText("Suggested new topics")).toBeNull();
  });

  it("lists up to three items and summarizes the rest", () => {
    const items = ["a", "b", "c", "d", "e"].map((id) => ({ ...proposal().items[0], id, description: `desc ${id}` }));
    render(<TopicProposalList proposals={[proposal({ items })]} topics={TOPICS} />);
    expect(screen.getByText("5 items")).toBeTruthy();
    expect(screen.getByText("desc c")).toBeTruthy();
    expect(screen.queryByText("desc d")).toBeNull();
    expect(screen.getByText("…and 2 more")).toBeTruthy();
  });

  it("restores the proposal when rejecting fails", async () => {
    actions.rejectTopicProposalAction.mockRejectedValue(new Error("network down"));
    render(<TopicProposalList proposals={[proposal()]} topics={TOPICS} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("network down")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Infra" })).toBeTruthy();
    expect(actions.rejectTopicProposalAction).toHaveBeenCalledWith("Infra");
  });
});

describe("IngestMeetingsButton", () => {
  it.each([
    [{ meetings: 4, new: 0, updated: 0, unchanged: 4 }, "No new or changed meetings · 4 checked"],
    [{ meetings: 4, new: 1, updated: 0, unchanged: 3 }, "1 new meeting · 4 checked"],
    [{ meetings: 9, new: 2, updated: 3, unchanged: 4 }, "2 new meetings, 3 updated · 9 checked"],
    [{ meetings: 2, new: 0, updated: 1, unchanged: 1 }, "1 updated · 2 checked"],
  ])("summarizes %j", async (result, text) => {
    actions.ingestMeetingsAction.mockResolvedValue({ result });
    render(<IngestMeetingsButton />);
    await userEvent.click(screen.getByRole("button", { name: "Ingest from SeaweedFS" }));
    expect(await screen.findByText(text)).toBeTruthy();
  });

  it("disables itself while running and shows errors", async () => {
    const pending = deferred<{ error?: string }>();
    actions.ingestMeetingsAction.mockReturnValue(pending.promise);
    render(<IngestMeetingsButton />);
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button", { name: "Ingesting…" })).toHaveProperty("disabled", true);
    await act(async () => pending.resolve({ error: "Ingestion is already running" }));
    expect(screen.getByText("Ingestion is already running")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ingest from SeaweedFS" })).toHaveProperty("disabled", false);
  });
});

describe("BulkTopicMove", () => {
  function renderList() {
    render(
      <BulkMoveProvider topics={[topic(), topic({ id: "t2", name: "Infra" })]} returnTo="/items">
        <SelectableItem id="a">A</SelectableItem>
        <SelectableItem id="b">B</SelectableItem>
      </BulkMoveProvider>,
    );
    return screen.getAllByLabelText("Select item");
  }

  it("moves the selected items once a topic is chosen", async () => {
    const [a, b] = renderList();
    expect(screen.queryByText(/selected/)).toBeNull();
    await userEvent.click(a);
    await userEvent.click(b);
    expect(screen.getByText("2 selected")).toBeTruthy();
    const move = screen.getByRole("button", { name: "Move" });
    expect(move).toHaveProperty("disabled", true);
    await userEvent.selectOptions(screen.getByRole("combobox"), "t2");
    await userEvent.click(move);
    expect(actions.moveItemsTopicAction).toHaveBeenCalledWith(["a", "b"], "t2", "/items");
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("maps Unassigned to null and Cancel clears the selection", async () => {
    const [a] = renderList();
    await userEvent.click(a);
    await userEvent.selectOptions(screen.getByRole("combobox"), "");
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    expect(actions.moveItemsTopicAction).toHaveBeenCalledWith(["a"], null, "/items");

    await userEvent.click(a);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("refuses SelectableItem outside a provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<SelectableItem id="x">X</SelectableItem>)).toThrow("SelectableItem must be used inside a BulkMoveProvider");
  });
});

describe("SuggestedItemTopics", () => {
  const rows = [
    suggestion("i1", "HIGH", 0.9, [["t1", "Launch"], ["t2", "Infra"]]),
    suggestion("i2", "MEDIUM", 0.6, [["t1", "Launch"]]),
    suggestion("i3", "LOW", 0.3, [["t2", "Infra"]]),
    suggestion("i4", "HIGH", 0.8, [["t2", "Infra"]]),
    suggestion("i5", "HIGH", 0.95, [["t2", "Infra"]]),
  ];

  function renderPanel(suggestions = rows) {
    return render(<SuggestedItemTopics suggestions={suggestions} topics={TOPICS} returnTo="/topics/unc" uncategorizedTopicId="unc" />);
  }

  it("groups by best topic, most high-confidence matches first, and pre-selects HIGH rows", () => {
    renderPanel();
    expect(screen.getByText(/5 items · 3 high · 1 medium · 1 low confidence/)).toBeTruthy();
    const groups = document.querySelectorAll("details.suggestion-group");
    expect([...groups].map((g) => g.querySelector("summary b")!.textContent)).toEqual(["Infra", "Launch"]);
    const infraRows = groups[0].querySelectorAll(".suggestion-row p");
    expect([...infraRows].map((p) => p.textContent)).toEqual(["Item i5", "Item i4", "Item i3"]);
    expect(screen.getByRole("button", { name: "File 3 selected into 2 topics" })).toBeTruthy();
  });

  it("selects by confidence band", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "High + medium" }));
    expect(screen.getByRole("button", { name: "File 4 selected into 2 topics" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "None" }));
    expect(screen.getByRole("button", { name: "File 0 selected into 0 topics" })).toHaveProperty("disabled", true);
  });

  it("files every group's selection in one batch, hides it, and can undo to Uncategorized", async () => {
    actions.moveSuggestedItemsAction.mockResolvedValue({});
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "File 3 selected into 2 topics" }));
    expect(actions.moveSuggestedItemsAction).toHaveBeenCalledWith(
      [
        { topicId: "t2", itemIds: ["i5", "i4"] },
        { topicId: "t1", itemIds: ["i1"] },
      ],
      "/topics/unc",
    );
    expect(screen.queryByText("Item i5")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Filed 3 items into 2 topics.");

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(actions.moveSuggestedItemsAction).toHaveBeenLastCalledWith([{ itemIds: ["i5", "i4", "i1"], topicId: "unc" }], "/topics/unc");
    expect(screen.getByText("Item i5")).toBeTruthy();
  });

  it("brings back only the items that failed to move", async () => {
    actions.moveSuggestedItemsAction.mockResolvedValue({ error: "Topic not found", failedItemIds: ["i1"] });
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "File 3 selected into 2 topics" }));
    expect(screen.getByText("Topic not found")).toBeTruthy();
    expect(screen.getByText("Item i1")).toBeTruthy();
    expect(screen.queryByText("Item i5")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Filed 2 items into 1 topic.");
  });

  it("moves a single row to an alternative candidate topic", async () => {
    actions.moveSuggestedItemsAction.mockResolvedValue({});
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /→ Infra/ }));
    expect(actions.moveSuggestedItemsAction).toHaveBeenCalledWith([{ itemIds: ["i1"], topicId: "t2" }], "/topics/unc");
  });

  it("creates a new topic for a row, reusing an existing topic with the same name", async () => {
    actions.createTopicAndMoveItemsAction.mockResolvedValue({ topicId: "new" });
    actions.moveSuggestedItemsAction.mockResolvedValue({});
    renderPanel([rows[1], rows[2]]);

    const [first, second] = screen.getAllByRole("button", { name: "+ New topic…" });
    await userEvent.click(first);
    await userEvent.type(screen.getByLabelText("New topic name"), "Pricing{Enter}");
    // groups sort by mean score when none has a HIGH match: Launch (i2, 0.6) before Infra (i3, 0.3)
    expect(actions.createTopicAndMoveItemsAction).toHaveBeenCalledWith("Pricing", ["i2"], "/topics/unc");

    await userEvent.click(second);
    await userEvent.type(screen.getByLabelText("New topic name"), " launch {Enter}");
    expect(actions.moveSuggestedItemsAction).toHaveBeenCalledWith([{ itemIds: ["i3"], topicId: "t1" }], "/topics/unc");
    expect(actions.createTopicAndMoveItemsAction).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state", () => {
    renderPanel([]);
    expect(screen.getByText("No topic suggestions right now.")).toBeTruthy();
  });
});
