import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProjectStatusPage from "./page";

describe("project status page", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("shows factual health without stale test or migration counters", async () => {
    vi.stubEnv("COMMAND_CENTER_API_URL", "https://api.example.test");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    render(await ProjectStatusPage());

    expect(screen.getByText("OPERAÇÃO ONLINE")).toBeInTheDocument();
    expect(screen.getByText("Healthcheck direto, sem valor simulado")).toBeInTheDocument();
    expect(screen.queryByText("V27")).not.toBeInTheDocument();
    expect(screen.queryByText("307+")).not.toBeInTheDocument();
  });

  it("reports an unavailable API instead of claiming it is online", async () => {
    vi.stubEnv("COMMAND_CENTER_API_URL", "https://api.example.test");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));
    render(await ProjectStatusPage());
    expect(screen.getByText("VERIFICAÇÃO INDISPONÍVEL")).toBeInTheDocument();
    expect(screen.getByText("SEM RESPOSTA")).toBeInTheDocument();
  });
});
