"""
Unit tests for core.git_manager module.
Tests Git operations including cloning, pulling, and repository management.
"""

from unittest.mock import Mock, patch

import git
import pytest
from git.exc import GitCommandError

from core.git_manager import GitManager


@pytest.fixture
def git_manager():
    """Fixture to create a GitManager instance."""
    return GitManager(base_path="/tmp/test_repos")


@pytest.fixture
def mock_repo():
    """Fixture to create a mock Git repository."""
    repo = Mock(spec=git.Repo)
    repo.git = Mock()
    repo.remotes = Mock()
    repo.head = Mock()
    repo.head.commit = Mock()
    repo.head.commit.hexsha = "abc123"
    return repo


class TestGitManagerInit:
    """Test GitManager initialization."""

    def test_init_creates_base_path(self, tmp_path):
        """Test that initialization creates base path if it doesn't exist."""
        test_path = tmp_path / "new_repos"
        manager = GitManager(base_path=str(test_path))
        assert test_path.exists()
        assert manager.base_path == str(test_path)

    def test_init_with_existing_path(self, tmp_path):
        """Test initialization with existing path."""
        manager = GitManager(base_path=str(tmp_path))
        assert manager.base_path == str(tmp_path)


class TestCloneRepository:
    """Test repository cloning functionality."""

    @patch('core.git_manager.git.Repo.clone_from')
    def test_clone_new_repository_success(self, mock_clone, git_manager, mock_repo):
        """Test successful cloning of a new repository."""
        mock_clone.return_value = mock_repo

        result = git_manager.clone_repository(
            repo_url="https://github.com/test/repo.git", app_name="test-app"
        )

        expected_path = f"{git_manager.base_path}/test-app"
        mock_clone.assert_called_once_with(
            "https://github.com/test/repo.git", expected_path
        )
        assert result == expected_path

    @patch('core.git_manager.Path.exists')
    @patch('core.git_manager.git.Repo')
    def test_clone_existing_repository_pulls(
        self, mock_repo_class, mock_exists, git_manager, mock_repo
    ):
        """Test that existing repository is pulled instead of cloned."""
        mock_exists.return_value = True
        mock_repo_class.return_value = mock_repo
        mock_origin = Mock()
        mock_repo.remotes.origin = mock_origin

        result = git_manager.clone_repository(
            repo_url="https://github.com/test/repo.git", app_name="test-app"
        )

        mock_origin.pull.assert_called_once()
        assert result == f"{git_manager.base_path}/test-app"

    @patch('core.git_manager.git.Repo.clone_from')
    def test_clone_repository_git_error(self, mock_clone, git_manager):
        """Test handling of Git errors during cloning."""
        mock_clone.side_effect = GitCommandError("clone", "error message")

        with pytest.raises(GitCommandError):
            git_manager.clone_repository(
                repo_url="https://github.com/test/repo.git", app_name="test-app"
            )

    @patch('core.git_manager.git.Repo.clone_from')
    def test_clone_with_special_characters_in_name(
        self, mock_clone, git_manager, mock_repo
    ):
        """Test cloning with special characters in app name."""
        mock_clone.return_value = mock_repo

        result = git_manager.clone_repository(
            repo_url="https://github.com/test/repo.git", app_name="test_app-123"
        )

        assert "test_app-123" in result


class TestPullRepository:
    """Test repository pull functionality."""

    @patch('core.git_manager.git.Repo')
    def test_pull_repository_success(self, mock_repo_class, git_manager, mock_repo):
        """Test successful repository pull."""
        mock_repo_class.return_value = mock_repo
        mock_origin = Mock()
        mock_repo.remotes.origin = mock_origin

        git_manager.pull_repository("test-app")

        mock_origin.pull.assert_called_once()

    @patch('core.git_manager.git.Repo')
    def test_pull_repository_not_found(self, mock_repo_class, git_manager):
        """Test pull when repository doesn't exist."""
        mock_repo_class.side_effect = git.exc.NoSuchPathError("path not found")

        with pytest.raises(git.exc.NoSuchPathError):
            git_manager.pull_repository("nonexistent-app")

    @patch('core.git_manager.git.Repo')
    def test_pull_repository_git_error(self, mock_repo_class, git_manager, mock_repo):
        """Test handling of Git errors during pull."""
        mock_repo_class.return_value = mock_repo
        mock_origin = Mock()
        mock_origin.pull.side_effect = GitCommandError("pull", "network error")
        mock_repo.remotes.origin = mock_origin

        with pytest.raises(GitCommandError):
            git_manager.pull_repository("test-app")


class TestGetCommitHash:
    """Test commit hash retrieval."""

    @patch('core.git_manager.git.Repo')
    def test_get_commit_hash_success(self, mock_repo_class, git_manager, mock_repo):
        """Test successful retrieval of commit hash."""
        mock_repo_class.return_value = mock_repo
        mock_repo.head.commit.hexsha = "abc123def456"

        commit_hash = git_manager.get_commit_hash("test-app")

        assert commit_hash == "abc123def456"

    @patch('core.git_manager.git.Repo')
    def test_get_commit_hash_short(self, mock_repo_class, git_manager, mock_repo):
        """Test retrieval of short commit hash."""
        mock_repo_class.return_value = mock_repo
        mock_repo.head.commit.hexsha = "abc123def456"

        commit_hash = git_manager.get_commit_hash("test-app", short=True)

        assert commit_hash == "abc123d"
        assert len(commit_hash) == 7

    @patch('core.git_manager.git.Repo')
    def test_get_commit_hash_repository_not_found(self, mock_repo_class, git_manager):
        """Test get_commit_hash when repository doesn't exist."""
        mock_repo_class.side_effect = git.exc.NoSuchPathError("path not found")

        with pytest.raises(git.exc.NoSuchPathError):
            git_manager.get_commit_hash("nonexistent-app")


class TestGetRepositoryPath:
    """Test repository path construction."""

    def test_get_repository_path(self, git_manager):
        """Test correct repository path construction."""
        path = git_manager.get_repository_path("test-app")
        assert path == f"{git_manager.base_path}/test-app"

    def test_get_repository_path_with_base_path_trailing_slash(self):
        """Test path construction with trailing slash in base path."""
        manager = GitManager(base_path="/tmp/repos/")
        path = manager.get_repository_path("test-app")
        assert path == "/tmp/repos/test-app"


class TestRepositoryExists:
    """Test repository existence checks."""

    @patch('core.git_manager.Path.exists')
    @patch('core.git_manager.Path.is_dir')
    def test_repository_exists_true(self, mock_is_dir, mock_exists, git_manager):
        """Test repository exists check returns True."""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        exists = git_manager.repository_exists("test-app")

        assert exists is True

    @patch('core.git_manager.Path.exists')
    def test_repository_exists_false(self, mock_exists, git_manager):
        """Test repository exists check returns False."""
        mock_exists.return_value = False

        exists = git_manager.repository_exists("nonexistent-app")

        assert exists is False


class TestDeleteRepository:
    """Test repository deletion."""

    @patch('core.git_manager.shutil.rmtree')
    @patch('core.git_manager.Path.exists')
    def test_delete_repository_success(self, mock_exists, mock_rmtree, git_manager):
        """Test successful repository deletion."""
        mock_exists.return_value = True

        git_manager.delete_repository("test-app")

        expected_path = f"{git_manager.base_path}/test-app"
        mock_rmtree.assert_called_once_with(expected_path)

    @patch('core.git_manager.Path.exists')
    def test_delete_repository_not_found(self, mock_exists, git_manager):
        """Test deletion of non-existent repository."""
        mock_exists.return_value = False

        # Should not raise an error
        git_manager.delete_repository("nonexistent-app")

    @patch('core.git_manager.shutil.rmtree')
    @patch('core.git_manager.Path.exists')
    def test_delete_repository_permission_error(
        self, mock_exists, mock_rmtree, git_manager
    ):
        """Test handling of permission errors during deletion."""
        mock_exists.return_value = True
        mock_rmtree.side_effect = PermissionError("Permission denied")

        with pytest.raises(PermissionError):
            git_manager.delete_repository("test-app")


class TestListRepositories:
    """Test repository listing."""

    @patch('core.git_manager.Path.iterdir')
    def test_list_repositories(self, mock_iterdir, git_manager):
        """Test listing all repositories."""
        mock_dirs = [
            Mock(is_dir=lambda: True, name="app1"),
            Mock(is_dir=lambda: True, name="app2"),
            Mock(is_dir=lambda: False, name="file.txt"),
        ]
        mock_iterdir.return_value = mock_dirs

        repos = git_manager.list_repositories()

        assert len(repos) == 2
        assert "app1" in repos
        assert "app2" in repos
        assert "file.txt" not in repos

    @patch('core.git_manager.Path.iterdir')
    def test_list_repositories_empty(self, mock_iterdir, git_manager):
        """Test listing repositories when directory is empty."""
        mock_iterdir.return_value = []

        repos = git_manager.list_repositories()

        assert repos == []


class TestIntegration:
    """Integration tests combining multiple operations."""

    @patch('core.git_manager.git.Repo.clone_from')
    @patch('core.git_manager.git.Repo')
    def test_clone_and_get_commit_hash(
        self, mock_repo_class, mock_clone, git_manager, mock_repo
    ):
        """Test cloning a repository and getting commit hash."""
        mock_clone.return_value = mock_repo
        mock_repo_class.return_value = mock_repo
        mock_repo.head.commit.hexsha = "integration123"

        # Clone
        path = git_manager.clone_repository(
            "https://github.com/test/repo.git", "integration-app"
        )

        # Get commit hash
        commit = git_manager.get_commit_hash("integration-app")

        assert "integration-app" in path
        assert commit == "integration123"
