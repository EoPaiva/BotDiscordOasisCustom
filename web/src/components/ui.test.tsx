import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CommandState, DataTable, EmptyState, LoadingState, MetricStrip, Status } from "./ui";

describe("shared command center components", () => {
  it("maps operational states to an explicit visual status", () => {
    render(<Status value="REVIEW_REQUIRED" />);
    const status = screen.getByText("REVIEW REQUIRED");
    expect(status).toHaveClass("status-label", "warning");
  });

  it.each(["UNAVAILABLE", "INVALID", "INVALIDATED"])("never presents %s as a success", (value) => {
    render(<Status value={value} />);
    expect(screen.getByText(value)).toHaveClass("status-label", "danger");
  });

  it("accepts a contextual tone for ambiguous states", () => {
    render(<Status tone="danger" value="ACTIVE" />);
    expect(screen.getByText("ACTIVE")).toHaveClass("status-label", "danger");
  });

  it("preserves column labels for responsive table rows", () => {
    render(
      <DataTable
        caption="Efetivo em serviço"
        columns={[{ key: "name", label: "Militar" }]}
        rows={[{ id: 1, name: "Sentinela" }]}
      />,
    );
    expect(screen.getByText("Sentinela")).toHaveAttribute("data-label", "Militar");
    expect(screen.getByText("Efetivo em serviço").closest("caption")).toHaveClass("visually-hidden");
    expect(screen.getByRole("columnheader", { name: "Militar" })).toHaveAttribute("scope", "col");
    expect(screen.getByRole("region", { name: "Efetivo em serviço" })).toHaveAttribute("tabindex", "0");
  });

  it("renders a semantic empty state", () => {
    render(<EmptyState title="Sem ocorrências" detail="Fila regular." />);
    expect(screen.getByText("Sem ocorrências")).toBeInTheDocument();
    expect(screen.getByText("Fila regular.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("exposes metric labels and values as semantic term pairs", () => {
    const view = render(<MetricStrip items={[{ label: "EM PATRULHA", value: 4 }]} />);

    expect(view.container.querySelector("dl.metric-strip")).toBeInTheDocument();
    expect(screen.getByText("EM PATRULHA").closest("dt")).toBeInTheDocument();
    expect(screen.getByText("4").closest("dd")).toBeInTheDocument();
  });

  it("explains operational states with an outcome and a next action", () => {
    render(
      <CommandState
        code="SYS / FALHA"
        title="Comunicação interrompida"
        happened="O serviço não respondeu."
        next="Tente novamente em alguns instantes."
        reference="ABC123"
        tone="danger"
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("O que aconteceu").closest("dt")).toBeInTheDocument();
    expect(screen.getByText("O serviço não respondeu.").closest("dd")).toBeInTheDocument();
    expect(screen.getByText("Próxima ação").closest("dt")).toBeInTheDocument();
    expect(screen.getByText("Referência ABC123")).toBeInTheDocument();
  });

  it("announces loading while keeping skeletons decorative", () => {
    const view = render(<LoadingState label="Carregando recrutamento" />);
    expect(screen.getByRole("status", { name: "Carregando recrutamento" })).toHaveAttribute("aria-busy", "true");
    expect(view.container.querySelectorAll('[aria-hidden="true"].skeleton')).toHaveLength(3);
  });
});
