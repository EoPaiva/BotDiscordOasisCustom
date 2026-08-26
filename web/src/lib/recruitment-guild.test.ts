import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: vi.fn() }),
}));

describe("recruitment guild routing", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.DEFAULT_GUILD_ID = "1146622062895579186";
    delete process.env.RECRUITMENT_GUILD_IDS;
    delete process.env.RECRUITMENT_DEFAULT_GUILD_ID;
  });

  it("routes new recruitment traffic to REC without an explicit context", async () => {
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });

  it("routes the REC context to the secondary guild", async () => {
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });

  it("ignores a stale primary-guild cookie after the definitive cutover", async () => {
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });

  it("ignores an untrusted guild cookie and falls back to REC", async () => {
    const { getRecruitmentGuildId } = await import("./recruitment-guild");
    await expect(getRecruitmentGuildId()).resolves.toBe("1541908574463070311");
  });
});
