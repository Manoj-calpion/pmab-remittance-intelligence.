import { test, expect } from "@playwright/test";

test("sign-in states the product and does not require Central Reach", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Every remittance tells a story." })).toBeVisible();
  await expect(page.getByText("Central Reach is not required.")).toBeVisible();
});

test("reduced motion keeps the sign-in headline readable", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Every remittance tells a story." })).toBeVisible();
});
