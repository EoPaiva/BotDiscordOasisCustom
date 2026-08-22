import { redirect } from "next/navigation";

import { getDiscordIdentity } from "@/lib/identity";

export default async function Home() {
  redirect((await getDiscordIdentity()) ? "/dashboard" : "/login");
}

