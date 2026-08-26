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

    await expect(assignRecruitmentApplication(formData)).rejects.toThrow(
      "REDIRECT:/login?reauth=1&returnTo=%2Frecruitment%2F20",
    );
    expect(mocks.redirect).toHaveBeenCalledWith("/login?reauth=1&returnTo=%2Frecruitment%2F20");
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
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

    await expect(decideRecruitmentApplication(formData)).rejects.toThrow(
      "REDIRECT:/login?reauth=1&returnTo=%2Frecruitment%2F20",
    );
    expect(mocks.redirect).toHaveBeenCalledTimes(1);
  });
});
