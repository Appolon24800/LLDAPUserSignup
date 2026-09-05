import { AtSign, Mail, User, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import Field from "../components/Field";
import {
  validateEmail,
  validateName,
  validateUsername,
} from "../validation";

export interface Identity {
  username: string;
  firstName: string;
  lastName: string;
  displayName: string;
  email: string;
}

export function identityErrors(identity: Identity): Partial<Record<keyof Identity, string>> {
  return {
    username: validateUsername(identity.username) ?? undefined,
    firstName: validateName(identity.firstName) ?? undefined,
    lastName: validateName(identity.lastName) ?? undefined,
    displayName: validateName(identity.displayName) ?? undefined,
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
  /** Errors keyed by the server's snake_case field names. */
  serverErrors?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const errors = identityErrors(identity);

  return (
    <div className="fade-in">
      <Field
        id="username"
        label={t("fields.username.label")}
        placeholder={t("fields.username.placeholder")}
        hint={t("fields.username.hint")}
        icon={<User aria-hidden />}
        autoComplete="username"
        value={identity.username}
        onChange={(v) => onChange({ username: v })}
        error={errors.username ?? null}
        serverError={serverErrors?.username ?? null}
      />
      <Field
        id="firstName"
        label={t("fields.firstName.label")}
        placeholder={t("fields.firstName.placeholder")}
        icon={<Users aria-hidden />}
        autoComplete="given-name"
        value={identity.firstName}
        onChange={(v) => onChange({ firstName: v })}
        error={errors.firstName ?? null}
        serverError={serverErrors?.firstName ?? null}
      />
      <Field
        id="lastName"
        label={t("fields.lastName.label")}
        placeholder={t("fields.lastName.placeholder")}
        icon={<Users aria-hidden />}
        autoComplete="family-name"
        value={identity.lastName}
        onChange={(v) => onChange({ lastName: v })}
        error={errors.lastName ?? null}
        serverError={serverErrors?.lastName ?? null}
      />
      <Field
        id="displayName"
        label={t("fields.displayName.label")}
        placeholder={t("fields.displayName.placeholder")}
        hint={t("fields.displayName.hint")}
        icon={<Users aria-hidden />}
        value={identity.displayName}
        onChange={(v) => onChange({ displayName: v })}
        error={errors.displayName ?? null}
        serverError={serverErrors?.displayName ?? null}
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

export function UsernameIconFallback() {
  return <AtSign aria-hidden />;
}
