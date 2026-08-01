from __future__ import annotations

from pathlib import Path

from app.services.scanner import classify, diff_scan, scan_directory


def make_tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    (root / "src" / "app.ts").write_text("export const x = 1", encoding="utf-8")
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "README.md").write_text("# doc", encoding="utf-8")
    (root / "node_modules" / "pkg" / "index.js").write_text("junk", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG fake")


def test_scan_ignores_and_classifies(tmp_path: Path) -> None:
    make_tree(tmp_path)
    files = scan_directory(str(tmp_path))
    paths = {f.rel_path for f in files}
    assert "main.py" in paths
    assert "src/app.ts" in paths
    assert not any("node_modules" in p for p in paths)
    kinds = {f.rel_path: f.kind for f in files}
    assert kinds["main.py"] == "code"
    assert kinds["package.json"] == "config"
    assert kinds["README.md"] == "doc"
    assert kinds["logo.png"] == "asset"


def test_diff_add_modify_delete(tmp_path: Path) -> None:
    make_tree(tmp_path)
    first = scan_directory(str(tmp_path))
    known = {f.rel_path: (f.mtime, f.size, f.sha256) for f in first}

    diff0 = diff_scan(first, known)
    assert not diff0.added and not diff0.modified and not diff0.deleted

    (tmp_path / "new.py").write_text("new = True", encoding="utf-8")
    (tmp_path / "main.py").write_text("print(2) # changed", encoding="utf-8")
    (tmp_path / "README.md").unlink()

    second = scan_directory(str(tmp_path), known)
    diff = diff_scan(second, known)
    assert {f.rel_path for f in diff.added} == {"new.py"}
    assert {f.rel_path for f in diff.modified} == {"main.py"}
    assert diff.deleted == ["README.md"]
    assert diff.stats["total"] == len(second)


def test_known_hash_reuse(tmp_path: Path) -> None:
    make_tree(tmp_path)
    first = scan_directory(str(tmp_path))
    known = {f.rel_path: (f.mtime, f.size, "REUSED") for f in first}
    second = scan_directory(str(tmp_path), known)
    by_path = {f.rel_path: f for f in second}
    assert by_path["main.py"].sha256 == "REUSED"  # mtime/size совпали — хэш не пересчитан
    third = scan_directory(str(tmp_path), known, force=True)
    assert {f.rel_path: f for f in third}["main.py"].sha256 != "REUSED"


def test_classify_tests() -> None:
    assert classify("tests/test_api.py", 100) == "test"
    assert classify("src/service.spec.ts", 100) == "test"
    assert classify("src/service.ts", 100) == "code"


def test_gitignore_respected(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n*.log\nsecret.txt\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "artifact.js").write_text("x", encoding="utf-8")
    (tmp_path / "app.log").write_text("log", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    (tmp_path / "main.py").write_text("ok", encoding="utf-8")
    # вложенный подпроект со своим .gitignore (монорепо)
    sub = tmp_path / "mobile"
    sub.mkdir()
    (sub / ".gitignore").write_text("*.freezed.dart\n.dart_tool/\n", encoding="utf-8")
    (sub / "model.freezed.dart").write_text("gen", encoding="utf-8")
    (sub / "model.dart").write_text("code", encoding="utf-8")

    paths = {f.rel_path for f in scan_directory(str(tmp_path))}
    assert "main.py" in paths
    assert "mobile/model.dart" in paths
    assert ".gitignore" in paths  # сам .gitignore — часть проекта
    assert not any(p.startswith("build/") for p in paths)
    assert "app.log" not in paths
    assert "secret.txt" not in paths
    assert "mobile/model.freezed.dart" not in paths
