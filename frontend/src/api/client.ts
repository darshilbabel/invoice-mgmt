/**
 * Thin fetch wrapper. Attaches the auth token, unwraps JSON, and turns non-2xx
 * responses into a typed ApiError instead of a silently-ignored result.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
const TOKEN_KEY = "invoice-mgmt.token";

/** DRF error bodies are either {detail: "..."} or {field: ["...", ...]}. */
export type ApiErrorBody = { detail?: string } & Record<string, unknown>;

export class ApiError extends Error {
  // Declared and assigned explicitly rather than as constructor parameter
  // properties: the Vite template enables `erasableSyntaxOnly`, which rejects
  // any TS syntax that emits runtime code.
  readonly status: number;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(ApiError.messageFrom(status, body));
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** Flatten DRF's two error shapes into something showable to a user. */
  private static messageFrom(status: number, body: ApiErrorBody): string {
    if (typeof body?.detail === "string") return body.detail;
    const fieldErrors = Object.entries(body ?? {})
      .map(([field, value]) =>
        Array.isArray(value) ? `${field}: ${value.join(" ")}` : null,
      )
      .filter(Boolean);
    return fieldErrors.length ? fieldErrors.join("\n") : `Request failed (${status})`;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token === null) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(TOKEN_KEY, token);
}

/**
 * Called when the API rejects our token. AuthContext registers a handler so the
 * redirect lives in React-router land rather than this module reaching for
 * window.location.
 */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

/** The single place a fetch happens. Everything else here builds an init for it. */
async function send<T>(path: string, init: RequestInit): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Token ${token}` } : {}),
    },
  });

  // A 401 means "your session is invalid" only if we actually presented a
  // session. A 401 from the login endpoint is just wrong credentials — treating
  // that as an expiry would sign out a logged-in user for a typo, and fire a
  // redirect out of the very page they are on.
  const isLoginAttempt = path.startsWith("/auth/login");
  if (response.status === 401 && token && !isLoginAttempt) {
    setToken(null);
    onUnauthorized();
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload as ApiErrorBody);
  return payload as T;
}

function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  return send<T>(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),

  /**
   * Multipart POST, for file uploads. Deliberately sets NO Content-Type — the
   * browser has to write it itself so the multipart boundary in the header
   * matches the one in the body. Setting it by hand produces a request the
   * server cannot parse, with no useful error.
   *
   * `signal` is here because uploads are the only requests slow enough to be
   * worth cancelling.
   */
  upload: <T>(path: string, form: FormData, signal?: AbortSignal) =>
    send<T>(path, { method: "POST", body: form, signal }),
};
