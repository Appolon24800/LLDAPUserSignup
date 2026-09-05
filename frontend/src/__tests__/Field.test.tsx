import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { User } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import Field from "../components/Field";

function setup(overrides: Partial<Parameters<typeof Field>[0]> = {}) {
  const onChange = vi.fn();
  const props: Parameters<typeof Field>[0] = {
    id: "username",
    label: "Username",
    icon: <User aria-hidden />,
    value: "",
    onChange,
    ...overrides,
  };
  render(<Field {...props} />);
  return { onChange, input: screen.getByLabelText("Username") };
}

describe("Field", () => {
  it("shows no status icon while untouched", () => {
    setup();
    expect(screen.queryByTestId("status-valid")).toBeNull();
    expect(screen.queryByTestId("status-invalid")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a check when touched and valid", () => {
    setup({ value: "alice", error: null });
    expect(screen.getByTestId("status-valid")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a cross and a translated message when invalid", () => {
    setup({ value: "AB", error: "invalid_format" });
    expect(screen.getByTestId("status-invalid")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/lowercase letters/i);
  });

  it("prefers serverError over client error", () => {
    setup({ value: "alice", error: null, serverError: "taken" });
    expect(screen.getByTestId("status-invalid")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/already taken/i);
  });

  it("hides the hint while an error is shown", () => {
    setup({ value: "AB", error: "invalid_format", hint: "Some hint" });
    expect(screen.queryByText("Some hint")).toBeNull();
  });

  it("reports every keystroke to onChange", async () => {
    const { input, onChange } = setup();
    await userEvent.type(input, "ab");
    expect(onChange).toHaveBeenLastCalledWith("b");
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});
