import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  recruitmentAdminFetch: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  recruitmentAdminFetch: mocks.recruitmentAdminFetch,
}));

vi.mock("../actions", () => ({
  addRecruitmentAdaptation: vi.fn(),
  addRecruitmentNote: vi.fn(),
  assignRecruitmentApplication: vi.fn(),
  decideRecruitmentApplication: vi.fn(),
  evaluateRecruitmentInterview: vi.fn(),
  reanalyzeRecruitmentApplication: vi.fn(),
  recordRecruitmentAnalysisFeedback: vi.fn(),
  scheduleRecruitmentInterview: vi.fn(),
}));

import RecruitmentDossierPage from "./page";

function dossier(status: string, assignedTo: number | null = null) {
  return {
    application: {
      id: 96,
      protocol: "AL-00096",
      candidate_nick: "Candidata",
      bgr_id: "BGR-96",
      discord_id: 123,
      discord_username: "candidata",
      age: 18,
      status,
      stage: status === "DRAFT" ? "APPLICATION" : "REVIEW",
      version: 1,
      assigned_to: assignedTo,
      submitted_at: status === "DRAFT" ? null : Date.now(),
    },
    questions: [],
    interviews: [],
    evaluations: [],
    history: [],
    notes: [],
    adaptations: [],
  };
}

async function renderDossier(status: string, assignedTo: number | null = null) {
  mocks.recruitmentAdminFetch.mockResolvedValue(dossier(status, assignedTo));
  render(
    await RecruitmentDossierPage({
      params: Promise.resolve({ id: "96" }),
    } as never),
  );
}

describe("recruitment assignment state", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not offer assignment while the candidate is still drafting", async () => {
    await renderDossier("DRAFT");

    expect(screen.queryByRole("button", { name: "Assumir análise" })).not.toBeInTheDocument();
    expect(screen.getByText("Aguardando o candidato concluir e enviar a candidatura.")).toBeInTheDocument();
  });

  it("offers assignment for an unassigned submitted application", async () => {
    await renderDossier("SUBMITTED");

    expect(screen.getByRole("button", { name: "Assumir análise" })).toBeInTheDocument();
  });

  it("does not offer a silent takeover when a reviewer is already assigned", async () => {
    await renderDossier("UNDER_REVIEW", 456);

    expect(screen.queryByRole("button", { name: "Assumir análise" })).not.toBeInTheDocument();
    expect(screen.getByText("456")).toBeInTheDocument();
  });
});
