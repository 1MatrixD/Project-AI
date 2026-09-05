from __future__ import annotations

import logging
import threading

from ..config import get_settings
from .. import i18n

log = logging.getLogger("projectai.transcribe")

_model = None
_model_name: str | None = None
_lock = threading.Lock()


class TranscribeError(RuntimeError):
    pass


def _load_model():
    """Ленивая загрузка faster-whisper (модель скачивается при первом использовании)."""
    global _model, _model_name
    s = get_settings()
    with _lock:
        if _model is not None and _model_name == s.whisper_model:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscribeError(i18n._("faster-whisper не установлен: {error}").format(error=e))

        device = s.whisper_device
        compute = "int8"
        if device == "auto":
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() > 0:
                    device, compute = "cuda", "float16"
                else:
                    device = "cpu"
            except Exception:
                device = "cpu"
        elif device == "cuda":
            compute = "float16"

        log.info("Загружаю whisper %s на %s (%s)…", s.whisper_model, device, compute)
        try:
            _model = WhisperModel(s.whisper_model, device=device, compute_type=compute)
        except Exception as e:
            if device == "cuda":
                log.warning("CUDA не завелась (%s), падаю на CPU int8", e)
                _model = WhisperModel(s.whisper_model, device="cpu", compute_type="int8")
            else:
                raise TranscribeError(i18n._("Не удалось загрузить модель whisper: {error}").format(error=e))
        _model_name = s.whisper_model
        return _model


def transcribe_file(path: str, language: str | None = None) -> dict:
    """Транскрибация аудио/видео. Блокирующая — вызывать через asyncio.to_thread."""
    model = _load_model()
    try:
        segments_iter, info = model.transcribe(
            path,
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        segments = []
        texts = []
        for seg in segments_iter:
            segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
            texts.append(seg.text.strip())
    except Exception as e:
        raise TranscribeError(i18n._("Транскрибация не удалась: {error}").format(error=e))

    def fmt_ts(t: float) -> str:
        h, rem = divmod(int(t), 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    lines = [f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments if s["text"]]
    return {
        "text": "\n".join(lines),
        "plain_text": " ".join(texts),
        "language": info.language,
        "duration": round(info.duration, 1),
        "segments_count": len(segments),
    }
