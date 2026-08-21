import type { Task } from "./types";

/** Проработанная задача одним текстом — чтобы вставить её в Claude Code, чат или тикет.
 *
 *  Собирается из того, что уже сохранено в карточке. Исходный промпт RLM-исследования
 *  нигде не хранится (переменные `enrich_one` живут только на время прогона), поэтому
 *  копируется результат проработки, а не запрос, которым он получен. */
export function taskAsPrompt(task: Task, projectName?: string): string {
  const out: string[] = [];
  const e = task.extra ?? {};

  out.push(`# ${task.title}`);
  if (projectName) out.push(`Проект: ${projectName}`);

  if (task.description.trim()) {
    out.push("", task.description.trim());
  }

  if (e.reading?.trim()) {
    out.push("", "## Как понята задача", e.reading.trim());
  }

  if (e.hypothesis?.text) {
    out.push("", `## Гипотеза (уверенность: ${e.hypothesis.confidence})`, e.hypothesis.text);
  }

  if (e.original_description?.trim() && e.original_description.trim() !== task.description.trim()) {
    out.push("", "## Как задача была сформулирована изначально", e.original_description.trim());
  }

  if (e.where_to_look?.length) {
    out.push("", "## Где смотреть");
    for (const w of e.where_to_look) out.push(`- \`${w.path}\` — ${w.why}`);
  }

  if (e.reference?.trim()) {
    out.push("", "## Образец рядом", e.reference.trim());
  }

  if (e.impact?.length) {
    out.push("", "## Нюансы — что заденет работа");
    for (const i of e.impact) out.push(`- ${i.what} — ${i.why}`);
  }

  if (e.how_to_verify?.length) {
    out.push("", "## Как проверить");
    for (const v of e.how_to_verify) out.push(`- ${v.what} — ${v.how}`);
  }

  if (e.open_questions?.length) {
    out.push("", "## Решить до начала (ИИ намеренно не выбирал)");
    for (const q of e.open_questions) {
      out.push(`- ${q.question}`);
      for (const o of q.options) out.push(`  - ${o}`);
      if (q.lean) out.push(`  склоняется к: ${q.lean}`);
    }
  }

  if (e.plan_summary?.trim()) {
    out.push("", "## План решения", e.plan_summary.trim());
  }

  if (task.plan.length) {
    out.push("", "## Шаги");
    task.plan.forEach((p, i) => out.push(`${i + 1}. ${p.text}`));
  }

  if (e.files?.length) {
    out.push("", "## Файлы");
    for (const f of e.files) out.push(`- ${f}`);
  }

  if (e.related?.length) {
    out.push("", "## Связанные темы");
    for (const r of e.related) out.push(`- [${r.relation}] «${r.title}» — ${r.note}`);
  }

  if (e.duplicate_of) {
    out.push("", `⚠️ Возможный дубликат: «${e.duplicate_of}»`);
  }

  if (task.report?.trim()) {
    out.push("", "## Отчёт", task.report.trim());
  }

  return out.join("\n");
}

/** Буфер обмена. navigator.clipboard недоступен вне secure context (например,
 *  если приложение открыли по IP в локальной сети) — тогда старый execCommand. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* падаем в фолбэк ниже */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
