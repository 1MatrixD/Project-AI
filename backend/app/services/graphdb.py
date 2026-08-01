from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase

from ..config import get_settings

log = logging.getLogger("projectai.graph")

_driver = None

# Все узлы скоупятся project_id и имеют uid = f"{project_id}|{вид}|{идентификатор}"
# (составные unique-констрейнты в community-версии ненадёжны, поэтому один uid).

NODE_LABELS = ["Project", "Directory", "File", "Entity", "Component", "Document", "Task", "WorkLog"]


def get_driver():
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


def uid(project_id: str, kind: str, ident: str) -> str:
    return f"{project_id}|{kind}|{ident}"


async def ensure_constraints() -> None:
    async with get_driver().session() as s:
        for label in NODE_LABELS:
            await s.run(
                f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE"
            )
        await s.run(
            "CREATE FULLTEXT INDEX knowledge_fulltext IF NOT EXISTS "
            "FOR (n:File|Entity|Component|Document|Task) "
            "ON EACH [n.name, n.path, n.summary, n.title, n.role]"
        )


async def sync_project_node(project_id: str, name: str, meta: dict) -> None:
    async with get_driver().session() as s:
        await s.run(
            """
            MERGE (p:Project {uid: $uid})
            SET p.project_id = $pid, p.name = $name,
                p.kinds = $kinds, p.stack = $stack
            """,
            uid=uid(project_id, "project", "root"),
            pid=project_id,
            name=name,
            kinds=meta.get("project_kinds", []),
            stack=meta.get("stack", []),
        )


async def sync_structure(project_id: str, files: list[dict], deleted: list[str]) -> None:
    """Синхронизация дерева каталогов и файлов. files: {path, name, kind, size, dir}."""
    pid = project_id
    dirs: set[str] = set()
    for f in files:
        d = f["path"].rsplit("/", 1)[0] if "/" in f["path"] else ""
        while d:
            dirs.add(d)
            d = d.rsplit("/", 1)[0] if "/" in d else ""

    async with get_driver().session() as s:
        if deleted:
            # удаляем файлы и их сущности
            await s.run(
                """
                UNWIND $paths AS path
                MATCH (f:File {uid: $pid + '|file|' + path})
                OPTIONAL MATCH (f)-[:DEFINES]->(e:Entity)
                DETACH DELETE f, e
                """,
                paths=deleted,
                pid=pid,
            )
        if dirs:
            await s.run(
                """
                UNWIND $dirs AS d
                MERGE (n:Directory {uid: $pid + '|dir|' + d})
                SET n.project_id = $pid, n.path = d,
                    n.name = CASE WHEN d CONTAINS '/' THEN split(d, '/')[-1] ELSE d END
                """,
                dirs=sorted(dirs),
                pid=pid,
            )
            # связи каталогов: родитель → ребёнок
            await s.run(
                """
                UNWIND $dirs AS d
                WITH d WHERE d CONTAINS '/'
                MATCH (child:Directory {uid: $pid + '|dir|' + d})
                MATCH (parent:Directory {uid: $pid + '|dir|' + substring(d, 0, size(d) - size(split(d, '/')[-1]) - 1)})
                MERGE (parent)-[:CONTAINS]->(child)
                """,
                dirs=sorted(dirs),
                pid=pid,
            )
            # каталоги верхнего уровня → проект
            await s.run(
                """
                UNWIND $dirs AS d
                WITH d WHERE NOT d CONTAINS '/'
                MATCH (child:Directory {uid: $pid + '|dir|' + d})
                MATCH (p:Project {uid: $pid + '|project|root'})
                MERGE (p)-[:CONTAINS]->(child)
                """,
                dirs=sorted(dirs),
                pid=pid,
            )
        if files:
            await s.run(
                """
                UNWIND $files AS f
                MERGE (n:File {uid: $pid + '|file|' + f.path})
                SET n.project_id = $pid, n.path = f.path, n.name = f.name,
                    n.kind = f.kind, n.size = f.size
                """,
                files=files,
                pid=pid,
            )
            await s.run(
                """
                UNWIND $files AS f
                WITH f WHERE f.dir = ''
                MATCH (n:File {uid: $pid + '|file|' + f.path})
                MATCH (p:Project {uid: $pid + '|project|root'})
                MERGE (p)-[:CONTAINS]->(n)
                """,
                files=files,
                pid=pid,
            )
            await s.run(
                """
                UNWIND $files AS f
                WITH f WHERE f.dir <> ''
                MATCH (n:File {uid: $pid + '|file|' + f.path})
                MATCH (d:Directory {uid: $pid + '|dir|' + f.dir})
                MERGE (d)-[:CONTAINS]->(n)
                """,
                files=files,
                pid=pid,
            )


async def upsert_file_analysis(project_id: str, path: str, analysis: dict) -> None:
    """Результат ИИ-анализа файла → граф: роль файла, сущности, связи."""
    pid = project_id
    entities = analysis.get("entities") or []
    links = analysis.get("links") or []
    async with get_driver().session() as s:
        await s.run(
            """
            MERGE (f:File {uid: $pid + '|file|' + $path})
            SET f.project_id = $pid, f.path = $path,
                f.summary = $summary, f.role = $role, f.tags = $tags
            WITH f
            OPTIONAL MATCH (f)-[:DEFINES]->(old:Entity)
            DETACH DELETE old
            """,
            pid=pid,
            path=path,
            summary=analysis.get("summary", ""),
            role=analysis.get("role", ""),
            tags=analysis.get("tags", []),
        )
        if entities:
            await s.run(
                """
                MATCH (f:File {uid: $pid + '|file|' + $path})
                UNWIND $entities AS e
                MERGE (n:Entity {uid: $pid + '|entity|' + $path + '#' + e.name})
                SET n.project_id = $pid, n.name = e.name, n.etype = e.etype,
                    n.summary = e.summary, n.file_path = $path
                MERGE (f)-[:DEFINES]->(n)
                """,
                pid=pid,
                path=path,
                entities=[
                    {
                        "name": str(e.get("name", ""))[:200],
                        "etype": str(e.get("etype", "other"))[:40],
                        "summary": str(e.get("summary", ""))[:1000],
                    }
                    for e in entities
                    if e.get("name")
                ],
            )
        if links:
            # связи файла с другими файлами/сущностями (по путям)
            await s.run(
                """
                UNWIND $links AS l
                MATCH (a:File {uid: $pid + '|file|' + $path})
                MERGE (b:File {uid: $pid + '|file|' + l.to})
                ON CREATE SET b.project_id = $pid, b.path = l.to,
                              b.name = CASE WHEN l.to CONTAINS '/' THEN split(l.to, '/')[-1] ELSE l.to END
                MERGE (a)-[r:RELATES {type: l.type}]->(b)
                SET r.note = l.note
                """,
                pid=pid,
                path=path,
                links=[
                    {
                        "to": str(l.get("to", ""))[:500],
                        "type": str(l.get("type", "references"))[:40],
                        "note": str(l.get("note", ""))[:300],
                    }
                    for l in links
                    if l.get("to") and l.get("to") != path
                ],
            )


async def set_project_overview(project_id: str, overview: dict) -> None:
    pid = project_id
    async with get_driver().session() as s:
        await s.run(
            """
            MERGE (p:Project {uid: $pid + '|project|root'})
            SET p.summary = $summary, p.project_id = $pid
            """,
            pid=pid,
            summary=overview.get("summary", ""),
        )
        comps = overview.get("components") or []
        if comps:
            await s.run(
                """
                MATCH (p:Project {uid: $pid + '|project|root'})
                UNWIND $comps AS c
                MERGE (n:Component {uid: $pid + '|component|' + c.name})
                SET n.project_id = $pid, n.name = c.name, n.kind = c.kind, n.summary = c.summary
                MERGE (p)-[:HAS_COMPONENT]->(n)
                WITH n, c
                UNWIND c.paths AS path
                MATCH (f:File {uid: $pid + '|file|' + path})
                MERGE (n)-[:INCLUDES]->(f)
                """,
                pid=pid,
                comps=[
                    {
                        "name": str(c.get("name", ""))[:150],
                        "kind": str(c.get("kind", "module"))[:40],
                        "summary": str(c.get("summary", ""))[:2000],
                        "paths": [str(p)[:500] for p in (c.get("paths") or [])[:50]],
                    }
                    for c in comps
                    if c.get("name")
                ],
            )
        features = overview.get("business_logic") or []
        if features:
            await s.run(
                """
                MATCH (p:Project {uid: $pid + '|project|root'})
                UNWIND $features AS ft
                MERGE (n:Component {uid: $pid + '|feature|' + ft.name})
                SET n.project_id = $pid, n.name = ft.name, n.kind = 'feature', n.summary = ft.summary
                MERGE (p)-[:HAS_FEATURE]->(n)
                """,
                pid=pid,
                features=[
                    {"name": str(f.get("name", ""))[:150], "summary": str(f.get("summary", ""))[:2000]}
                    for f in features
                    if f.get("name")
                ],
            )


async def upsert_document(project_id: str, material_id: str, title: str, dtype: str, summary: str, mentions: list[str]) -> None:
    async with get_driver().session() as s:
        await s.run(
            """
            MATCH (p:Project {uid: $pid + '|project|root'})
            MERGE (d:Document {uid: $pid + '|doc|' + $mid})
            SET d.project_id = $pid, d.title = $title, d.dtype = $dtype, d.summary = $summary
            MERGE (p)-[:HAS_DOCUMENT]->(d)
            """,
            pid=project_id,
            mid=material_id,
            title=title,
            dtype=dtype,
            summary=summary[:3000],
        )
        if mentions:
            await s.run(
                """
                MATCH (d:Document {uid: $pid + '|doc|' + $mid})
                UNWIND $paths AS path
                MATCH (f:File {uid: $pid + '|file|' + path})
                MERGE (d)-[:MENTIONS]->(f)
                """,
                pid=project_id,
                mid=material_id,
                paths=mentions,
            )


async def upsert_task_node(project_id: str, task_id: str, title: str, status: str, files: list[str] | None = None) -> None:
    async with get_driver().session() as s:
        await s.run(
            """
            MATCH (p:Project {uid: $pid + '|project|root'})
            MERGE (t:Task {uid: $pid + '|task|' + $tid})
            SET t.project_id = $pid, t.title = $title, t.status = $status
            MERGE (p)-[:HAS_TASK]->(t)
            """,
            pid=project_id,
            tid=task_id,
            title=title[:300],
            status=status,
        )
        if files:
            await s.run(
                """
                MATCH (t:Task {uid: $pid + '|task|' + $tid})
                UNWIND $paths AS path
                MATCH (f:File {uid: $pid + '|file|' + path})
                MERGE (t)-[:AFFECTS]->(f)
                """,
                pid=project_id,
                tid=task_id,
                paths=files,
            )


async def upsert_worklog_node(project_id: str, entry_id: str, description: str, files: list[str]) -> None:
    async with get_driver().session() as s:
        await s.run(
            """
            MATCH (p:Project {uid: $pid + '|project|root'})
            MERGE (w:WorkLog {uid: $pid + '|worklog|' + $wid})
            SET w.project_id = $pid, w.summary = $descr
            MERGE (p)-[:HAS_WORKLOG]->(w)
            """,
            pid=project_id,
            wid=entry_id,
            descr=description[:2000],
        )
        if files:
            await s.run(
                """
                MATCH (w:WorkLog {uid: $pid + '|worklog|' + $wid})
                UNWIND $paths AS path
                MERGE (f:File {uid: $pid + '|file|' + path})
                ON CREATE SET f.project_id = $pid, f.path = path,
                              f.name = CASE WHEN path CONTAINS '/' THEN split(path, '/')[-1] ELSE path END
                MERGE (w)-[:UPDATED]->(f)
                """,
                pid=project_id,
                wid=entry_id,
                paths=files,
            )


async def fulltext_search(project_id: str, query: str, limit: int = 20) -> list[dict]:
    async with get_driver().session() as s:
        res = await s.run(
            """
            CALL db.index.fulltext.queryNodes('knowledge_fulltext', $q)
            YIELD node, score
            WHERE node.project_id = $pid
            RETURN labels(node) AS labels, properties(node) AS props, score
            LIMIT $limit
            """,
            q=query,
            pid=project_id,
            limit=limit,
        )
        out = []
        async for rec in res:
            props = dict(rec["props"])
            props.pop("uid", None)
            props.pop("project_id", None)
            out.append({"labels": rec["labels"], "score": rec["score"], **props})
        return out


async def run_readonly_cypher(project_id: str, query: str, limit: int = 100) -> list[dict]:
    """Read-only cypher для MCP. Все узлы графа несут project_id — фильтрация на совести
    запроса, но публикуем project_id параметром $pid и запрещаем записи."""
    lowered = query.lower()
    for kw in ("create ", "merge ", "delete ", "set ", "remove ", "drop ", "load csv", "call db.", "call apoc.trigger", "call apoc.periodic"):
        if kw in lowered:
            raise ValueError(f"Запрос отклонён: запись/административная операция ({kw.strip()})")
    async with get_driver().session(default_access_mode="READ") as s:
        res = await s.run(query, pid=project_id)  # type: ignore[arg-type]
        out = []
        async for rec in res:
            row = {}
            for key in rec.keys():
                val = rec[key]
                if hasattr(val, "items"):
                    val = dict(val.items())
                elif hasattr(val, "labels"):
                    val = {"labels": list(val.labels), **dict(val)}
                row[key] = val
            out.append(row)
            if len(out) >= limit:
                break
        return out


async def get_graph_view(project_id: str, limit: int = 400) -> dict:
    """Подграф для визуализации карты знаний."""
    pid = project_id
    async with get_driver().session(default_access_mode="READ") as s:
        res = await s.run(
            """
            MATCH (n)
            WHERE n.project_id = $pid AND NOT n:Directory
            WITH n, CASE
                WHEN n:Project THEN 0
                WHEN n:Component THEN 1
                WHEN n:Task THEN 2
                WHEN n:Document THEN 3
                WHEN n:WorkLog THEN 4
                WHEN n:Entity THEN 5
                WHEN n.summary IS NOT NULL AND n.summary <> '' THEN 6
                ELSE 7
            END AS prio
            ORDER BY prio
            LIMIT $limit
            WITH collect(n) AS ns
            UNWIND ns AS n
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE m.project_id = $pid AND NOT m:Directory
            RETURN collect(DISTINCT {uid: n.uid, labels: labels(n),
                                     name: coalesce(n.name, n.title, n.path, 'узел'),
                                     summary: coalesce(n.summary, ''),
                                     kind: coalesce(n.kind, n.etype, n.dtype, n.status, '')}) AS nodes,
                   collect(DISTINCT CASE WHEN m IS NULL THEN NULL ELSE
                       {source: startNode(r).uid, target: endNode(r).uid, type: type(r)} END) AS links
            """,
            pid=pid,
            limit=limit,
        )
        rec = await res.single()
        if rec is None:
            return {"nodes": [], "links": []}
        nodes = rec["nodes"]
        node_ids = {n["uid"] for n in nodes}
        links = [l for l in rec["links"] if l and l["source"] in node_ids and l["target"] in node_ids]
        return {"nodes": nodes, "links": links}


async def get_project_summary_context(project_id: str, max_len: int = 6000) -> str:
    """Краткая текстовая выжимка графа — для системного промпта чата."""
    pid = project_id
    parts: list[str] = []
    async with get_driver().session(default_access_mode="READ") as s:
        res = await s.run(
            "MATCH (p:Project {uid: $pid + '|project|root'}) RETURN p.summary AS s, p.kinds AS kinds, p.stack AS stack",
            pid=pid,
        )
        rec = await res.single()
        if rec and rec["s"]:
            parts.append(f"Обзор проекта: {rec['s']}")
            if rec["stack"]:
                parts.append("Стек: " + ", ".join(rec["stack"]))
        res = await s.run(
            """
            MATCH (p:Project {uid: $pid + '|project|root'})-[:HAS_COMPONENT|HAS_FEATURE]->(c:Component)
            RETURN c.name AS name, c.kind AS kind, c.summary AS summary LIMIT 30
            """,
            pid=pid,
        )
        comps = [f"- [{r['kind']}] {r['name']}: {(r['summary'] or '')[:200]}" async for r in res]
        if comps:
            parts.append("Компоненты и фичи:\n" + "\n".join(comps))
        res = await s.run(
            "MATCH (n:File) WHERE n.project_id = $pid RETURN count(n) AS files", pid=pid
        )
        rec = await res.single()
        if rec:
            parts.append(f"Файлов в графе: {rec['files']}")
    text = "\n\n".join(parts)
    return text[:max_len]


async def get_stats(project_id: str) -> dict:
    async with get_driver().session(default_access_mode="READ") as s:
        res = await s.run(
            """
            MATCH (n) WHERE n.project_id = $pid
            RETURN [l IN labels(n) | l][0] AS label, count(n) AS cnt
            """,
            pid=project_id,
        )
        counts = {rec["label"]: rec["cnt"] async for rec in res}
        res = await s.run(
            "MATCH (a)-[r]->(b) WHERE a.project_id = $pid RETURN count(r) AS rels",
            pid=project_id,
        )
        rec = await res.single()
        return {"nodes": counts, "relations": rec["rels"] if rec else 0}


async def delete_project_graph(project_id: str) -> None:
    async with get_driver().session() as s:
        await s.run("MATCH (n) WHERE n.project_id = $pid DETACH DELETE n", pid=project_id)
