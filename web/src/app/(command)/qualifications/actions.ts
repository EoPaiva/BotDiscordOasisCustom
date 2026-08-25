"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CommandCenterApiError, commandCenterFetch } from "@/lib/api";

const qualificationSchema = z.object({
  // Discord snowflakes are larger than JavaScript's largest safe integer.
  // Keep them as decimal text across the web boundary; FastAPI converts the
  // JSON string to Python's arbitrary-precision int after validation.
  discordId: z.string().trim().regex(/^\d{15,22}$/),
  courseId: z.coerce.number().int().positive(),
  granted: z.enum(["true", "false"]),
});

export async function setMemberQualification(formData: FormData) {
  const input = qualificationSchema.parse(Object.fromEntries(formData));
  const granted = input.granted === "true";
  let missingResource: "member" | "course" | null = null;
  try {
    await commandCenterFetch("/v1/qualifications/manage", {
      method: "POST",
      body: JSON.stringify({
        discord_id: input.discordId,
        course_id: input.courseId,
        granted,
        reason: granted
          ? "Qualificação concedida pelo Centro de Comando."
          : "Qualificação revogada pelo Centro de Comando.",
      }),
    });
  } catch (error) {
    if (error instanceof CommandCenterApiError && error.status === 404) {
      missingResource = error.message === "Curso ativo não encontrado." ? "course" : "member";
    } else {
      throw error;
    }
  }
  if (missingResource) {
    redirect(`/qualifications?notice=${missingResource}-not-found`);
    return;
  }
  revalidatePath("/qualifications");
  revalidatePath(`/members/${input.discordId}`);
}
