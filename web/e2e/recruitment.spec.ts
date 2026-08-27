import { expect, test } from "@playwright/test";

test("recruitment portal keeps its public military layout without exposing data", async ({ page }) => {
  await page.goto("/recrutamento");
  await expect(page).toHaveTitle(/Recrutamento/);
  await expect(
    page.getByRole("heading", { name: /Seu primeiro passo começa pela postura/i }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "O que você precisa" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Simples do início ao resultado." }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Iniciar candidatura/i })).toBeVisible();
  await expect(page.getByText("10 QUESTÕES", { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText("Decisão final sempre realizada por pessoa autorizada."),
  ).toBeVisible();
  await expect(
    page.getByText("Alistamento oficial • dados protegidos por controle de acesso"),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(1);

  const unnamedControls = await page.locator(
    "a, button, input:not([type='hidden']), select, textarea",
  ).evaluateAll(
    (nodes) => nodes.filter((node) => {
      const element = node as HTMLElement;
      const name = element.getAttribute("aria-label")
        || element.getAttribute("title")
        || element.textContent?.trim()
        || (element instanceof HTMLInputElement ? element.labels?.[0]?.textContent?.trim() : "");
      return !name;
    }).length,
  );
  expect(unnamedControls).toBe(0);
});
