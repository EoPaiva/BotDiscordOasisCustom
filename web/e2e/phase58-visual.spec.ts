import { expect, test } from "@playwright/test";

const surfaces = [
  { heading: "CHOQUE BGR", path: "/login", slug: "login" },
  { heading: "SEU PRIMEIRO PASSO COMEÇA PELA POSTURA.", path: "/recrutamento", slug: "recrutamento" },
  { heading: "ACESSO NÃO AUTORIZADO", path: "/access-denied", slug: "access-denied" },
] as const;

test("phase 58 surfaces fit the desktop and 390px viewports", async ({ browserName, page }, testInfo) => {
  test.skip(browserName !== "chromium", "Visual acceptance is captured once per target viewport in Chromium.");

  const mobile = testInfo.project.name === "mobile-chromium";
  const viewport = mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 };
  await page.setViewportSize(viewport);

  for (const surface of surfaces) {
    await page.goto(surface.path);
    await expect(page.getByRole("heading", { name: surface.heading })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(horizontalOverflow, `${surface.path} must not overflow at ${viewport.width}px`).toBe(0);

    await page.screenshot({
      animations: "disabled",
      fullPage: true,
      path: testInfo.outputPath(`${surface.slug}-${viewport.width}.png`),
    });
  }
});
