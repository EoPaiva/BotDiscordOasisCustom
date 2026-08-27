import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));

import ChangesPage from "./page";

describe("changes briefing", () => {
  afterEach(() => vi.clearAllMocks());

  it("exposes the briefing start as machine-readable time", async () => {
    api.commandCenterFetch.mockResolvedValue({
      period_days: 7,
      since: Date.parse("2026-08-27T05:29:00.000Z"),
      counts: {},
      events: [],
    });

    const view = render(await ChangesPage());
    const briefing = view.container.querySelector(".page-header p");
    const since = briefing?.querySelector("time");

    expect(briefing).toHaveTextContent("Briefing operacional desde 27 de ago., 02:29.");
    expect(since).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(since).toHaveTextContent("27 de ago., 02:29");
  });

  it("exposes event timestamps as machine-readable time", async () => {
    api.commandCenterFetch.mockResolvedValue({
      period_days: 7,
      since: Date.parse("2026-08-20T05:29:00.000Z"),
      counts: {},
      events: [{
        id: 1,
        created_at: Date.parse("2026-08-27T05:29:00.000Z"),
        event_type: "PROMOTION",
        aggregate_type: "MEMBER",
        aggregate_id: 7,
      }],
    });

    const view = render(await ChangesPage());
    const timeline = view.getByRole("region", { name: "Linha de mudanças" });
    const eventTime = timeline.querySelector("tbody time");

    expect(eventTime).toHaveAttribute("dateTime", "2026-08-27T05:29:00.000Z");
    expect(eventTime).toHaveTextContent("27 de ago., 02:29");
  });
});
