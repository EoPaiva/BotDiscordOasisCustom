type LoginQuery = {
  returnTo?: string | string[];
  callbackUrl?: string | string[];
};

export function safeLoginReturnTo(
  value: string | FormDataEntryValue | null | undefined,
  fallback = "/dashboard",
): string {
  const candidate = typeof value === "string" ? value : "";
  return candidate.startsWith("/")
    && !candidate.startsWith("//")
    && !candidate.startsWith("/\\")
    ? candidate
    : fallback;
}

export function resolveLoginDestination(query: LoginQuery): string {
  const current = typeof query.returnTo === "string" ? query.returnTo : undefined;
  const legacy = typeof query.callbackUrl === "string" ? query.callbackUrl : undefined;
  return safeLoginReturnTo(current ?? legacy, "/dashboard");
}

export function buildLoginUrl(destination: string, authUrl: string | undefined): string {
  const safeDestination = safeLoginReturnTo(destination, "/dashboard");
  const query = `returnTo=${encodeURIComponent(safeDestination)}`;
  if (!authUrl) return `/login?${query}`;

  const login = new URL("/login", authUrl);
  login.search = query;
  return login.toString();
}
