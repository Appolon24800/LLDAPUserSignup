/**
 * Backend API client. Base URL comes from VITE_API_BASE_URL; empty means
 * same-origin (the bundled nginx proxies /api/v1 to the backend).
 */

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

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
}

export async function validateCode(code: string): Promise<ValidateCodeResult> {
  const body = await request("/api/v1/validate-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  return { valid: Boolean(body.valid), expires_at: body.expires_at as string | undefined };
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
