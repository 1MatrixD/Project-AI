"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/projects" : "/login");
  }, [router]);
  return (
    <div className="flex-1 flex items-center justify-center text-[var(--muted)]">
      Загрузка…
    </div>
  );
}
