"use server";

import { signIn, signOut } from "@/auth";
import { safeLoginReturnTo } from "@/lib/login-return";

export async function loginWithDiscord(formData?: FormData) {
  await signIn("discord", {
    redirectTo: safeLoginReturnTo(formData?.get("returnTo"), "/dashboard"),
  });
}

export async function loginForRecruitment() {
  await signIn("discord", { redirectTo: "/recrutamento" });
}

export async function logout() {
  await signOut({ redirectTo: "/login" });
}
