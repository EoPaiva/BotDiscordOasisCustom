"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { signOut } from "@/auth";
import { commandCenterFetch } from "@/lib/api";

const rankSchema = z.object({
  discordId: z.coerce.number().int().positive(),
  targetRankId: z.coerce.number().int().positive(),
  action: z.enum(["PROMOTION", "DEMOTION"]),
  reason: z.string().trim().min(3).max(500),
  confirmation: z.literal("CONFIRMAR"),
});

export async function changeRank(formData: FormData) {
  const input = rankSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/members/${input.discordId}/rank`, {
    method: "POST",
    body: JSON.stringify({
      target_rank_id: input.targetRankId,
      action: input.action,
      reason: input.reason,
    }),
  });
  revalidatePath(`/members/${input.discordId}`);
  revalidatePath("/members");
}

const decisionSchema = z.object({
  requestId: z.coerce.number().int().positive(),
  decision: z.enum(["approve", "deny"]),
  reason: z.string().trim().min(3).max(500),
});

export async function decideRequest(formData: FormData) {
  const input = decisionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/requests/${input.requestId}/decision`, {
    method: "POST",
    body: JSON.stringify({ approved: input.decision === "approve", reason: input.reason }),
  });
  revalidatePath("/inbox");
  revalidatePath("/dashboard");
}

const inboxDecisionSchema = z.object({
  itemId: z.coerce.number().int().positive(),
  itemType: z.string().trim().min(2).max(60),
  decision: z.enum(["approve", "deny"]),
  reason: z.string().trim().min(3).max(500),
});

export async function decideInboxItem(formData: FormData) {
  const input = inboxDecisionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(
    `/v1/inbox/${encodeURIComponent(input.itemType)}/${input.itemId}/decision`,
    {
      method: "POST",
      body: JSON.stringify({ approved: input.decision === "approve", reason: input.reason }),
    },
  );
  revalidatePath("/inbox");
  revalidatePath("/dashboard");
}

const maintenanceSchema = z.object({
  moduleKey: z.string().trim().min(2).max(60),
  active: z.enum(["true", "false"]),
  reason: z.string().trim().max(500).optional(),
});

export async function setMaintenance(formData: FormData) {
  const input = maintenanceSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/maintenance/${encodeURIComponent(input.moduleKey)}`, {
    method: "POST",
    body: JSON.stringify({ active: input.active === "true", reason: input.reason || null }),
  });
  revalidatePath("/maintenance");
  revalidatePath("/settings");
}

const generalSettingSchema = z.object({
  key: z.string().trim().min(2).max(80),
  value: z.string().max(500),
  valueType: z.enum(["string", "number", "boolean", "list"]),
});

export async function updateGeneralSetting(formData: FormData) {
  const input = generalSettingSchema.parse(Object.fromEntries(formData));
  let value: string | number | boolean | string[] = input.value;
  if (input.valueType === "number") value = z.coerce.number().parse(input.value);
  if (input.valueType === "boolean") value = input.value === "true";
  if (input.valueType === "list") {
    value = input.value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  await commandCenterFetch("/v1/settings/general", {
    method: "PATCH",
    body: JSON.stringify({ key: input.key, value }),
  });
  revalidatePath("/settings");
}

const channelSettingSchema = z.object({
  key: z.string().trim().min(2).max(80),
  resourceId: z.coerce.number().int().positive(),
});

export async function updateChannelSetting(formData: FormData) {
  const input = channelSettingSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/settings/channel", {
    method: "PATCH",
    body: JSON.stringify({ key: input.key, resource_id: input.resourceId }),
  });
  revalidatePath("/settings");
}

const rankSettingSchema = z.object({
  rankId: z.coerce.number().int().positive(),
  name: z.string().trim().min(2).max(60),
  prefix: z.string().trim().max(20),
  level: z.coerce.number().int().min(0).max(999),
  discordRoleId: z.union([z.literal(""), z.string().regex(/^\d+$/)]),
  rbacProfile: z.enum([
    "CANDIDATO", "RECRUTA", "MEMBRO", "GRADUADO", "INSTRUTOR",
    "SUPERVISOR", "COMANDO", "ALTO_COMANDO", "ADMINISTRADOR",
  ]),
  active: z.enum(["true", "false"]),
});

export async function updateRankSetting(formData: FormData) {
  const input = rankSettingSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/settings/ranks/${input.rankId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: input.name,
      prefix: input.prefix,
      level: input.level,
      discord_role_id: input.discordRoleId ? Number(input.discordRoleId) : null,
      rbac_profile: input.rbacProfile,
      active: input.active === "true",
    }),
  });
  revalidatePath("/settings");
}

const voiceChannelSchema = z.object({
  operation: z.enum(["upsert", "remove"]),
  channelId: z.coerce.number().int().positive(),
  label: z.string().trim().max(100).optional(),
  countsTowardPatrol: z.enum(["true", "false"]).default("true"),
});

export async function configureVoiceChannel(formData: FormData) {
  const input = voiceChannelSchema.parse(Object.fromEntries(formData));
  if (input.operation === "remove") {
    await commandCenterFetch(`/v1/settings/voice-channels/${input.channelId}`, {
      method: "DELETE",
    });
  } else {
    await commandCenterFetch("/v1/settings/voice-channels", {
      method: "PUT",
      body: JSON.stringify({
        channel_id: input.channelId,
        label: input.label || null,
        counts_toward_patrol_minimum: input.countsTowardPatrol === "true",
      }),
    });
  }
  revalidatePath("/settings");
}

const lockdownSchema = z.object({
  active: z.enum(["true", "false"]),
  reason: z.string().trim().min(10).max(500),
  confirmation: z.string().trim().min(7).max(10),
});

export async function setSecurityLockdown(formData: FormData) {
  const input = lockdownSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/security/lockdown", {
    method: "POST",
    body: JSON.stringify({
      active: input.active === "true",
      reason: input.reason,
      confirmation: input.confirmation,
    }),
  });
  revalidatePath("/security");
}

const sessionRevocationSchema = z.object({
  discordId: z.union([z.literal(""), z.string().regex(/^\d+$/)]),
  reason: z.string().trim().min(10).max(500),
  confirmation: z.string().trim().min(7).max(20),
});

export async function revokeSecuritySessions(formData: FormData) {
  const input = sessionRevocationSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/security/sessions/revoke", {
    method: "POST",
    body: JSON.stringify({
      discord_id: input.discordId ? Number(input.discordId) : null,
      reason: input.reason,
      confirmation: input.confirmation,
    }),
  });
  await signOut({ redirectTo: "/login" });
}

const registrationDecisionSchema = z.object({
  registrationId: z.coerce.number().int().positive(),
  action: z.enum(["APPROVE", "DENY", "CORRECT_ID", "LINK_EXISTING"]),
  reason: z.string().trim().min(3).max(500),
  bgrId: z.string().trim().max(32).optional(),
  memberId: z.union([z.literal(""), z.string().regex(/^\d+$/)]).optional(),
});

export async function decideRegistrationGate(formData: FormData) {
  const input = registrationDecisionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/registration-gate/${input.registrationId}/decision`, {
    method: "POST",
    body: JSON.stringify({
      action: input.action,
      reason: input.reason,
      bgr_id: input.bgrId || null,
      member_id: input.memberId ? Number(input.memberId) : null,
    }),
  });
  revalidatePath("/registration");
  revalidatePath("/inbox");
  revalidatePath("/dashboard");
}

const registrationConfigurationSchema = z.object({
  key: z.enum([
    "registration_gate_enabled",
    "unregistered_role_id",
    "candidate_role_id",
    "member_role_id",
    "registration_onboarding_category_id",
    "registration_panel_channel_id",
    "registration_support_channel_id",
    "registration_onboarding_channel_ids",
    "registration_bypass_role_ids",
    "registration_bypass_user_ids",
    "registration_dm_enabled",
  ]),
  value: z.string().max(1000),
  valueType: z.enum(["boolean", "id", "id_list"]),
});

export async function updateRegistrationGateConfiguration(formData: FormData) {
  const input = registrationConfigurationSchema.parse(Object.fromEntries(formData));
  let value: boolean | number | number[];
  if (input.valueType === "boolean") {
    value = input.value === "true";
  } else if (input.valueType === "id") {
    value = z.coerce.number().int().positive().parse(input.value);
  } else {
    value = input.value.trim()
      ? input.value.split(",").map((item) => z.coerce.number().int().positive().parse(item.trim()))
      : [];
  }
  await commandCenterFetch("/v1/registration-gate/configuration", {
    method: "PATCH",
    body: JSON.stringify({ [input.key]: value }),
  });
  revalidatePath("/registration");
}

const ticketConfigurationSchema = z.object({
  key: z.enum([
    "ticket_active_category_id",
    "ticket_archive_category_id",
    "ticket_responsible_role_id",
    "ticket_transcript_channel_id",
    "ticket_requester_notify_cooldown_seconds",
  ]),
  value: z.string().trim().max(100),
});

export async function updateTicketConfiguration(formData: FormData) {
  const input = ticketConfigurationSchema.parse(Object.fromEntries(formData));
  const value = z.coerce.number().int().positive().parse(input.value);
  await commandCenterFetch("/v1/tickets/configuration", {
    method: "PATCH",
    body: JSON.stringify({ [input.key]: value }),
  });
  revalidatePath("/tickets");
}
