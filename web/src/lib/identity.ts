import "server-only";

import { createHmac, timingSafeEqual } from "node:crypto";

import { cookies } from "next/headers";

import { auth } from "@/auth";

const RECRUITMENT_GUEST_COOKIE = "choque.recruitment";

export type CandidateIdentity = {
  discordId: string;
  sessionIssuedAt: number;
  guildVerified: boolean;
  username: string;
  globalName: string | null;
  avatar: string | null;
};

function guestSecret() {
  const value = process.env.RECRUITMENT_TOKEN_SECRET ?? process.env.COMMAND_CENTER_INTERNAL_SECRET;
  if (!value || value.length < 32) throw new Error("Segredo do recrutamento não configurado.");
  return value;
}

function signGuest(payload: string) {
  return createHmac("sha256", guestSecret()).update(payload).digest("base64url");
}

export async function setRecruitmentGuestIdentity(discordId: string, username: string) {
  const payload = Buffer.from(JSON.stringify({ discordId, username, issuedAt: Math.floor(Date.now() / 1000) })).toString("base64url");
  (await cookies()).set(RECRUITMENT_GUEST_COOKIE, `${payload}.${signGuest(payload)}`, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 30 * 24 * 60 * 60,
    priority: "high",
  });
}

export async function getRecruitmentGuestIdentity(): Promise<CandidateIdentity | null> {
  const raw = (await cookies()).get(RECRUITMENT_GUEST_COOKIE)?.value;
  if (!raw) return null;
  const [payload, signature] = raw.split(".");
  if (!payload || !signature) return null;
  const expected = signGuest(payload);
  const left = Buffer.from(signature);
  const right = Buffer.from(expected);
  if (left.length !== right.length || !timingSafeEqual(left, right)) return null;
  try {
    const value = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { discordId?: string; username?: string; issuedAt?: number };
    if (!value.discordId?.match(/^\d{15,22}$/) || !value.issuedAt) return null;
    return { discordId: value.discordId, sessionIssuedAt: value.issuedAt, guildVerified: false, username: String(value.username || `discord-${value.discordId}`).slice(0, 100), globalName: null, avatar: null };
  } catch { return null; }
}

export async function getDiscordIdentity(): Promise<string | null> {
  const session = await auth();
  if (session?.user.discordId) return session.user.discordId;
  if (process.env.NODE_ENV !== "production" && process.env.WEB_DEV_DISCORD_ID) {
    return process.env.WEB_DEV_DISCORD_ID;
  }
  return null;
}

export async function getDiscordSessionIdentity(): Promise<{
  discordId: string;
  sessionIssuedAt: number;
  guildVerified: boolean;
  username: string;
  globalName: string | null;
  avatar: string | null;
} | null> {
  const session = await auth();
  if (session?.user.discordId) {
    return {
      discordId: session.user.discordId,
      sessionIssuedAt: session.user.sessionIssuedAt,
      guildVerified: session.user.guildVerified,
      username: session.user.name ?? `discord-${session.user.discordId}`,
      globalName: session.user.name ?? null,
      avatar: session.user.image ?? null,
    };
  }
  if (process.env.NODE_ENV !== "production" && process.env.WEB_DEV_DISCORD_ID) {
    return {
      discordId: process.env.WEB_DEV_DISCORD_ID,
      sessionIssuedAt: Math.floor(Date.now() / 1000),
      guildVerified: true,
      username: process.env.WEB_DEV_DISCORD_USERNAME ?? "Candidato de desenvolvimento",
      globalName: process.env.WEB_DEV_DISCORD_USERNAME ?? null,
      avatar: null,
    };
  }
  return null;
}

export async function getRecruitmentCandidateIdentity(): Promise<CandidateIdentity | null> {
  return (await getDiscordSessionIdentity()) ?? getRecruitmentGuestIdentity();
}

export function authConfigurationReady(): boolean {
  return Boolean(process.env.AUTH_DISCORD_ID && process.env.AUTH_DISCORD_SECRET);
}
