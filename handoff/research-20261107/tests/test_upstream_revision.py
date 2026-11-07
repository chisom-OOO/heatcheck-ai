"""upstream_revision(): COMMIT file first; never a parent repository's HEAD (reviewer RV-R3 follow-up)."""
import subprocess

import pytest

from heatcheck.util import UpstreamRevisionError, upstream_revision

UP = "46488f0f8e1cab58fc1256511ea808166a443a15"


def _git(*args, cwd):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True,
                                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}).strip()


@pytest.fixture
def parent(tmp_path):
    _git("init", "-q", cwd=tmp_path); (tmp_path / "f").write_text("x")
    _git("add", "f", cwd=tmp_path); _git("commit", "-qm", "parent", cwd=tmp_path)
    nested = tmp_path / "raw" / "repo"; nested.mkdir(parents=True)
    return tmp_path, nested


def test_nested_copy_with_commit_file_uses_commit_file(parent):
    top, nested = parent
    (nested / "COMMIT").write_text(UP + "\n")
    assert upstream_revision(nested) == UP
    assert _git("-C", str(nested), "rev-parse", "HEAD", cwd=top) != UP   # what the old code recorded


def test_nested_copy_without_commit_file_is_refused(parent):
    _, nested = parent
    with pytest.raises(UpstreamRevisionError, match="PARENT"):
        upstream_revision(nested)


def test_real_checkout_top_level_uses_git(parent):
    top, _ = parent
    assert upstream_revision(top) == _git("rev-parse", "HEAD", cwd=top)


def test_bad_commit_file_and_plain_directory_refused(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "a" / "COMMIT").write_text("not-a-sha")
    with pytest.raises(UpstreamRevisionError):
        upstream_revision(tmp_path / "a")
    (tmp_path / "b").mkdir()
    with pytest.raises(UpstreamRevisionError):
        upstream_revision(tmp_path / "b")
