// The Briefing page's filter bar (a client component that navigates on every change) and its hidden-items note.
// The page itself is an async server component, covered by tests/e2e/briefing.spec.ts.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { BriefingFilterBar } from "@/Presentation/Components/BriefingFilterBar";
import { StaleItemsNote } from "@/Presentation/Components/StaleItemsNote";
import { DEFAULT_BRIEFING_FILTERS, type BriefingFilters } from "@/Presentation/briefingFilters";

const OPTIONS = {
  stakeholders: ["Ana", "Ben"],
  meetings: [{ id: "m1", title: "Sync", date: "2026-06-01" }],
  topics: [{ id: "t1", name: "Launch" }],
};

const renderBar = (filters: Partial<BriefingFilters> = {}) =>
  render(<BriefingFilterBar filters={{ ...DEFAULT_BRIEFING_FILTERS, ...filters }} {...OPTIONS} />);
const pushed = () => router.push.mock.lastCall?.[0];

beforeEach(() => router.push.mockReset());

describe("BriefingFilterBar", () => {
  it("starts with nothing picked, stale items hidden and five topics", () => {
    renderBar();
    expect(screen.getAllByRole("checkbox", { checked: true }).map((box) => box.parentElement?.textContent)).toEqual([
      "Hide items with no activity in 30 days",
    ]);
    expect((screen.getByLabelText("Topics to show") as HTMLSelectElement).value).toBe("5");
    expect(screen.getByText("Stakeholders").className).toBe("filter");
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
  });

  it("navigates to the URL for each choice", async () => {
    renderBar();
    await userEvent.click(screen.getByLabelText("Ana"));
    expect(pushed()).toBe("/briefing?stakeholder=Ana");
    await userEvent.click(screen.getByLabelText("2026-06-01 · Sync"));
    expect(pushed()).toBe("/briefing?meeting=m1");
    await userEvent.click(screen.getByLabelText("Launch"));
    expect(pushed()).toBe("/briefing?topic=t1");
    await userEvent.click(screen.getByLabelText("Hide items with no activity in 30 days"));
    expect(pushed()).toBe("/briefing?stale=show");
    await userEvent.selectOptions(screen.getByLabelText("Topics to show"), "10");
    expect(pushed()).toBe("/briefing?limit=10");
  });

  it("keeps the other filters when one changes, and offers to clear them", async () => {
    renderBar({ showStale: true, limit: 10, stakeholders: ["Ana", "Gone"], topicIds: ["t1"] });
    expect(screen.getByText("Stakeholders (2)").className).toBe("filter active");
    expect(screen.getByText("Topics (1)").className).toBe("filter active");
    expect(screen.getByText("Meetings").className).toBe("filter");
    // a name from the URL that is no longer on any item can still be unticked
    const stakeholders = within(screen.getByRole("group", { name: "Stakeholders" }));
    expect(
      stakeholders.getAllByRole("checkbox").map((box) => [box.parentElement?.textContent, (box as HTMLInputElement).checked]),
    ).toEqual([
      ["Ana", true],
      ["Ben", false],
      ["Gone", true],
    ]);

    await userEvent.click(stakeholders.getByLabelText("Gone"));
    expect(pushed()).toBe("/briefing?stakeholder=Ana&topic=t1&stale=show&limit=10");
    await userEvent.click(stakeholders.getByLabelText("Ben"));
    expect(pushed()).toBe("/briefing?stakeholder=Ana&stakeholder=Gone&stakeholder=Ben&topic=t1&stale=show&limit=10");
    await userEvent.click(screen.getByLabelText("Hide items with no activity in 30 days"));
    expect(pushed()).toBe("/briefing?stakeholder=Ana&stakeholder=Gone&topic=t1&limit=10");
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe("/briefing");
  });

  it("says so when there is nothing to choose from", () => {
    render(<BriefingFilterBar filters={DEFAULT_BRIEFING_FILTERS} stakeholders={[]} meetings={[]} topics={[]} />);
    expect(screen.getAllByText("Nothing to choose from yet.")).toHaveLength(3);
  });
});

describe("StaleItemsNote", () => {
  it("says how many items are hidden and links to all of them", () => {
    const { container } = render(<StaleItemsNote count={3} days={30} showAllHref="/briefing?stale=show" />);
    expect(container.textContent).toBe("3 items with no activity in 30 days are hidden. Show them");
    expect(screen.getByRole("link", { name: "Show them" }).getAttribute("href")).toBe("/briefing?stale=show");
  });

  it("words a single item in the singular", () => {
    const { container } = render(<StaleItemsNote count={1} days={30} showAllHref="/briefing?stale=show" />);
    expect(container.textContent).toBe("1 item with no activity in 30 days is hidden. Show it");
  });

  it("renders nothing when no item is hidden or the cut-off is off", () => {
    expect(render(<StaleItemsNote count={0} days={30} showAllHref="/x" />).container.innerHTML).toBe("");
    expect(render(<StaleItemsNote count={0} days={null} showAllHref="/x" />).container.innerHTML).toBe("");
  });
});
