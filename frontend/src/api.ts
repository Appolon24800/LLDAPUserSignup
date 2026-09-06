/**
 * Backend API client.
 *
 * Base URL resolution, in order:
 * 1. VITE_API_BASE_URL (split-origin deployments);
 * 2. derived from the page URL, so a subpath deployment
 *    (https://host/signup/register?code=...) calls /signup/api/v1/...;
 * 3. same-origin root ("" -> /api/v1/...).
 */

/**
 * Pure helper for the runtime base derivation. The wizard page is always
 * served at {base}/register, so stripping a trailing "/register" (or a
 * trailing slash) from the pathname yields the deployment base path.
 */
export function deriveApiBase(pathname: string, envBase?: string): string {
  const configured = envBase?.replace(/\/+$/, "");
  if (configured) return configured;
  if (pathname.endsWith("/register")) return pathname.slice(0, -"/register".length);
  if (pathname.length > 1 && pathname.endsWith("/")) return pathname.slice(0, -1);
  return "";
}

const BASE = deriveApiBase(
  window.location.pathname,
  import.meta.env.VITE_API_BASE_URL as string | undefined,
);

export class ApiError extends Error {
  code: string;
  fieldErrors?: Record<string, string>;
  status?: number;

  constructor(code: string, status?: number, fieldErrors?: Record<string, string>) {
    super(code);
    this.code = code;
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

interface ErrorBody {
  error?: { code?: string; field_errors?: Record<string, string> };
}

async function request(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError("network_error");
  }

  let body: Record<string, unknown> | null = null;
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    body = null;
  }

  if (!res.ok) {
    const error = (body as ErrorBody | null)?.error;
    throw new ApiError(
      error?.code ?? (res.status >= 500 ? "internal_error" : "unknown"),
      res.status,
      error?.field_errors,
    );
  }
  return body ?? {};
}

export interface ValidateCodeResult {
  valid: boolean;
  expires_at?: string;
  platform_name?: string;
  redirect_url?: string;
}

export async function validateCode(code: string): Promise<ValidateCodeResult> {
  const body = await request("/api/v1/validate-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  return {
    valid: Boolean(body.valid),
    expires_at: body.expires_at as string | undefined,
    platform_name: body.platform_name as string | undefined,
    redirect_url: body.redirect_url as string | undefined,
  };
}

export interface RegistrationForm {
  code: string;
  username: string;
  fullName: string;
  email: string;
  password: string;
}

export async function register(form: RegistrationForm, photo?: File | null): Promise<string> {
  const data = new FormData();
  data.set("code", form.code);
  data.set("username", form.username);
  data.set("full_name", form.fullName);
  data.set("email", form.email);
  data.set("password", form.password);
  if (photo) {
    data.set("photo", photo);
  }

  const body = await request("/api/v1/register", { method: "POST", body: data });
  return String(body.username ?? "");
}
