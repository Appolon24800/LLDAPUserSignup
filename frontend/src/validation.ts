/**
 * Client-side validation — mirrors the backend rules for live feedback.
 * The server re-validates everything; this is UX only, never a security
 * boundary.
 */

export const USERNAME_RE = /^[a-z0-9._-]{3,32}$/;
const EMAIL_RE =
  /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$/;

export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MIN_ENTROPY_BITS = 60;
const NAME_MAX_LENGTH = 64;

export const RESERVED_USERNAMES = new Set([
  "admin", "administrator", "root", "system", "postmaster", "hostmaster",
  "webmaster", "abuse", "support", "help", "info", "mail", "mailer-daemon",
  "news", "www", "ldap", "ldapadmin", "lldap", "auth", "authadmin",
  "security", "sysadmin", "operator", "guest", "anonymous", "service",
  "api", "backup", "nobody", "daemon",
]);

// Trimmed client copy of the server denylist (top entries only).
const COMMON_PASSWORDS = [
  "password", "passw0rd", "123456", "12345678", "123456789", "qwerty",
  "azerty", "abc123", "iloveyou", "princess", "monkey", "dragon", "letmein",
  "welcome", "admin", "master", "sunshine", "football", "shadow", "hunter2",
  "secret", "changeme", "soleil", "marseille", "doudou", "loulou", "lapin",
  "motdepasse", "bonjour", "chocolat", "azertyuiop",
];

function hasControlChars(value: string): boolean {
  return [...value].some((ch) => ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127);
}

export type FieldError = string | null;

export function validateUsername(value: string): FieldError {
  const v = value;
  if (!v) return "required";
  if (hasControlChars(v)) return "invalid_format";
  if (!USERNAME_RE.test(v)) return "invalid_format";
  if (RESERVED_USERNAMES.has(v.toLowerCase())) return "reserved";
  return null;
}

export function validateName(value: string): FieldError {
  const stripped = value.trim();
  if (stripped.length < 1 || stripped.length > NAME_MAX_LENGTH) return "invalid_length";
  if (hasControlChars(stripped)) return "invalid_format";
  for (const ch of stripped) {
    if (!(ch === " " || ch === "-" || ch === "'" || /[\p{L}]/u.test(ch))) {
      return "invalid_format";
    }
  }
  if (![...stripped].some((ch) => /[\p{L}]/u.test(ch))) return "invalid_format";
  return null;
}

export function validateEmail(value: string): FieldError {
  const stripped = value.trim();
  if (!stripped) return "required";
  if (stripped.length > 254) return "invalid_length";
  if (hasControlChars(stripped)) return "invalid_format";
  if (!EMAIL_RE.test(stripped)) return "invalid_format";
  const local = stripped.slice(0, stripped.lastIndexOf("@"));
  if (local.startsWith(".") || local.endsWith(".") || local.includes("..")) {
    return "invalid_format";
  }
  return null;
}

/** Pool-based entropy over unique characters (same formula as the server). */
export function passwordEntropyBits(value: string): number {
  let pool = 0;
  if (/[a-z]/.test(value)) pool += 26;
  if (/[A-Z]/.test(value)) pool += 26;
  if (/\d/.test(value)) pool += 10;
  if (/[^a-zA-Z0-9]/.test(value)) pool += 33;
  if (pool === 0) return 0;
  return new Set(value).size * Math.log2(pool);
}

export function validatePassword(value: string): FieldError {
  if (!value) return "required";
  if (value.length < PASSWORD_MIN_LENGTH) return "too_short";
  if (hasControlChars(value)) return "invalid_format";
  const lowered = value.toLowerCase();
  if (COMMON_PASSWORDS.some((common) => lowered.includes(common))) return "too_common";
  if (passwordEntropyBits(value) < PASSWORD_MIN_ENTROPY_BITS) return "too_weak";
  return null;
}

export function validateConfirm(password: string, confirm: string): FieldError {
  if (!confirm) return "required";
  return password === confirm ? null : "mismatch";
}

export type Strength = "empty" | "weak" | "fair" | "strong";

export function passwordStrength(value: string): Strength {
  if (!value) return "empty";
  const bits = passwordEntropyBits(value);
  if (bits < 45) return "weak";
  if (bits < PASSWORD_MIN_ENTROPY_BITS) return "fair";
  return "strong";
}

/** Magic-byte sniffing for instant client feedback (server re-checks). */
export async function sniffImage(file: File): Promise<boolean> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const head = bytes.slice(0, 12);
  const startsWith = (...prefix: number[]) => prefix.every((b, i) => head[i] === b);
  if (startsWith(0xff, 0xd8, 0xff)) return true; // JPEG
  if (startsWith(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return true; // PNG
  const ascii = String.fromCharCode(...head.slice(0, 6));
  if (ascii === "GIF87a" || ascii === "GIF89a") return true;
  if (startsWith(0x52, 0x49, 0x46, 0x46) && String.fromCharCode(...head.slice(8, 12)) === "WEBP") {
    return true;
  }
  return false;
}
