from ai_pr_reviewer.vcs_provider import ChangedFile, NormalizedComment, VCSProvider


def test_changed_file_holds_filename_and_patch():
    file = ChangedFile(filename="a.py", patch="@@ -1 +1 @@\n+x")

    assert file.filename == "a.py"
    assert file.patch == "@@ -1 +1 @@\n+x"


def test_changed_file_allows_none_patch_for_binary_files():
    file = ChangedFile(filename="image.png", patch=None)

    assert file.patch is None


def test_normalized_comment_holds_path_line_body():
    comment = NormalizedComment(path="a.py", line=5, body="fix this")

    assert comment.path == "a.py"
    assert comment.line == 5
    assert comment.body == "fix this"
    assert comment.old_line is None


def test_normalized_comment_accepts_old_line_for_context_comments():
    comment = NormalizedComment(path="a.py", line=5, body="fix this", old_line=3)

    assert comment.old_line == 3


def test_provider_protocol_is_runtime_checkable():
    class _FakeProvider:
        def fetch_pr_files(self):
            return []

        def post_review(self, summary, comments):
            return {}

    assert isinstance(_FakeProvider(), VCSProvider)


def test_incomplete_class_does_not_satisfy_provider_protocol():
    class _Incomplete:
        def fetch_pr_files(self):
            return []

    assert not isinstance(_Incomplete(), VCSProvider)
