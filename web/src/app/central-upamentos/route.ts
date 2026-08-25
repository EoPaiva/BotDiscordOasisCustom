import { redirect } from "next/navigation";

import { buildLoginUrl } from "@/lib/login-return";

export async function GET() {
  redirect(buildLoginUrl("/officer-candidacies", process.env.AUTH_URL));
}
