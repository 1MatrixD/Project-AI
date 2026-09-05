"use client";

import { useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { LOCALES } from "@/i18n/config";
import { setUserLocale } from "@/i18n/locale";

/** RU | EN. Локаль хранится в cookie (см. i18n/request.ts), поэтому смена языка —
 *  server action + refresh: страница перерисуется с новыми сообщениями без
 *  перезагрузки и без потери клиентского состояния. */
export default function LanguageSwitcher({ className = "" }: { className?: string }) {
  const locale = useLocale();
  const router = useRouter();
  const t = useTranslations("common");
  const [pending, startTransition] = useTransition();

  return (
    <div
      className={`inline-flex rounded-lg border border-[var(--border)] p-0.5 text-xs ${className}`}
      role="group"
      aria-label={t("language")}
      title={t("language")}
    >
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          disabled={pending}
          onClick={() => {
            if (l === locale) return;
            startTransition(async () => {
              await setUserLocale(l);
              router.refresh();
            });
          }}
          className={`px-2 py-1 rounded-md uppercase tracking-wide transition-colors ${
            l === locale
              ? "bg-[var(--surface-2)] text-[var(--foreground)]"
              : "text-[var(--muted)] hover:text-[var(--foreground)]"
          }`}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
