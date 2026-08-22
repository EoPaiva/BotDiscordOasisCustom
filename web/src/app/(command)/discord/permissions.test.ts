import { describe, expect, it } from "vitest";

import {
  decodePermissionSubject,
  normalizePermissionMatrix,
  permissionSubjectValue,
} from "./permissions";

describe("Discord permission matrix", () => {
  it("normalizes the stable API contract and preserves explicit DENY", () => {
    const matrix = normalizePermissionMatrix({
      catalog: ["member.edit", "identity.configure", "member.edit"],
      profiles: [{ id: 1, code: "MEMBRO", name: "Membro" }],
      ranks: [{ id: 2, name: "Coronel", level: 20 }],
      positions: [{ id: 3, code: "INSTRUCTOR", name: "Instrutor" }],
      members: [{ id: 4, discord_id: 99, mta_nick: "Sentinela" }],
      rules: [
        {
          subject_type: "MEMBER",
          subject_id: 4,
          subject_name: "Sentinela",
          permission: "member.edit",
          effect: "DENY",
          reason: "Restrição individual",
          updated_at: 1_000,
        },
      ],
      summary: { total: 1, grants: 0, denies: 1 },
      ignored_future_field: true,
    });

    expect(matrix.catalog).toEqual(["identity.configure", "member.edit"]);
    expect(matrix.rules[0]).toMatchObject({
      _key: "MEMBER:4:member.edit",
      effect: "DENY",
      reason: "Restrição individual",
    });
    expect(matrix.summary).toEqual({ total: 1, grants: 0, denies: 1 });
  });

  it("uses type and numeric ID rather than the mutable display name", () => {
    expect(permissionSubjectValue("POSITION", 42)).toBe("POSITION:42");
    expect(decodePermissionSubject("POSITION:42")).toEqual({
      subjectType: "POSITION",
      subjectId: 42,
    });
    expect(decodePermissionSubject("Comandante Geral")).toBeNull();
    expect(decodePermissionSubject("POSITION:0")).toBeNull();
  });

  it("drops malformed rules and derives summary when the API omits it", () => {
    const matrix = normalizePermissionMatrix({
      rules: [
        { subject_type: "PROFILE", subject_id: 8, permission: "reports.view", effect: "GRANT" },
        { subject_type: "UNKNOWN", subject_id: 8, permission: "*", effect: "GRANT" },
        { subject_type: "MEMBER", subject_id: -1, permission: "member.edit", effect: "DENY" },
      ],
    });

    expect(matrix.rules).toHaveLength(1);
    expect(matrix.summary).toEqual({ total: 1, grants: 1, denies: 0 });
  });
});
