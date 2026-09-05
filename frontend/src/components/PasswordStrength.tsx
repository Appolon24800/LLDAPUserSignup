import { useTranslation } from "react-i18next";
import { passwordStrength } from "../validation";

export default function PasswordStrength({ password }: { password: string }) {
  const { t } = useTranslation();
  const level = passwordStrength(password);
  if (level === "empty") return null;

  return (
    <div className="strength" data-strength={level} aria-live="polite">
      <span className="visually-hidden">{t("strength.label")}</span>
      <div
        className="strength-bar"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={3}
        aria-valuenow={level === "weak" ? 1 : level === "fair" ? 2 : 3}
        aria-valuetext={t(`strength.${level}`)}
      >
        <div className="strength-fill" />
      </div>
      <span aria-hidden>{t(`strength.${level}`)}</span>
    </div>
  );
}
