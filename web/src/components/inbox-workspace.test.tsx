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
});
