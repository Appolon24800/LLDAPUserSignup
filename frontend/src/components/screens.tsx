import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Full-screen spinner while the invitation code is being checked. */
export function CheckingScreen() {
  const { t } = useTranslation();
  return (
    <div className="screen fade-in" role="status">
      <div className="spinner" aria-hidden />
      <p>{t("code.checking")}</p>
    </div>
  );
}

/** Error screen for an invalid/missing/expired invitation code. */
export function CodeErrorScreen({ errorCode }: { errorCode: string }) {
  const { t } = useTranslation();
  const known = t(`errors.${errorCode}`, { defaultValue: "" }) !== "";
  return (
    <div className="screen fade-in">
      <div className="screen-icon err">
        <X strokeWidth={3} aria-hidden />
      </div>
      <h2>{t("failure.title")}</h2>
      <p>{known ? t(`errors.${errorCode}`) : t("errors.unknown")}</p>
    </div>
  );
}

/** Final success screen. */
export function SuccessScreen({ username }: { username: string }) {
  const { t } = useTranslation();
  return (
    <div className="screen fade-in">
      <div className="screen-icon ok">
        <Check strokeWidth={3} aria-hidden />
      </div>
      <h2>{t("success.title")}</h2>
      <p>{t("success.body", { username })}</p>
    </div>
  );
}

/** Submission failure with a retry action. */
export function FailureScreen({
  errorCode,
  onRetry,
  retryLabel,
}: {
  errorCode: string;
  onRetry: () => void;
  retryLabel: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="screen fade-in">
      <div className="screen-icon err">
        <X strokeWidth={3} aria-hidden />
      </div>
      <h2>{t("failure.title")}</h2>
      <p>{t(`errors.${errorCode}`, { defaultValue: t("errors.unknown") })}</p>
      <button type="button" className="btn primary" onClick={onRetry}>
        {retryLabel}
      </button>
    </div>
  );
}
