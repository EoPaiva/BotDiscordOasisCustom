import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
const layout = readFileSync(join(process.cwd(), "src/app/layout.tsx"), "utf8");

describe("CHOQUE visual contract", () => {
  it("centralizes the approved military command palette and system tokens", () => {
    expect(styles).toContain("--color-background: #080f12");
    expect(styles).toContain("--color-surface: #1a2126");
    expect(styles).toContain("--color-action: #2ecc71");
    expect(styles).toContain("--space-1: 4px");
    expect(styles).toContain("--space-8: 64px");
    expect(styles).toContain("--motion-fast: 160ms");
    expect(styles).toContain("--radius-control: 2px");
  });

  it("uses the approved technical display and legible interface typefaces", () => {
    expect(layout).toContain("Rajdhani");
    expect(layout).toContain("Inter");
    expect(layout).toContain("IBM_Plex_Mono");
    expect(layout).not.toContain("Source_Sans_3");
  });

  it("keeps operational controls touch-safe, explicit and usable on reduced-motion devices", () => {
    expect(styles).toContain("min-height: 44px");
    expect(styles).toContain('.button[aria-busy="true"]');
    expect(styles).toContain("env(safe-area-inset-left)");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
