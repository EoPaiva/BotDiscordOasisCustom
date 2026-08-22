import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProjectStatusPage from "./page";

describe("project status page", () => {
  it("shows the production exception without hiding the security debt", () => {
    render(<ProjectStatusPage />);

    expect(screen.getByText("21 / 24")).toBeInTheDocument();
    expect(screen.getByText("PAUSADO")).toBeInTheDocument();
    expect(screen.getByText("MANUTENÇÃO DE DEPLOY")).toBeInTheDocument();
    expect(screen.getByText("Rotação de credenciais e permissões mínimas")).toBeInTheDocument();
  });
});
