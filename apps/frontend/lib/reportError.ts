/**
 * Fire-and-forget client error reporting to the backend telemetry endpoint.
 * Failures here must never affect UX — swallow all network errors.
 */

export type ErrorSurface = "onboarding" | "lesson" | "dashboard" | "api" | "unknown";

export interface ClientErrorPayload {
  code: string;
  message: string;
  surface?: ErrorSurface;
  requestId?: string | null;
  path?: string;
  meta?: Record<string, string | number | boolean | null | undefined>;
}

function getApiBaseUrl(): string {
  if (typeof window === "undefined" && process.env.API_URL) {
    return process.env.API_URL;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

function createRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function reportClientError(payload: ClientErrorPayload): void {
  if (typeof window === "undefined") return;

  const body = {
    code: payload.code.slice(0, 64),
    message: payload.message.slice(0, 500),
    surface: payload.surface ?? "unknown",
    request_id: payload.requestId ?? undefined,
    path: payload.path ?? window.location.pathname,
    meta: payload.meta
      ? Object.fromEntries(
          Object.entries(payload.meta)
            .slice(0, 10)
            .map(([k, v]) => [k.slice(0, 64), v == null ? null : String(v).slice(0, 200)])
        )
      : undefined,
  };

  const requestId = payload.requestId ?? createRequestId();

  void fetch(`${getApiBaseUrl()}/api/v1/telemetry/client-errors`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
    },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {
    // Telemetry must never surface to the user.
  });
}
