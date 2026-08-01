from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..config import get_settings

log = logging.getLogger("projectai.claude")

# reasoning → бюджет размышлений (MAX_THINKING_TOKENS)
REASONING_BUDGETS = {"none": "0", "low": "4096", "medium": "12288", "high": "31999"}


class ClaudeError(RuntimeError):
    pass


def resolve_cmd_prefix() -> list[str]:
    s = get_settings()
    # .py-скрипт (фейковый claude в тестах) запускаем текущим python:
    # cmd-обёртки Windows искажают многострочные аргументы
    if s.claude_bin.lower().endswith(".py"):
        return [sys.executable, s.claude_bin]
    path = shutil.which(s.claude_bin)
    if path is None:
        raise ClaudeError(
            f"Claude Code CLI не найден ({s.claude_bin}). Установи и авторизуй claude."
        )
    return [path]


def _build_env(reasoning: str | None) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # не наследуем вложенным вызовам служебные переменные Claude Code
    env.pop("CLAUDECODE", None)
    if reasoning and reasoning in REASONING_BUDGETS and reasoning != "none":
        env["MAX_THINKING_TOKENS"] = REASONING_BUDGETS[reasoning]
    return env


def _base_cmd(
    prompt: str,
    *,
    system: str | None,
    tools: list[str] | None,
    model: str | None,
    session_id: str | None,
    mcp_config: str | None,
    output_format: str,
    max_turns: int | None = None,
) -> list[str]:
    cmd = [*resolve_cmd_prefix(), "-p", prompt, "--output-format", output_format]
    if output_format == "stream-json":
        cmd.append("--verbose")
    if system:
        cmd += ["--append-system-prompt", system]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    if mcp_config:
        cmd += ["--mcp-config", mcp_config, "--strict-mcp-config"]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    return cmd


def _run_sync(cmd: list[str], cwd: str | None, env: dict, timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out, err


async def run_prompt(
    prompt: str,
    *,
    cwd: str | None = None,
    system: str | None = None,
    tools: list[str] | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    mcp_config: str | None = None,
    max_turns: int | None = None,
    timeout: int | None = None,
) -> dict:
    """Одиночный вызов claude -p, возвращает распарсенный result-JSON CLI."""
    s = get_settings()
    cmd = _base_cmd(
        prompt,
        system=system,
        tools=tools,
        model=model,
        session_id=None,
        mcp_config=mcp_config,
        output_format="json",
        max_turns=max_turns,
    )
    env = _build_env(reasoning)
    code, out, err = await asyncio.to_thread(
        _run_sync, cmd, cwd, env, timeout or s.claude_timeout_sec
    )
    if code != 0 and not out.strip():
        raise ClaudeError(f"claude завершился с кодом {code}: {err[:2000]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise ClaudeError(f"Невалидный JSON от claude (код {code}): {out[:500]} / stderr: {err[:500]}")
    if data.get("is_error"):
        raise ClaudeError(f"claude вернул ошибку: {str(data.get('result'))[:2000]}")
    return data


_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str):
    """Достаёт JSON из ответа модели (с код-фенсами или без)."""
    text = text.strip()
    m = _JSON_RE.search(text)
    if m:
        text = m.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start > 0:
        text = text[start:]
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text)
    return obj


async def run_json_prompt(prompt: str, **kwargs) -> tuple[object, dict]:
    """Вызов, от которого ждём строго JSON-ответ. Возвращает (объект, мета)."""
    data = await run_prompt(prompt, **kwargs)
    result_text = data.get("result", "")
    try:
        obj = extract_json(result_text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ClaudeError(f"Модель вернула не-JSON: {result_text[:500]} ({e})")
    meta = {
        "cost_usd": data.get("total_cost_usd"),
        "duration_ms": data.get("duration_ms"),
        "session_id": data.get("session_id"),
    }
    return obj, meta


@dataclass
class StreamHandle:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


async def stream_prompt(
    prompt: str,
    *,
    cwd: str | None = None,
    system: str | None = None,
    tools: list[str] | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    session_id: str | None = None,
    mcp_config: str | None = None,
    timeout: int | None = None,
) -> AsyncIterator[dict]:
    """Стриминг stream-json событий claude -p (через поток, безопасно для Windows)."""
    s = get_settings()
    cmd = _base_cmd(
        prompt,
        system=system,
        tools=tools,
        model=model,
        session_id=session_id,
        mcp_config=mcp_config,
        output_format="stream-json",
    )
    env = _build_env(reasoning)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                loop.call_soon_threadsafe(queue.put_nowait, event)
            proc.wait()
            if proc.returncode != 0:
                err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "process_error", "code": proc.returncode, "stderr": err[:2000]},
                )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    threading.Thread(target=reader, daemon=True).start()

    deadline = loop.time() + (timeout or s.claude_timeout_sec)
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                proc.kill()
                yield {"type": "process_error", "code": -1, "stderr": "Таймаут ответа ИИ"}
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                proc.kill()
                yield {"type": "process_error", "code": -1, "stderr": "Таймаут ответа ИИ"}
                return
            if item is _SENTINEL:
                return
            yield item
    finally:
        if proc.poll() is None:
            proc.kill()
