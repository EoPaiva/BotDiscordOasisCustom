import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTable, EmptyState, Status } from "./ui";

describe("shared command center components", () => {
  it("maps operational states to an explicit visual status", () => {
    render(<Status value="REVIEW_REQUIRED" />);
    const status = screen.getByText("REVIEW REQUIRED");
    expect(status).toHaveClass("status-label", "warning");
  });

  it("preserves column labels for responsive table rows", () => {
    render(
      <DataTable
        columns={[{ key: "name", label: "Militar" }]}
        rows={[{ id: 1, name: "Sentinela" }]}
      />,
    );
    expect(screen.getByText("Sentinela")).toHaveAttribute("data-label", "Militar");
  });

  it("renders a semantic empty state", () => {
    render(<EmptyState title="Sem ocorrências" detail="Fila regular." />);
    expect(screen.getByText("Sem ocorrências")).toBeInTheDocument();
    expect(screen.getByText("Fila regular.")).toBeInTheDocument();
  });
});
