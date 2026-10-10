import { expect, test, type Page } from "@playwright/test";
import { gotoHydrated, seeded } from "./fixture";

const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

const seed = seeded();
const topicUrl = `/topics/${seed.topicId}`;

async function openTopic(page: Page) {
  await gotoHydrated(page, topicUrl);
  await expect(page.getByRole("heading", { level: 1, name: seed.topicName })).toBeVisible();
}

test("create, rename and delete a topic", async ({ page }) => {
  const name = `${seed.topicName} created`;
  await page.goto("/topics");
  await page.getByPlaceholder("New topic name").fill(name);
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page).toHaveURL(/\/topics$/);
  await page.getByRole("link", { name: new RegExp(name) }).first().click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  const renamed = `${seed.topicName} renamed`;
  const nameField = page.locator(".topic-detail-actions input[name=name]");
  await nameField.fill(renamed);
  await page.getByRole("button", { name: "Rename" }).click();
  await expect(page.getByRole("heading", { level: 1, name: renamed })).toBeVisible();

  await page.getByRole("button", { name: "Delete topic" }).click();
  await expect(page).toHaveURL(/\/topics$/);
  await expect(page.getByRole("link", { name: new RegExp(renamed) })).toHaveCount(0);
});

test("duplicate topic names are reported", async ({ page }) => {
  await page.goto("/topics");
  await page.getByPlaceholder("New topic name").fill(seed.topicName);
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page.locator(".error-banner")).toBeVisible();
});

test.describe.serial("working inside a seeded topic", () => {
  test("add, edit and delete a topic note", async ({ page }) => {
    await openTopic(page);
    const notes = page.locator(".topic-notes");
    await notes.getByPlaceholder("Add a note…").fill("e2e first note");
    await notes.getByRole("button", { name: "Add note" }).click();
    await expect(notes.locator("li > p", { hasText: "e2e first note" })).toBeVisible();

    await notes.locator("details.note-edit summary").first().click();
    await notes.locator("details.note-edit textarea").first().fill("e2e edited note");
    await notes.getByRole("button", { name: "Save" }).first().click();
    await expect(notes.locator("li > p", { hasText: "e2e edited note" })).toBeVisible();

    await notes.getByRole("button", { name: "Delete note" }).click();
    await expect(notes.locator("li > p", { hasText: "e2e edited note" })).toHaveCount(0);
  });

  test("add and remove a topic tag", async ({ page }) => {
    await openTopic(page);
    const tags = page.locator(".topic-tags");
    await tags.getByLabel("New tag").fill(" E2E-Tag ");
    await tags.getByRole("button", { name: "Add tag" }).click();
    const chip = tags.locator(".tag-chip");
    await expect(chip).toHaveCount(1);
    const tag = (await chip.textContent()) ?? "";
    await tags.getByRole("button", { name: `Remove tag ${tag}` }).click();
    await expect(tags.getByText("No tags yet")).toBeVisible();
  });

  test("upload, view and remove a topic image", async ({ page }) => {
    await openTopic(page);
    const images = page.locator(".topic-images");
    await images.locator("input[type=file]").setInputFiles({ name: "e2e.png", mimeType: "image/png", buffer: PNG_1x1 });
    await images.getByRole("button", { name: "Add image" }).click();
    const image = images.getByRole("img", { name: "e2e.png" });
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);

    await images.getByRole("button", { name: "Remove image e2e.png" }).click();
    await expect(images.getByRole("img")).toHaveCount(0);
  });

  test("rejects an upload that is not an image", async ({ page }) => {
    await openTopic(page);
    const images = page.locator(".topic-images");
    await images.locator("input[type=file]").setInputFiles({ name: "notes.png", mimeType: "image/png", buffer: Buffer.from("hello") });
    await images.getByRole("button", { name: "Add image" }).click();
    await expect(page.locator(".error-banner")).toBeVisible();
  });

  test("override, then clear, the topic priority", async ({ page }) => {
    await openTopic(page);
    // the priority panel is collapsed until its badge is clicked
    const panel = page.locator("#priority-details");
    await page.locator(".priority-toggle").click();
    await panel.locator(".priority-override-form select[name=priority]").selectOption("MAJOR");
    await panel.locator(".priority-override-form input[name=reason]").fill("e2e reason");
    await panel.getByRole("button", { name: "Override" }).click();
    await expect(page.locator(".priority-toggle")).toContainText("manual override");

    // the redirect lands on the same route, so the panel keeps its open state
    await expect(panel.getByText("Manually overridden to MAJOR — e2e reason")).toBeVisible();
    await panel.getByRole("button", { name: "Clear override" }).click();
    await expect(page.locator(".priority-toggle")).not.toContainText("manual override");
  });

  test("add and delete a manual item", async ({ page }) => {
    await openTopic(page);
    const description = `Try a quieter standup format (${seed.run})`;
    await page.locator("details.add-item summary", { hasText: "Add idea" }).click();
    await page.getByPlaceholder("Describe the idea…").fill(description);
    await page.getByRole("button", { name: "Add idea" }).click();
    const card = page.locator(".selectable-item", { hasText: description });
    await expect(card).toBeVisible();

    await card.locator("summary", { hasText: "Delete item" }).click();
    await card.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.locator(".selectable-item", { hasText: description })).toHaveCount(0);
  });

  test("move an item to another topic", async ({ page }) => {
    await openTopic(page);
    await page.locator(".selectable-item", { hasText: seed.itemDescription }).getByLabel("Select item").first().check();
    await page.locator(".bulk-move-bar select").selectOption({ label: seed.targetTopicName });
    await page.locator(".bulk-move-bar").getByRole("button", { name: "Move" }).click();
    await expect(page.locator(".selectable-item", { hasText: seed.itemDescription })).toHaveCount(0);

    await page.goto(`/topics/${seed.targetTopicId}`);
    await expect(page.locator(".selectable-item", { hasText: seed.itemDescription })).toBeVisible();
  });
});
