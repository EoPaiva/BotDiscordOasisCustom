import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProjectStatusPage from "./page";

describe("project status page", () => {
  it("shows the current Discloud production state without hiding external debt", () => {
    render(<ProjectStatusPage />);

    expect(screen.getByText("OPERAÇÃO ONLINE")).toBeInTheDocument();
    expect(screen.getByText("Discloud Diamond · instância única")).toBeInTheDocument();
    expect(screen.getByText("V27")).toBeInTheDocument();
    expect(screen.getByText("Rotação de credenciais e menor privilégio")).toBeInTheDocument();
  });
});
