export type IdentityReference = {
  id: number | null;
  code: string | null;
  name: string;
};

export type AccessContext = {
  guild_id: number;
  member: {
    discord_id: number;
    mta_nick: string;
    character_id: string | null;
    status: string;
    rank: IdentityReference | null;
    rank_name: string | null;
    rank_prefix: string | null;
    primary_position: IdentityReference | null;
    functions: IdentityReference[];
    discord_synced_at: number | null;
    identity_sync_status: string;
    discord_present: boolean;
  };
  access: {
    profile: string;
    profile_name: string;
    permissions: string[];
    authorization_version: number;
  };
  /** Compatibilidade temporária com consumidores do contrato plano da API v1. */
  profile: string;
  permissions: string[];
  authorization_version: number;
};

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function nullableText(value: unknown): string | null {
  if (value == null) return null;
  const normalized = String(value).trim();
  return normalized || null;
}

function integer(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

function nullableInteger(value: unknown): number | null {
  if (value == null || value === "") return null;
  const parsed = integer(value, Number.NaN);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (value === 1 || value === "1" || value === "true") return true;
  if (value === 0 || value === "0" || value === "false") return false;
  return fallback;
}

function identityReference(value: unknown, fallbackName?: unknown): IdentityReference | null {
  if (typeof value === "string" && value.trim()) {
    return { id: null, code: null, name: value.trim() };
  }
  const item = record(value);
  const name = text(item.name ?? item.display_name ?? fallbackName);
  if (!name) return null;
  return {
    id: nullableInteger(item.id),
    code: nullableText(item.code ?? item.internal_code),
    name,
  };
}

function identityFunctions(value: unknown): IdentityReference[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const functions: IdentityReference[] = [];
  for (const item of value) {
    const source = record(item);
    if (source.is_primary === true || source.is_primary === 1) continue;
    const normalized = identityReference(item);
    if (!normalized) continue;
    const key = normalized.code ?? `${normalized.id ?? ""}:${normalized.name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    functions.push(normalized);
  }
  return functions;
}

/** Adapta tanto o contrato nested da identidade quanto o contrato plano legado. */
export function normalizeAccessContext(value: unknown): AccessContext {
  const root = record(value);
  const member = record(root.member);
  const access = record(root.access);
  const profile = text(access.profile ?? root.profile, "MEMBRO");
  const permissionsSource = access.permissions ?? root.permissions;
  const permissions = Array.isArray(permissionsSource)
    ? [...new Set(permissionsSource.filter((item): item is string => typeof item === "string"))].sort()
    : [];
  const rank = identityReference(member.rank, member.rank_name ?? member.rankName);
  const primaryPosition = identityReference(
    member.primary_position ?? member.primaryPosition,
    member.primary_position_name ?? member.primaryPositionName,
  );
  const authorizationVersion = Math.max(
    1,
    integer(
      access.authorization_version
        ?? access.authorizationVersion
        ?? root.authorization_version
        ?? root.authorizationVersion,
      1,
    ),
  );
  const discordSyncedAt = nullableInteger(
    member.discord_synced_at
      ?? member.discordSyncedAt
      ?? member.discord_roles_synced_at,
  );

  return {
    guild_id: integer(root.guild_id ?? root.guildId),
    member: {
      discord_id: integer(member.discord_id ?? member.discordId),
      mta_nick: text(member.mta_nick ?? member.mtaNick, "Membro"),
      character_id: nullableText(member.character_id ?? member.characterId),
      status: text(member.status, "UNKNOWN"),
      rank,
      rank_name: nullableText(member.rank_name ?? member.rankName ?? rank?.name),
      rank_prefix: nullableText(member.rank_prefix ?? member.rankPrefix),
      primary_position: primaryPosition,
      functions: identityFunctions(member.functions ?? member.positions),
      discord_synced_at: discordSyncedAt,
      identity_sync_status: text(
        member.identity_sync_status ?? member.identitySyncStatus,
        discordSyncedAt == null ? "PENDING" : "SYNCED",
      ),
      discord_present: booleanValue(member.discord_present ?? member.discordPresent, true),
    },
    access: {
      profile,
      profile_name: text(access.profile_name ?? access.profileName, profile),
      permissions,
      authorization_version: authorizationVersion,
    },
    profile,
    permissions,
    authorization_version: authorizationVersion,
  };
}

export function can(context: AccessContext, permission: string): boolean {
  return context.permissions.includes("*") || context.permissions.includes(permission);
}

export function canAny(context: AccessContext, permissions: readonly string[]): boolean {
  return permissions.some((permission) => can(context, permission));
}

export function accessFingerprint(context: AccessContext): string {
  return [
    context.authorization_version,
    context.profile,
    context.member.identity_sync_status,
    context.member.discord_present ? "1" : "0",
    context.permissions.join("\u001f"),
  ].join("\u001e");
}

type RouteRule = { path: string; permissions: readonly string[] };

/** Rotas públicas deliberadas; nenhuma outra rota é liberada implicitamente. */
const PUBLIC_ROUTES = new Set([
  "/",
  "/access-denied",
  "/login",
  "/minha-candidatura",
  "/recrutamento",
  "/recrutamento/avaliacao",
  "/status",
]);

/** Cada página real do route group `(command)` possui uma regra explícita. */
const ROUTE_RULES: RouteRule[] = [
  { path: "/audit", permissions: ["decisions.view", "audit.read"] },
  { path: "/career", permissions: ["career.manage"] },
  { path: "/changes", permissions: ["changes.view"] },
  { path: "/dashboard", permissions: ["patrol.view.self", "operations.view"] },
  { path: "/discipline", permissions: ["discipline.manage"] },
  { path: "/discord", permissions: ["identity.manage", "identity.configure", "identity.reconcile"] },
  { path: "/identity", permissions: ["integrity.view"] },
  { path: "/inbox", permissions: ["admin.inbox.view"] },
  { path: "/maintenance", permissions: ["maintenance.manage", "settings.manage"] },
  { path: "/members", permissions: ["member.view"] },
  { path: "/patrols", permissions: ["patrol.view.all"] },
  { path: "/profile", permissions: [] },
  { path: "/qualifications", permissions: ["qualification.view.all"] },
  { path: "/readiness", permissions: ["operations.view"] },
  { path: "/recruitment", permissions: ["recruitment.view"] },
  { path: "/recruitment/ai", permissions: ["recruitment.ai.config"] },
  { path: "/recruitment/blocks", permissions: ["recruitment.block.manage"] },
  { path: "/recruitment/campaign", permissions: ["recruitment.campaign.manage"] },
  { path: "/recruitment/form", permissions: ["recruitment.form.manage"] },
  { path: "/recruitment/form/preview", permissions: ["recruitment.form.manage"] },
  { path: "/recruits", permissions: ["recruitment.review"] },
  { path: "/registration", permissions: ["registration.view"] },
  { path: "/reports", permissions: ["reports.view"] },
  { path: "/requests", permissions: ["admin.inbox.view"] },
  { path: "/security", permissions: ["security.manage"] },
  { path: "/settings", permissions: ["settings.manage"] },
  { path: "/shifts", permissions: ["shift.view.all"] },
  { path: "/tickets", permissions: ["ticket.view"] },
  { path: "/trainings", permissions: ["training.view.self"] },
];

function normalizedPath(pathname: string): string {
  const withoutQuery = pathname.split(/[?#]/, 1)[0] || "/";
  return withoutQuery.length > 1 ? withoutQuery.replace(/\/+$/, "") : withoutQuery;
}

export function canAccessPath(context: AccessContext, pathname: string): boolean {
  const path = normalizedPath(pathname);
  if (PUBLIC_ROUTES.has(path)) return true;

  const memberMatch = path.match(/^\/members\/(\d+)$/);
  if (memberMatch) {
    return Number(memberMatch[1]) === context.member.discord_id || can(context, "dossier.view");
  }
  if (/^\/recruitment\/\d+$/.test(path)) return can(context, "recruitment.read");
  if (/^\/settings\/[^/]+$/.test(path)) return can(context, "settings.manage");

  const rule = ROUTE_RULES.find((candidate) => path === candidate.path);
  if (!rule) return false;
  return rule.permissions.length === 0 || canAny(context, rule.permissions);
}
