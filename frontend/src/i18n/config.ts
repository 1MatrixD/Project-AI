/** Поддерживаемые языки интерфейса. Локаль живёт в cookie, а не в URL:
 *  приложение локальное и за авторизацией, красивые /ru/… адреса ему не нужны. */
export const LOCALES = ["ru", "en"] as const;
export type Locale = (typeof LOCALES)[number];

/** Без cookie и без подсказки браузера — английский: репозиторий публичный. */
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "projectai_locale";

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}
