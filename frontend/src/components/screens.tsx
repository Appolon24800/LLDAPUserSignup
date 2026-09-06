import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";
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

const REDIRECT_DELAY_SECONDS = 5;

/** Final success screen: platform-prefixed title, display name welcome,
 * optional link + delayed redirect to the configured destination. */
export function SuccessScreen({
  displayName,
  platform,
  redirectUrl,
}: {
  displayName: string;
  platform: string;
  redirectUrl?: string;
}) {
  const { t } = useTranslation();
  const title = platform ? t("success.titlePlatform", { platform }) : t("success.title");
  const [seconds, setSeconds] = useState(REDIRECT_DELAY_SECONDS);

  useEffect(() => {
    if (!redirectUrl) return;
    if (seconds <= 0) {
      window.location.assign(redirectUrl);
      return;
    }
    const timer = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [redirectUrl, seconds]);

  return (
    <div className="screen fade-in">
      <div className="screen-icon ok">
        <Check strokeWidth={3} aria-hidden />
      </div>
      <h2>{title}</h2>
      <p>{t("success.body", { name: displayName })}</p>
      {redirectUrl && (
        <>
          <a className="btn primary" href={redirectUrl}>
            {t("success.continue")}
          </a>
          <p className="field-hint" aria-live="polite">
            {t("success.redirecting", { seconds })}
          </p>
        </>
      )}
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
