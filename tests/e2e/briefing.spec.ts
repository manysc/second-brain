import { expect, test, type Locator, type Page } from "@playwright/test";
import { gotoHydrated, seeded } from "./fixture";

const seed = seeded();
// Always narrowed to the seeded topic: among real data it might not be one of the five topics the page shows.
const briefing = `/briefing?topic=${encodeURIComponent(seed.topicId)}`;

/** The seeded topic's card with its item list expanded (cards start minimized). */
async function openCard(page: Page): Promise<Locator> {
  const card = page.locator(".follow-up-topic");
  await expect(card).toHaveCount(1);
  const body = card.locator("details.follow-up-body");
  // the direct child: each item card inside has summaries of its own
  if ((await body.getAttribute("open")) === null) await body.locator("> summary").click();
  return card;
}

test("the briefing hides items with no recent activity until asked for them", async ({ page }) => {
  await gotoHydrated(page, briefing);
  let card = await openCard(page);
  await expect(card.getByText(seed.freshQuestion)).toBeVisible();
  await expect(card.getByText(seed.staleQuestion)).toHaveCount(0);
  await expect(page.locator(".briefing-note")).toContainText("1 item with no activity in 30 days is hidden");

  await page.getByLabel("Hide items with no activity in 30 days").uncheck();
  await expect(page).toHaveURL(/stale=show/);
  card = await openCard(page);
  await expect(card.getByText(seed.staleQuestion)).toBeVisible();
  await expect(card.getByText(seed.freshQuestion)).toBeVisible();
  await expect(page.locator(".briefing-note")).toHaveCount(0);
});

test("the briefing narrows to a stakeholder and keeps the choice in the URL", async ({ page }) => {
  await gotoHydrated(page, briefing);
  await page.locator(".filter-menu summary", { hasText: "Stakeholders" }).click();
  await page.getByRole("group", { name: "Stakeholders" }).getByLabel(seed.owner, { exact: true }).check();
  await expect(page).toHaveURL(/stakeholder=/);

  const card = await openCard(page);
  await expect(card.getByText(seed.freshQuestion)).toBeVisible();
  await expect(card.getByText(seed.itemDescription)).toHaveCount(0); // the seeded action has no owner

  await page.reload();
  await expect(page.locator(".filter-menu summary", { hasText: "Stakeholders (1)" })).toBeVisible();
  await page.getByRole("link", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/briefing$/);
});

test("a filter that matches nothing says so instead of claiming there is nothing to follow up", async ({ page }) => {
  await page.goto(`${briefing}&meeting=no-such-meeting`);
  await expect(page.getByText("No follow-up items match these filters.")).toBeVisible();
  await expect(page.locator(".follow-up-topic")).toHaveCount(0);
});
