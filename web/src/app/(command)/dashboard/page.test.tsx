import { render } from "@testing-library/react";
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
});
