import { expect, test } from "@playwright/test";
import { gotoHydrated, seeded } from "./fixture";

const seed = seeded();

test("accept a review candidate into a chosen topic", async ({ page }) => {
  await gotoHydrated(page, "/review");
  const card = page.locator("article.review-item", { hasText: seed.acceptDescription });
  await card.getByLabel("File under topic").selectOption({ label: seed.topicName });
  await card.getByRole("button", { name: "Accept" }).click();
  await expect(card).toHaveCount(0);
  await page.waitForLoadState("networkidle"); // the card hides optimistically; let the action finish

  await page.goto(`/topics/${seed.topicId}`);
  await expect(page.locator(".selectable-item", { hasText: seed.acceptDescription })).toBeVisible();
});

test("reject a review candidate", async ({ page }) => {
  await gotoHydrated(page, "/review");
  const card = page.locator("article.review-item", { hasText: seed.rejectDescription });
  await card.getByRole("button", { name: "Reject" }).click();
  await expect(card).toHaveCount(0);
  await page.reload();
  await expect(page.locator("article.review-item", { hasText: seed.rejectDescription })).toHaveCount(0);
});

test("ingest from SeaweedFS reports a summary", async ({ page }) => {
  test.setTimeout(240_000);
  await gotoHydrated(page, "/meetings");
  await page.getByRole("button", { name: "Ingest from SeaweedFS" }).click();
  await expect(page.locator(".ingest-status, .ingest-control .error-banner")).toBeVisible({ timeout: 220_000 });
  await expect(page.locator(".ingest-status")).toContainText("checked");
});
