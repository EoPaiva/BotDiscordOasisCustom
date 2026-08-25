import { cookies } from "next/headers";

export const RECRUITMENT_GUILD_COOKIE = "choque.recruitment.guild";
export const REC_CHOQUE_GUILD_ID = "1541908574463070311";

export function allowedRecruitmentGuildIds(): Set<string> {
  const configured = (process.env.RECRUITMENT_GUILD_IDS ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter((value) => /^\d{15,22}$/.test(value));
  const primary = process.env.DEFAULT_GUILD_ID;
  return new Set([
    ...(primary && /^\d{15,22}$/.test(primary) ? [primary] : []),
    REC_CHOQUE_GUILD_ID,
    ...configured,
  ]);
}

export async function getRecruitmentGuildId(): Promise<string> {
  const primary = process.env.DEFAULT_GUILD_ID;
  if (!primary) throw new Error("Servidor principal não configurado.");
  const selected = (await cookies()).get(RECRUITMENT_GUILD_COOKIE)?.value;
  return selected && allowedRecruitmentGuildIds().has(selected) ? selected : primary;
}
