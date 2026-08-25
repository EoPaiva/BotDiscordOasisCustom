import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  requestCommandCenter: vi.fn(),
  revalidatePath: vi.fn(),
  redirect: vi.fn(),
  CommandCenterApiError: class CommandCenterApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
      readonly correlationId: string,
    ) {
      super(message);
    }
  },
}));

vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/lib/api", () => ({
  CommandCenterApiError: mocks.CommandCenterApiError,
  commandCenterFetch: mocks.requestCommandCenter,
}));

import { setMemberQualification } from "./actions";

describe("qualification server actions", () => {
  beforeEach(() => {
    mocks.requestCommandCenter.mockReset();
    mocks.revalidatePath.mockReset();
    mocks.redirect.mockReset();
  });

  it("keeps a Discord snowflake exact instead of coercing it to an unsafe JavaScript number", async () => {
    const discordId = "1146622062895579186";
    const formData = new FormData();
    formData.set("discordId", discordId);
    formData.set("courseId", "12");
    formData.set("granted", "true");

    await setMemberQualification(formData);

    expect(mocks.requestCommandCenter).toHaveBeenCalledWith(
      "/v1/qualifications/manage",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          discord_id: discordId,
          course_id: 12,
          granted: true,
          reason: "Qualificação concedida pelo Centro de Comando.",
        }),
      }),
    );
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/qualifications");
    expect(mocks.revalidatePath).toHaveBeenCalledWith(`/members/${discordId}`);
  });

  it("rejects IDs that are not valid Discord snowflakes before requesting the API", async () => {
    const formData = new FormData();
    formData.set("discordId", "not-a-discord-id");
    formData.set("courseId", "12");
    formData.set("granted", "false");

    await expect(setMemberQualification(formData)).rejects.toThrow();
    expect(mocks.requestCommandCenter).not.toHaveBeenCalled();
  });

  it("returns to the matrix with a clear notice when the displayed member was removed", async () => {
    const formData = new FormData();
    formData.set("discordId", "1146622062895579186");
    formData.set("courseId", "12");
    formData.set("granted", "true");
    mocks.requestCommandCenter.mockRejectedValue(
      new mocks.CommandCenterApiError("Membro cadastrado não encontrado.", 404, "test-correlation"),
    );

    await setMemberQualification(formData);

    expect(mocks.redirect).toHaveBeenCalledWith("/qualifications?notice=member-not-found");
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });
});
