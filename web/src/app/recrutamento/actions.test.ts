import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  class ApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
      readonly correlationId: string,
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    candidateFetch: vi.fn(),
    redirect: vi.fn((location: string) => {
      throw new Error(`REDIRECT:${location}`);
    }),
    revalidatePath: vi.fn(),
    setGuestIdentity: vi.fn(),
  };
});

vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/lib/api", () => ({
  CommandCenterApiError: mocks.ApiError,
  recruitmentCandidateFetch: mocks.candidateFetch,
}));
vi.mock("@/lib/identity", () => ({
  setRecruitmentGuestIdentity: mocks.setGuestIdentity,
}));

import { startRecruitmentApplication } from "./actions";

function validFormData() {
  const formData = new FormData();
  formData.set("discordId", "689953336941609088");
  formData.set("discordUsername", "candidato");
  formData.set("candidateNick", "Candidato BGR");
  formData.set("bgrId", "3270");
  formData.set("age", "18");
  formData.set("consent", "accepted");
  return formData;
}

describe("candidate recruitment start", () => {
  beforeEach(() => {
    mocks.candidateFetch.mockReset();
    mocks.redirect.mockClear();
    mocks.setGuestIdentity.mockReset();
  });

  it("redirects an eligible candidate to the assessment", async () => {
    mocks.candidateFetch.mockResolvedValue({ application_id: 1 });

    await expect(startRecruitmentApplication(validFormData())).rejects.toThrow(
      "REDIRECT:/recrutamento/avaliacao",
    );
    expect(mocks.setGuestIdentity).toHaveBeenCalledWith(
      "689953336941609088",
      "candidato",
    );
  });

  it("returns a cooldown conflict to the landing page instead of React error 441", async () => {
    mocks.candidateFetch.mockRejectedValue(
      new mocks.ApiError("Candidatura indisponível: COOLDOWN_ACTIVE", 409, "corr-1"),
    );

    await expect(startRecruitmentApplication(validFormData())).rejects.toThrow(
      "REDIRECT:/recrutamento",
    );
    expect(mocks.redirect).toHaveBeenCalledTimes(1);
  });

  it("does not hide unexpected API failures", async () => {
    mocks.candidateFetch.mockRejectedValue(
      new mocks.ApiError("Falha da API", 500, "corr-2"),
    );

    await expect(startRecruitmentApplication(validFormData())).rejects.toThrow("Falha da API");
    expect(mocks.redirect).not.toHaveBeenCalled();
  });
});
