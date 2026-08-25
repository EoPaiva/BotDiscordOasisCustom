"use server";

import { randomUUID } from "node:crypto";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CommandCenterApiError, recruitmentCandidateFetch } from "@/lib/api";
import { setRecruitmentGuestIdentity } from "@/lib/identity";

const startSchema = z.object({
  discordId: z.string().trim().regex(/^\d{15,22}$/),
  discordUsername: z.string().trim().min(2).max(100),
  candidateNick: z.string().trim().min(2).max(80),
  bgrId: z.string().trim().min(1).max(40),
  age: z.coerce.number().int().min(13).max(100),
  consent: z.literal("accepted"),
});

export async function startRecruitmentApplication(formData: FormData) {
  const input = startSchema.parse(Object.fromEntries(formData));
  await setRecruitmentGuestIdentity(input.discordId, input.discordUsername);
  try {
    await recruitmentCandidateFetch("/v1/recruitment/applications/start", {
      method: "POST",
      body: JSON.stringify({
        candidate_nick: input.candidateNick,
        bgr_id: input.bgrId,
        age: input.age,
        consent_accepted: true,
        idempotency_key: randomUUID(),
      }),
    });
  } catch (error) {
    if (error instanceof CommandCenterApiError && error.status === 409) {
      // A identidade já foi persistida. A página consegue mostrar a restrição
      // canônica (candidatura ativa, cooldown ou bloqueio) sem derrubar o React.
      redirect("/recrutamento");
    }
    throw error;
  }
  redirect("/recrutamento/avaliacao");
}

export type CandidateQuestionPayload = {
  question: {
    id: number;
    title: string;
    description: string | null;
    type: string;
    required: boolean;
    min_length: number | null;
    max_length: number | null;
    options: string[];
    security_level: string;
    allow_back: boolean;
    clipboard_adapted?: boolean;
    alternative_format?: string | null;
  };
  started_at: number;
  expires_at: number | null;
  draft: unknown;
  question_token: string;
};

export async function startRecruitmentQuestion(
  applicationId: number,
  questionId: number,
): Promise<{ ok: true; data: CandidateQuestionPayload } | { ok: false; error: string }> {
  try {
    const data = await recruitmentCandidateFetch<CandidateQuestionPayload>(
      `/v1/recruitment/applications/${applicationId}/questions/${questionId}/start`,
      { method: "POST" },
    );
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Falha ao iniciar questão." };
  }
}

export async function saveRecruitmentAnswer(input: {
  applicationId: number;
  questionId: number;
  answer: unknown;
  questionToken: string;
  submit: boolean;
}): Promise<{ ok: boolean; error?: string }> {
  try {
    const action = input.submit ? "submit" : "autosave";
    const method = input.submit ? "POST" : "PATCH";
    await recruitmentCandidateFetch(
      `/v1/recruitment/applications/${input.applicationId}/questions/${input.questionId}/${action}`,
      {
        method,
        body: JSON.stringify({ answer: input.answer, question_token: input.questionToken }),
      },
    );
    revalidatePath("/recrutamento/avaliacao");
    revalidatePath("/minha-candidatura");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Falha ao salvar resposta." };
  }
}

export async function recordRecruitmentIntegrity(input: {
  applicationId: number;
  questionId: number;
  eventType: string;
  durationMs?: number;
}) {
  try {
    await recruitmentCandidateFetch(
      `/v1/recruitment/applications/${input.applicationId}/questions/${input.questionId}/integrity`,
      {
        method: "POST",
        body: JSON.stringify({
          event_type: input.eventType,
          duration_ms: input.durationMs ?? null,
        }),
      },
    );
  } catch {
    // Telemetria de UX não deve interromper a resposta do candidato.
  }
}

export async function submitRecruitmentApplication(
  applicationId: number,
  expectedVersion: number,
): Promise<{ ok: boolean; error?: string }> {
  try {
    await recruitmentCandidateFetch(`/v1/recruitment/applications/${applicationId}/submit`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    });
    revalidatePath("/minha-candidatura");
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Falha ao enviar candidatura." };
  }
}

const withdrawSchema = z.object({
  applicationId: z.coerce.number().int().positive(),
  expectedVersion: z.coerce.number().int().positive(),
  confirmation: z.literal("RETIRAR"),
});

export async function withdrawRecruitmentApplication(formData: FormData) {
  const input = withdrawSchema.parse(Object.fromEntries(formData));
  await recruitmentCandidateFetch(
    `/v1/recruitment/applications/${input.applicationId}/withdraw`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: input.expectedVersion }),
    },
  );
  revalidatePath("/minha-candidatura");
  revalidatePath("/recrutamento");
}
