import type { Task } from "./types";

/** Переводчик заголовков досье — `useTranslations("taskPrompt")` из next-intl.
 *  Принимается параметром: модуль без хуков, а язык известен только компоненту. */
export type PromptTranslator = (key: string, values?: Record<string, string | number>) => string;

/** Проработанная задача одним текстом — чтобы вставить её в Claude Code, чат или тикет.
 *
 *  Собирается из того, что уже сохранено в карточке. Исходный промпт RLM-исследования
 *  нигде не хранится (переменные `enrich_one` живут только на время прогона), поэтому
 *  копируется результат проработки, а не запрос, которым он получен. */
export function taskAsPrompt(task: Task, t: PromptTranslator, projectName?: string): string {
  const out: string[] = [];
  const e = task.extra ?? {};

  out.push(`# ${task.title}`);
  if (projectName) out.push(t("project", { name: projectName }));

  if (task.description.trim()) {
    out.push("", task.description.trim());
  }

  if (e.notes?.trim()) {
    out.push("", t("notes"), e.notes.trim());
  }

  if (e.clarifications?.length) {
    out.push("", t("clarifications"));
    for (const c of e.clarifications) out.push(`- [${c.source}] ${c.text}`);
  }

  if (e.reading?.trim()) {
    out.push("", t("reading"), e.reading.trim());
  }

  if (e.hypothesis?.text) {
    out.push("", t("hypothesis", { confidence: e.hypothesis.confidence }), e.hypothesis.text);
  }

  if (e.original_description?.trim() && e.original_description.trim() !== task.description.trim()) {
    out.push("", t("original"), e.original_description.trim());
  }

  if (e.where_to_look?.length) {
    out.push("", t("whereToLook"));
    for (const w of e.where_to_look) out.push(`- \`${w.path}\` — ${w.why}`);
  }

  if (e.reference?.trim()) {
    out.push("", t("reference"), e.reference.trim());
  }

  if (e.impact?.length) {
    out.push("", t("impact"));
    for (const i of e.impact) out.push(`- ${i.what} — ${i.why}`);
  }

  if (e.how_to_verify?.length) {
    out.push("", t("howToVerify"));
    for (const v of e.how_to_verify) out.push(`- ${v.what} — ${v.how}`);
  }

  if (e.open_questions?.length) {
    out.push("", t("openQuestions"));
    for (const q of e.open_questions) {
      out.push(`- ${q.question}`);
      for (const o of q.options) out.push(`  - ${o}`);
      if (q.lean) out.push(`  ${t("lean", { lean: q.lean })}`);
    }
  }

  if (e.plan_summary?.trim()) {
    out.push("", t("planSummary"), e.plan_summary.trim());
  }

  if (task.plan.length) {
    out.push("", t("steps"));
    task.plan.forEach((p, i) => out.push(`${i + 1}. ${p.text}`));
  }

  if (e.files?.length) {
    out.push("", t("files"));
    for (const f of e.files) out.push(`- ${f}`);
  }

  if (e.related?.length) {
    out.push("", t("related"));
    for (const r of e.related) out.push(`- [${r.relation}] «${r.title}» — ${r.note}`);
  }

  if (e.duplicate_of) {
    out.push("", t("duplicate", { title: e.duplicate_of }));
  }

  if (task.report?.trim()) {
    out.push("", t("report"), task.report.trim());
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
