from pathlib import Path

from ai_pr_reviewer.context_finder import find_related_files


def test_finds_python_import_match(tmp_path):
    related_dir = tmp_path / "src" / "ai_pr_reviewer"
    related_dir.mkdir(parents=True)
    (related_dir / "config.py").write_text("class Config:\n    pass\n")

    diff_text = "@@ -1,1 +1,2 @@\n+from ai_pr_reviewer.config import Config"

    results = find_related_files(
        target_filename="src/ai_pr_reviewer/review_engine.py",
        target_diff_text=diff_text,
        other_filenames=["src/ai_pr_reviewer/config.py", "src/ai_pr_reviewer/review_engine.py"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert results[0].filename == "src/ai_pr_reviewer/config.py"
    assert "class Config" in results[0].excerpt


def test_finds_js_import_match(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "helpers.js").write_text("export function helpers() {}\n")

    diff_text = "@@ -1,1 +1,2 @@\n+import { helpers } from './helpers';"

    results = find_related_files(
        target_filename="src/main.js",
        target_diff_text=diff_text,
        other_filenames=["src/helpers.js", "src/main.js"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert results[0].filename == "src/helpers.js"


def test_finds_js_require_match(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "utils.js").write_text("module.exports = {};\n")

    diff_text = "@@ -1,1 +1,2 @@\n+const utils = require('./lib/utils');"

    results = find_related_files(
        target_filename="index.js",
        target_diff_text=diff_text,
        other_filenames=["lib/utils.js", "index.js"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert results[0].filename == "lib/utils.js"


def test_finds_java_import_match(tmp_path):
    (tmp_path / "com" / "example").mkdir(parents=True)
    (tmp_path / "com" / "example" / "Foo.java").write_text("public class Foo {}\n")

    diff_text = "@@ -1,1 +1,2 @@\n+import com.example.Foo;"

    results = find_related_files(
        target_filename="com/example/Main.java",
        target_diff_text=diff_text,
        other_filenames=["com/example/Foo.java", "com/example/Main.java"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert results[0].filename == "com/example/Foo.java"


def test_finds_c_include_match(tmp_path):
    (tmp_path / "include").mkdir()
    (tmp_path / "include" / "myheader.h").write_text("#define FOO 1\n")

    diff_text = '@@ -1,1 +1,2 @@\n+#include "include/myheader.h"'

    results = find_related_files(
        target_filename="src/main.c",
        target_diff_text=diff_text,
        other_filenames=["include/myheader.h", "src/main.c"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert results[0].filename == "include/myheader.h"


def test_returns_empty_when_no_imports_referenced(tmp_path):
    diff_text = "@@ -1,1 +1,2 @@\n+x = 1"

    results = find_related_files(
        target_filename="a.py",
        target_diff_text=diff_text,
        other_filenames=["b.py"],
        workspace_root=tmp_path,
    )

    assert results == []


def test_never_includes_target_file_itself(tmp_path):
    (tmp_path).joinpath("config.py").write_text("class Config: pass\n")
    diff_text = "@@ -1,1 +1,2 @@\n+from config import Config"

    results = find_related_files(
        target_filename="config.py",
        target_diff_text=diff_text,
        other_filenames=["config.py"],
        workspace_root=tmp_path,
    )

    assert results == []


def test_skips_files_that_do_not_exist_on_disk(tmp_path):
    diff_text = "@@ -1,1 +1,2 @@\n+from ai_pr_reviewer.config import Config"

    results = find_related_files(
        target_filename="review_engine.py",
        target_diff_text=diff_text,
        other_filenames=["config.py"],
        workspace_root=tmp_path,
    )

    assert results == []


def test_truncates_excerpt_to_max_length(tmp_path):
    long_content = "x = 1\n" * 1000
    (tmp_path / "config.py").write_text(long_content)
    diff_text = "@@ -1,1 +1,2 @@\n+import config"

    results = find_related_files(
        target_filename="main.py",
        target_diff_text=diff_text,
        other_filenames=["config.py"],
        workspace_root=tmp_path,
    )

    assert len(results) == 1
    assert len(results[0].excerpt) <= 2000


def test_caps_number_of_related_files(tmp_path):
    diff_lines = ["@@ -1,1 +1,5 @@"]
    other_filenames = []
    for i in range(5):
        (tmp_path / f"mod{i}.py").write_text(f"# module {i}\n")
        diff_lines.append(f"+import mod{i}")
        other_filenames.append(f"mod{i}.py")

    results = find_related_files(
        target_filename="main.py",
        target_diff_text="\n".join(diff_lines),
        other_filenames=other_filenames,
        workspace_root=tmp_path,
    )

    assert len(results) == 3


def test_skips_symlinked_candidates_even_when_target_is_inside_workspace(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text("class Config: pass\n")
    diff_text = "@@ -1,1 +1,2 @@\n+import config"

    monkeypatch.setattr(Path, "is_symlink", lambda self: True)

    results = find_related_files(
        target_filename="main.py",
        target_diff_text=diff_text,
        other_filenames=["config.py"],
        workspace_root=tmp_path,
    )

    assert results == []


def test_ignores_js_import_on_removed_line(tmp_path):
    (tmp_path / "helpers.js").write_text("export function helpers() {}\n")
    diff_text = "@@ -1,1 +1,2 @@\n-import { helpers } from './helpers';\n+x = 1"

    results = find_related_files(
        target_filename="main.js",
        target_diff_text=diff_text,
        other_filenames=["helpers.js"],
        workspace_root=tmp_path,
    )

    assert results == []


def test_ignores_unrelated_files_in_pr(tmp_path):
    (tmp_path / "config.py").write_text("class Config: pass\n")
    (tmp_path / "unrelated.py").write_text("# nothing to do with this diff\n")
    diff_text = "@@ -1,1 +1,2 @@\n+from config import Config"

    results = find_related_files(
        target_filename="main.py",
        target_diff_text=diff_text,
        other_filenames=["config.py", "unrelated.py"],
        workspace_root=tmp_path,
    )

    assert [r.filename for r in results] == ["config.py"]


def test_rejects_path_traversal_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_secret = tmp_path / "secret.py"
    outside_secret.write_text("SECRET = 'do-not-leak'\n")

    diff_text = "@@ -1,1 +1,2 @@\n+import secret"

    results = find_related_files(
        target_filename="main.py",
        target_diff_text=diff_text,
        other_filenames=["../secret.py"],
        workspace_root=workspace,
    )

    assert results == []
