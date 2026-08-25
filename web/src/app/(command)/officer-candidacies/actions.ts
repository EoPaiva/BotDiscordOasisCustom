"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CommandCenterApiError, commandCenterFetch } from "@/lib/api";

async function officerRequest(path: string, init: RequestInit = {}) {
  try {
    return await commandCenterFetch(path, init);
  } catch (error) {
    if (
      error instanceof CommandCenterApiError
      && error.status === 401
      && error.message === "Autenticação recente necessária. Entre novamente."
    ) {
      const match = path.match(/officer-applications\/(\d+)/);
      const returnTo = match ? `/officer-candidacies/${match[1]}` : "/officer-candidacies";
      redirect(`/login?reauth=1&returnTo=${encodeURIComponent(returnTo)}`);
    }
    throw error;
  }
}

const applicationSchema = z.object({
  applicationId: z.coerce.number().int().positive(),
});

export async function claimOfficerApplication(formData: FormData) {
  const input = applicationSchema.parse(Object.fromEntries(formData));
  await officerRequest(`/v1/officer-applications/${input.applicationId}/claim`, {
    method: "POST",
  });
  revalidatePath(`/officer-candidacies/${input.applicationId}`);
  revalidatePath("/officer-candidacies");
}

const interviewSchema = applicationSchema.extend({
  scheduledAt: z.string().optional(),
  result: z.enum(["PENDING", "POSITIVE", "NEUTRAL", "NEGATIVE"]),
  observations: z.string().trim().max(4000).optional(),
});

export async function recordOfficerInterview(formData: FormData) {
  const input = interviewSchema.parse(Object.fromEntries(formData));
  await officerRequest(`/v1/officer-applications/${input.applicationId}/interviews`, {
    method: "POST",
    body: JSON.stringify({
      scheduled_at: input.scheduledAt ? new Date(input.scheduledAt).getTime() : null,
      result: input.result,
      observations: input.observations || null,
    }),
  });
  revalidatePath(`/officer-candidacies/${input.applicationId}`);
}

const scoreSchema = applicationSchema.extend({
  questionId: z.coerce.number().int().positive(),
  score: z.coerce.number().int().min(1).max(10),
  rationale: z.string().trim().min(5).max(2000),
});

export async function scoreOfficerQuestion(formData: FormData) {
  const input = scoreSchema.parse(Object.fromEntries(formData));
  await officerRequest(`/v1/officer-applications/${input.applicationId}/scores`, {
    method: "POST",
    body: JSON.stringify({
      question_id: input.questionId,
      score: input.score,
      rationale: input.rationale,
    }),
  });
  revalidatePath(`/officer-candidacies/${input.applicationId}`);
}

const decisionSchema = applicationSchema.extend({
  decision: z.enum(["APPROVED", "APPROVED_CONDITIONAL", "REJECTED", "RETURNED"]),
  reason: z.string().trim().min(10).max(2000),
  conditionText: z.string().trim().max(2000).optional(),
  conditionDueAt: z.string().optional(),
  confirmation: z.literal("CONFIRMAR"),
});

export async function decideOfficerApplication(formData: FormData) {
  const input = decisionSchema.parse(Object.fromEntries(formData));
  await officerRequest(`/v1/officer-applications/${input.applicationId}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision: input.decision,
      reason: input.reason,
      condition_text: input.conditionText || null,
      condition_due_at: input.conditionDueAt
        ? new Date(input.conditionDueAt).getTime()
        : null,
    }),
  });
  revalidatePath(`/officer-candidacies/${input.applicationId}`);
  revalidatePath("/officer-candidacies");
}
