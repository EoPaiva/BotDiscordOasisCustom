import { NextRequest, NextResponse } from "next/server";

import {
  allowedRecruitmentGuildIds,
  REC_CHOQUE_GUILD_ID,
  RECRUITMENT_GUILD_COOKIE,
} from "@/lib/recruitment-guild";

export async function GET(request: NextRequest) {
  const requested = request.nextUrl.searchParams.get("guild");
  const guildId = requested === "rec" ? REC_CHOQUE_GUILD_ID : requested;
  const destination = new URL("/recrutamento", request.nextUrl.origin);
  if (!guildId || !allowedRecruitmentGuildIds().has(guildId)) {
    return NextResponse.redirect(destination, 303);
  }
  const response = NextResponse.redirect(destination, 303);
  response.cookies.set(RECRUITMENT_GUILD_COOKIE, guildId, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 30 * 24 * 60 * 60,
    priority: "high",
  });
  return response;
}
