from ai_pr_reviewer.diff_parser import LineType, parse_patch, split_unified_diff_by_file


def test_parse_patch_returns_empty_for_no_patch():
    file_diff = parse_patch("binary.png", None)

    assert file_diff.filename == "binary.png"
    assert file_diff.lines == []
    assert file_diff.commentable_lines() == set()


def test_parse_patch_tracks_added_removed_and_context_lines():
    patch = "@@ -1,3 +1,4 @@\n line1\n-old line\n+new line\n+added line\n line3"

    file_diff = parse_patch("foo.py", patch)

    assert [(line.line_type, line.old_lineno, line.new_lineno) for line in file_diff.lines] == [
        (LineType.CONTEXT, 1, 1),
        (LineType.REMOVED, 2, None),
        (LineType.ADDED, None, 2),
        (LineType.ADDED, None, 3),
        (LineType.CONTEXT, 3, 4),
    ]


def test_parse_patch_handles_multiple_hunks():
    patch = (
        "@@ -1,2 +1,2 @@\n"
        " line1\n"
        "-old\n"
        "+new\n"
        "@@ -10,2 +10,3 @@\n"
        " line10\n"
        "+inserted\n"
        " line11"
    )

    file_diff = parse_patch("foo.py", patch)
    new_linenos = [line.new_lineno for line in file_diff.lines if line.new_lineno is not None]

    assert new_linenos == [1, 2, 10, 11, 12]


def test_parse_patch_ignores_no_newline_marker():
    patch = "@@ -1,1 +1,1 @@\n-old\n+new\n\\ No newline at end of file"

    file_diff = parse_patch("foo.py", patch)

    assert len(file_diff.lines) == 2


def test_commentable_lines_excludes_removed_only_lines():
    patch = "@@ -1,2 +1,1 @@\n line1\n-removed line"

    file_diff = parse_patch("foo.py", patch)

    assert file_diff.commentable_lines() == {1}


def test_old_lineno_for_returns_none_for_added_line():
    patch = "@@ -1,1 +1,2 @@\n line1\n+added line"

    file_diff = parse_patch("foo.py", patch)

    assert file_diff.old_lineno_for(2) is None


def test_old_lineno_for_returns_old_line_for_context_line():
    patch = "@@ -1,3 +1,3 @@\n line1\n-removed\n+added\n line3"

    file_diff = parse_patch("foo.py", patch)

    assert file_diff.old_lineno_for(3) == 3


def test_old_lineno_for_returns_none_for_unknown_line():
    patch = "@@ -1,1 +1,1 @@\n line1"

    file_diff = parse_patch("foo.py", patch)

    assert file_diff.old_lineno_for(999) is None


def test_split_unified_diff_by_file_splits_two_files():
    combined = (
        "diff --git a/foo.py b/foo.py\n"
        "index abc123..def456 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,2 @@\n"
        " line1\n"
        "+added in foo\n"
        "diff --git a/bar.py b/bar.py\n"
        "index 111..222 100644\n"
        "--- a/bar.py\n"
        "+++ b/bar.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old in bar\n"
        "+new in bar\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"foo.py", "bar.py"}
    assert result["foo.py"].startswith("@@ -1,1 +1,2 @@")
    assert "+added in foo" in result["foo.py"]
    assert "+new in bar" in result["bar.py"]
    assert "added in foo" not in result["bar.py"]


def test_split_unified_diff_by_file_excludes_header_lines_from_patch():
    combined = (
        "diff --git a/foo.py b/foo.py\n"
        "index abc123..def456 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )

    result = split_unified_diff_by_file(combined)

    assert "diff --git" not in result["foo.py"]
    assert "index abc123" not in result["foo.py"]
    assert "--- a/foo.py" not in result["foo.py"]


def test_split_unified_diff_by_file_returns_empty_dict_for_empty_diff():
    assert split_unified_diff_by_file("") == {}


def test_split_unified_diff_by_file_handles_single_file():
    combined = (
        "diff --git a/only.py b/only.py\n"
        "--- a/only.py\n"
        "+++ b/only.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+b\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"only.py"}


def test_split_unified_diff_by_file_handles_added_file():
    combined = (
        "diff --git a/new.py b/new.py\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+content\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"new.py"}


def test_split_unified_diff_by_file_handles_deleted_file():
    combined = (
        "diff --git a/removed.py b/removed.py\n"
        "--- a/removed.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-content\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"removed.py"}


def test_split_unified_diff_by_file_handles_renamed_file():
    combined = (
        "diff --git a/old_name.py b/new_name.py\n"
        "--- a/old_name.py\n"
        "+++ b/new_name.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"new_name.py"}
    assert "+y" in result["new_name.py"]


def test_split_unified_diff_by_file_handles_path_containing_b_slash():
    # A filename that itself contains the literal substring " b/" — the exact ambiguous case a
    # naive `diff --git a/X b/Y` regex would mis-split. Deriving the path from the unambiguous
    # `+++ b/<path>` line (which has nothing after the path) avoids the ambiguity entirely.
    combined = (
        "diff --git a/evil b/file.py b/evil b/file.py\n"
        "--- a/evil b/file.py\n"
        "+++ b/evil b/file.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )

    result = split_unified_diff_by_file(combined)

    assert set(result.keys()) == {"evil b/file.py"}
