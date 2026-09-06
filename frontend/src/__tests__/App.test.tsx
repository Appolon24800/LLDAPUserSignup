import { act, render, screen, waitFor } from "@testing-library/react";
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
  // Full name auto-fills the username suggestion.
  await userEvent.type(await screen.findByLabelText(/full name/i), "Alice Smith");
  expect(screen.getByLabelText(/^username/i)).toHaveValue("alice_smith");
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
    expect(form.username).toBe("alice_smith");
    expect(form.fullName).toBe("Alice Smith");
    expect(form.password).toBe("Phrase-Harbor7-Velvet");
    expect(photo).toBeFalsy();
  });

  it("suggests a username from the full name and respects manual edits", async () => {
    render(<App />);
    const fullName = await screen.findByLabelText(/full name/i);
    await userEvent.type(fullName, "Éloi Fontaine");
    const username = screen.getByLabelText(/^username/i);
    expect(username).toHaveValue("eloi_fontaine");

    // Manual entry wins and later name edits must not clobber it.
    await userEvent.clear(username);
    await userEvent.type(username, "custom-user");
    await userEvent.type(fullName, " Jr");
    expect(username).toHaveValue("custom-user");

    // Clearing the username hands control back to the suggestion.
    await userEvent.clear(username);
    await userEvent.type(fullName, ".");
    expect(username).toHaveValue("eloi_fontaine_jr");
  });

  it("shows the platform name and display name on success", async () => {
    setUrl("/register?code=good");
    mockedValidate.mockResolvedValue({
      valid: true,
      expires_at: "2030-01-01T00:00:00Z",
      platform_name: "Acme",
    });
    mockedRegister.mockResolvedValue("alice_smith");
    render(<App />);
    await fillIdentity();
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.type(await screen.findByLabelText(/^password/i), "Phrase-Harbor7-Velvet");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "Phrase-Harbor7-Velvet");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.click(await screen.findByRole("button", { name: /create my account/i }));

    expect(await screen.findByText("Acme account created")).toBeInTheDocument();
    expect(screen.getByText(/Welcome, Alice Smith!/i)).toBeInTheDocument();
  });

  it("redirects after a countdown when the backend provides a redirect_url", async () => {
    const locationDescriptor = Object.getOwnPropertyDescriptor(window, "location");
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });
    try {
      setUrl("/register?code=good");
      mockedValidate.mockResolvedValue({
        valid: true,
        expires_at: "2030-01-01T00:00:00Z",
        platform_name: "Acme",
        redirect_url: "https://chat.example.com/rooms/main",
      });
      mockedRegister.mockResolvedValue("alice_smith");
      render(<App />);
      await fillIdentity();
      await userEvent.click(screen.getByRole("button", { name: /continue/i }));
      await userEvent.type(await screen.findByLabelText(/^password/i), "Phrase-Harbor7-Velvet");
      await userEvent.type(screen.getByLabelText(/confirm password/i), "Phrase-Harbor7-Velvet");
      await userEvent.click(screen.getByRole("button", { name: /continue/i }));
      await userEvent.click(await screen.findByRole("button", { name: /create my account/i }));

      expect(await screen.findByText(/Welcome, Alice Smith!/i)).toBeInTheDocument();
      const link = screen.getByRole("link", { name: /continue/i });
      expect(link).toHaveAttribute("href", "https://chat.example.com/rooms/main");
      expect(screen.getByText(/Automatic redirection in 5s/i)).toBeInTheDocument();

      // Real 5s countdown; the assign spy fires when it elapses.
      await waitFor(
        () => expect(assign).toHaveBeenCalledWith("https://chat.example.com/rooms/main"),
        { timeout: 7000 },
      );
    } finally {
      if (locationDescriptor) {
        Object.defineProperty(window, "location", locationDescriptor);
      }
    }
  }, 9000);

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
  it("renders English by default and French when the language changes", async () => {
    setUrl("/register?code=good");
    mockedValidate.mockResolvedValue({ valid: true });
    render(<App />);
    expect(await screen.findByText("Create your account")).toBeInTheDocument();
    // No manual switcher: language follows the browser (detector config).
    expect(screen.queryByRole("button", { name: "FR" })).toBeNull();

    const i18n = (await import("../i18n")).default;
    await act(async () => {
      await i18n.changeLanguage("fr");
    });
    expect(await screen.findByText("Créez votre compte")).toBeInTheDocument();
    await act(async () => {
      await i18n.changeLanguage("en");
    });
    expect(await screen.findByText("Create your account")).toBeInTheDocument();
  });
});
