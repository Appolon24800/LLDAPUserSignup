import "@testing-library/jest-dom/vitest";
import "./i18n";
import i18n from "./i18n";

// Deterministic language for all tests, independent of the host browser.
void i18n.changeLanguage("en");
