/**
 * REST client for the FastAPI backend.
 *
 * Kept free of any Clerk imports so it can be called from both Server
 * Components (token via `(await auth()).getToken()`) and Client Components
 * (token via `useAuth().getToken()`) — see app/page.tsx and
 * app/(protected)/*.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Authenticated fetch against the backend, attaching `Authorization: Bearer <token>`. */
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

  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

/**
 * Builds an `ApiError` from a non-2xx response, following the common error
 * shape in readiness §6 (`{ "detail": "...", "code": "..." }`). Falls back to
 * a generic message when the body isn't JSON (e.g. an HTML error page from a
 * proxy, or an unreachable/misconfigured backend).
 */
export async function toApiError(response: Response, fallbackMessage: string): Promise<ApiError> {
  let detail = `${fallbackMessage} (status ${response.status})`;
  let code: string | undefined;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    if (typeof body?.code === "string") code = body.code;
  } catch {
    // Response body wasn't JSON — keep the default message.
  }
  return new ApiError(response.status, detail, code);
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
