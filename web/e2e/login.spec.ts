import { expect, test } from "@playwright/test";

test("login identifies the restricted command center", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  const response = await page.goto("/login");
  const csp = response?.headers()["content-security-policy"] ?? "";
  await expect(page).toHaveTitle(/Centro de Comando/);
  await expect(page.getByRole("heading", { name: "CHOQUE BGR" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Identificação operacional" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("OAuth Discord ainda não configurado");
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
  expect(csp).toContain("script-src 'self' 'nonce-");
  expect(csp).toContain("style-src 'self' 'nonce-");
  expect(csp).not.toContain("unsafe-inline");
  expect(csp).not.toContain("unsafe-eval");
  expect(consoleErrors).toEqual([]);
});
