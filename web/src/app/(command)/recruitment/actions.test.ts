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
    requestCommandCenter: vi.fn(),
    revalidatePath: vi.fn(),
    redirect: vi.fn((location: string) => {
      throw new Error(`REDIRECT:${location}`);
    }),
  };
});

vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/lib/api", () => ({
  CommandCenterApiError: mocks.ApiError,
  recruitmentAdminFetch: mocks.requestCommandCenter,
}));

import { assignRecruitmentApplication, decideRecruitmentApplication } from "./actions";

const initialState = { kind: "idle" as const, message: "" };

describe("recruitment server actions", () => {
  beforeEach(() => {
    mocks.requestCommandCenter.mockReset();
    mocks.revalidatePath.mockReset();
    mocks.redirect.mockClear();
  });

  it("sends an expired recent-authentication session to the renewal flow", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError("Autenticação recente necessária. Entre novamente.", 401, "corr-1"),
    );
    const formData = new FormData();
    formData.set("applicationId", "20");
    formData.set("expectedVersion", "1");

    await expect(assignRecruitmentApplication(initialState, formData)).rejects.toThrow(
      "REDIRECT:/login?reauth=1&returnTo=%2Frecruitment%2F20",
    );
    expect(mocks.redirect).toHaveBeenCalledWith("/login?reauth=1&returnTo=%2Frecruitment%2F20");
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it("returns an expected conflict instead of crashing the recruitment route", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError("Transição de candidatura inválida.", 409, "corr-conflict"),
    );
    const formData = new FormData();
    formData.set("applicationId", "96");
    formData.set("expectedVersion", "1");

    await expect(assignRecruitmentApplication(initialState, formData)).resolves.toEqual({
      kind: "error",
      message: "Transição de candidatura inválida.",
      reference: "corr-conflict",
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/recruitment/96");
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/recruitment");
  });

  it("keeps assignment on the dossier while the API is updating", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError("Falha ao processar a operação.", 500, "corr-rollout-assign"),
    );
    const formData = new FormData();
    formData.set("applicationId", "95");
    formData.set("expectedVersion", "3");

    await expect(assignRecruitmentApplication(initialState, formData)).resolves.toEqual({
      kind: "error",
      message: "Não foi possível concluir agora. O sistema pode estar sendo atualizado; aguarde alguns segundos e tente novamente.",
      reference: "corr-rollout-assign",
    });
  });

  it("uses the same safe recovery for final approval and rejection", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError("Autenticação recente necessária. Entre novamente.", 401, "corr-2"),
    );
    const formData = new FormData();
    formData.set("applicationId", "20");
    formData.set("expectedVersion", "1");
    formData.set("decision", "approve");
    formData.set("internalReason", "Revisão humana concluída.");
    formData.set("candidateMessage", "Sua candidatura foi aprovada.");
    formData.set("confirmation", "CONFIRMAR");

    await expect(decideRecruitmentApplication(initialState, formData)).rejects.toThrow(
      "REDIRECT:/login?reauth=1&returnTo=%2Frecruitment%2F20",
    );
    expect(mocks.redirect).toHaveBeenCalledTimes(1);
  });

  it("shows an identity conflict without crashing the dossier", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError(
        "O ID in-game informado já está vinculado a outro perfil.",
        409,
        "corr-identity",
      ),
    );
    const formData = new FormData();
    formData.set("applicationId", "95");
    formData.set("expectedVersion", "3");
    formData.set("decision", "approve");
    formData.set("internalReason", "Revisão humana concluída.");
    formData.set("candidateMessage", "Sua candidatura foi aprovada.");
    formData.set("confirmation", "CONFIRMAR");

    await expect(decideRecruitmentApplication(initialState, formData)).resolves.toEqual({
      kind: "error",
      message: "O ID in-game informado já está vinculado a outro perfil.",
      reference: "corr-identity",
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/recruitment/95");
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/recruitment");
  });

  it.each(["approve", "reject"] as const)(
    "returns invalid final-decision fields inline instead of crashing the dossier for %s",
    async (decision) => {
      const formData = new FormData();
      formData.set("applicationId", "95");
      formData.set("expectedVersion", "3");
      formData.set("decision", decision);
      formData.set("internalReason", "   ");
      formData.set("candidateMessage", "");
      formData.set("confirmation", "CONFIRMAR");

      await expect(decideRecruitmentApplication(initialState, formData)).resolves.toEqual({
        kind: "error",
        message: "Preencha o motivo interno e a mensagem ao candidato com 3 a 2.000 caracteres cada.",
      });
      expect(mocks.requestCommandCenter).not.toHaveBeenCalled();
      expect(mocks.revalidatePath).not.toHaveBeenCalled();
    },
  );

  it("returns an invalid confirmation inline instead of throwing a Zod error", async () => {
    const formData = new FormData();
    formData.set("applicationId", "95");
    formData.set("expectedVersion", "3");
    formData.set("decision", "approve");
    formData.set("internalReason", "Revisão humana concluída.");
    formData.set("candidateMessage", "Sua candidatura foi aprovada.");
    formData.set("confirmation", "confirmar");

    await expect(decideRecruitmentApplication(initialState, formData)).resolves.toEqual({
      kind: "error",
      message: "Digite CONFIRMAR no campo de confirmação antes de concluir a decisão.",
    });
    expect(mocks.requestCommandCenter).not.toHaveBeenCalled();
  });

  it("keeps approval on the dossier when an older backend returns 500", async () => {
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.ApiError("Falha ao processar a operação.", 500, "corr-rollout-approve"),
    );
    const formData = new FormData();
    formData.set("applicationId", "95");
    formData.set("expectedVersion", "3");
    formData.set("decision", "approve");
    formData.set("internalReason", "Revisão humana concluída.");
    formData.set("candidateMessage", "Sua candidatura foi aprovada.");
    formData.set("confirmation", "CONFIRMAR");

    await expect(decideRecruitmentApplication(initialState, formData)).resolves.toEqual({
      kind: "error",
      message: "Não foi possível concluir agora. O sistema pode estar sendo atualizado; aguarde alguns segundos e tente novamente.",
      reference: "corr-rollout-approve",
    });
  });
});
