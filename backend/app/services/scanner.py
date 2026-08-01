from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pathspec

# каталоги, которые не несут знаний о проекте
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".nuxt", "dist", "build",
    "out", "target", "bin", "obj", ".gradle", ".idea", ".vscode", ".dart_tool",
    "Pods", "DerivedData", ".expo", "coverage", ".turbo", ".cache", "vendor",
    ".terraform", ".serverless", "__snapshots__",
}

IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

IGNORED_EXTENSIONS = {
    ".pyc", ".pyo", ".class", ".o", ".obj", ".dll", ".so", ".dylib", ".exe",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".jar", ".war",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".ico", ".icns", ".lock",
}

CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs", ".java",
    ".kt", ".kts", ".swift", ".m", ".mm", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb",
    ".php", ".dart", ".scala", ".sql", ".sh", ".ps1", ".bat", ".pl", ".lua", ".r",
    ".ex", ".exs", ".erl", ".clj", ".groovy", ".graphql", ".proto", ".prisma",
}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml", ".plist", ".gradle", ".properties", ".editorconfig"}
DOC_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc", ".pdf", ".docx", ".doc", ".rtf"}
DATA_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".db", ".sqlite"}
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp3", ".mp4", ".wav", ".m4a", ".mov", ".avi", ".webm", ".pdf", ".css", ".scss", ".less", ".html", ".htm"}

CONFIG_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "cargo.toml",
    "pubspec.yaml", "composer.json", "gemfile", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "makefile", "cmakelists.txt", "settings.gradle",
    "build.gradle", "pom.xml", "podfile", "tsconfig.json", "next.config.js",
    "vite.config.ts", "tailwind.config.js", "alembic.ini", "manage.py",
}

# файлы крупнее не хэшируем целиком побайтово в память — читаем чанками (всегда), а крупнее лимита помечаем asset
MAX_ANALYZABLE_SIZE = 2 * 1024 * 1024  # 2 МБ — больше почти наверняка не исходник


@dataclass
class ScannedFile:
    rel_path: str
    sha256: str
    size: int
    mtime: float
    kind: str


def classify(rel_path: str, size: int) -> str:
    name = os.path.basename(rel_path).lower()
    ext = os.path.splitext(name)[1]
    if name in CONFIG_NAMES:
        return "config"
    parts = {p.lower() for p in rel_path.replace("\\", "/").split("/")}
    if ext in CODE_EXT:
        if "test" in name or "spec" in name or parts & {"tests", "test", "__tests__", "spec"}:
            return "test"
        return "code"
    if ext in CONFIG_EXT:
        return "config"
    if ext in DOC_EXT:
        return "doc"
    if ext in DATA_EXT:
        return "data"
    if ext in ASSET_EXT:
        return "asset"
    if size > MAX_ANALYZABLE_SIZE:
        return "asset"
    return "other"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_gitignore(dirpath: str) -> pathspec.PathSpec | None:
    gi = os.path.join(dirpath, ".gitignore")
    if not os.path.isfile(gi):
        return None
    try:
        with open(gi, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        spec = pathspec.GitIgnoreSpec.from_lines(lines)
        return spec if spec.patterns else None
    except OSError:
        return None


class _GitIgnoreStack:
    """Вложенные .gitignore (монорепо): паттерны применяются относительно
    каталога, в котором лежит .gitignore."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self._specs: dict[str, pathspec.PathSpec] = {}
        spec = _load_gitignore(self.root)
        if spec:
            self._specs[self.root] = spec

    def enter_dir(self, dirpath: str) -> None:
        spec = _load_gitignore(dirpath)
        if spec:
            self._specs[os.path.abspath(dirpath)] = spec

    def is_ignored(self, abs_path: str, is_dir: bool) -> bool:
        abs_path = os.path.abspath(abs_path)
        for base, spec in self._specs.items():
            if abs_path == base or not abs_path.startswith(base + os.sep):
                continue
            rel = abs_path[len(base) + 1 :].replace("\\", "/")
            if is_dir:
                rel += "/"
            if spec.match_file(rel):
                return True
        return False


def scan_directory(
    root: str,
    known: dict[str, tuple[float, int, str]] | None = None,
    force: bool = False,
    prefix: str = "",
) -> list[ScannedFile]:
    """Инвентаризация каталога.

    known: rel_path -> (mtime, size, sha256) из БД. Если mtime и size не изменились
    и не force — переиспользуем известный хэш (быстрые инкрементальные сканы).
    Файлы и каталоги из .gitignore (включая вложенные) не попадают в индекс.
    prefix — алиас дополнительного корня мультирепо-проекта: пути в результате
    получают вид "prefix/rel" и так же ищутся в known.
    """
    known = known or {}
    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(f"Каталог не найден: {root}")

    gitignore = _GitIgnoreStack(str(root_path))
    result: list[ScannedFile] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        if os.path.abspath(dirpath) != gitignore.root:
            gitignore.enter_dir(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower() not in IGNORED_DIRS
            and not d.startswith(".git")
            and not gitignore.is_ignored(os.path.join(dirpath, d), is_dir=True)
        ]
        for fn in filenames:
            if fn in IGNORED_FILES:
                continue
            if gitignore.is_ignored(os.path.join(dirpath, fn), is_dir=False):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in IGNORED_EXTENSIONS:
                continue
            full = Path(dirpath) / fn
            try:
                st = full.stat()
            except OSError:
                continue
            if st.st_size > 100 * 1024 * 1024:  # >100МБ — пропускаем
                continue
            rel = str(full.relative_to(root_path)).replace("\\", "/")
            if prefix:
                rel = f"{prefix}/{rel}"
            prev = known.get(rel)
            if prev and not force and abs(prev[0] - st.st_mtime) < 1e-6 and prev[1] == st.st_size:
                sha = prev[2]
            else:
                try:
                    sha = _hash_file(full)
                except OSError:
                    continue
            result.append(
                ScannedFile(
                    rel_path=rel,
                    sha256=sha,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    kind=classify(rel, st.st_size),
                )
            )
    return result


@dataclass
class ScanDiff:
    added: list[ScannedFile]
    modified: list[ScannedFile]
    deleted: list[str]
    unchanged: int

    @property
    def stats(self) -> dict:
        return {
            "added": len(self.added),
            "modified": len(self.modified),
            "deleted": len(self.deleted),
            "unchanged": self.unchanged,
            "total": len(self.added) + len(self.modified) + self.unchanged,
        }


def diff_scan(
    scanned: list[ScannedFile], known: dict[str, tuple[float, int, str]]
) -> ScanDiff:
    added, modified = [], []
    seen: set[str] = set()
    unchanged = 0
    for f in scanned:
        seen.add(f.rel_path)
        prev = known.get(f.rel_path)
        if prev is None:
            added.append(f)
        elif prev[2] != f.sha256:
            modified.append(f)
        else:
            unchanged += 1
    deleted = [p for p in known if p not in seen]
    return ScanDiff(added=added, modified=modified, deleted=deleted, unchanged=unchanged)
