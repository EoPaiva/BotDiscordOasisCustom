import "server-only";

import { auth } from "@/auth";

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

export function authConfigurationReady(): boolean {
  return Boolean(process.env.AUTH_DISCORD_ID && process.env.AUTH_DISCORD_SECRET);
}
