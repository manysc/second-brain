// Characterizes the pure helpers behind the /ask conversation view.
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelInfo } from "@anthropic-ai/claude-agent-sdk";
import { citationHref, effortLevelsFor, timeAgo, withCitations } from "@/components/AskConversation";

const model = (value: string, levels?: string[]) =>
  ({ value, displayName: value, description: "", supportedEffortLevels: levels }) as unknown as ModelInfo;

afterEach(() => vi.useRealTimers());

describe("effortLevelsFor", () => {
  const all = [model("default", ["low", "high"]), model("opus", ["low", "medium", "max"]), model("haiku")];

  it("uses the selected model's levels", () => {
    expect(effortLevelsFor(all[1], all)).toEqual(["low", "medium", "max"]);
    expect(effortLevelsFor(all[2], all)).toEqual([]);
  });

  it("falls back to the default entry, then the union of all models", () => {
    expect(effortLevelsFor(undefined, all)).toEqual(["low", "high"]);
    expect(effortLevelsFor(undefined, all.slice(1))).toEqual(["low", "medium", "max"]);
  });
});

describe("timeAgo", () => {
  it("formats recent times relatively and older ones as a date", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-09T12:00:00Z"));
    const now = Date.now();
    expect(timeAgo(now - 10_000)).toBe("just now");
    expect(timeAgo(now + 60_000)).toBe("just now");
    expect(timeAgo(now - 5 * 60_000)).toBe("5m ago");
    expect(timeAgo(now - 3 * 3_600_000)).toBe("3h ago");
    expect(timeAgo(now - 3 * 86_400_000)).toBe(new Date(now - 3 * 86_400_000).toLocaleDateString());
  });
});

describe("citations", () => {
  it("links topic UUIDs to topics and item ids to their meeting", () => {
    expect(citationHref("0f8fad5b-d9cb-469f-a165-70867728950e")).toBe("/topics/0f8fad5b-d9cb-469f-a165-70867728950e");
    expect(citationHref("2026-01-02 sync:item-3")).toBe("/meetings/2026-01-02%20sync");
    expect(citationHref("plain")).toBeNull();
  });

  it("renders [id] citations as links or plain spans and keeps surrounding text", () => {
    const { container } = render(<p>{withCitations("See [m1:a] and [nope], done.")}</p>);
    expect(container.textContent).toBe("See [m1:a] and [nope], done.");
    const link = container.querySelector("a.citation")!;
    expect(link.getAttribute("href")).toBe("/meetings/m1");
    expect(link.getAttribute("title")).toBe("m1:a");
    expect(container.querySelector("span.citation")!.textContent).toBe("[nope]");
  });
});
