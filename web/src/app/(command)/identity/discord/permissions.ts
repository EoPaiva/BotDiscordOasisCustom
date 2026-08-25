export const PERMISSION_SUBJECT_TYPES = ["PROFILE", "RANK", "POSITION", "MEMBER"] as const;
export type PermissionSubjectType = typeof PERMISSION_SUBJECT_TYPES[number];

export type PermissionResource = Record<string, unknown>;
export type PermissionRule = PermissionResource & {
  _key: string;
  subject_type: PermissionSubjectType;
  subject_id: number;
  subject_name: string;
  permission: string;
  effect: "GRANT" | "DENY";
  reason: string | null;
  updated_at: number | null;
};

export type PermissionMatrix = {
  catalog: string[];
  profiles: PermissionResource[];
  ranks: PermissionResource[];
  positions: PermissionResource[];
  members: PermissionResource[];
  rules: PermissionRule[];
  summary: { total: number; grants: number; denies: number };
};

function record(value: unknown): PermissionResource {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as PermissionResource
    : {};
}

function resources(value: unknown): PermissionResource[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function positiveInteger(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function decodePermissionSubject(value: string): {
  subjectType: PermissionSubjectType;
  subjectId: number;
} | null {
  const match = value.match(/^(PROFILE|RANK|POSITION|MEMBER):([1-9]\d*)$/);
  if (!match) return null;
  return {
    subjectType: match[1] as PermissionSubjectType,
    subjectId: Number(match[2]),
  };
}

export function permissionSubjectValue(type: PermissionSubjectType, id: unknown): string {
  const normalizedId = positiveInteger(id);
  return normalizedId ? `${type}:${normalizedId}` : "";
}

export function normalizePermissionMatrix(value: unknown): PermissionMatrix {
  const root = record(value);
  const catalog = Array.isArray(root.catalog)
    ? [...new Set(root.catalog.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim()))].sort()
    : [];
  const normalizedRules: PermissionRule[] = [];
  for (const item of resources(root.rules)) {
    const subjectType = String(item.subject_type ?? "").toUpperCase();
    const subjectId = positiveInteger(item.subject_id);
    const permission = String(item.permission ?? "").trim();
    const effect = String(item.effect ?? "").toUpperCase();
    if (
      !PERMISSION_SUBJECT_TYPES.includes(subjectType as PermissionSubjectType)
      || subjectId == null
      || !permission
      || (effect !== "GRANT" && effect !== "DENY")
    ) continue;
    normalizedRules.push({
      ...item,
      _key: `${subjectType}:${subjectId}:${permission}`,
      subject_type: subjectType as PermissionSubjectType,
      subject_id: subjectId,
      subject_name: String(item.subject_name ?? `${subjectType} #${subjectId}`),
      permission,
      effect,
      reason: item.reason == null || String(item.reason).trim() === "" ? null : String(item.reason),
      updated_at: item.updated_at == null ? null : Number(item.updated_at),
    });
  }
  const summary = record(root.summary);
  const grants = normalizedRules.filter((rule) => rule.effect === "GRANT").length;
  const denies = normalizedRules.length - grants;
  return {
    catalog,
    profiles: resources(root.profiles),
    ranks: resources(root.ranks),
    positions: resources(root.positions),
    members: resources(root.members),
    rules: normalizedRules,
    summary: {
      total: Number.isFinite(Number(summary.total)) ? Number(summary.total) : normalizedRules.length,
      grants: Number.isFinite(Number(summary.grants)) ? Number(summary.grants) : grants,
      denies: Number.isFinite(Number(summary.denies)) ? Number(summary.denies) : denies,
    },
  };
}
