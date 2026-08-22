import NextAuth from "next-auth";
import Discord from "next-auth/providers/discord";

const discordConfigured = Boolean(
  process.env.AUTH_DISCORD_ID && process.env.AUTH_DISCORD_SECRET,
);

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: discordConfigured
    ? [
        Discord({
          clientId: process.env.AUTH_DISCORD_ID!,
          clientSecret: process.env.AUTH_DISCORD_SECRET!,
          authorization: { params: { scope: "identify guilds" } },
        }),
      ]
    : [],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async jwt({ token, profile, account }) {
      if (profile?.id) token.discordId = profile.id;
      if (account?.access_token) {
        token.guildVerified = false;
        const guildId = process.env.DEFAULT_GUILD_ID;
        if (guildId) {
          try {
            const response = await fetch("https://discord.com/api/v10/users/@me/guilds", {
              headers: { Authorization: `Bearer ${account.access_token}` },
              cache: "no-store",
              signal: AbortSignal.timeout(8_000),
            });
            if (response.ok) {
              const guilds = await response.json() as { id?: string }[];
              token.guildVerified = guilds.some((guild) => guild.id === guildId);
            }
          } catch {
            token.guildVerified = false;
          }
        }
      }
      token.sessionIssuedAt ??= token.iat ?? Math.floor(Date.now() / 1000);
      return token;
    },
    session({ session, token }) {
      if (session.user) {
        session.user.discordId = String(token.discordId ?? token.sub ?? "");
        session.user.sessionIssuedAt = Number(token.sessionIssuedAt ?? token.iat ?? 0);
        session.user.guildVerified = token.guildVerified === true;
      }
      return session;
    },
  },
  cookies: {
    sessionToken: {
      name: process.env.NODE_ENV === "production" ? "__Secure-choque.session" : "choque.session",
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
  },
});
