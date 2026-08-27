import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));
vi.mock("@/components/live-data-refresh", () => ({ LiveDataRefresh: () => null }));

import PatrolsPage from "./page";

describe("patrols command center", () => {
  afterEach(() => vi.clearAllMocks());

  it("exposes active patrols as a named semantic list", async () => {
    const generatedAt = Date.parse("2026-08-27T05:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      active: [{
        id: 7,
        sequence_number: 12,
        status: "ACTIVE",
        voice_channel_name: "ROCAM 01",
        member_count: 3,
        commander_discord_id: "395061579101503491",
        commander_mta_nick: "Sentinela",
        commander_rank_prefix: "CAP",
        started_at: generatedAt - 60_000,
      }],
      queue: [],
    });

    render(await PatrolsPage());
    const patrols = screen.getByRole("list", { name: "Patrulhas em andamento" });

    expect(patrols.tagName).toBe("UL");
    expect(within(patrols).getAllByRole("listitem")).toHaveLength(1);
    const patrol = within(patrols).getByRole("article");
    expect(patrol).toBeInTheDocument();
    expect(within(patrols).getByText("ROCAM 01")).toBeInTheDocument();
    expect(within(patrols).getByText("[CAP] Sentinela")).toBeInTheDocument();
    const patrolDuration = patrol.querySelector(".patrol-time time");
    expect(patrolDuration).toHaveAttribute("dateTime", "PT1M");
    expect(patrolDuration).toHaveTextContent("1m");
    const patrolStartedAt = patrol.querySelector(".patrol-time span time");
    expect(patrolStartedAt).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(patrolStartedAt).toHaveTextContent("27 de ago., 02:29");
  });

  it("exposes the FIFO entry timestamp as machine-readable time", async () => {
    api.commandCenterFetch.mockResolvedValue({
      generated_at: Date.parse("2026-08-27T05:30:00.000Z"),
      active: [],
      queue: [{
        id: 8,
        mta_nick: "Sentinela",
        queue_entered_at: Date.parse("2026-08-27T05:29:00.000Z"),
        status: "QUEUED",
      }],
    });

    render(await PatrolsPage());
    const queue = screen.getByRole("region", { name: "Fila de patrulha" });
    const queueEnteredAt = queue.querySelector("time");

    expect(queueEnteredAt).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(queueEnteredAt).toHaveTextContent("27 de ago., 02:29");
  });
});
