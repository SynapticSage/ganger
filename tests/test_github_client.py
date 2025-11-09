"""
Tests for GitHub API client.

Modified: 2025-11-07
"""

from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pytest

from ganger.core.github_client import GitHubAPIClient
from ganger.core.auth import GitHubAuth
from ganger.core.models import StarredRepo, RepoMetadata
from ganger.core.exceptions import RepoNotFoundError, AuthenticationError, RateLimitExceededError


@pytest.fixture
def mock_auth():
    """Create a mocked GitHubAuth instance."""
    auth = Mock(spec=GitHubAuth)
    auth.get_token.return_value = "ghp_test_token"

    mock_github = Mock()
    auth.get_github_client.return_value = mock_github

    return auth


@pytest.fixture
def mock_repo():
    """Create a mocked PyGithub Repository object."""
    repo = Mock()
    repo.id = 12345
    repo.full_name = "octocat/Hello-World"
    repo.name = "Hello-World"
    repo.owner.login = "octocat"
    repo.description = "Test repository"
    repo.stargazers_count = 1000
    repo.forks_count = 500
    repo.watchers_count = 750
    repo.language = "Python"
    repo.get_topics.return_value = ["python", "test"]
    repo.archived = False
    repo.private = False
    repo.fork = False
    repo.created_at = datetime(2020, 1, 1)
    repo.updated_at = datetime(2023, 1, 1)
    repo.pushed_at = datetime(2023, 1, 1)
    repo.html_url = "https://github.com/octocat/Hello-World"
    repo.clone_url = "https://github.com/octocat/Hello-World.git"
    repo.homepage = "https://example.com"
    repo.default_branch = "main"
    repo.license = None
    repo.has_issues = True
    repo.open_issues_count = 5
    repo.has_wiki = True
    repo.has_projects = True
    repo.has_pages = False

    return repo


class TestGitHubAPIClient:
    """Test GitHubAPIClient."""

    def test_init(self, mock_auth):
        """Test client initialization."""
        client = GitHubAPIClient(mock_auth)

        assert client.auth == mock_auth
        assert client.rest_api is not None
        assert client.rate_limiter is not None

    @patch("ganger.core.github_client.GhApi")
    def test_get_starred_repos_rest(self, mock_ghapi, mock_auth, mock_repo):
        """Test getting starred repos via REST API."""
        # Setup mock
        mock_user = Mock()
        mock_user.get_starred.return_value = [mock_repo]
        mock_auth.get_github_client.return_value.get_user.return_value = mock_user

        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_rest(max_count=10)

        assert len(repos) == 1
        assert repos[0].full_name == "octocat/Hello-World"
        assert repos[0].language == "Python"
        assert repos[0].stars_count == 1000

    @patch("ganger.core.github_client.GhApi")
    def test_get_repo(self, mock_ghapi, mock_auth, mock_repo):
        """Test getting a specific repository."""
        mock_auth.get_github_client.return_value.get_repo.return_value = mock_repo

        client = GitHubAPIClient(mock_auth)
        repo = client.get_repo("octocat/Hello-World")

        assert repo.full_name == "octocat/Hello-World"
        assert repo.name == "Hello-World"
        assert repo.owner == "octocat"

    @patch("ganger.core.github_client.GhApi")
    def test_get_repo_not_found(self, mock_ghapi, mock_auth):
        """Test getting a non-existent repository."""
        from github import GithubException

        mock_auth.get_github_client.return_value.get_repo.side_effect = GithubException(
            404, {"message": "Not Found"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RepoNotFoundError):
            client.get_repo("nonexistent/repo")

    @patch("ganger.core.github_client.GhApi")
    def test_star_repo(self, mock_ghapi, mock_auth, mock_repo):
        """Test starring a repository."""
        mock_github = mock_auth.get_github_client.return_value
        mock_github.get_repo.return_value = mock_repo

        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        client = GitHubAPIClient(mock_auth)
        client.star_repo("octocat/Hello-World")

        mock_user.add_to_starred.assert_called_once_with(mock_repo)

    @patch("ganger.core.github_client.GhApi")
    def test_unstar_repo(self, mock_ghapi, mock_auth, mock_repo):
        """Test unstarring a repository."""
        mock_github = mock_auth.get_github_client.return_value
        mock_github.get_repo.return_value = mock_repo

        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        client = GitHubAPIClient(mock_auth)
        client.unstar_repo("octocat/Hello-World")

        mock_user.remove_from_starred.assert_called_once_with(mock_repo)

    @patch("ganger.core.github_client.GhApi")
    def test_get_readme(self, mock_ghapi, mock_auth, mock_repo):
        """Test getting repository README."""
        import base64

        # Mock README
        readme_content = "# Hello World\nTest README"
        encoded_content = base64.b64encode(readme_content.encode()).decode()

        mock_readme = Mock()
        mock_readme.content = encoded_content
        mock_readme.name = "README.md"

        mock_repo.get_readme.return_value = mock_readme

        mock_auth.get_github_client.return_value.get_repo.return_value = mock_repo

        client = GitHubAPIClient(mock_auth)
        metadata = client.get_readme("octocat/Hello-World")

        assert metadata is not None
        assert metadata.readme_content == readme_content
        assert metadata.readme_format == "markdown"
        assert metadata.has_issues == True
        assert metadata.open_issues_count == 5

    @patch("ganger.core.github_client.GhApi")
    def test_get_readme_no_readme(self, mock_ghapi, mock_auth, mock_repo):
        """Test getting README when none exists."""
        from github import GithubException

        mock_repo.get_readme.side_effect = GithubException(404, {"message": "Not Found"})

        mock_auth.get_github_client.return_value.get_repo.return_value = mock_repo

        client = GitHubAPIClient(mock_auth)
        metadata = client.get_readme("octocat/Hello-World")

        assert metadata is not None
        assert metadata.readme_content is None

    @patch("ganger.core.github_client.GhApi")
    def test_search_repos(self, mock_ghapi, mock_auth, mock_repo):
        """Test searching repositories."""
        mock_results = [mock_repo]
        mock_auth.get_github_client.return_value.search_repositories.return_value = (
            mock_results
        )

        client = GitHubAPIClient(mock_auth)
        repos = client.search_repos("python")

        assert len(repos) == 1
        assert repos[0].full_name == "octocat/Hello-World"

    @patch("ganger.core.github_client.GhApi")
    def test_get_rate_limit_status(self, mock_ghapi, mock_auth):
        """Test getting rate limit status."""
        mock_rate_limit = Mock()
        mock_core = Mock()
        mock_core.limit = 5000
        mock_core.remaining = 4500
        mock_core.reset = datetime(2023, 1, 1, 12, 0, 0)
        mock_rate_limit.core = mock_core

        mock_auth.get_github_client.return_value.get_rate_limit.return_value = (
            mock_rate_limit
        )

        client = GitHubAPIClient(mock_auth)
        status = client.get_rate_limit_status()

        assert status["limit"] == 5000
        assert status["remaining"] == 4500
        assert status["used"] == 500


class TestRateLimiting:
    """Test rate limiting functionality."""

    @patch("ganger.core.github_client.GhApi")
    def test_rate_limiter_tracks_requests(self, mock_ghapi, mock_auth, mock_repo):
        """Test that rate limiter tracks requests."""
        mock_user = Mock()
        mock_user.get_starred.return_value = [mock_repo] * 10
        mock_auth.get_github_client.return_value.get_user.return_value = mock_user

        client = GitHubAPIClient(mock_auth, rate_limit_buffer=100)
        repos = client._get_starred_rest(max_count=10)

        assert client.rate_limiter.quota_used == 10

    @patch("ganger.core.github_client.GhApi")
    def test_rate_limiter_warns_on_low_quota(self, mock_ghapi, mock_auth):
        """Test that rate limiter warns when quota is low."""
        client = GitHubAPIClient(mock_auth, rate_limit_buffer=100)
        client.rate_limiter.quota_used = 4950  # Near limit

        assert client.rate_limiter.should_warn()


class TestErrorHandling:
    """Test error handling in GitHub API client."""

    @patch("ganger.core.github_client.GhApi")
    def test_list_starred_with_max_count(self, mock_ghapi, mock_auth, mock_repo):
        """Test listing starred repos with max_count limit (line 87)."""
        # Create 5 repos but limit to 2
        mock_user = Mock()
        mock_user.get_starred.return_value = [mock_repo for _ in range(5)]
        mock_auth.get_github_client.return_value.get_user.return_value = mock_user

        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_rest(max_count=2)

        assert len(repos) == 2

    @patch("ganger.core.github_client.GhApi")
    def test_list_starred_auth_error(self, mock_ghapi, mock_auth):
        """Test 401 auth error raises AuthenticationError (lines 104-110)."""
        from github import GithubException

        mock_auth.get_github_client.return_value.get_user.side_effect = GithubException(
            401, {"message": "Bad credentials"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(AuthenticationError, match="authentication failed"):
            client._get_starred_rest()

    @patch("ganger.core.github_client.GhApi")
    def test_list_starred_rate_limit_error(self, mock_ghapi, mock_auth):
        """Test 403 rate limit error raises RateLimitExceededError (lines 104-110)."""
        from github import GithubException

        error_data = {"message": "API rate limit exceeded"}
        mock_auth.get_github_client.return_value.get_user.side_effect = GithubException(
            403, error_data
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RateLimitExceededError, match="API rate limit exceeded"):
            client._get_starred_rest()

    @patch("ganger.core.github_client.GhApi")
    def test_list_starred_generic_error(self, mock_ghapi, mock_auth):
        """Test generic GitHub error raises GangerError (line 110)."""
        from github import GithubException
        from ganger.core.exceptions import GangerError

        mock_auth.get_github_client.return_value.get_user.side_effect = GithubException(
            500, {"message": "Internal Server Error"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(GangerError, match="GitHub API error"):
            client._get_starred_rest()

    @patch("ganger.core.github_client.GhApi")
    def test_star_repo_not_found(self, mock_ghapi, mock_auth):
        """Test starring nonexistent repo raises RepoNotFoundError (lines 281-284)."""
        from github import GithubException

        mock_auth.get_github_client.return_value.get_repo.side_effect = GithubException(
            404, {"message": "Not Found"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RepoNotFoundError, match="Repository.*not found"):
            client.star_repo("invalid/repo")

    @patch("ganger.core.github_client.GhApi")
    def test_unstar_repo_not_found(self, mock_ghapi, mock_auth):
        """Test unstarring nonexistent repo raises RepoNotFoundError (lines 303-306)."""
        from github import GithubException

        mock_auth.get_github_client.return_value.get_repo.side_effect = GithubException(
            404, {"message": "Not Found"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RepoNotFoundError, match="Repository.*not found"):
            client.unstar_repo("invalid/repo")

    @patch("ganger.core.github_client.GhApi")
    def test_get_readme_repo_not_found(self, mock_ghapi, mock_auth):
        """Test getting README for nonexistent repo (lines 359-362)."""
        from github import GithubException

        mock_auth.get_github_client.return_value.get_repo.side_effect = GithubException(
            404, {"message": "Not Found"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RepoNotFoundError, match="Repository.*not found"):
            client.get_readme("invalid/repo")

    @patch("ganger.core.github_client.GhApi")
    def test_search_repos_rate_limit(self, mock_ghapi, mock_auth):
        """Test search with rate limit error (lines 393-396)."""
        from github import GithubException

        error_data = {"message": "API rate limit exceeded for search"}
        mock_auth.get_github_client.return_value.search_repositories.side_effect = GithubException(
            403, error_data
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(RateLimitExceededError, match="rate limit"):
            client.search_repos("python")

    @patch("ganger.core.github_client.GhApi")
    def test_search_repos_generic_error(self, mock_ghapi, mock_auth):
        """Test search with generic error (line 396)."""
        from github import GithubException
        from ganger.core.exceptions import GangerError

        mock_auth.get_github_client.return_value.search_repositories.side_effect = GithubException(
            401, {"message": "Unauthorized"}
        )

        client = GitHubAPIClient(mock_auth)

        with pytest.raises(GangerError, match="Search error"):
            client.search_repos("python")
