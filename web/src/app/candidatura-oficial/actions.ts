"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { commandCenterFetch } from "@/lib/api";

const applicationSchema = z.coerce.number().int().positive();

export async function startOfficerApplication() {
  await commandCenterFetch("/v1/officer-candidacy/application", { method: "POST" });
  revalidatePath("/candidatura-oficial");
  redirect("/candidatura-oficial");
}

export async function saveOfficerDraft(formData: FormData) {
  const applicationId = applicationSchema.parse(formData.get("applicationId"));
  const answers = [...formData.entries()]
    .filter(([key]) => key.startsWith("answer:"))
    .map(([key, value]) => ({
      questionId: applicationSchema.parse(key.slice("answer:".length)),
      answer: String(value).trim(),
    }))
    .filter((item) => item.answer.length >= 20);
  for (const item of answers) {
    await commandCenterFetch(
      `/v1/officer-candidacy/applications/${applicationId}/answers/${item.questionId}`,
      {
        method: "PUT",
        body: JSON.stringify({ answer: item.answer }),
      },
    );
  }
  revalidatePath("/candidatura-oficial");
}

export async function submitOfficerApplication(formData: FormData) {
  const applicationId = applicationSchema.parse(formData.get("applicationId"));
  await saveOfficerDraft(formData);
  await commandCenterFetch(
    `/v1/officer-candidacy/applications/${applicationId}/submit`,
    { method: "POST" },
  );
  revalidatePath("/candidatura-oficial");
  redirect("/candidatura-oficial");
}
