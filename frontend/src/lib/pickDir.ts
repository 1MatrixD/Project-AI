import { api, ApiError } from "./api";

/** Системный диалог выбора каталога — его открывает бэкенд на своей машине.
 *
 *  Из браузера настоящий диалог Windows не вызвать (File System Access API
 *  абсолютного пути не отдаёт), поэтому диалог рисует бэкенд; работает это
 *  благодаря тому же допущению «бэкенд и клиент на одной машине», на котором
 *  построен весь /fs/*.
 *
 *  Возвращает путь, `null` при отмене и `"unsupported"`, когда системного
 *  диалога нет (не Windows, нет PowerShell) — тогда зовите DirPicker. */
export async function pickDirNative(initial?: string): Promise<string | null | "unsupported"> {
  try {
    const r = await api<{ path: string | null; cancelled: boolean }>("/fs/pick-dir", {
      method: "POST",
      body: JSON.stringify({ initial: initial ?? "" }),
    });
    return r.path;
  } catch (e) {
    if (e instanceof ApiError && e.status === 501) return "unsupported";
    throw e; // 409 «диалог уже открыт», 504 и прочее — показать пользователю
  }
}
