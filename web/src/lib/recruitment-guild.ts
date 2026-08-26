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
  if (selected && allowedRecruitmentGuildIds().has(selected)) return selected;

  // O recrutamento novo opera no REC CHOQUE. O servidor principal continua
  // aceito quando o contexto é explícito, preservando candidaturas legadas,
  // mas uma aba antiga ou um cookie ausente não pode criar novas fichas no DC1.
  const configuredDefault = process.env.RECRUITMENT_DEFAULT_GUILD_ID?.trim();
  if (configuredDefault && allowedRecruitmentGuildIds().has(configuredDefault)) {
    return configuredDefault;
  }
  return REC_CHOQUE_GUILD_ID;
}
