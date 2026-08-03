from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import uuid as uuid_mod

from qdrant_client import AsyncQdrantClient, models

from ..config import get_settings

log = logging.getLogger("projectai.vectors")

"""Семантический (векторный) поиск по знаниям проекта — Qdrant.

Эмбеддинги считаются локально (fastembed/ONNX, без API-затрат) и складываются
в одну коллекцию Qdrant: файлы (роль + сводка ИИ-анализа + сущности), материалы
(выжимки созвонов/ТЗ), соглашения проекта. Поиск в приложении гибридный:
fulltext по графу Neo4j + семантика отсюда (роутер /graph/search).

Недоступный Qdrant не валит пайплайны: запись/удаление — warning и no-op,
поиск возвращает пусто (остаётся fulltext). EMBED_FAKE=1 (тесты) заменяет
модель детерминированным bag-of-words-эмбеддером.
"""

_client: AsyncQdrantClient | None = None
_embedder = None  # fastembed.TextEmbedding; ленивый — первый вызов скачивает модель
_collection_ready = False
_lock = asyncio.Lock()

FAKE_DIM = 64
# косинусная близость ниже — шум, а не смысловое совпадение
MIN_SCORE = 0.25

KIND_LABELS = {"file": "File", "doc": "Document", "decision": "Decision"}


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=20)
    return _client


async def close_client() -> None:
    global _client, _collection_ready
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            pass
        _client = None
    _collection_ready = False


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Детерминированный bag-of-words-эмбеддер для тестов: тексты с общими
    словами дают близкие вектора, модель не скачивается."""
    out: list[list[float]] = []
    for t in texts:
        vec = [0.0] * FAKE_DIM
        for word in re.findall(r"\w+", t.lower(), flags=re.UNICODE):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % FAKE_DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def _real_embed(texts: list[str]) -> list[list[float]]:
    # выполняется в отдельном потоке: fastembed синхронный и CPU-bound
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=get_settings().embed_model)
    return [[float(x) for x in v] for v in _embedder.embed(texts)]


async def embed(texts: list[str]) -> list[list[float]]:
    if get_settings().embed_fake:
        return _fake_embed(texts)
    return await asyncio.to_thread(_real_embed, texts)


async def _ensure_collection(dim: int) -> None:
    global _collection_ready
    if _collection_ready:
        return
    async with _lock:
        if _collection_ready:
            return
        client = get_client()
        name = get_settings().qdrant_collection
        exists = await client.collection_exists(name)
        if exists:
            info = await client.get_collection(name)
            size = info.config.params.vectors.size  # type: ignore[union-attr]
            if size != dim:
                log.warning(
                    "Коллекция %s имеет размерность %s, модель даёт %s — пересоздаю",
                    name, size, dim,
                )
                await client.delete_collection(name)
                exists = False
        if not exists:
            await client.create_collection(
                name,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
            for field in ("project_id", "kind", "key", "root"):
                await client.create_payload_index(
                    name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
                )
        _collection_ready = True


def _point_id(project_id: str, kind: str, key: str) -> str:
    return str(uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"projectai|{project_id}|{kind}|{key}"))


def _filter(
    project_id: str,
    kind: str | None = None,
    keys: list[str] | None = None,
    kinds: list[str] | None = None,
    root: str | None = None,
) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="project_id", match=models.MatchValue(value=project_id))
    ]
    if kind:
        must.append(models.FieldCondition(key="kind", match=models.MatchValue(value=kind)))
    if kinds:
        must.append(models.FieldCondition(key="kind", match=models.MatchAny(any=kinds)))
    if keys:
        must.append(models.FieldCondition(key="key", match=models.MatchAny(any=list(keys))))
    if root is not None:
        must.append(models.FieldCondition(key="root", match=models.MatchValue(value=root)))
    return models.Filter(must=must)


async def upsert(project_id: str, docs: list[dict]) -> int:
    """Записать/обновить документы. docs: {kind, key, title, text, root?}.

    Возвращает число записанных точек; при недоступном Qdrant — 0 (warning).
    """
    docs = [d for d in docs if str(d.get("text") or "").strip()]
    if not docs:
        return 0
    try:
        vectors = await embed(
            [f"{d.get('title', '')}\n{d['text']}"[:2000] for d in docs]
        )
        await _ensure_collection(len(vectors[0]))
        points = [
            models.PointStruct(
                id=_point_id(project_id, str(d["kind"]), str(d["key"])),
                vector=vectors[i],
                payload={
                    "project_id": project_id,
                    "kind": str(d["kind"]),
                    "key": str(d["key"])[:500],
                    "title": str(d.get("title", ""))[:300],
                    "text": str(d["text"])[:600],
                    "root": str(d.get("root", "")),
                },
            )
            for i, d in enumerate(docs)
        ]
        await get_client().upsert(get_settings().qdrant_collection, points=points)
        return len(points)
    except Exception as e:
        log.warning("Qdrant-запись не удалась (%d док.): %s", len(docs), e)
        return 0


async def delete(
    project_id: str,
    kind: str | None = None,
    keys: list[str] | None = None,
    root: str | None = None,
) -> None:
    """Удалить точки по фильтру (без kind/keys/root — весь проект)."""
    try:
        client = get_client()
        name = get_settings().qdrant_collection
        if not await client.collection_exists(name):
            return
        await client.delete(
            name,
            points_selector=models.FilterSelector(
                filter=_filter(project_id, kind=kind, keys=keys, root=root)
            ),
        )
    except Exception as e:
        log.warning("Qdrant-удаление не удалось: %s", e)


async def clone(old_project_id: str, new_project_id: str) -> int:
    """Скопировать все точки проекта под новый project_id.

    Вектора переносятся как есть — эмбеддинги не пересчитываются (это и есть
    смысл дублирования: не платить второй раз за уже сделанную работу).
    Точки копии получают свои id, поэтому удаление оригинала их не заденет.
    """
    copied = 0
    try:
        client = get_client()
        name = get_settings().qdrant_collection
        if not await client.collection_exists(name):
            return 0
        offset = None
        while True:
            points, offset = await client.scroll(
                name,
                scroll_filter=_filter(old_project_id),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if not points:
                break
            new_points = []
            for p in points:
                payload = dict(p.payload or {})
                payload["project_id"] = new_project_id
                new_points.append(
                    models.PointStruct(
                        id=_point_id(
                            new_project_id, str(payload.get("kind", "")), str(payload.get("key", ""))
                        ),
                        vector=p.vector,
                        payload=payload,
                    )
                )
            await client.upsert(name, points=new_points)
            copied += len(new_points)
            if offset is None:
                break
    except Exception as e:
        log.warning("Qdrant-клонирование не удалось (скопировано %d): %s", copied, e)
    return copied


async def search(
    project_id: str,
    query: str,
    limit: int = 10,
    kinds: list[str] | None = None,
    min_score: float = MIN_SCORE,
) -> list[dict]:
    """Семантический поиск: [{kind, key, title, text, score}] по убыванию близости."""
    query = query.strip()
    if not query:
        return []
    try:
        client = get_client()
        name = get_settings().qdrant_collection
        if not await client.collection_exists(name):
            return []
        vec = (await embed([query]))[0]
        res = await client.query_points(
            name,
            query=vec,
            limit=max(1, min(limit, 50)),
            query_filter=_filter(project_id, kinds=kinds),
            score_threshold=min_score,
            with_payload=True,
        )
        return [
            {
                "kind": p.payload.get("kind", ""),
                "key": p.payload.get("key", ""),
                "title": p.payload.get("title", ""),
                "text": p.payload.get("text", ""),
                "score": round(float(p.score), 4),
            }
            for p in res.points
            if p.payload
        ]
    except Exception as e:
        log.warning("Семантический поиск не удался: %s", e)
        return []
