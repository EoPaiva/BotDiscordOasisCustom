import { describe, expect, it } from "vitest";

import { normalizeCommandCenterPath } from "./request-target";

describe("command center request targets", () => {
  it("removes an empty trailing query before signing and fetching", () => {
    expect(normalizeCommandCenterPath("/v1/admin/recruitment/applications?")).toBe(
      "/v1/admin/recruitment/applications",
    );
  });

  it("preserves an actual query exactly in the signed target", () => {
    expect(normalizeCommandCenterPath("/v1/admin/recruitment/applications?status=SUBMITTED")).toBe(
      "/v1/admin/recruitment/applications?status=SUBMITTED",
    );
  });

  it("rejects non-origin-relative request targets", () => {
    expect(() => normalizeCommandCenterPath("https://example.test/v1/me")).toThrow(
      "Destino interno inválido.",
    );
    expect(() => normalizeCommandCenterPath("//example.test/v1/me")).toThrow(
      "Destino interno inválido.",
    );
  });
});
