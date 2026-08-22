import { describe, expect, it } from "vitest";

import { dateTime, duration, label } from "./format";

describe("format helpers", () => {
  it("renders operational durations without negative values", () => {
    expect(duration(3_900_000)).toBe("1h 05m");
    expect(duration(-10)).toBe("0m");
  });

  it("uses the configured Sao Paulo timezone", () => {
    expect(dateTime(Date.UTC(2026, 7, 22, 15, 30))).toMatch(/22.*12:30/);
  });

  it("normalizes internal identifiers for presentation", () => {
    expect(label("REVIEW_REQUIRED")).toBe("REVIEW REQUIRED");
  });
});
