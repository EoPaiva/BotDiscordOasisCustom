export const RECRUITMENT_GUILD_COOKIE = "choque.recruitment.guild";
export const REC_CHOQUE_GUILD_ID = "1541908574463070311";

export function allowedRecruitmentGuildIds(): Set<string> {
  const configured = (process.env.RECRUITMENT_GUILD_IDS ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter((value) => /^\d{15,22}$/.test(value));
  return new Set([
    REC_CHOQUE_GUILD_ID,
    ...configured,
  ]);
}

export async function getRecruitmentGuildId(): Promise<string> {
  // Após o corte definitivo, cookies antigos do DC1 não podem reabrir o fluxo
  // no servidor principal. O destino configurado precisa estar explicitamente
  // na lista de servidores de recrutamento; o fallback canônico é o REC CHOQUE.
  const configuredDefault = process.env.RECRUITMENT_DEFAULT_GUILD_ID?.trim();
  if (configuredDefault && allowedRecruitmentGuildIds().has(configuredDefault)) {
    return configuredDefault;
  }
  return REC_CHOQUE_GUILD_ID;
}
