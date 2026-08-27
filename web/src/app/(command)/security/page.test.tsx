import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));
vi.mock("../actions", () => ({
  revokeSecuritySessions: vi.fn(),
  setSecurityLockdown: vi.fn(),
}));

import SecurityPage from "./page";

const timestamp = Date.parse("2026-08-27T05:29:00.000Z");

describe("security command center", () => {
  beforeEach(() => {
    api.commandCenterFetch.mockResolvedValue({
      lockdown: {
        active: true,
        reason: "Contenção controlada",
        changed_at: timestamp,
      },
      last_24_hours: [],
      events: [{
        id: 1,
        created_at: timestamp,
        severity: "WARNING",
        event_type: "SESSION_REVOKED",
        result: "SUCCESS",
        actor_discord_id: "123",
        route: "/v1/security",
        request_id: "req-1",
      }],
      health: { api: "ONLINE", database: "ONLINE", migration: 54, failed_jobs: 0 },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("exposes the lockdown start as machine-readable time", async () => {
    render(await SecurityPage());
    const lockdown = screen.getByText("SECURITY LOCKDOWN ATIVO").closest("div");
    const changedAt = lockdown?.querySelector("p time");

    expect(lockdown).toHaveTextContent("Contenção controlada Desde 27 de ago., 02:29.");
    expect(changedAt).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(changedAt).toHaveTextContent("27 de ago., 02:29");
  });

  it("exposes security event timestamps as machine-readable time", async () => {
    render(await SecurityPage());
    const events = screen.getByRole("region", { name: "Eventos recentes de segurança" });
    const createdAt = events.querySelector("tbody time");

    expect(createdAt).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(createdAt).toHaveTextContent("27 de ago., 02:29");
  });
});
