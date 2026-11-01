/**
 * REST client for the FastAPI backend.
 *
 * Kept free of any Clerk imports so it can be called from both Server
 * Components (token via `(await auth()).getToken()`) and Client Components
 * (token via `useAuth().getToken()`).
 */

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

  return fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
    // Authenticated GETs must not be cached across users by the Next.js RSC fetch cache.
    cache: "no-store",
  });
}

/**
 * Builds an `ApiError` from a non-2xx response, following the common error
 * shape (`{ "detail": "...", "code": "..." }`). Falls back to
 * a generic message when the body isn't JSON.
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

  return new ApiError(response.status, detail, code, requestId);
}

/** `apiFetch` that throws `toApiError(response, fallbackMessage)` on a non-2xx status. */
export async function apiRequest(
  path: string,
  token: string | null,
  init: RequestInit = {},
  fallbackMessage = "Request failed"
): Promise<Response> {
  const response = await apiFetch(path, token, init);
  if (!response.ok) {
    throw await toApiError(response, fallbackMessage);
  }
  return response;
}

/** `apiRequest` plus the parsed JSON body. Types mirror the backend by hand, so `T` is not validated. */
export async function apiJson<T>(
  path: string,
  token: string | null,
  init: RequestInit = {},
  fallbackMessage = "Request failed"
): Promise<T> {
  const response = await apiRequest(path, token, init, fallbackMessage);
  return (await response.json()) as T;
}

/**
 * True when an id route (`/lessons/{id}`, `/chat/sessions/{id}`, `/jobs/{id}`)
 * says the resource doesn't exist for this user. A well-formed id that is
 * missing or foreign is `404`; a malformed id is rejected by FastAPI's path
 * validation with `422` and no `code`. Both mean "not found" to the UI. A 422
 * with a business code (e.g. `EMPTY_MESSAGE`) is a real validation error.
 */
export function isNotFoundError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.status === 404) return true;
  return error.status === 422 && error.code === undefined;
}

export interface SyncUserResponse {
  user_id: string;
  onboarding_complete: boolean;
  email: string | null;
}

/** `POST /api/v1/auth/sync` — idempotently ensures a Postgres user exists. */
export function syncUser(token: string | null): Promise<SyncUserResponse> {
  return apiJson("/api/v1/auth/sync", token, { method: "POST" }, "Failed to sync user");
}
