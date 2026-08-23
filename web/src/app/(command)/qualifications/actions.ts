"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { commandCenterFetch } from "@/lib/api";

const qualificationSchema = z.object({
  discordId: z.coerce.number().int().positive(),
  courseId: z.coerce.number().int().positive(),
  granted: z.enum(["true", "false"]),
});

export async function setMemberQualification(formData: FormData) {
  const input = qualificationSchema.parse(Object.fromEntries(formData));
  const granted = input.granted === "true";
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
  revalidatePath("/qualifications");
  revalidatePath(`/members/${input.discordId}`);
}
