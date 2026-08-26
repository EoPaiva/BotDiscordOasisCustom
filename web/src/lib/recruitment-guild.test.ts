import { beforeEach, describe, expect, it, vi } from "vitest";

const cookieGet = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: cookieGet }),
}));

describe("recruitment guild routing", () => {
  beforeEach(() => {
    vi.resetModules();
    cookieGet.mockReset();
    process.env.DEFAULT_GUILD_ID = "1146622062895579186";
    delete process.env.RECRUITMENT_GUILD_IDS;
    delete process.env.RECRUITMENT_DEFAULT_GUILD_ID;
  });

  it("routes new recruitment traffic to REC without an explicit context", async () => {
    cookieGet.mockReturnValue(undefined);
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });

  it("routes the REC context to the secondary guild", async () => {
    cookieGet.mockReturnValue({ value: "1541908574463070311" });
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });

  it("keeps the primary guild when its context is explicit", async () => {
    cookieGet.mockReturnValue({ value: "1146622062895579186" });
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1146622062895579186");
  });

  it("ignores an untrusted guild cookie and falls back to REC", async () => {
    cookieGet.mockReturnValue({ value: "999999999999999999" });
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });
});
