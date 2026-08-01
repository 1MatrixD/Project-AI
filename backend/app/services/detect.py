from __future__ import annotations

import json
from pathlib import Path

# маркеры технологий: файл → (тип, технология)
MARKERS: list[tuple[str, str, str]] = [
    ("package.json", "node", "Node.js"),
    ("pyproject.toml", "python", "Python"),
    ("requirements.txt", "python", "Python"),
    ("manage.py", "backend", "Django"),
    ("go.mod", "backend", "Go"),
    ("Cargo.toml", "backend", "Rust"),
    ("pubspec.yaml", "mobile", "Flutter"),
    ("composer.json", "backend", "PHP"),
    ("Gemfile", "backend", "Ruby"),
    ("build.gradle", "mobile", "Android/Gradle"),
    ("settings.gradle", "mobile", "Android/Gradle"),
    ("Podfile", "mobile", "iOS/CocoaPods"),
    ("docker-compose.yml", "infra", "Docker Compose"),
    ("docker-compose.yaml", "infra", "Docker Compose"),
    ("Dockerfile", "infra", "Docker"),
    ("serverless.yml", "infra", "Serverless"),
    ("terraform.tf", "infra", "Terraform"),
]

NODE_FRAMEWORKS = {
    "next": ("frontend", "Next.js"),
    "nuxt": ("frontend", "Nuxt"),
    "react": ("frontend", "React"),
    "vue": ("frontend", "Vue"),
    "svelte": ("frontend", "Svelte"),
    "@angular/core": ("frontend", "Angular"),
    "express": ("backend", "Express"),
    "fastify": ("backend", "Fastify"),
    "@nestjs/core": ("backend", "NestJS"),
    "react-native": ("mobile", "React Native"),
    "expo": ("mobile", "Expo"),
    "electron": ("desktop", "Electron"),
}

PY_FRAMEWORKS = {
    "fastapi": ("backend", "FastAPI"),
    "django": ("backend", "Django"),
    "flask": ("backend", "Flask"),
    "aiohttp": ("backend", "aiohttp"),
    "celery": ("backend", "Celery"),
    "pytest": ("tooling", "pytest"),
}


def detect_project(root: str, rel_paths: list[str]) -> dict:
    """Быстрое эвристическое определение типа проекта по маркер-файлам."""
    root_p = Path(root)
    kinds: set[str] = set()
    stack: list[str] = []
    markers_found: list[str] = []

    lower_paths = {p.lower(): p for p in rel_paths}

    def has(name: str) -> str | None:
        name_l = name.lower()
        if name_l in lower_paths:
            return lower_paths[name_l]
        # маркер на глубине 1-2 (монорепо)
        for lp, orig in lower_paths.items():
            if lp.endswith("/" + name_l) and lp.count("/") <= 2:
                return orig
        return None

    for marker, kind, tech in MARKERS:
        found = has(marker)
        if found:
            kinds.add(kind)
            if tech not in stack:
                stack.append(tech)
            markers_found.append(found)

    # уточнение по package.json
    pkg_rel = has("package.json")
    if pkg_rel:
        try:
            pkg = json.loads((root_p / pkg_rel).read_text(encoding="utf-8", errors="replace"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for dep, (kind, tech) in NODE_FRAMEWORKS.items():
                if dep in deps:
                    kinds.add(kind)
                    if tech not in stack:
                        stack.append(tech)
        except (OSError, json.JSONDecodeError):
            pass

    # уточнение по python-зависимостям
    req_rel = has("requirements.txt")
    if req_rel:
        try:
            text = (root_p / req_rel).read_text(encoding="utf-8", errors="replace").lower()
            for dep, (kind, tech) in PY_FRAMEWORKS.items():
                if dep in text:
                    kinds.add(kind)
                    if tech not in stack:
                        stack.append(tech)
        except OSError:
            pass

    kinds.discard("node")
    kinds.discard("python")
    if not kinds:
        kinds.add("unknown")

    return {
        "project_kinds": sorted(kinds),
        "stack": stack,
        "markers": markers_found[:20],
    }
