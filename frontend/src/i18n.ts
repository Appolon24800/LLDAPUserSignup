import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import en from "./i18n/en.json";
import fr from "./i18n/fr.json";

export const SUPPORTED_LANGUAGES = ["en", "fr"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

void i18n.use(LanguageDetector).use(initReactI18next).init({
  resources: {
    en: { translation: en },
    fr: { translation: fr },
  },
  supportedLngs: SUPPORTED_LANGUAGES as unknown as string[],
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React already escapes
  detection: {
    order: ["localStorage", "navigator"],
    lookupLocalStorage: "signupLang",
    caches: ["localStorage"],
  },
});

export default i18n;
