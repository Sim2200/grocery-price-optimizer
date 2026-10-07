import { test, expect } from "@playwright/test";

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.request.post("/api/demo/load", {
    data: { reset: true },
  });
  await context.close();
});

test("main flow", async ({ page }) => {
  // Prices page: filter and select a product
  await page.goto("/prices");
  await expect(page.locator("table")).toBeVisible();

  const filterCombobox = page.getByRole("combobox", {
    name: "Filter products or categories",
  });
  await filterCombobox.fill("apple");
  await page.waitForTimeout(300);
  const listbox = page.getByRole("listbox");
  await expect(listbox).toBeVisible();
  const option = listbox.getByRole("option").first();
  await expect(option).toBeVisible();
  await option.click();

  // Check that a product heading is visible after selection (the selected-heading)
  const heading = page.getByRole("heading", { level: 2, name: /^apple/ });
  await expect(heading).toBeVisible();

  // Watchlist: add a product
  const productCombobox = page.getByRole("combobox", { name: "Product", exact: true });
  await productCombobox.fill("banana");
  await page.waitForTimeout(300);
  const watchlistListbox = productCombobox.locator("~ ul[role='listbox']");
  await expect(watchlistListbox).toBeVisible();
  const watchlistOption = watchlistListbox.getByRole("option").first();
  await watchlistOption.click();

  const targetPriceInput = page
    .getByLabel(/^Target price/)
    .first();
  await targetPriceInput.fill("0.5");

  await page.getByRole("button", { name: "Watch" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "banana" })).toBeVisible();

  // Remove from watchlist
  const removeButton = page.getByRole("button", { name: /Remove banana/ });
  await removeButton.click();
  await expect(page.getByRole("listitem").filter({ hasText: "banana" })).not.toBeVisible();

  // Plan page
  await page.goto("/plan");
  await page.getByRole("button", { name: "Use sample list" }).click();
  await page.getByRole("button", { name: "Plan my trip" }).click();
  await expect(page.getByText("Optimal plan (MILP)")).toBeVisible();

  // Insights page
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Spending" })).toBeVisible();
});
