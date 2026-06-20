from ai_pr_reviewer.diff_parser import LineType, parse_patch


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
