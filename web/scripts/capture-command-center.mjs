import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

const outputDirectory = resolve(process.cwd(), "..", "artifacts", "command-center");
await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
const targets = [
  { name: "dashboard-desktop", width: 1440, height: 1100 },
  { name: "dashboard-notebook", width: 1280, height: 1100 },
  { name: "dashboard-tablet", width: 1024, height: 1200 },
  { name: "dashboard-tablet-compact", width: 768, height: 1200 },
  { name: "dashboard-mobile", width: 390, height: 1100 },
];

try {
  for (const target of targets) {
    const context = await browser.newContext({
      viewport: { width: target.width, height: target.height },
      colorScheme: "dark",
    });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    const response = await page.goto("http://127.0.0.1:3000/dashboard", {
      waitUntil: "networkidle",
      timeout: 30_000,
    });
    if (!response?.ok()) throw new Error(`${target.name}: HTTP ${response?.status() ?? "sem resposta"}`);
    await page.getByRole("heading", { name: "Centro de Comando" }).waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) throw new Error(`${target.name}: overflow horizontal global`);
    if (consoleErrors.length) throw new Error(`${target.name}: ${consoleErrors.join(" | ")}`);
    await page.screenshot({
      path: resolve(outputDirectory, `${target.name}.png`),
      fullPage: true,
    });
    await context.close();
    process.stdout.write(`${target.name}:ok\n`);
  }
} finally {
  await browser.close();
}
