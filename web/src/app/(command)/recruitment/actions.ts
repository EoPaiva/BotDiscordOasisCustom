"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CommandCenterApiError, commandCenterFetch as requestCommandCenter } from "@/lib/api";

function returnPathFor(path: string): string {
  const application = path.match(/^\/v1\/admin\/recruitment\/applications\/(\d+)/);
  if (application) return `/recruitment/${application[1]}`;
  if (path.includes("/campaign")) return "/recruitment/campaign";
  if (path.includes("/question") || path.includes("/form/")) return "/recruitment/form";
  if (path.includes("/blocks")) return "/recruitment/blocks";
  if (path.includes("/ai/")) return "/recruitment/ai";
  return "/recruitment";
}

/**
 * All recruitment mutations share the same recent-authentication recovery.
 * A Server Action must redirect to the renewal page instead of propagating a
 * 401 into React's Server Component error boundary.
 */
async function commandCenterFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await requestCommandCenter<T>(path, init);
  } catch (error) {
    if (
      error instanceof CommandCenterApiError
      && error.status === 401
      && error.message === "Autenticação recente necessária. Entre novamente."
    ) {
      redirect(`/login?reauth=1&returnTo=${encodeURIComponent(returnPathFor(path))}`);
    }
    throw error;
  }
}

const versioned = z.object({
  applicationId: z.coerce.number().int().positive(),
  expectedVersion: z.coerce.number().int().positive(),
});

export async function assignRecruitmentApplication(formData: FormData) {
  const input = versioned.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/applications/${input.applicationId}/assign`, {
    method: "POST",
    body: JSON.stringify({ expected_version: input.expectedVersion }),
  });
  revalidatePath(`/recruitment/${input.applicationId}`);
  revalidatePath("/recruitment");
}

const interviewSchema = versioned.extend({
  scheduledAt: z.coerce.date(),
  interviewerId: z.coerce.number().int().positive(),
  notes: z.string().trim().max(1000).optional(),
});

export async function scheduleRecruitmentInterview(formData: FormData) {
  const input = interviewSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/applications/${input.applicationId}/interview`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: input.expectedVersion,
      scheduled_at: input.scheduledAt.getTime(),
      interviewer_id: input.interviewerId,
      notes: input.notes || null,
    }),
  });
  revalidatePath(`/recruitment/${input.applicationId}`);
}

const evaluationSchema = versioned.extend({
  interviewId: z.coerce.number().int().positive(),
  communication: z.enum(["EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"]),
  posture: z.enum(["EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"]),
  knowledge: z.enum(["EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"]),
  discipline: z.enum(["EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"]),
  result: z.enum(["FIT", "UNFIT", "REEVALUATE"]),
  observation: z.string().trim().max(2000).optional(),
});

export async function evaluateRecruitmentInterview(formData: FormData) {
  const input = evaluationSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/applications/${input.applicationId}/evaluate`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: input.expectedVersion,
      interview_id: input.interviewId,
      communication: input.communication,
      posture: input.posture,
      knowledge: input.knowledge,
      discipline: input.discipline,
      result: input.result,
      observation: input.observation || null,
    }),
  });
  revalidatePath(`/recruitment/${input.applicationId}`);
}

const decisionSchema = versioned.extend({
  decision: z.enum(["approve", "reject"]),
  internalReason: z.string().trim().min(3).max(2000),
  candidateMessage: z.string().trim().min(3).max(2000),
  confirmation: z.literal("CONFIRMAR"),
});

export async function decideRecruitmentApplication(formData: FormData) {
  const input = decisionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(
    `/v1/admin/recruitment/applications/${input.applicationId}/${input.decision}`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        internal_reason: input.internalReason,
        candidate_message: input.candidateMessage,
      }),
    },
  );
  revalidatePath(`/recruitment/${input.applicationId}`);
  revalidatePath("/recruitment");
  revalidatePath("/recruits");
}

const noteSchema = z.object({
  applicationId: z.coerce.number().int().positive(),
  note: z.string().trim().min(3).max(4000),
});

export async function addRecruitmentNote(formData: FormData) {
  const input = noteSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/applications/${input.applicationId}/notes`, {
    method: "POST",
    body: JSON.stringify({ note: input.note }),
  });
  revalidatePath(`/recruitment/${input.applicationId}`);
}

const adaptationSchema = z.object({
  applicationId: z.coerce.number().int().positive(),
  extraTimePercent: z.coerce.number().int().min(0).max(200),
  clipboardAdapted: z.string().optional(),
  alternativeFormat: z.string().trim().max(500).optional(),
  reason: z.string().trim().min(3).max(2000),
});

export async function addRecruitmentAdaptation(formData: FormData) {
  const input = adaptationSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(
    `/v1/admin/recruitment/applications/${input.applicationId}/adaptations`,
    {
      method: "POST",
      body: JSON.stringify({
        extra_time_percent: input.extraTimePercent,
        clipboard_adapted: input.clipboardAdapted === "on",
        alternative_format: input.alternativeFormat || null,
        reason: input.reason,
      }),
    },
  );
  revalidatePath(`/recruitment/${input.applicationId}`);
}

const campaignSchema = z.object({
  campaignId: z.coerce.number().int().positive(),
  name: z.string().trim().min(3).max(150),
  status: z.enum(["DRAFT", "SCHEDULED", "OPEN", "PAUSED", "CLOSED", "ARCHIVED"]),
  opensAt: z.string().optional(),
  closesAt: z.string().optional(),
  cooldownDays: z.coerce.number().int().min(0).max(365),
  minimumAge: z.coerce.number().int().min(13).max(100),
  maximumApplications: z.string().optional(),
  initialRankId: z.string().optional(),
  candidateRoleId: z.string().optional(),
  interviewChannelId: z.string().optional(),
});

export async function updateRecruitmentCampaign(formData: FormData) {
  const input = campaignSchema.parse(Object.fromEntries(formData));
  const timestamp = (value?: string) => value ? new Date(value).getTime() : null;
  await commandCenterFetch(`/v1/admin/recruitment/campaign/${input.campaignId}`, {
    method: "PUT",
    body: JSON.stringify({
      name: input.name,
      status: input.status,
      opens_at: timestamp(input.opensAt),
      closes_at: timestamp(input.closesAt),
      cooldown_days: input.cooldownDays,
      minimum_age: input.minimumAge,
      maximum_applications: input.maximumApplications ? Number(input.maximumApplications) : null,
      initial_rank_id: input.initialRankId ? Number(input.initialRankId) : null,
      candidate_role_id: input.candidateRoleId ? Number(input.candidateRoleId) : null,
      interview_channel_id: input.interviewChannelId ? Number(input.interviewChannelId) : null,
    }),
  });
  revalidatePath("/recruitment/campaign");
  revalidatePath("/recruitment");
}

const questionSchema = z.object({
  questionId: z.coerce.number().int().positive(),
  groupId: z.coerce.number().int().positive(),
  title: z.string().trim().min(3).max(1000),
  description: z.string().trim().max(2000).optional(),
  questionType: z.enum(["SHORT_TEXT", "LONG_TEXT", "NUMBER", "DATE", "BOOLEAN", "SINGLE_SELECT", "MULTI_SELECT"]),
  required: z.enum(["true", "false"]),
  position: z.coerce.number().int().positive().max(10000),
  enabled: z.enum(["true", "false"]),
  minLength: z.string().optional(),
  maxLength: z.string().optional(),
  expectedMinLength: z.string().optional(),
  expectedMaxLength: z.string().optional(),
  securityLevel: z.enum(["NORMAL", "CONTROLLED", "STRICT"]),
  timerEnabled: z.enum(["true", "false"]),
  timerMode: z.enum(["AUTO", "FIXED", "NONE"]),
  fixedTimeSeconds: z.string().optional(),
  allowBack: z.enum(["true", "false"]),
  shufflePosition: z.enum(["true", "false"]),
  difficulty: z.enum(["EASY", "MEDIUM", "HARD"]),
  options: z.string().max(2000).optional(),
  conditionQuestion: z.string().trim().max(50).optional(),
  conditionValue: z.string().trim().max(500).optional(),
});

function conditionPayload(question?: string, rawValue?: string) {
  if (!question) return null;
  if (!rawValue) throw new Error("Informe o valor da condição.");
  let equals: unknown;
  try {
    equals = JSON.parse(rawValue);
  } catch {
    equals = rawValue;
  }
  return { question: question.toUpperCase(), equals };
}

function questionPayload(input: Omit<z.infer<typeof questionSchema>, "questionId">) {
  const optionalNumber = (value?: string) => value ? Number(value) : null;
  return {
    group_id: input.groupId,
    title: input.title,
    description: input.description || null,
    question_type: input.questionType,
    required: input.required === "true",
    position: input.position,
    enabled: input.enabled === "true",
    min_length: optionalNumber(input.minLength),
    max_length: optionalNumber(input.maxLength),
    expected_min_length: optionalNumber(input.expectedMinLength),
    expected_max_length: optionalNumber(input.expectedMaxLength),
    security_level: input.securityLevel,
    timer_enabled: input.timerEnabled === "true",
    timer_mode: input.timerMode,
    fixed_time_seconds: optionalNumber(input.fixedTimeSeconds),
    allow_back: input.allowBack === "true",
    shuffle_position: input.shufflePosition === "true",
    difficulty: input.difficulty,
    options: input.options?.split("|").map((item) => item.trim()).filter(Boolean) ?? [],
    condition: conditionPayload(input.conditionQuestion, input.conditionValue),
  };
}

export async function updateRecruitmentQuestion(formData: FormData) {
  const input = questionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/questions/${input.questionId}`, {
    method: "PUT",
    body: JSON.stringify(questionPayload(input)),
  });
  revalidatePath("/recruitment/form");
}

const createQuestionSchema = questionSchema.omit({ questionId: true }).extend({
  stableKey: z.string().trim().min(2).max(50).regex(/^[A-Za-z0-9_]+$/),
});

export async function createRecruitmentQuestion(formData: FormData) {
  const input = createQuestionSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/admin/recruitment/questions", {
    method: "POST",
    body: JSON.stringify({ stable_key: input.stableKey.toUpperCase(), ...questionPayload(input) }),
  });
  revalidatePath("/recruitment/form");
}

const groupSchema = z.object({
  groupId: z.coerce.number().int().positive(),
  name: z.string().trim().min(2).max(100),
  position: z.coerce.number().int().positive().max(1000),
  questionsPerApplication: z.coerce.number().int().min(0).max(100),
  active: z.enum(["true", "false"]),
});

export async function updateRecruitmentQuestionGroup(formData: FormData) {
  const input = groupSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/question-groups/${input.groupId}`, {
    method: "PUT",
    body: JSON.stringify({
      name: input.name,
      position: input.position,
      questions_per_application: input.questionsPerApplication,
      active: input.active === "true",
    }),
  });
  revalidatePath("/recruitment/form");
}

export async function publishRecruitmentForm() {
  await commandCenterFetch("/v1/admin/recruitment/form/publish", { method: "POST" });
  revalidatePath("/recruitment/form");
  revalidatePath("/recruitment/campaign");
}

const blockSchema = z.object({
  discordId: z.string().optional(),
  bgrId: z.string().trim().max(40).optional(),
  reason: z.string().trim().min(3).max(2000),
});

export async function createRecruitmentBlock(formData: FormData) {
  const input = blockSchema.parse(Object.fromEntries(formData));
  await commandCenterFetch("/v1/admin/recruitment/blocks", {
    method: "POST",
    body: JSON.stringify({
      discord_id: input.discordId ? Number(input.discordId) : null,
      bgr_id: input.bgrId || null,
      reason: input.reason,
    }),
  });
  revalidatePath("/recruitment/blocks");
}

export async function revokeRecruitmentBlock(formData: FormData) {
  const blockId = z.coerce.number().int().positive().parse(formData.get("blockId"));
  await commandCenterFetch(`/v1/admin/recruitment/blocks/${blockId}`, { method: "DELETE" });
  revalidatePath("/recruitment/blocks");
}

export async function reanalyzeRecruitmentApplication(formData: FormData) {
  const applicationId = z.coerce.number().int().positive().parse(formData.get("applicationId"));
  const analysisType = z.enum(["PRE_INTERVIEW", "FINAL_ASSISTED"]).parse(
    formData.get("analysisType") ?? "PRE_INTERVIEW",
  );
  await commandCenterFetch(
    `/v1/admin/recruitment/applications/${applicationId}/analysis/reanalyze`,
    { method: "POST", body: JSON.stringify({ analysis_type: analysisType }) },
  );
  revalidatePath(`/recruitment/${applicationId}`);
}

export async function recordRecruitmentAnalysisFeedback(formData: FormData) {
  const input = z.object({
    applicationId: z.coerce.number().int().positive(),
    resultId: z.coerce.number().int().positive(),
    usefulness: z.enum(["YES", "PARTIAL", "NO"]),
    note: z.string().trim().max(1000).optional(),
  }).parse(Object.fromEntries(formData));
  await commandCenterFetch(`/v1/admin/recruitment/analysis/${input.resultId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ usefulness: input.usefulness, note: input.note || null }),
  });
  revalidatePath(`/recruitment/${input.applicationId}`);
}

export async function updateRecruitmentAiConfiguration(formData: FormData) {
  const enabled = formData.get("enabled") === "on";
  const boolean = (key: string) => formData.get(key) === "on";
  await commandCenterFetch("/v1/admin/recruitment/ai/config", {
    method: "PUT",
    body: JSON.stringify({
      enabled,
      auto_analyze: boolean("autoAnalyze"),
      analyze_integrity: boolean("analyzeIntegrity"),
      generate_interview_questions: boolean("generateInterviewQuestions"),
      generate_summary: boolean("generateSummary"),
      final_assisted_after_interview: boolean("finalAssistedAfterInterview"),
      discord_notice: boolean("discordNotice"),
      show_score: boolean("showScore"),
    }),
  });
  revalidatePath("/recruitment/ai");
}

export async function createRecruitmentAiRubricDraft() {
  await commandCenterFetch("/v1/admin/recruitment/ai/rubric/draft", { method: "POST" });
  revalidatePath("/recruitment/ai");
}

export async function updateRecruitmentAiRubric(formData: FormData) {
  const rubricId = z.coerce.number().int().positive().parse(formData.get("rubricId"));
  const codes = formData.getAll("code").map(String);
  const labels = formData.getAll("criterionLabel").map(String);
  const descriptions = formData.getAll("description").map(String);
  const weights = formData.getAll("weight").map((value) => Number(value));
  const reviewMin = z.coerce.number().int().min(0).max(99).parse(formData.get("reviewMin"));
  const recommendedMin = z.coerce.number().int().min(1).max(100).parse(formData.get("recommendedMin"));
  if (![labels.length, descriptions.length, weights.length].every((size) => size === codes.length)) {
    throw new Error("Campos da rubrica estão incompletos.");
  }
  const criteria = codes.map((code, index) => ({
    code,
    label: labels[index],
    description: descriptions[index],
    weight: weights[index],
  }));
  await commandCenterFetch(`/v1/admin/recruitment/ai/rubric/${rubricId}`, {
    method: "PUT",
    body: JSON.stringify({
      criteria,
      review_min: reviewMin,
      recommended_min: recommendedMin,
      show_score: formData.get("rubricShowScore") === "on",
    }),
  });
  revalidatePath("/recruitment/ai");
}

export async function publishRecruitmentAiRubric(formData: FormData) {
  const rubricId = z.coerce.number().int().positive().parse(formData.get("rubricId"));
  await commandCenterFetch(`/v1/admin/recruitment/ai/rubric/${rubricId}/publish`, {
    method: "POST",
  });
  revalidatePath("/recruitment/ai");
}

export async function previewRecruitmentAiRubric() {
  await commandCenterFetch("/v1/admin/recruitment/ai/rubric/preview", { method: "POST" });
}

export async function createRecruitmentAiContextDraft() {
  await commandCenterFetch("/v1/admin/recruitment/ai/context/draft", { method: "POST" });
  revalidatePath("/recruitment/ai");
}

export async function updateRecruitmentAiContext(formData: FormData) {
  const contextId = z.coerce.number().int().positive().parse(formData.get("contextId"));
  const split = (value: FormDataEntryValue | null) => String(value ?? "").split("\n").map((item) => item.trim()).filter(Boolean);
  await commandCenterFetch(`/v1/admin/recruitment/ai/context/${contextId}`, {
    method: "PUT",
    body: JSON.stringify({
      principles: split(formData.get("principles")),
      prohibitions: split(formData.get("prohibitions")),
    }),
  });
  revalidatePath("/recruitment/ai");
}

export async function publishRecruitmentAiContext(formData: FormData) {
  const contextId = z.coerce.number().int().positive().parse(formData.get("contextId"));
  await commandCenterFetch(`/v1/admin/recruitment/ai/context/${contextId}/publish`, {
    method: "POST",
  });
  revalidatePath("/recruitment/ai");
}
