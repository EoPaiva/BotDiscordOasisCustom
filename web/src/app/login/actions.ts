"use server";

import { signIn, signOut } from "@/auth";

export async function loginWithDiscord() {
  await signIn("discord", { redirectTo: "/dashboard" });
}

export async function loginForRecruitment() {
  await signIn("discord", { redirectTo: "/recrutamento" });
}

export async function logout() {
  await signOut({ redirectTo: "/login" });
}
