import { describe, expect, it } from "vitest";

import {
  buildLoginUrl,
  resolveLoginDestination,
  safeLoginReturnTo,
} from "./login-return";

describe("login return destination", () => {
  it("preserves the official candidacy destination", () => {
    expect(resolveLoginDestination({ returnTo: "/candidatura-oficial" })).toBe(
      "/candidatura-oficial",
    );
  });

  it("accepts the legacy callback parameter during the transition", () => {
    expect(resolveLoginDestination({ callbackUrl: "/candidatura-oficial" })).toBe(
      "/candidatura-oficial",
    );
  });

  it("preserves the Upamentos destination", () => {
    expect(resolveLoginDestination({ returnTo: "/officer-candidacies" })).toBe(
      "/officer-candidacies",
    );
  });

  it("rejects external and protocol-relative redirects", () => {
    expect(safeLoginReturnTo("https://example.com", "/dashboard")).toBe("/dashboard");
    expect(safeLoginReturnTo("//example.com", "/dashboard")).toBe("/dashboard");
    expect(safeLoginReturnTo("/\\example.com", "/dashboard")).toBe("/dashboard");
  });

  it("starts OAuth on the configured canonical authentication host", () => {
    expect(
      buildLoginUrl(
        "/officer-candidacies",
        "https://web-plum-tau-82.vercel.app",
      ),
    ).toBe(
      "https://web-plum-tau-82.vercel.app/login?returnTo=%2Fofficer-candidacies",
    );
  });

  it("uses a local login path when no canonical host is configured", () => {
    expect(buildLoginUrl("/candidatura-oficial", undefined)).toBe(
      "/login?returnTo=%2Fcandidatura-oficial",
    );
  });
});
