import { describe, expect, it } from "vitest";

import { accessFingerprint, canAccessPath, normalizeAccessContext } from "./access";

describe("functional access context", () => {
  it("normalizes the nested Discord identity contract", () => {
    const context = normalizeAccessContext({
      guild_id: 10,
      member: {
        discord_id: 20,
        mta_nick: "Sentinela",
        status: "ACTIVE",
        rank: { id: 3, name: "Coronel", code: "COLONEL" },
        primaryPosition: { id: 8, name: "Comandante Geral", code: "COMMANDER_GENERAL" },
        functions: [
          { id: 8, name: "Comandante Geral", code: "COMMANDER_GENERAL", is_primary: 1 },
          { id: 9, name: "Instrutor", code: "INSTRUCTOR", is_primary: 0 },
        ],
        discordSyncedAt: 1_787_418_840_000,
        identitySyncStatus: "SYNCED",
      },
      access: {
        profile: "ALTO_COMANDO",
        profileName: "Alto Comando",
        permissions: ["identity.configure", "identity.reconcile"],
        authorizationVersion: 12,
      },
    });

    expect(context.member.rank?.name).toBe("Coronel");
    expect(context.member.primary_position?.code).toBe("COMMANDER_GENERAL");
    expect(context.member.functions.map((item) => item.code)).toEqual(["INSTRUCTOR"]);
    expect(context.authorization_version).toBe(12);
    expect(canAccessPath(context, "/discord")).toBe(true);
  });

  it("keeps the flat v1 context compatible during rollout", () => {
    const context = normalizeAccessContext({
      guild_id: 10,
      profile: "MEMBRO",
      permissions: ["training.view.self"],
      member: {
        discord_id: 20,
        mta_nick: "Sentinela",
        status: "ACTIVE",
        rank_name: "Soldado",
      },
    });

    expect(context.member.rank_name).toBe("Soldado");
    expect(context.access.profile).toBe("MEMBRO");
    expect(context.authorization_version).toBe(1);
    expect(canAccessPath(context, "/discord")).toBe(false);
    expect(canAccessPath(context, "/profile")).toBe(true);
    expect(canAccessPath(context, "/trainings")).toBe(true);
  });

  it("changes the fingerprint when a live downgrade changes authorization", () => {
    const elevated = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "ALTO_COMANDO", permissions: ["settings.manage"], authorization_version: 3 },
    });
    const downgraded = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "MEMBRO", permissions: [], authorization_version: 4 },
    });

    expect(accessFingerprint(downgraded)).not.toBe(accessFingerprint(elevated));
    expect(canAccessPath(downgraded, "/settings")).toBe(false);
  });

  it("revokes the trainings route when its explicit permission is removed", () => {
    const authorized = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: {
        profile: "MEMBRO",
        permissions: ["training.view.self"],
        authorization_version: 5,
      },
    });
    const downgraded = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "MEMBRO", permissions: [], authorization_version: 6 },
    });

    expect(canAccessPath(authorized, "/trainings")).toBe(true);
    expect(canAccessPath(downgraded, "/trainings")).toBe(false);
  });

  it("fails closed for unknown authenticated routes, including technical admins", () => {
    const administrator = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "ADMINISTRADOR", permissions: ["*"], authorization_version: 9 },
    });

    expect(canAccessPath(administrator, "/future-admin-surface")).toBe(false);
    expect(canAccessPath(administrator, "/security/unknown-child")).toBe(false);
    expect(canAccessPath(administrator, "/dashboard?view=operational")).toBe(true);
  });

  it("keeps only the declared public routes available without RBAC grants", () => {
    const visitor = normalizeAccessContext({
      member: { discord_id: 0, mta_nick: "Visitante", status: "UNKNOWN" },
      access: { profile: "MEMBRO", permissions: [], authorization_version: 1 },
    });

    for (const path of ["/", "/login", "/status", "/recrutamento", "/minha-candidatura"]) {
      expect(canAccessPath(visitor, path), path).toBe(true);
    }
    expect(canAccessPath(visitor, "/recrutamento/interno")).toBe(false);
  });

  it("has an explicit rule for every command center page", () => {
    const administrator = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "ADMINISTRADOR", permissions: ["*"], authorization_version: 9 },
    });
    const commandRoutes = [
      "/audit", "/career", "/changes", "/dashboard", "/discipline", "/discord",
      "/identity", "/inbox", "/maintenance", "/members", "/patrols", "/profile",
      "/qualifications", "/readiness", "/recruitment", "/recruitment/ai",
      "/recruitment/blocks", "/recruitment/campaign", "/recruitment/form",
      "/recruitment/form/preview", "/recruits", "/registration", "/reports",
      "/requests", "/security", "/settings", "/settings/channels", "/shifts",
      "/tickets", "/trainings", "/members/99", "/recruitment/99",
    ];

    for (const path of commandRoutes) expect(canAccessPath(administrator, path), path).toBe(true);
  });
});
