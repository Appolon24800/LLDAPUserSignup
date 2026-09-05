import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { type ReactNode } from "react";

export interface FieldProps {
  id: string;
  label: string;
  icon: ReactNode;
  value: string;
  onChange: (value: string) => void;
  /** Error code from validation; null = valid (once touched and non-empty). */
  error?: string | null;
  hint?: string;
  type?: string;
  inputMode?: "text" | "email" | "numeric" | "tel" | "url" | "search" | "none" | "decimal";
  placeholder?: string;
  autoComplete?: string;
  /** Extra feedback override, e.g. server-side 'taken'. */
  serverError?: string | null;
  trailing?: ReactNode;
}

/**
 * Labelled input with icon+shape validation feedback (check / cross).
 * Errors only appear once the user has typed something (gentle for
 * first-time and elderly users).
 */
export default function Field({
  id,
  label,
  icon,
  value,
  onChange,
  error,
  hint,
  type = "text",
  inputMode,
  placeholder,
  autoComplete,
  serverError,
  trailing,
}: FieldProps) {
  const { t } = useTranslation();
  const touched = value.length > 0;
  const shownError = touched ? (serverError ?? error) : serverError;
  const state = !touched && !serverError ? "idle" : shownError ? "invalid" : "valid";

  const specific = error === "invalid_format" && id === "username" ? "username_format" : null;
  const emailSpecific = error === "invalid_format" && id === "email" ? "email_format" : null;
  const messageKey = specific ?? emailSpecific;

  return (
    <div className={`field ${state === "invalid" ? "invalid" : ""}`}>
      <label className="field-label" htmlFor={id}>
        {icon}
        {label}
      </label>
      <div className="input-wrap">
        <input
          id={id}
          className="input"
          type={type}
          inputMode={inputMode}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          aria-invalid={state === "invalid"}
          aria-describedby={shownError ? `${id}-error` : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        {state === "valid" && (
          <span className="field-status" data-testid="status-valid" aria-label={t("a11y.validField")}>
            <Check strokeWidth={3.5} aria-hidden />
          </span>
        )}
        {state === "invalid" && (
          <span className="field-status" data-testid="status-invalid" aria-label={t("a11y.invalidField")}>
            <X strokeWidth={3.5} aria-hidden />
          </span>
        )}
        {trailing}
      </div>
      {shownError && (
        <p className="field-error" id={`${id}-error`} role="alert">
          <X size={18} strokeWidth={3} aria-hidden />
          {messageKey ? t(`feedback.${messageKey}`) : t(`feedback.${shownError}`)}
        </p>
      )}
      {!shownError && hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}
