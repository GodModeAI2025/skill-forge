"""Snapshot und Revert.

In v2 gab es beides nicht als Code. `SKILL.md:403` sagte "REVERT, zurück zur
vorherigen Baseline", und das war die vollständige Spezifikation. Der
Snapshot-Befehl aus agents/mutator.md war zusätzlich kaputt:

    cp -r <datei> <snapshot_dir>/v1/

bricht mit Exit 1 ab, wenn v1 nicht existiert, und legt ohne Trailing-Slash
eine Datei namens v1 an. Die dokumentierte Sicherheitsgarantie war damit
unwahr: eine erkannte Regression wurde geloggt und blieb in der Datei stehen.

Die Tests ab "SICHERHEIT" pinnen Fehler der ersten v3-Fassung, die ein
Code-Review gefunden hat. Sie sind die wichtigsten Tests in dieser Datei: ein
Revert, der fremde Dateien löscht, ist schlimmer als gar kein Revert.
"""

import json
import os

import pytest

from scripts.composite_score import (
    ScopeMismatchError,
    SnapshotConflictError,
    resolve_scope,
    revert,
    snapshot,
)


def _files(target):
    _, files, _ = resolve_scope(target)
    return sorted(str(f) for f in files)


def test_snapshot_creates_missing_directories(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    snap_dir = tmp_path / "snapshots"   # existiert bewusst noch nicht
    manifest = snapshot(str(target), str(snap_dir), "pre-exp-001")
    assert (snap_dir / "pre-exp-001" / "files" / "SKILL.md").read_text() == "# v0\n"
    assert manifest["file_count"] == 1


def test_snapshot_writes_a_directory_not_a_file(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    assert (tmp_path / "snap" / "pre-exp-001").is_dir()


def test_revert_restores_the_previous_content(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    target.write_text("# mutiert\n")
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert target.read_text() == "# v0\n"
    assert result["restored"] == ["SKILL.md"]


def test_revert_removes_files_the_mutation_added(tmp_path):
    """Sonst ist der Zustand nach dem Revert weder v(N) noch v(N+1)."""
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "b.py").write_text("neu vom Mutator\n")   # script_add
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert not (scope / "b.py").exists()
    assert result["removed"] == ["b.py"]
    assert (scope / "a.py").read_text() == "a\n"


def test_revert_restores_a_deleted_file(tmp_path):
    """prune darf nicht dauerhaft löschen können."""
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    (scope / "b.py").write_text("b\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "b.py").unlink()
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (scope / "b.py").read_text() == "b\n"


def test_glob_scope_is_resolved_in_python(tmp_path, monkeypatch):
    """agents/mutator.md gab das Glob an find weiter und splittete auf
    Leerzeichen. Ein Verzeichnis mit Leerzeichen im Namen zerlegte das."""
    scope = tmp_path / "mein projekt"
    (scope / "sub").mkdir(parents=True)
    (scope / "a.py").write_text("a\n")
    (scope / "sub" / "b.py").write_text("b\n")
    (scope / "notiz.txt").write_text("nicht im scope\n")
    pattern = str(scope / "**" / "*.py")
    assert _files(pattern) == ["a.py", "sub/b.py"]
    snapshot(pattern, str(tmp_path / "snap"), "pre-exp-001")
    (scope / "a.py").write_text("kaputt\n")
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (scope / "a.py").read_text() == "a\n"
    assert (scope / "notiz.txt").exists()


def test_snapshot_is_repeatable_on_the_same_version(tmp_path):
    """Ein Resume darf nicht daran scheitern, dass das Verzeichnis existiert."""
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    assert (tmp_path / "snap" / "pre-exp-001" / "files" / "SKILL.md").exists()


def test_manifest_records_target_and_base(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("# v0\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    manifest = json.loads(
        (tmp_path / "snap" / "pre-exp-001" / "manifest.json").read_text()
    )
    assert manifest["files"] == ["SKILL.md"]
    assert manifest["target"].endswith("SKILL.md")
    assert manifest["version"] == "pre-exp-001"


def test_revert_without_manifest_fails_loudly(tmp_path):
    (tmp_path / "snap" / "pre-exp-009").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        revert(str(tmp_path / "snap"), "pre-exp-009")


def test_missing_target_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_scope(str(tmp_path / "gibt-es-nicht.md"))


# ─── SICHERHEIT: gefundene Fehler der ersten v3-Fassung ───────────────────


def test_glob_base_does_not_climb_when_the_prefix_is_missing(tmp_path, monkeypatch):
    """Der gefährlichste gefundene Fehler.

    `_glob_base` fiel auf `base.parent` zurück, wenn das Präfix-Verzeichnis
    noch nicht existierte. Damit lag die Snapshot-Basis eine Ebene zu hoch,
    Snapshot und Revert rechneten mit verschiedenen Basen, und der Revert
    löschte eine fremde Datei, während die Mutation stehen blieb.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "helper.ts").write_text("wichtig\n")   # ausserhalb des Scopes

    pattern = "src/api/**/*.ts"                                 # src/api fehlt noch
    manifest = snapshot(pattern, str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["base"] == str((tmp_path / "src" / "api").resolve())

    (tmp_path / "src" / "api").mkdir()
    (tmp_path / "src" / "api" / "helper.ts").write_text("von der Mutation\n")

    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (tmp_path / "src" / "helper.ts").read_text() == "wichtig\n"
    assert not (tmp_path / "src" / "api" / "helper.ts").exists()
    assert result["removed"] == ["helper.ts"]


def test_revert_works_from_a_different_working_directory(tmp_path, monkeypatch):
    """Ein Resume ist per Definition eine neue Session mit anderem cwd.

    Mit relativer Basis im Manifest legte der Revert einen Schattenbaum an,
    meldete Erfolg und rollte nichts zurück. Genau der Pfad, für den revert
    existiert.
    """
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (work / "SKILL.md").write_text("# v0\n")
    snapshot("SKILL.md", str(tmp_path / "snap"), "pre-exp-001")
    (work / "SKILL.md").write_text("# mutiert\n")

    anderswo = tmp_path / "anderswo"
    anderswo.mkdir()
    monkeypatch.chdir(anderswo)
    revert(str(tmp_path / "snap"), "pre-exp-001")

    assert (work / "SKILL.md").read_text() == "# v0\n"
    assert not (anderswo / "SKILL.md").exists()


def test_revert_restores_at_the_recorded_absolute_path(tmp_path):
    """Das Manifest hält den absoluten Pfad. Ein umbenanntes Verzeichnis
    verschiebt den Revert nicht mit; er stellt dort wieder her, wo der
    Snapshot entstanden ist."""
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    scope.rename(tmp_path / "src-verschoben")
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (scope / "a.py").read_text() == "a\n"
    assert result["restored"] == ["a.py"]


def test_revert_cleans_up_from_a_different_cwd(tmp_path, monkeypatch):
    """Der Löschdurchgang darf nicht still ausfallen, nur weil das cwd ein
    anderes ist. Sonst bleibt die von der Mutation angelegte Datei liegen und
    das nächste Experiment misst gegen einen kontaminierten Zustand."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (work / "src").mkdir()
    (work / "src" / "a.py").write_text("a\n")
    snapshot("src", str(tmp_path / "snap"), "pre-exp-001")
    (work / "src" / "b.py").write_text("neu vom Mutator\n")

    anderswo = tmp_path / "anderswo"
    anderswo.mkdir()
    monkeypatch.chdir(anderswo)
    result = revert(str(tmp_path / "snap"), "pre-exp-001")

    assert result["removed"] == ["b.py"]
    assert not (work / "src" / "b.py").exists()
    assert result["cleanup_skipped"] is False


def test_glob_revert_works_from_a_different_cwd(tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    monkeypatch.chdir(work)
    (work / "src" / "a.ts").write_text("a\n")
    snapshot("src/**/*.ts", str(tmp_path / "snap"), "pre-exp-001")
    (work / "src" / "b.ts").write_text("neu\n")

    anderswo = tmp_path / "anderswo"
    anderswo.mkdir()
    monkeypatch.chdir(anderswo)
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert result["removed"] == ["b.ts"]
    assert (work / "src" / "a.ts").read_text() == "a\n"


def test_snapshot_refuses_to_overwrite_with_different_content(tmp_path):
    """Der Resume-Pfad legt für dasselbe Experiment erneut pre-exp-NNN an.
    Ohne diese Sperre schreibt der zweite Snapshot den mutierten Stand über
    die saubere Baseline, und danach gibt es keinen Weg zurück."""
    target = tmp_path / "SKILL.md"
    target.write_text("# v0 sauber\n")
    snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    target.write_text("# MUTIERT\n")
    with pytest.raises(SnapshotConflictError):
        snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    gespeichert = tmp_path / "snap" / "pre-exp-001" / "files" / "SKILL.md"
    assert gespeichert.read_text() == "# v0 sauber\n"


def test_empty_glob_snapshot_reverts_without_error(tmp_path, monkeypatch):
    """Ein leerer Snapshot auf ein noch fehlendes Präfixverzeichnis darf den
    Rollback nicht sprengen: es gibt schlicht nichts zurückzurollen."""
    monkeypatch.chdir(tmp_path)
    manifest = snapshot("src/api/**/*.ts", str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["file_count"] == 0
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert result["restored"] == []
    assert result["cleanup_skipped"] is True


@pytest.mark.skipif(os.name == "nt", reason="Symlinks brauchen Rechte unter Windows")
def test_symlinked_files_are_skipped(tmp_path):
    """copy2 folgt Symlinks und schreibt beim Revert ausserhalb des Scopes."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "geheim.txt").write_text("original\n")
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    (scope / "link.txt").symlink_to(outside / "geheim.txt")

    manifest = snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["files"] == ["a.py"]
    assert "link.txt" in manifest["skipped_symlinks"]

    (outside / "geheim.txt").write_text("inzwischen geaendert\n")
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (outside / "geheim.txt").read_text() == "inzwischen geaendert\n"


@pytest.mark.skipif(os.name == "nt", reason="Symlinks brauchen Rechte unter Windows")
def test_symlinked_directories_do_not_widen_the_scope(tmp_path, monkeypatch):
    """glob folgt symlinkten Verzeichnissen, rglob nicht. Der Revert löschte
    darüber Dateien ausserhalb der Basis."""
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "fremd.py").write_text("fremd\n")
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    (scope / "vendor").symlink_to(outside, target_is_directory=True)

    snapshot("src/**/*.py", str(tmp_path / "snap"), "pre-exp-001")
    (outside / "neu.py").write_text("von der Mutation\n")
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (outside / "neu.py").exists()
    assert (outside / "fremd.py").read_text() == "fremd\n"


def test_revert_has_no_target_override(tmp_path):
    """Ein --target-Override konnte den Scope verbreitern. Im Test löschte ein
    Snapshot auf eine einzelne Datei plus Revert auf das Elternverzeichnis
    alles daneben, unter anderem LICENSE."""
    import inspect

    from scripts.composite_score import revert as revert_fn

    assert "target" not in inspect.signature(revert_fn).parameters


def test_revert_tolerates_an_already_deleted_extra_file(tmp_path):
    """unlink ohne missing_ok brach mitten im Rollback ab."""
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "b.py").write_text("neu\n")
    manifest_path = tmp_path / "snap" / "pre-exp-001" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    (scope / "b.py").unlink()
    manifest_path.write_text(json.dumps(manifest))
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert result["restored"] == ["a.py"]


def test_safe_join_rejects_paths_outside_the_base(tmp_path):
    """Letzte Sicherung gegen ein manipuliertes Manifest."""
    scope = tmp_path / "src"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    manifest_path = tmp_path / "snap" / "pre-exp-001" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = ["../../entkommen.py"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ScopeMismatchError):
        revert(str(tmp_path / "snap"), "pre-exp-001")


def test_glob_base_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "deep" / "x.ts").write_text("x\n")
    (tmp_path / "y.py").write_text("y\n")
    base, files, _ = resolve_scope("src/**/*.ts")
    assert base == (tmp_path / "src").resolve()
    assert [str(f) for f in files] == ["deep/x.ts"]
    base, files, _ = resolve_scope("*.py")
    assert base == tmp_path.resolve()
    assert [str(f) for f in files] == ["y.py"]


def test_glob_without_matches_is_an_empty_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    base, files, _ = resolve_scope("src/**/*.ts")
    assert files == []
    assert base == (tmp_path / "src").resolve()


def test_existing_paths_with_glob_characters_are_literal(tmp_path, monkeypatch):
    """Next.js-, Remix- und SvelteKit-Routen heissen app/[slug]. Als Glob
    behandelt fand der Snapshot nichts, schrieb file_count 0 mit Exit 0, und
    der Revert rollte nichts zurueck, ohne das zu melden."""
    monkeypatch.chdir(tmp_path)
    route = tmp_path / "app" / "[slug]"
    route.mkdir(parents=True)
    (route / "page.tsx").write_text("original\n")

    manifest = snapshot("app/[slug]", str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["is_glob"] is False
    assert manifest["files"] == ["page.tsx"]
    assert manifest["base"] == str(route.resolve())

    (route / "page.tsx").write_text("MUTIERT\n")
    result = revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (route / "page.tsx").read_text() == "original\n"
    assert result["restored"] == ["page.tsx"]


def test_a_file_with_brackets_in_its_name_is_literal(tmp_path):
    target = tmp_path / "REPORT[2026].md"
    target.write_text("original\n")
    manifest = snapshot(str(target), str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["files"] == ["REPORT[2026].md"]
    target.write_text("MUTIERT\n")
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert target.read_text() == "original\n"


def test_a_pattern_without_matches_stays_a_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    manifest = snapshot("src/**/*.ts", str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["is_glob"] is True


@pytest.mark.skipif(os.name == "nt", reason="Symlinks brauchen Rechte unter Windows")
def test_a_symlinked_target_file_can_be_reverted(tmp_path):
    """absolute_target loeste die letzte Komponente mit auf, resolve_scope
    nicht. Manifest-target und -base zeigten dadurch in verschiedene
    Verzeichnisse, und jeder Revert brach mit ScopeMismatchError ab."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("original\n")
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").symlink_to(repo / "SKILL.md")

    manifest = snapshot(str(skills / "SKILL.md"), str(tmp_path / "snap"), "pre-exp-001")
    assert manifest["base"] == str(skills.resolve())
    assert manifest["target"] == str(skills.resolve() / "SKILL.md")


def test_revert_removes_directories_the_mutation_created(tmp_path):
    """Ein leerer Ordner kann im Generic-Modus die Metrik beeinflussen, etwa
    als Paketverzeichnis oder ueber Lint- und Build-Discovery."""
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "neu" / "tiefer").mkdir(parents=True)
    (scope / "neu" / "tiefer" / "x.py").write_text("neu\n")

    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert not (scope / "neu").exists()
    assert (scope / "a.py").read_text() == "a\n"


def test_revert_keeps_directories_that_were_in_the_snapshot(tmp_path):
    scope = tmp_path / "scope"
    (scope / "sub").mkdir(parents=True)
    (scope / "sub" / "a.py").write_text("a\n")
    snapshot(str(scope), str(tmp_path / "snap"), "pre-exp-001")
    (scope / "sub" / "b.py").write_text("neu\n")
    revert(str(tmp_path / "snap"), "pre-exp-001")
    assert (scope / "sub").is_dir()
    assert (scope / "sub" / "a.py").read_text() == "a\n"
    assert not (scope / "sub" / "b.py").exists()
