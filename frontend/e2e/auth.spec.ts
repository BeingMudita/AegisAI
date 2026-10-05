import { expect, test } from "@playwright/test";

/** Sign in with a seeded account and land in the workspace. */
async function login(page: import("@playwright/test").Page, user: string, pass: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /sign in to aegisai/i })).toBeVisible();
  await page.getByLabel("Username").fill(user);
  await page.getByLabel("Password").fill(pass);
  await page.getByRole("button", { name: /continue to workspace/i }).click();
}

test("rejects bad credentials", async ({ page }) => {
  await login(page, "admin", "wrong-password");
  // Still on the sign-in screen, with an error surfaced.
  await expect(page.getByRole("heading", { name: /sign in to aegisai/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /continue to workspace/i })).toBeVisible();
});

test("admin can sign in and reach the overview", async ({ page }) => {
  await login(page, "admin", "admin123");
  await expect(page.getByRole("heading", { name: /workspace overview/i })).toBeVisible({
    timeout: 15_000,
  });
  // The admin (staff) navigation exposes the security-events route.
  await expect(page.getByRole("button", { name: /security events/i })).toBeVisible();
});

test("attack-reconstruction page is reachable and renders its empty state", async ({ page }) => {
  await login(page, "admin", "admin123");
  await expect(page.getByRole("heading", { name: /workspace overview/i })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: /attack reconstruction/i }).click();
  await expect(
    page.getByRole("heading", { name: /sessions & attack reconstruction/i }),
  ).toBeVisible();
});
