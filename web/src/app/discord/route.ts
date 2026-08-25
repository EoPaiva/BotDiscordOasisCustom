import { NextResponse } from "next/server";

const OFFICIAL_DISCORD_INVITE = "https://discord.gg/A2gcq6Vcmm";

/**
 * A stable, public invitation alias. It is intentionally independent of
 * Auth.js so it cannot become an OAuth callback or leak session state.
 */
export function GET() {
  return NextResponse.redirect(OFFICIAL_DISCORD_INVITE, 308);
}
