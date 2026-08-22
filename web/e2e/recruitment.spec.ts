import { expect, test } from "@playwright/test";

test("recruitment portal keeps its public military layout without exposing data", async ({ page }) => {
  await page.goto("/recrutamento");
  await expect(page).toHaveTitle(/Centro de Comando/);
  await expect(page.getByRole("heading", { name: /Disciplina antes da função/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Antes de iniciar" })).toBeVisible();
  await expect(page.getByText("Decisão final realizada por pessoa autorizada")).toBeVisible();
  await expect(page.getByText("Dados protegidos por controle de acesso e trilha de auditoria")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
});
