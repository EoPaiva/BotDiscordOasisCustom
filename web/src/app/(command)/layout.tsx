import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { CommandCenterApiError, getAccessContext, type AccessContext } from "@/lib/api";
import { getDiscordIdentity } from "@/lib/identity";

export const dynamic = "force-dynamic";

export default async function CommandLayout({ children }: { children: React.ReactNode }) {
  if (!(await getDiscordIdentity())) redirect("/login");
  let context: AccessContext;
  try {
    context = await getAccessContext();
  } catch (error) {
    if (error instanceof CommandCenterApiError && error.status === 403) redirect("/access-denied");
    throw error;
  }
  return <AppShell context={context}>{children}</AppShell>;
}
