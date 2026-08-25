import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("official Discord invite route", () => {
  it("permanently redirects to the official invitation without involving authentication", async () => {
    const response = await GET();

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("https://discord.gg/A2gcq6Vcmm");
  });
});
