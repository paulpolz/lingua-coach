/**
 * REST client for the FastAPI backend.
 *
 * Kept free of any Clerk imports so it can be called from both Server
 * Components (token via `(await auth()).getToken()`) and Client Components
 * (token via `useAuth().getToken()`) — see app/page.tsx and
 * app/(protected)/*.
 */

import { reportClientError } from "@/lib/reportError";

export function getApiBaseUrl(): string {
  // Server Components / SSR in Docker Compose reach the backend via the
  // internal service name; the browser still uses NEXT_PUBLIC_API_URL.
  if (typeof window === "undefined" && process.env.API_URL) {
    return process.env.API_URL;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export function createRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;

  constructor(status: number, message: string, code?: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Authenticated fetch against the FastAPI backend, attaching `Authorization` + `X-Request-ID`. */
export async function apiFetch(
  path: string,
  token: string | null,
  init: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!headers.has("X-Request-ID")) {
    headers.set("X-Request-ID", createRequestId());
  }

  return fetch(`${getApiBaseUrl()}${path}`, { ...init, headers });
}

/**
 * Builds an `ApiError` from a non-2xx response, following the common error
 * shape in readiness §6 (`{ "detail": "...", "code": "..." }`). Falls back to
 * a generic message when the body isn't JSON (e.g. an HTML error page from a
 * proxy, or an unreachable/misconfigured backend).
 *
 * Also fire-and-forgets a telemetry report so frontend failures show up next
 * to backend logs under the same `request_id`.
 */
export async function toApiError(response: Response, fallbackMessage: string): Promise<ApiError> {
  let detail = `${fallbackMessage} (status ${response.status})`;
  let code: string | undefined;
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    if (typeof body?.code === "string") code = body.code;
  } catch {
    // Response body wasn't JSON — keep the default message.
  }

  if (typeof window !== "undefined") {
    reportClientError({
      code: code ?? `HTTP_${response.status}`,
      message: detail,
      surface: "api",
      requestId,
      path: typeof window !== "undefined" ? window.location.pathname : undefined,
      meta: { status: response.status, url: response.url },
    });
  }

  return new ApiError(response.status, detail, code, requestId);
}

export interface SyncUserResponse {
  user_id: string;
  onboarding_complete: boolean;
  email: string | null;
}

/** `POST /api/v1/auth/sync` — idempotently ensures a Postgres user exists. */
export async function syncUser(token: string | null): Promise<SyncUserResponse> {
  const response = await apiFetch("/api/v1/auth/sync", token, { method: "POST" });

  if (!response.ok) {
    throw await toApiError(response, "Failed to sync user");
  }

  return response.json();
}
