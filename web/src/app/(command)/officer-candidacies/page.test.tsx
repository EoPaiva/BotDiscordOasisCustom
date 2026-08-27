import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ commandCenterFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({ commandCenterFetch: api.commandCenterFetch }));

import OfficerCandidaciesPage from "./page";

describe("officer candidacy queue", () => {
  afterEach(() => vi.clearAllMocks());

  it("names the filter form and its controls", async () => {
    api.commandCenterFetch.mockResolvedValue([]);

    render(await OfficerCandidaciesPage({
      searchParams: Promise.resolve({}),
    } as PageProps<"/officer-candidacies">));
    const filters = screen.getByRole("form", { name: "Filtros das candidaturas ao Oficialato" });

    expect(within(filters).getByRole("combobox", { name: "Filtrar por status" })).toBeInTheDocument();
    expect(within(filters).getByRole("textbox", { name: "Filtrar por ID do responsável" })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: "Filtrar" })).toBeInTheDocument();
  });
});
