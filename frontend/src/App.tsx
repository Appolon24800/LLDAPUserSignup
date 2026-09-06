import { ArrowLeft, ArrowRight, UserRoundPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, register, validateCode } from "./api";
import ProgressDots from "./components/ProgressDots";
import {
  CheckingScreen,
  CodeErrorScreen,
  FailureScreen,
  SuccessScreen,
} from "./components/screens";
import IdentityStep, {
  identityValid,
  type Identity,
} from "./steps/IdentityStep";
import PasswordStep from "./steps/PasswordStep";
import PhotoStep from "./steps/PhotoStep";
import { suggestUsername, validateConfirm, validatePassword } from "./validation";

type Phase =
  | { name: "checking-code" }
  | { name: "code-error"; errorCode: string }
  | { name: "identity" }
  | { name: "password" }
  | { name: "photo" }
  | { name: "submitting" }
  | { name: "success"; username: string }
  | { name: "failure"; errorCode: string };

const STEP_LABEL_KEYS = ["steps.code", "steps.identity", "steps.password", "steps.photo"];
const TOTAL_STEPS = 4;

function stepOf(phase: Phase["name"]): number {
  switch (phase) {
    case "identity":
      return 1;
    case "password":
      return 2;
    case "photo":
      return 3;
    default:
      return 0;
  }
}

const EMPTY_IDENTITY: Identity = {
  fullName: "",
  username: "",
  email: "",
};

export default function App() {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>({ name: "checking-code" });
  const [code, setCode] = useState<string | null>(null);
  const [platform, setPlatform] = useState("");
  const [identity, setIdentity] = useState<Identity>(EMPTY_IDENTITY);
  const [usernameEdited, setUsernameEdited] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const codeParam = params.get("code");
    if (!codeParam) {
      setPhase({ name: "code-error", errorCode: "missing_code" });
      return;
    }
    let cancelled = false;
    validateCode(codeParam)
      .then((result) => {
        if (cancelled) return;
        if (result.valid) {
          setCode(codeParam);
          setPlatform(result.platform_name ?? "");
          setPhase({ name: "identity" });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        const errorCode = err instanceof ApiError ? err.code : "unknown";
        setPhase({ name: "code-error", errorCode });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const submit = useCallback(async () => {
    if (!code) return;
    setPhase({ name: "submitting" });
    try {
      const username = await register(
        {
          code,
          username: identity.username,
          fullName: identity.fullName,
          email: identity.email,
          password,
        },
        photo,
      );
      setPhase({ name: "success", username });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.fieldErrors) {
          setServerErrors(err.fieldErrors);
          setPhase({ name: "identity" });
          return;
        }
        setPhase({ name: "failure", errorCode: err.code });
      } else {
        setPhase({ name: "failure", errorCode: "unknown" });
      }
    }
  }, [code, identity, password, photo]);

  const passwordOk = !validatePassword(password) && !validateConfirm(password, confirm);
  const stepIndex = stepOf(phase.name);

  return (
    <div className="shell">
      {phase.name === "checking-code" && <CheckingScreen />}
      {phase.name === "code-error" && <CodeErrorScreen errorCode={phase.errorCode} />}
      {phase.name === "submitting" && <CheckingScreen />}
      {phase.name === "success" && (
        <SuccessScreen displayName={identity.fullName} platform={platform} />
      )}
      {phase.name === "failure" && (
        <FailureScreen
          errorCode={phase.errorCode}
          onRetry={() => setPhase({ name: "identity" })}
          retryLabel={t("buttons.retry")}
        />
      )}

      {(phase.name === "identity" || phase.name === "password" || phase.name === "photo") && (
        <>
          <header className="header">
            <h1>{t("app.title")}</h1>
            <p className="subtitle">{t("app.subtitle")}</p>
          </header>

          <ProgressDots
            current={stepIndex}
            total={TOTAL_STEPS}
            labels={STEP_LABEL_KEYS.map((key) => t(key))}
          />

          {phase.name === "identity" && (
            <>
              <IdentityStep
                identity={identity}
                onChange={(patch) => {
                  setServerErrors({});
                  if (patch.username !== undefined) {
                    // While the user hasn't touched it, the username follows
                    // the suggestion derived from the full name; clearing the
                    // field hands control back to the suggestion.
                    setUsernameEdited(patch.username.length > 0);
                  }
                  if (patch.fullName !== undefined && !usernameEdited) {
                    patch = {
                      ...patch,
                      username: suggestUsername(patch.fullName),
                    };
                  }
                  setIdentity((prev) => ({ ...prev, ...patch }));
                }}
                serverErrors={serverErrors}
              />
              <div className="actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={!identityValid(identity)}
                  onClick={() => setPhase({ name: "password" })}
                >
                  {t("buttons.next")}
                  <ArrowRight aria-hidden />
                </button>
              </div>
            </>
          )}

          {phase.name === "password" && (
            <>
              <PasswordStep
                password={password}
                confirm={confirm}
                onChange={(patch) => {
                  if (patch.password !== undefined) setPassword(patch.password);
                  if (patch.confirm !== undefined) setConfirm(patch.confirm);
                }}
              />
              <div className="actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={!passwordOk}
                  onClick={() => setPhase({ name: "photo" })}
                >
                  {t("buttons.next")}
                  <ArrowRight aria-hidden />
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => setPhase({ name: "identity" })}
                >
                  <ArrowLeft aria-hidden />
                  {t("buttons.back")}
                </button>
              </div>
            </>
          )}

          {phase.name === "photo" && (
            <>
              <PhotoStep
                photo={photo}
                onChange={(file) => {
                  setPhoto(file);
                  setPhotoError(null);
                }}
                onError={(code_) => setPhotoError(code_)}
              />
              {photoError && (
                <p className="field-error" role="alert">
                  {t(`feedback.${photoError}`, {
                    defaultValue: t("feedback.photo_unsupported"),
                    max: 2,
                  })}
                </p>
              )}
              <div className="actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={photoError !== null}
                  onClick={() => void submit()}
                >
                  <UserRoundPlus aria-hidden />
                  {t("buttons.submit")}
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => setPhase({ name: "password" })}
                >
                  <ArrowLeft aria-hidden />
                  {t("buttons.back")}
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
