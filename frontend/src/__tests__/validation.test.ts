import { describe, expect, it } from "vitest";
import {
  passwordEntropyBits,
  passwordStrength,
  sniffImage,
  suggestUsername,
  validateConfirm,
  validateEmail,
  validateName,
  validatePassword,
  validateUsername,
} from "../validation";

describe("validateUsername", () => {
  it.each(["alice", "jean.dupont", "a_b-c", "x".repeat(32), "0.0"])(
    "accepts %s",
    (value) => {
      expect(validateUsername(value)).toBeNull();
    },
  );

  it.each([
    ["", "required"],
    ["ab", "invalid_format"],
    ["Alice", "invalid_format"],
    ["x".repeat(33), "invalid_format"],
    ["alice doe", "invalid_format"],
    ["admin", "reserved"],
    ["alice\n", "invalid_format"],
  ])("rejects %j with %s", (value, code) => {
    expect(validateUsername(value)).toBe(code);
  });
});

describe("validateName", () => {
  it.each(["Alice", "Jean Dupont", "O'Brien", "Marie-Claire", "Élodie", "Zoë"])(
    "accepts %s",
    (value) => {
      expect(validateName(value)).toBeNull();
    },
  );

  it.each([
    ["", "invalid_length"],
    ["Alice123", "invalid_format"],
    ["😀", "invalid_format"],
    ["-", "invalid_format"],
    ["x".repeat(65), "invalid_length"],
  ])("rejects %j with %s", (value, code) => {
    expect(validateName(value)).toBe(code);
  });
});

describe("validateEmail", () => {
  it.each([
    "alice@example.com",
    "first.last+tag@sub.example.co.uk",
    "a@b.cd",
  ])("accepts %s", (value) => {
    expect(validateEmail(value)).toBeNull();
  });

  it.each([
    ["", "required"],
    ["nope", "invalid_format"],
    ["a@b", "invalid_format"],
    ["a..b@example.com", "invalid_format"],
    [".a@example.com", "invalid_format"],
  ])("rejects %j with %s", (value, code) => {
    expect(validateEmail(value)).toBe(code);
  });
});

describe("validatePassword", () => {
  it("accepts a long varied phrase", () => {
    expect(validatePassword("Phrase-Harbor7-Velvet")).toBeNull();
    expect(validatePassword("correct horse battery staple 42")).toBeNull();
  });

  it("accepts natural words and phrases", () => {
    expect(validatePassword("anticonstitutionnellement")).toBeNull();
    expect(validatePassword("MonChatDortBienLeSoir")).toBeNull();
    expect(validatePassword("phrase-cheval-batterie")).toBeNull();
  });

  it.each([
    ["", "required"],
    ["short1!A", "too_short"],
    ["Phr4se-Hb", "too_short"], // 9 chars
    ["aaaaaaaaaaaa", "too_weak"],
    ["abcabcabcabc", "too_weak"],
    ["coucoucoucou1", "too_weak"],
    ["password12345", "too_common"],
    ["PASSWORDPASSWORD", "too_common"],
    ["987654987654", "too_weak"],
  ])("rejects %j with %s", (value, code) => {
    expect(validatePassword(value)).toBe(code);
  });

  it("accepts a 10-character strong password", () => {
    expect(validatePassword("Phr4se-Hb7")).toBeNull();
  });

  it("entropy rewards length but caps degenerate repetition", () => {
    const repetitive = passwordEntropyBits("a".repeat(12));
    const pattern = passwordEntropyBits("abcabcabcabc");
    const natural = passwordEntropyBits("anticonstitutionnellement");
    expect(repetitive).toBeLessThan(pattern);
    expect(pattern).toBeLessThan(natural);
    expect(natural).toBeGreaterThan(60);
    expect(pattern).toBeLessThan(60);
  });

  it("strength levels", () => {
    expect(passwordStrength("")).toBe("empty");
    expect(passwordStrength("aaaaaaaaaaaa")).toBe("weak");
    expect(passwordStrength("abcdefghi12")).toBe("fair"); // ~57 bits
    expect(passwordStrength("Phrase-Harbor7-Velvet")).toBe("strong");
  });
});

describe("suggestUsername", () => {
  it("derives an underscored username from a full name", () => {
    expect(suggestUsername("Jean Dupont")).toBe("jean_dupont");
  });

  it("strips accents", () => {
    expect(suggestUsername("Éloi Fontaine")).toBe("eloi_fontaine");
  });

  it("collapses separators and trims edges", () => {
    expect(suggestUsername("  Marie-Claire  O'Brien ")).toBe("marie_claire_o_brien");
  });

  it("returns empty for names too short to be valid", () => {
    expect(suggestUsername("Al")).toBe("");
    expect(suggestUsername("")).toBe("");
  });

  it("caps length at 32 characters on a letter boundary", () => {
    const long = "Ab Cd Ef Gh Ij Kl Mn Op Qr St Uv Wx Yz Ab Cd Ef Gh Ij";
    const suggested = suggestUsername(long);
    expect(suggested.length).toBeLessThanOrEqual(32);
    expect(suggested).toMatch(/^[a-z0-9]/);
    expect(suggested).toMatch(/[a-z0-9]$/);
  });
});

describe("validateConfirm", () => {
  it("matches", () => {
    expect(validateConfirm("abc", "abc")).toBeNull();
  });
  it("mismatches", () => {
    expect(validateConfirm("abc", "abd")).toBe("mismatch");
  });
  it("empty is required", () => {
    expect(validateConfirm("abc", "")).toBe("required");
  });
});

describe("sniffImage", () => {
  // jsdom's File lacks arrayBuffer(), so duck-type a minimal stand-in.
  function file(bytes: number[]) {
    const buffer = new Uint8Array(bytes).buffer;
    return { arrayBuffer: async () => buffer } as unknown as File;
  }

  it("accepts jpeg/png/gif/webp magic bytes", async () => {
    expect(await sniffImage(file([0xff, 0xd8, 0xff, 0xe0]))).toBe(true);
    expect(await sniffImage(file([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe(true);
    expect(await sniffImage(file([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]))).toBe(true); // GIF89a
    expect(
      await sniffImage(file([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50])),
    ).toBe(true); // RIFF....WEBP
  });

  it("rejects text and empty content regardless of declared type", async () => {
    expect(await sniffImage(file([...new TextEncoder().encode("<?php")]))).toBe(false);
    expect(await sniffImage(file([]))).toBe(false);
  });
});
