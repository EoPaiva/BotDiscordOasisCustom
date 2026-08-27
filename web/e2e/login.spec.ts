import { expect, test } from "@playwright/test";

test("login identifies the restricted command center", async ({ page }) => {
  const consoleErrors: string[] = [];
  await page.addInitScript(() => {
    const violations: Array<Record<string, string>> = [];
    Object.defineProperty(window, "__cspViolations", { value: violations });
    document.addEventListener("securitypolicyviolation", (event) => {
      violations.push({
        blockedURI: event.blockedURI,
        directive: event.effectiveDirective,
        sample: event.sample,
        sourceFile: event.sourceFile,
      });
    });
  });
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
  expect(csp).toContain("style-src-attr 'unsafe-hashes' 'sha256-zlqnbDt84zf1iSefLU/ImC54isoprH/MRiVZGskwexk='");
  expect(csp).not.toContain("unsafe-inline");
  expect(csp).not.toContain("unsafe-eval");
  const cspViolations = await page.evaluate(() => (
    window as typeof window & { __cspViolations: Array<Record<string, string>> }
  ).__cspViolations);
  expect(cspViolations).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
