"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const t = useTranslations("common");
  useEffect(() => {
    router.replace(getToken() ? "/projects" : "/login");
  }, [router]);
  return (
    <div className="flex-1 flex items-center justify-center text-[var(--muted)]">
      {t("loading")}
    </div>
  );
}
