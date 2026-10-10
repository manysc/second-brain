// Characterizes the server-rendered presentational components (rendered synchronously in jsdom).
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// every server action becomes a spy; the components only pass them to <form action>
const spies = vi.hoisted(
  () => async (importOriginal: () => Promise<object>) =>
    Object.fromEntries(Object.keys(await importOriginal()).map((name) => [name, vi.fn()])),
);
vi.mock("@/Presentation/Controllers/itemActions", spies);
vi.mock("@/Presentation/Controllers/reviewActions", spies);
vi.mock("@/Presentation/Controllers/topicActions", spies);

import { KnowledgeCard } from "@/Presentation/Components/KnowledgeCard";
import { NotesSection } from "@/Presentation/Components/NotesSection";
import { PriorityBadge } from "@/Presentation/Components/PriorityBadge";
import { StatusBadge, StatusFilterRow, parseStatusFilter } from "@/Presentation/Components/StatusBadge";
import { TagChip } from "@/Presentation/Components/TagChip";
import { ItemTags } from "@/Presentation/Components/ItemTags";
import { item } from "../support/factories";

const noop = async () => {};

describe("PriorityBadge", () => {
  it("shows a placeholder until priority is calculated", () => {
    render(<PriorityBadge priority={null} />);
    expect(screen.getByText("Not yet calculated")).toHaveProperty("className", "priority-badge priority-unknown");
  });

  it("labels the level, score, confidence and a manual override", () => {
    const { container } = render(
      <PriorityBadge
        priority={{
          effectivePriority: "CRITICAL",
          calculatedScore: 81.6,
          confidence: "HIGH",
          manualOverride: { priority: "CRITICAL", reason: null, overriddenAt: "2026-01-01T00:00:00Z" },
        }}
      />,
    );
    const badge = container.querySelector(".priority-badge")!;
    expect(badge.className).toBe("priority-badge priority-critical");
    expect(badge.textContent).toBe("Critical · 82/100 · high confidence · manual override");
  });
});

describe("StatusBadge and filters", () => {
  it("renders the status with a class per value", () => {
    render(<StatusBadge status="Closed" />);
    expect(screen.getByText("Closed").className).toBe("status-badge status-closed");
  });

  it("parses ?status= case-insensitively and defaults to Open", () => {
    expect(parseStatusFilter(undefined)).toBe("Open");
    expect(parseStatusFilter("CLOSED")).toBe("Closed");
    expect(parseStatusFilter("all")).toBe("All");
    expect(parseStatusFilter("bogus")).toBe("Open");
  });

  it("links each filter with its count", () => {
    render(<StatusFilterRow basePath="/actions" active="Closed" counts={{ Open: 3, Closed: 2, All: 5 }} />);
    const links = screen.getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href"), a.className])).toEqual([
      ["Open 3", "/actions", "filter"],
      ["Closed 2", "/actions?status=closed", "filter active"],
      ["All 5", "/actions?status=all", "filter"],
    ]);
  });
});

describe("TagChip and ItemTags", () => {
  it("renders a chip", () => {
    render(<TagChip tag="infra" />);
    expect(screen.getByText("infra").className).toBe("tag-chip");
  });

  it("offers removal per tag and an add form below the limit", () => {
    render(<ItemTags itemId="i1" tags={["a", "b"]} />);
    expect(screen.getByText("Tags (2)")).toBeTruthy();
    expect(screen.getByLabelText("Remove tag a")).toBeTruthy();
    expect(screen.getByLabelText("New tag").getAttribute("maxLength")).toBe("40");
  });

  it("replaces the add form with a notice at the tag limit", () => {
    render(<ItemTags itemId="i1" tags={Array.from({ length: 20 }, (_, i) => `t${i}`)} />);
    expect(screen.queryByLabelText("New tag")).toBeNull();
    expect(screen.getByText("Tag limit reached (20)")).toBeTruthy();
  });
});

describe("NotesSection", () => {
  it("shows notes with ISO dates (raw text when unparseable) and parent ids on every form", () => {
    const { container } = render(
      <NotesSection
        notes={[
          { id: "n1", body: "first", createdAt: "2026-03-04T22:10:00Z" },
          { id: "n2", body: "second", createdAt: "yesterday" },
        ]}
        parentField="topicId"
        parentId="t9"
        addAction={noop}
        editAction={noop}
        deleteAction={noop}
      />,
    );
    expect(screen.getByText("2026-03-04")).toBeTruthy();
    expect(screen.getByText("yesterday")).toBeTruthy();
    const parents = container.querySelectorAll('input[type="hidden"][name="topicId"]');
    expect(parents).toHaveLength(5); // edit + delete per note, plus the add form
    expect([...parents].every((input) => (input as HTMLInputElement).value === "t9")).toBe(true);
  });
});

describe("KnowledgeCard", () => {
  it("shows owner, other stakeholders, due date and a topic link", () => {
    render(<KnowledgeCard item={item()} />);
    expect(screen.getByText("Ship the beta")).toBeTruthy();
    expect(screen.getByText("Ben")).toBeTruthy(); // owner Ana is not repeated as a stakeholder
    expect(screen.getByText("Due 2026-11-01")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Topic: Launch" }).getAttribute("href")).toBe("/topics/t1");
  });

  it("falls back when owner, stakeholders and due date are missing", () => {
    render(<KnowledgeCard item={item({ owner: null, stakeholders: [], dueDate: null, topicId: null })} />);
    expect(screen.getByText("Owner unassigned")).toBeTruthy();
    expect(screen.getByText("No other stakeholders")).toBeTruthy();
    expect(screen.getByText("No due date")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("offers close/reopen only for actions and questions", () => {
    const { rerender, container } = render(<KnowledgeCard item={item({ type: "ACTION", status: "Open" })} />);
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
    expect((container.querySelector('input[name="status"]') as HTMLInputElement).value).toBe("Closed");

    rerender(<KnowledgeCard item={item({ type: "QUESTION", status: "Closed" })} />);
    expect(screen.getByRole("button", { name: "Reopen" })).toBeTruthy();

    rerender(<KnowledgeCard item={item({ type: "IDEA" })} />);
    expect(screen.queryByRole("button", { name: /Close|Reopen/ })).toBeNull();
  });

  it("shows the inherited priority and a manual override with a clear button", () => {
    render(
      <KnowledgeCard
        item={item({
          effectivePriority: "MAJOR",
          manualOverride: { priority: "MAJOR", reason: "exec ask", overriddenAt: "2026-01-01T00:00:00Z" },
        })}
      />,
    );
    expect(screen.getByText(/^Major/).className).toBe("priority-badge priority-major");
    const override = screen.getByText(/Manually overridden to/);
    expect(override.textContent).toBe("Manually overridden to MAJOR — exec ask");
    expect(screen.getByRole("button", { name: "Clear override" })).toBeTruthy();
  });

  it("shows evidence with fallbacks for unknown speaker and timestamp", () => {
    const { container } = render(
      <KnowledgeCard item={item({ evidence: { speaker: null, timestamp: null, quote: "q", context: "c" } })} />,
    );
    const evidence = container.querySelector("details.evidence")!;
    expect(within(evidence as HTMLElement).getByText("Speaker uncertain · Timestamp unavailable")).toBeTruthy();
  });
});
