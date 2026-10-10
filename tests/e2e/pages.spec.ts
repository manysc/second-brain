import { expect, test } from "@playwright/test";
import { seeded } from "./fixture";

// Async server components cannot be unit-tested in Vitest, so every page is rendered here against the real backend.
test.describe("every page renders against the real backend", () => {
  const { meetingId, topicId } = seeded();
  const pages = [
    "/",
    "/dashboard",
    "/meetings",
    `/meetings/${encodeURIComponent(meetingId)}`,
    "/items",
    "/actions",
    "/questions",
    "/decisions",
    "/topics",
    `/topics/${topicId}`,
    "/review",
    "/briefing",
    "/graph",
    "/growth",
    "/growth/career",
    "/growth/impact",
    "/ask",
  ];

  for (const url of pages) {
    test(url, async ({ page }) => {
      const response = await page.goto(url);
      expect(response?.status(), `${url} status`).toBeLessThan(400);
      await expect(page.locator("main").first()).toBeVisible();
      await expect(page.getByText(/Unhandled Runtime Error|Application error/)).toHaveCount(0);
    });
  }
});

test("the ask page offers a composer without calling the agent", async ({ page }) => {
  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: "What do you need to know?" })).toBeVisible();
  await expect(page.getByPlaceholder("What should I follow up on?")).toBeVisible();
});
