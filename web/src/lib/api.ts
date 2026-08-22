import "server-only";

import { createHash, createHmac, randomUUID } from "node:crypto";

import { normalizeAccessContext, type AccessContext } from "@/lib/access";
import { getDiscordSessionIdentity } from "@/lib/identity";
export type { AccessContext } from "@/lib/access";

export class CommandCenterApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly correlationId: string,
  ) {
    super(message);
  }
}

type SignedIdentity = {
  discordId?: string;
  sessionIssuedAt?: number;
  guildVerified?: boolean;
  username?: string;
  globalName?: string | null;
  avatar?: string | null;
};

function requestBody(init: RequestInit): string {
  if (init.body == null) return "";
  if (typeof init.body !== "string") {
    throw new CommandCenterApiError(
      "Formato interno de request não suportado.",
      500,
      "body-format",
    );
  }
  return init.body;
}

function signedRequestHeaders(
  path: string,
  init: RequestInit,
  configuration: { internalSecret: string; guildId: string },
  correlationId: string,
  identity: SignedIdentity = {},
): Headers {
  const method = (init.method ?? "GET").toUpperCase();
  const body = requestBody(init);
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = randomUUID();
  const actorId = identity.discordId ?? "";
  const sessionIssuedAt = String(identity.sessionIssuedAt ?? 0);
  const username = identity.username ? encodeURIComponent(identity.username) : "";
  const globalName = identity.globalName ? encodeURIComponent(identity.globalName) : "";
  const avatar = identity.avatar ?? "";
  const guildVerified = identity.guildVerified ? "true" : "false";
  const bodyHash = createHash("sha256").update(body, "utf8").digest("hex");
  const canonical = [
    "choque-v1",
    method,
    path,
    bodyHash,
    configuration.guildId,
    actorId,
    correlationId,
    timestamp,
    nonce,
    sessionIssuedAt,
    username,
    globalName,
    avatar,
    guildVerified,
  ].join("\n");
  const signature = createHmac("sha256", configuration.internalSecret)
    .update(canonical, "utf8")
    .digest("hex");
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  headers.set("X-Guild-ID", configuration.guildId);
  headers.set("X-Correlation-ID", correlationId);
  headers.set("X-Request-Timestamp", timestamp);
  headers.set("X-Request-Nonce", nonce);
  headers.set("X-Request-Signature", signature);
  headers.set("X-Session-Issued-At", sessionIssuedAt);
  headers.set("X-Discord-Guild-Verified", guildVerified);
  if (actorId) headers.set("X-Actor-Discord-ID", actorId);
  if (username) headers.set("X-Discord-Username", username);
  if (globalName) headers.set("X-Discord-Global-Name", globalName);
  if (avatar) headers.set("X-Discord-Avatar", avatar);
  headers.delete("X-Internal-Secret");
  return headers;
}

export async function commandCenterFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const identity = await getDiscordSessionIdentity();
  if (!identity) throw new CommandCenterApiError("Sessão Discord necessária.", 401, "auth");
  const apiUrl = process.env.COMMAND_CENTER_API_URL;
  const internalSecret = process.env.COMMAND_CENTER_INTERNAL_SECRET;
  const guildId = process.env.DEFAULT_GUILD_ID;
  if (!apiUrl || !internalSecret || !guildId) {
    throw new CommandCenterApiError(
      "A integração segura com a API ainda não foi configurada.",
      503,
      "configuration",
    );
  }
  const correlationId = randomUUID();
  const configuration = { internalSecret, guildId };
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(15_000),
    headers: signedRequestHeaders(path, init, configuration, correlationId, identity),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new CommandCenterApiError(
      payload?.detail ?? `Falha da API (${response.status}).`,
      response.status,
      correlationId,
    );
  }
  return (await response.json()) as T;
}

/** Usa o novo DTO de identidade e mantém compatibilidade durante o rollout da API. */
export async function getAccessContext(): Promise<AccessContext> {
  try {
    return normalizeAccessContext(await commandCenterFetch<unknown>("/v1/me"));
  } catch (error) {
    if (
      !(error instanceof CommandCenterApiError)
      || (error.status !== 404 && error.status !== 405)
    ) {
      throw error;
    }
    return normalizeAccessContext(await commandCenterFetch<unknown>("/v1/context"));
  }
}

function integrationConfiguration() {
  const apiUrl = process.env.COMMAND_CENTER_API_URL;
  const internalSecret = process.env.COMMAND_CENTER_INTERNAL_SECRET;
  const guildId = process.env.DEFAULT_GUILD_ID;
  if (!apiUrl || !internalSecret || !guildId) {
    throw new CommandCenterApiError(
      "A integração segura com a API ainda não foi configurada.",
      503,
      "configuration",
    );
  }
  return { apiUrl: apiUrl.replace(/\/$/, ""), internalSecret, guildId };
}

async function decodeResponse<T>(response: Response, correlationId: string): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new CommandCenterApiError(
      payload?.detail ?? `Falha da API (${response.status}).`,
      response.status,
      correlationId,
    );
  }
  return (await response.json()) as T;
}

export async function recruitmentPublicFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const { apiUrl, internalSecret, guildId } = integrationConfiguration();
  const correlationId = randomUUID();
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(15_000),
    headers: signedRequestHeaders(path, init, { internalSecret, guildId }, correlationId),
  });
  return decodeResponse<T>(response, correlationId);
}

export async function recruitmentCandidateFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const identity = await getDiscordSessionIdentity();
  if (!identity) {
    throw new CommandCenterApiError("Sessão Discord necessária.", 401, "auth");
  }
  const { apiUrl, internalSecret, guildId } = integrationConfiguration();
  const correlationId = randomUUID();
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(15_000),
    headers: signedRequestHeaders(
      path,
      init,
      { internalSecret, guildId },
      correlationId,
      identity,
    ),
  });
  return decodeResponse<T>(response, correlationId);
}
