import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(command)/actions", () => ({ decideInboxItem: vi.fn() }));

import { InboxWorkspace } from "./inbox-workspace";

describe("administrative inbox workspace", () => {
  it("exposes pending processes as a semantic list of selection buttons", () => {
    render(<InboxWorkspace items={[
      { type: "TRANSFER", id: 3, data: { mta_nick: "Sentinela", status: "PENDING" } },
      { type: "SHIFT_REVIEW", id: 4, data: { mta_nick: "Batedor", status: "PENDING" } },
    ]} />);

    const list = screen.getByRole("list", { name: "Pendências administrativas" });
    const buttons = within(list).getAllByRole("button");

    expect(list.tagName).toBe("UL");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveAttribute("aria-current", "true");
    const panel = screen.getByRole("article", { name: "TRANSFER" });
    expect(panel).toHaveAttribute("id");
    expect(buttons[0]).toHaveAttribute("aria-controls", panel.id);
    expect(buttons[1]).toHaveAttribute("aria-controls", panel.id);

    fireEvent.click(buttons[1]);

    expect(buttons[0]).not.toHaveAttribute("aria-current");
    expect(buttons[1]).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("heading", { name: "SHIFT REVIEW" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "SHIFT REVIEW" })).toBe(panel);
  });

  it("exposes valid inbox times in a machine-readable format", () => {
    const inboxTime = Date.parse("2026-08-26T15:30:00.000Z");
    const view = render(<InboxWorkspace items={[
      { type: "TRANSFER", id: 3, data: { inbox_time: inboxTime, status: "PENDING" } },
      { type: "SHIFT_REVIEW", id: 4, data: { status: "PENDING" } },
    ]} />);

    const times = within(view.container).getByRole("list", { name: "Pendências administrativas" }).querySelectorAll("time");

    expect(times).toHaveLength(2);
    expect(times[0]).toHaveAttribute("dateTime", "2026-08-26T15:30:00.000Z");
    expect(times[1]).not.toHaveAttribute("dateTime");
  });

  it("formats temporal fields in the decision panel without raw timestamps", () => {
    const timestamp = Date.parse("2026-08-26T15:30:00.000Z");
    const view = render(<InboxWorkspace items={[
      { type: "TRANSFER", id: 3, data: { inbox_time: timestamp, created_at: timestamp, status: "PENDING" } },
    ]} />);

    const panel = within(view.container).getByRole("article", { name: "TRANSFER" });
    const times = panel.querySelectorAll("dl.decision-fields time");

    expect(times).toHaveLength(2);
    expect(times[0]).toHaveAttribute("dateTime", "2026-08-26T15:30:00.000Z");
    expect(times[1]).toHaveAttribute("dateTime", "2026-08-26T15:30:00.000Z");
    expect(panel).not.toHaveTextContent(String(timestamp));
  });
});
