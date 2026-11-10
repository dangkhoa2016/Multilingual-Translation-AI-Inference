"""Publication prerequisites use this revision's ancestry, not unrelated refs."""
import subprocess

import pytest
from documentation_test_support import README_NAMES, require_published_readmes


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE,
    ).strip()


def commit(root, message):
    git(root, "add", "-A")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Synthetic Publication Test")
    git(root, "config", "user.email", "publication@example.test")
    (root / "project.txt").write_text("synthetic source\n")
    commit(root, "source before documentation")
    return root


def publish(root):
    for name in README_NAMES:
        (root / name).write_text("Synthetic public documentation\n")
    return commit(root, "publish bilingual documentation")


def test_revision_before_publication_skips_readme_checks(repository):
    with pytest.raises(pytest.skip.Exception):
        require_published_readmes(repository)


def test_later_publication_on_other_refs_does_not_change_old_revision(repository):
    before = git(repository, "rev-parse", "HEAD")
    publish(repository)
    git(repository, "tag", "published-snapshot")
    git(repository, "checkout", "-q", "--detach", before)
    with pytest.raises(pytest.skip.Exception):
        require_published_readmes(repository)


def test_partial_unpublished_pair_is_an_error(repository):
    (repository / README_NAMES[0]).write_text("one language only")
    with pytest.raises(AssertionError):
        require_published_readmes(repository)


@pytest.mark.parametrize("names", [(README_NAMES[0],), README_NAMES])
@pytest.mark.parametrize("committed", [False, True])
def test_removing_published_readmes_is_an_error(repository, names, committed):
    publish(repository)
    for name in names:
        (repository / name).unlink()
    if committed:
        commit(repository, "remove documentation")
    with pytest.raises(AssertionError):
        require_published_readmes(repository)


def test_publication_in_merged_history_cannot_be_hidden(repository):
    main = git(repository, "symbolic-ref", "--short", "HEAD")
    git(repository, "checkout", "-qb", "publication")
    publish(repository)
    git(repository, "checkout", "-q", main)
    git(repository, "-c", "commit.gpgsign=false", "merge", "-q", "--no-commit", "--no-ff", "publication")
    git(repository, "rm", "-q", "-f", *README_NAMES)
    commit(repository, "merge history without documentation files")
    with pytest.raises(AssertionError):
        require_published_readmes(repository)


def test_export_without_readmes_cannot_claim_unpublished_history(tmp_path):
    with pytest.raises(AssertionError):
        require_published_readmes(tmp_path)


def test_shallow_deletion_cannot_claim_unpublished_history(repository, tmp_path):
    publish(repository)
    for name in README_NAMES:
        (repository / name).unlink()
    commit(repository, "remove published documentation")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repository.as_uri(), str(shallow)], check=True)
    with pytest.raises(AssertionError):
        require_published_readmes(shallow)


def test_both_readmes_are_valid_without_git_metadata(tmp_path):
    for name in README_NAMES:
        (tmp_path / name).write_text("Exported documentation\n")
    assert require_published_readmes(tmp_path) == tuple(tmp_path / name for name in README_NAMES)


def test_unborn_git_history_is_not_proof_of_no_publication(tmp_path):
    git(tmp_path, "init", "-q")
    with pytest.raises(AssertionError):
        require_published_readmes(tmp_path)
