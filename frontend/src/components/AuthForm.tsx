"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import type { User } from "@/lib/types";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const body =
        mode === "login" ? { email, password } : { email, password, name };
      const res = await api<{ token: string; user: User }>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setToken(res.token);
      router.replace("/projects");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm p-8 space-y-4">
        <div className="text-center space-y-1 mb-6">
          <div className="text-2xl font-semibold bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] bg-clip-text text-transparent">
            Проекты ИИ
          </div>
          <div className="text-sm text-[var(--muted)]">
            {mode === "login" ? "Вход в систему" : "Регистрация"}
          </div>
        </div>
        {mode === "register" && (
          <input
            className="input"
            placeholder="Имя"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
        <input
          className="input"
          type="email"
          required
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="input"
          type="password"
          required
          minLength={6}
          placeholder="Пароль (мин. 6 символов)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="text-sm text-red-400">{error}</div>}
        <button className="btn w-full justify-center" disabled={busy}>
          {busy ? "…" : mode === "login" ? "Войти" : "Создать аккаунт"}
        </button>
        <div className="text-center text-sm text-[var(--muted)]">
          {mode === "login" ? (
            <>
              Нет аккаунта?{" "}
              <Link href="/register" className="text-[var(--accent)]">
                Регистрация
              </Link>
            </>
          ) : (
            <>
              Уже есть аккаунт?{" "}
              <Link href="/login" className="text-[var(--accent)]">
                Войти
              </Link>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
