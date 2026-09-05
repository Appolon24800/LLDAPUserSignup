import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ApiError, validateCode, register } from "../api";

vi.mock("../api", () => ({
  ApiError: class extends Error {
    code: string;
    fieldErrors?: Record<string, string>;
    status?: number;
    constructor(code: string, status?: number, fieldErrors?: Record<string, string>) {
      super(code);
      this.code = code;
      this.status = status;
      this.fieldErrors = fieldErrors;
    }
  },
  validateCode: vi.fn(),
  register: vi.fn(),
}));

const mockedValidate = vi.mocked(validateCode);
const mockedRegister = vi.mocked(register);

function setUrl(query: string) {
  window.history.replaceState({}, "", query);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("invitation code handling", () => {
  it("shows an error when no code is in the URL", async () => {
    setUrl("/register");
    render(<App />);
    expect(await screen.findByText(/No invitation code/i)).toBeInTheDocument();
    expect(mockedValidate).not.toHaveBeenCalled();
  });

  it("shows an error for an unknown code", async () => {
    setUrl("/register?code=unknown");
    mockedValidate.mockRejectedValue(new ApiError("invalid_code", 400));
    render(<App />);
    expect(await screen.findByText(/unknown/i)).toBeInTheDocument();
  });

  it("shows an expiry message for an expired code", async () => {
    setUrl("/register?code=old");
    mockedValidate.mockRejectedValue(new ApiError("code_expired", 400));
    render(<App />);
    expect(await screen.findByText(/expired/i)).toBeInTheDocument();
  });

  it("proceeds to the identity step with a valid code", async () => {
    setUrl("/register?code=good");
    mockedValidate.mockResolvedValue({ valid: true, expires_at: "2030-01-01T00:00:00Z" });
    render(<App />);
    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    expect(mockedValidate).toHaveBeenCalledWith("good");
  });
});

async function fillIdentity() {
  await userEvent.type(await screen.findByLabelText(/^username/i), "alice");
  await userEvent.type(screen.getByLabelText(/first name/i), "Alice");
  await userEvent.type(screen.getByLabelText(/last name/i), "Smith");
  await userEvent.type(screen.getByLabelText(/display name/i), "Alice Smith");
  await userEvent.type(screen.getByLabelText(/email/i), "alice@example.com");
}

describe("wizard flow", () => {
  beforeEach(() => {
    setUrl("/register?code=good");
    mockedValidate.mockResolvedValue({ valid: true, expires_at: "2030-01-01T00:00:00Z" });
  });

  it("next is disabled until all identity fields are valid", async () => {
    render(<App />);
    const next = await screen.findByRole("button", { name: /continue/i });
    expect(next).toBeDisabled();
    await fillIdentity();
    await waitFor(() => expect(next).toBeEnabled());
  });

  it("walks identity -> password -> photo -> success", async () => {
    mockedRegister.mockResolvedValue("alice");
    render(<App />);
    await fillIdentity();
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    const passwordField = await screen.findByLabelText(/^password/i);
    const confirmField = screen.getByLabelText(/confirm password/i);
    const next = screen.getByRole("button", { name: /continue/i });
    expect(next).toBeDisabled();
    await userEvent.type(passwordField, "Phrase-Harbor7-Velvet");
    expect(screen.getByTestId("status-valid")).toBeInTheDocument();
    await userEvent.type(confirmField, "Phrase-Harbor7-Velvet");
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.click(next);

    // Photo step: skip with the dedicated action
    const submit = await screen.findByRole("button", { name: /create my account/i });
    await userEvent.click(submit);

    expect(await screen.findByText(/Account created/i)).toBeInTheDocument();
    expect(screen.getByText(/alice/i)).toBeInTheDocument();
    expect(mockedRegister).toHaveBeenCalledTimes(1);
    const [form, photo] = mockedRegister.mock.calls[0];
    expect(form.code).toBe("good");
    expect(form.username).toBe("alice");
    expect(form.password).toBe("Phrase-Harbor7-Velvet");
    expect(photo).toBeFalsy();
  });

  it("shows a failure screen with a translated error", async () => {
    mockedRegister.mockRejectedValue(new ApiError("ldap_error", 502));
    render(<App />);
    await fillIdentity();
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.type(await screen.findByLabelText(/^password/i), "Phrase-Harbor7-Velvet");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "Phrase-Harbor7-Velvet");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.click(await screen.findByRole("button", { name: /create my account/i }));

    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("surfaces server field errors back on the identity step", async () => {
    mockedRegister.mockRejectedValue(
      new ApiError("username_taken", 409, { username: "taken" }),
    );
    render(<App />);
    await fillIdentity();
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.type(await screen.findByLabelText(/^password/i), "Phrase-Harbor7-Velvet");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "Phrase-Harbor7-Velvet");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.click(await screen.findByRole("button", { name: /create my account/i }));

    expect(await screen.findByText(/already taken/i)).toBeInTheDocument();
  });
});

describe("i18n", () => {
  it("renders in English by default and switches to French", async () => {
    setUrl("/register?code=good");
    mockedValidate.mockResolvedValue({ valid: true });
    render(<App />);
    expect(await screen.findByText("Create your account")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "FR" }));
    expect(await screen.findByText("Créez votre compte")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(await screen.findByText("Create your account")).toBeInTheDocument();
  });
});
