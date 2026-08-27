import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./error";

describe("global operational error state", () => {
  it("keeps technical error details private and offers a safe retry", () => {
    const reset = vi.fn();
    render(
      <ErrorBoundary
        error={Object.assign(new Error("sensitive stack detail"), { digest: "441TEST" })}
        reset={reset}
      />,
    );

    expect(screen.queryByText("sensitive stack detail")).not.toBeInTheDocument();
    expect(screen.getByText("O que aconteceu")).toBeInTheDocument();
    expect(screen.getByText("Próxima ação")).toBeInTheDocument();
    expect(screen.getByText("Referência 441TEST")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(reset).toHaveBeenCalledOnce();
  });
});
