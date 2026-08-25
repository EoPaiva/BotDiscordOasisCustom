/**
 * Produces the exact origin-relative target that both Fetch and FastAPI will
 * see. In particular, Fetch drops a trailing empty query (`/route?`), so
 * signing the caller-provided string would otherwise make a valid request
 * fail HMAC verification on the API.
 */
export function normalizeCommandCenterPath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Destino interno inválido.");
  }
  const target = new URL(path, "https://command-center.invalid");
  return `${target.pathname}${target.search}`;
}
