import { useLocale, useTranslations } from "next-intl";

/** Форматирование дат и размеров под текущую локаль. Хук, а не свободные функции:
 *  язык известен только внутри дерева провайдера next-intl. */
export function useFmt() {
  const locale = useLocale();
  const t = useTranslations("units");

  function date(iso: string): string {
    return new Date(iso).toLocaleString(locale === "ru" ? "ru-RU" : "en-GB", {
      day: "2-digit",
      month: locale === "ru" ? "2-digit" : "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function bytes(n: number): string {
    if (n < 1024) return `${n} ${t("b")}`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} ${t("kb")}`;
    if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} ${t("mb")}`;
    return `${(n / 1024 ** 3).toFixed(2)} ${t("gb")}`;
  }

  return { date, bytes };
}
