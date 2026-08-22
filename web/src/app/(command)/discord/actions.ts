"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { commandCenterFetch } from "@/lib/api";

import { decodePermissionSubject } from "./permissions";

const optionalId = z.union([z.literal(""), z.string().regex(/^\d+$/)]).optional();
const mappingSchema = z.object({
  discordRoleId: z.coerce.number().int().positive(),
  mappingType: z.enum(["RANK", "POSITION", "QUALIFICATION", "SYSTEM", "COSMETIC", "ACCESS"]),
  internalCode: z.string().trim().min(2).max(80).transform((value) => value.toUpperCase().replaceAll(/[^A-Z0-9_]/g, "_")),
  displayName: z.string().trim().min(2).max(100),
  priority: z.coerce.number().int().min(-10_000).max(10_000),
  rankId: optionalId,
  positionId: optionalId,
  accessProfileId: optionalId,
  isPrimaryPositionCandidate: z.enum(["true", "false"]),
  enabled: z.enum(["true", "false"]),
});

function parsedId(value: string | undefined): number | null {
  return value ? Number(value) : null;
}

function bumpedVersions(value: unknown): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export async function upsertDiscordRoleMapping(formData: FormData) {
  const input = mappingSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/discord/role-mappings", {
    method: "PUT",
    body: JSON.stringify({
      discord_role_id: input.discordRoleId,
      mapping_type: input.mappingType,
      internal_code: input.internalCode,
      display_name: input.displayName,
      priority: input.priority,
      rank_id: parsedId(input.rankId),
      position_id: parsedId(input.positionId),
      access_profile_id: parsedId(input.accessProfileId),
      is_primary_position_candidate: input.isPrimaryPositionCandidate === "true",
      enabled: input.enabled === "true",
    }),
  });
  revalidatePath("/discord");
}

const memberSyncSchema = z.object({
  discordId: z.coerce.number().int().positive(),
});

export async function syncDiscordIdentity(formData: FormData) {
  const { discordId } = memberSyncSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/discord/identity/sync/${discordId}`, { method: "POST" });
  revalidatePath("/discord");
  revalidatePath(`/members/${discordId}`);
}

type JobReference = { id?: number; job_id?: number };

export async function previewDiscordReconciliation() {
  const result = await commandCenterFetch<JobReference>("/v1/discord/identity/reconciliation/preview", {
    method: "POST",
  });
  revalidatePath("/discord");
  const jobId = Number(result.job_id ?? result.id ?? 0);
  redirect(jobId > 0 ? `/discord?previewJob=${jobId}` : "/discord");
}

const applySchema = z.object({
  previewJobId: z.coerce.number().int().positive(),
});

export async function applyDiscordReconciliation(formData: FormData) {
  const { previewJobId } = applySchema.parse(Object.fromEntries(formData));
  const result = await commandCenterFetch<JobReference>("/v1/discord/identity/reconciliation/apply", {
    method: "POST",
    body: JSON.stringify({ preview_job_id: previewJobId }),
  });
  revalidatePath("/discord");
  const jobId = Number(result.job_id ?? result.id ?? 0);
  redirect(jobId > 0 ? `/discord?job=${jobId}` : "/discord");
}

const permissionRuleSchema = z.object({
  subject: z.string().regex(/^(PROFILE|RANK|POSITION|MEMBER):[1-9]\d*$/),
  permission: z.string().trim().min(2).max(120).regex(/^[A-Za-z0-9*._:-]+$/),
  effect: z.enum(["GRANT", "DENY"]),
  reason: z.string().trim().max(500).optional(),
  confirmation: z.literal("CONFIRMAR"),
});

export async function upsertDiscordPermission(formData: FormData) {
  const input = permissionRuleSchema.parse(Object.fromEntries(formData));
  const subject = decodePermissionSubject(input.subject);
  if (!subject) throw new Error("Sujeito de permissão inválido.");
  const result = await commandCenterFetch<{ authorization_versions_bumped?: number }>("/v1/discord/permissions", {
    method: "PUT",
    body: JSON.stringify({
      subject_type: subject.subjectType,
      subject_id: subject.subjectId,
      permission: input.permission,
      effect: input.effect,
      reason: input.reason || null,
    }),
  });
  revalidatePath("/discord");
  const bumped = bumpedVersions(result.authorization_versions_bumped);
  redirect(`/discord?permissionAction=saved&permissionBumped=${bumped}#permissoes`);
}

const permissionRemovalSchema = z.object({
  subjectType: z.enum(["PROFILE", "RANK", "POSITION", "MEMBER"]),
  subjectId: z.coerce.number().int().positive(),
  permission: z.string().trim().min(2).max(120).regex(/^[A-Za-z0-9*._:-]+$/),
  confirmation: z.literal("CONFIRMAR"),
});

export async function removeDiscordPermission(formData: FormData) {
  const input = permissionRemovalSchema.parse(Object.fromEntries(formData));
  const result = await commandCenterFetch<{ authorization_versions_bumped?: number }>(
    `/v1/discord/permissions/${input.subjectType}/${input.subjectId}/${encodeURIComponent(input.permission)}`,
    { method: "DELETE" },
  );
  revalidatePath("/discord");
  const bumped = bumpedVersions(result.authorization_versions_bumped);
  redirect(`/discord?permissionAction=removed&permissionBumped=${bumped}#permissoes`);
}
