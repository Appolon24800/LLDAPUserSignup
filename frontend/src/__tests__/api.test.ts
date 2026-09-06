import { describe, expect, it } from "vitest";
import { deriveApiBase } from "../api";

describe("deriveApiBase", () => {
  it("explicit env base wins and loses its trailing slash", () => {
    expect(deriveApiBase("/register?code=x", "https://api.example.com/")).toBe(
      "https://api.example.com",
    );
  });

  it("derives the subpath base from the wizard page URL", () => {
    expect(deriveApiBase("/signup/register")).toBe("/signup");
    expect(deriveApiBase("/signup/deep/nest/register")).toBe("/signup/deep/nest");
  });

  it("root hosting derives an empty base", () => {
    expect(deriveApiBase("/register")).toBe("");
    expect(deriveApiBase("/")).toBe("");
    expect(deriveApiBase("/signup/")).toBe("/signup");
  });
});
