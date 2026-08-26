import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));
vi.mock("@/components/live-data-refresh", () => ({ LiveDataRefresh: () => null }));

import DashboardPage from "./page";

describe("command dashboard snapshot", () => {
  afterEach(() => vi.clearAllMocks());

  it("anchors the situation timestamp to the backend snapshot", async () => {
    const generatedAt = Date.parse("2026-08-26T15:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      readiness: { counts: {} },
      patrols: [],
      queue: [],
      inbox: [],
      changes: { counts: {}, events: [] },
      capabilities: {
        view_inbox: false,
        view_changes: false,
        view_all_operations: false,
      },
    });

    const view = render(await DashboardPage());
    const snapshotTime = view.container.querySelector("time");

    expect(snapshotTime).toHaveAttribute("dateTime", "2026-08-26T15:30:00.000Z");
    expect(snapshotTime).toHaveTextContent("26 de agosto de 2026");
    expect(snapshotTime).toHaveTextContent("12:30");
  });

  it("exposes the FIFO queue as an ordered list", async () => {
    const generatedAt = Date.parse("2026-08-26T15:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      readiness: { counts: {} },
      patrols: [],
      queue: [{ id: 7, mta_nick: "Sentinela", queue_entered_at: generatedAt - 60_000 }],
      inbox: [],
      changes: { counts: {}, events: [] },
      capabilities: {
        view_inbox: false,
        view_changes: false,
        view_all_operations: false,
      },
    });

    render(await DashboardPage());
    const queue = screen.getByRole("list", { name: "Fila operacional em ordem FIFO" });

    expect(queue.tagName).toBe("OL");
    expect(within(queue).getAllByRole("listitem")).toHaveLength(1);
    expect(within(queue).getByText("Sentinela")).toBeInTheDocument();
  });

  it("exposes recent administrative items as a semantic list", async () => {
    const generatedAt = Date.parse("2026-08-26T15:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      readiness: { counts: {} },
      patrols: [],
      queue: [],
      inbox: [{
        id: 3,
        type: "TRANSFER",
        data: { code: "TRF-003", status: "PENDING", created_at: generatedAt },
      }],
      changes: { counts: {}, events: [] },
      capabilities: {
        view_inbox: true,
        view_changes: false,
        view_all_operations: false,
      },
    });

    const view = render(await DashboardPage());
    const inbox = within(view.container).getByRole("list", {
      name: "Pendências administrativas recentes",
    });

    expect(inbox.tagName).toBe("UL");
    expect(within(inbox).getAllByRole("listitem")).toHaveLength(1);
    expect(within(inbox).getByRole("link", { name: /TRF-003/ })).toHaveAttribute("href", "/inbox");
    expect(inbox.querySelector("time")).toHaveAttribute("dateTime", "2026-08-26T15:30:00.000Z");
  });

  it("exposes the change briefing as a semantic list", async () => {
    const generatedAt = Date.parse("2026-08-26T15:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      readiness: { counts: {} },
      patrols: [],
      queue: [],
      inbox: [],
      changes: { counts: { promotions: 2, transfers: 1 }, events: [] },
      capabilities: {
        view_inbox: false,
        view_changes: true,
        view_all_operations: false,
      },
    });

    const view = render(await DashboardPage());
    const briefing = within(view.container).getByRole("list", {
      name: "Resumo de mudanças dos últimos 7 dias",
    });

    expect(briefing.tagName).toBe("UL");
    expect(within(briefing).getAllByRole("listitem")).toHaveLength(2);
    expect(within(briefing).getByText("promotions")).toBeInTheDocument();
    expect(within(briefing).getByText("2")).toBeInTheDocument();
  });

  it("exposes active patrol records as a semantic list", async () => {
    const generatedAt = Date.parse("2026-08-26T15:30:00.000Z");
    api.commandCenterFetch.mockResolvedValue({
      generated_at: generatedAt,
      readiness: { counts: {} },
      patrols: [{
        id: 5,
        sequence_number: 5,
        status: "ACTIVE",
        voice_channel_name: "CALL ALFA",
        member_names: "Sentinela",
        member_count: 1,
        started_at: generatedAt - 60_000,
      }],
      queue: [],
      inbox: [],
      changes: { counts: {}, events: [] },
      capabilities: {
        view_inbox: false,
        view_changes: false,
        view_all_operations: false,
      },
    });

    const view = render(await DashboardPage());
    const patrols = within(view.container).getByRole("list", {
      name: "Patrulhas em andamento",
    });

    expect(patrols.tagName).toBe("UL");
    expect(within(patrols).getAllByRole("listitem")).toHaveLength(1);
    expect(within(patrols).getByRole("article")).toHaveTextContent("Sentinela");
    expect(within(patrols).getByText("CALL ALFA")).toBeInTheDocument();
  });
});
