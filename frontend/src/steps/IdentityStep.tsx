import { AtSign, Mail, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import Field from "../components/Field";
import { validateEmail, validateName, validateUsername } from "../validation";

export interface Identity {
  fullName: string;
  username: string;
  email: string;
}

export function identityErrors(identity: Identity): Partial<Record<keyof Identity, string>> {
  return {
    fullName: validateName(identity.fullName) ?? undefined,
    username: validateUsername(identity.username) ?? undefined,
    email: validateEmail(identity.email) ?? undefined,
  };
}

export function identityValid(identity: Identity): boolean {
  const errors = identityErrors(identity);
  return Object.values(errors).every((e) => e === undefined);
}

export default function IdentityStep({
  identity,
  onChange,
  serverErrors,
}: {
  identity: Identity;
  onChange: (patch: Partial<Identity>) => void;
  /** Errors keyed by the server's field names. */
  serverErrors?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const errors = identityErrors(identity);

  return (
    <div className="fade-in">
      <Field
        id="fullName"
        label={t("fields.fullName.label")}
        placeholder={t("fields.fullName.placeholder")}
        hint={t("fields.fullName.hint")}
        icon={<UserRound aria-hidden />}
        autoComplete="name"
        value={identity.fullName}
        onChange={(v) => onChange({ fullName: v })}
        error={errors.fullName ?? null}
        serverError={serverErrors?.fullName ?? serverErrors?.full_name ?? null}
      />
      <Field
        id="username"
        label={t("fields.username.label")}
        placeholder={t("fields.username.placeholder")}
        hint={t("fields.username.hint")}
        icon={<AtSign aria-hidden />}
        autoComplete="username"
        value={identity.username}
        onChange={(v) => onChange({ username: v })}
        error={errors.username ?? null}
        serverError={serverErrors?.username ?? null}
      />
      <Field
        id="email"
        label={t("fields.email.label")}
        placeholder={t("fields.email.placeholder")}
        icon={<Mail aria-hidden />}
        autoComplete="email"
        type="email"
        inputMode="email"
        value={identity.email}
        onChange={(v) => onChange({ email: v })}
        error={errors.email ?? null}
        serverError={serverErrors?.email ?? null}
      />
    </div>
  );
}
