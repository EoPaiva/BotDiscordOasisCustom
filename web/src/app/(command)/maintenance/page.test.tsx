import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));
vi.mock("../actions", () => ({ setMaintenance: vi.fn() }));

import MaintenancePage from "./page";

describe("maintenance command center", () => {
  afterEach(() => vi.clearAllMocks());

  it("exposes the maintenance start as machine-readable time", async () => {
    api.commandCenterFetch.mockResolvedValue({
      maintenance: [{
        module_key: "PATROLS",
        active: true,
        reason: "Ajuste controlado",
        enabled_at: Date.parse("2026-08-27T05:29:00.000Z"),
      }],
    });

    render(await MaintenancePage());
    const module = screen.getByRole("heading", { name: "PATROLS" }).closest("article");
    const sinceField = within(module as HTMLElement).getByText("Desde").closest("div");
    const since = sinceField?.querySelector("dd time");

    expect(since).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(since).toHaveTextContent("27 de ago., 02:29");
  });
});
