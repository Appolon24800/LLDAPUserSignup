import { Eye, EyeOff, KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import Field from "../components/Field";
import PasswordStrength from "../components/PasswordStrength";
import { validateConfirm, validatePassword } from "../validation";

export default function PasswordStep({
  password,
  confirm,
  onChange,
}: {
  password: string;
  confirm: string;
  onChange: (patch: { password?: string; confirm?: string }) => void;
}) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  const passwordError = validatePassword(password);
  const confirmError = validateConfirm(password, confirm);

  const toggle = (
    <button
      type="button"
      className="btn ghost"
      aria-label={visible ? t("buttons.hidePassword") : t("buttons.showPassword")}
      onClick={() => setVisible((v) => !v)}
      style={{ position: "absolute", right: "3.2rem", minHeight: "2.25rem", padding: "0 0.5rem" }}
    >
      {visible ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
    </button>
  );

  return (
    <div className="fade-in">
      <Field
        id="password"
        label={t("fields.password.label")}
        placeholder={t("fields.password.placeholder")}
        hint={t("fields.password.hint")}
        icon={<KeyRound aria-hidden />}
        autoComplete="new-password"
        type={visible ? "text" : "password"}
        value={password}
        onChange={(v) => onChange({ password: v })}
        error={passwordError}
        trailing={toggle}
      />
      <PasswordStrength password={password} />
      <div style={{ height: "1rem" }} />
      <Field
        id="confirm"
        label={t("fields.confirm.label")}
        placeholder={t("fields.confirm.placeholder")}
        icon={<KeyRound aria-hidden />}
        autoComplete="new-password"
        type={visible ? "text" : "password"}
        value={confirm}
        onChange={(v) => onChange({ confirm: v })}
        error={confirmError}
      />
    </div>
  );
}
