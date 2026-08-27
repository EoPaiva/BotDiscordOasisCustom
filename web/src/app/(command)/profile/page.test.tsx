import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getAccessContext: vi.fn() }));

vi.mock("@/lib/api", () => ({ getAccessContext: api.getAccessContext }));

import ProfilePage from "./page";

describe("functional identity profile", () => {
  afterEach(() => vi.clearAllMocks());

  it("exposes the latest Discord sync as machine-readable time", async () => {
    api.getAccessContext.mockResolvedValue({
      member: {
        discord_id: "395061579101503491",
        mta_nick: "Sentinela",
        rank: { name: "Capitão" },
        primary_position: { name: "Comando" },
        functions: [],
        identity_sync_status: "SYNCED",
        discord_present: true,
        discord_synced_at: Date.parse("2026-08-27T05:29:00.000Z"),
      },
      access: { profile_name: "ALTO COMANDO", authorization_version: 7 },
    });

    render(await ProfilePage());
    const latestSyncLabel = screen.getByText("Último sync");
    const latestSync = latestSyncLabel.closest("div")?.querySelector("dd time");

    expect(latestSync).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(latestSync).toHaveTextContent("27 de ago., 02:29");
  });
});
