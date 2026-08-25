import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

describe("public short links", () => {
  it("redirects /discord permanently to the official non-expiring invite", async () => {
    const redirects = await nextConfig.redirects?.();

    expect(redirects).toContainEqual({
      source: "/discord",
      destination: "https://discord.gg/A2gcq6Vcmm",
      permanent: true,
    });
  });
});
