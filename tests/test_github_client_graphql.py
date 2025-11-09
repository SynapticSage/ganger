"""
GraphQL-specific tests for GitHub API client.

These tests focus on bulk fetching, pagination, and error handling
for GraphQL operations which are critical for TUI performance.

Created: 2025-11-08
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import pytest

from ganger.core.github_client import GitHubAPIClient
from ganger.core.auth import GitHubAuth
from ganger.core.models import StarredRepo
from ganger.core.exceptions import RateLimitExceededError
from tests.utils import MockGraphQLResponse


@pytest.fixture
def mock_auth():
    """Create a mocked GitHubAuth instance."""
    auth = Mock(spec=GitHubAuth)
    auth.get_token.return_value = "ghp_test_token"

    mock_github = Mock()
    auth.get_github_client.return_value = mock_github

    return auth


@pytest.mark.graphql
class TestGraphQLBulkFetch:
    """Test GraphQL bulk repository fetching."""

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_single_page_success(self, mock_ghapi, mock_auth):
        """Test successful GraphQL query with single page of results."""
        # Setup: Mock GraphQL response
        response = MockGraphQLResponse.create_starred_response([
            {
                "id": "R_1",
                "nameWithOwner": "python/cpython",
                "stargazerCount": 50000,
                "primaryLanguage": {"name": "Python"},
                "topics": ["python", "cpython"],
            }
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert len(repos) == 1
        assert repos[0].full_name == "python/cpython"
        assert repos[0].stars_count == 50000
        assert repos[0].language == "Python"
        assert "python" in repos[0].topics
        mock_ghapi_instance.graphql.query.assert_called_once()

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_pagination_multiple_pages(self, mock_ghapi, mock_auth):
        """Test GraphQL pagination across multiple pages."""
        # Setup: Mock paginated responses
        page1_response = MockGraphQLResponse.create_starred_response([
            {"id": f"R_{i}", "nameWithOwner": f"user/repo{i}", "stargazerCount": 1000}
            for i in range(100)
        ], has_next_page=True, end_cursor="cursor_page2")

        page2_response = MockGraphQLResponse.create_starred_response([
            {"id": f"R_{i}", "nameWithOwner": f"user/repo{i}", "stargazerCount": 500}
            for i in range(100, 150)
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.side_effect = [page1_response, page2_response]
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert len(repos) == 150
        assert repos[0].full_name == "user/repo0"
        assert repos[149].full_name == "user/repo149"
        assert mock_ghapi_instance.graphql.query.call_count == 2

        # Verify cursor was passed
        second_call_vars = mock_ghapi_instance.graphql.query.call_args_list[1][1]["variables"]
        assert second_call_vars == {"cursor": "cursor_page2"}

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_empty_response(self, mock_ghapi, mock_auth):
        """Test GraphQL query with no starred repos."""
        # Setup: Empty response
        response = MockGraphQLResponse.create_starred_response([], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert repos == []

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_parses_topics_correctly(self, mock_ghapi, mock_auth):
        """Test that topics are correctly extracted from GraphQL response."""
        # Setup: Repo with multiple topics
        response = MockGraphQLResponse.create_starred_response([
            {
                "id": "R_1",
                "nameWithOwner": "Textualize/textual",
                "topics": ["python", "tui", "terminal", "textual"],
            }
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert len(repos[0].topics) == 4
        assert set(repos[0].topics) == {"python", "tui", "terminal", "textual"}

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_handles_null_language(self, mock_ghapi, mock_auth):
        """Test handling of repos with no primary language."""
        # Setup: Repo without language
        response = MockGraphQLResponse.create_starred_response([
            {
                "id": "R_1",
                "nameWithOwner": "user/markdown-only",
                "primaryLanguage": None,
            }
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert repos[0].language is None

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_handles_archived_repos(self, mock_ghapi, mock_auth):
        """Test that archived status is correctly parsed."""
        # Setup: Mix of archived and active repos
        response = MockGraphQLResponse.create_starred_response([
            {"id": "R_1", "nameWithOwner": "user/active", "isArchived": False},
            {"id": "R_2", "nameWithOwner": "user/archived", "isArchived": True},
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert repos[0].is_archived is False
        assert repos[1].is_archived is True


@pytest.mark.graphql
class TestGraphQLErrorHandling:
    """Test GraphQL error handling and recovery."""

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_falls_back_to_rest_on_error(self, mock_ghapi, mock_auth):
        """Test fallback to REST API when GraphQL fails."""
        # Setup: GraphQL fails, REST succeeds
        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.side_effect = Exception("GraphQL rate limited")
        mock_ghapi.return_value = mock_ghapi_instance

        # Mock REST API
        mock_repo = Mock()
        mock_repo.id = 1
        mock_repo.full_name = "user/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "user"
        mock_repo.description = "Test"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 10
        mock_repo.watchers_count = 50
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["test"]
        mock_repo.archived = False
        mock_repo.private = False
        mock_repo.fork = False
        mock_repo.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        mock_repo.updated_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
        mock_repo.pushed_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
        mock_repo.html_url = "https://github.com/user/repo"
        mock_repo.clone_url = "https://github.com/user/repo.git"
        mock_repo.homepage = None
        mock_repo.default_branch = "main"
        mock_repo.license = None

        mock_user = Mock()
        mock_user.get_starred.return_value = [mock_repo]
        mock_auth.get_github_client.return_value.get_user.return_value = mock_user

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify: Fell back to REST
        assert len(repos) == 1
        assert repos[0].full_name == "user/repo"

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_handles_rate_limit_error(self, mock_ghapi, mock_auth):
        """Test handling of GraphQL rate limit errors."""
        # Setup: GraphQL returns rate limit error
        error_response = MockGraphQLResponse.create_error_response(
            "API rate limit exceeded",
            "RATE_LIMITED"
        )

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = error_response
        mock_ghapi.return_value = mock_ghapi_instance

        client = GitHubAPIClient(mock_auth)

        # For now, this will fall back to REST (no explicit rate limit handling)
        # In future, could check for specific error and raise RateLimitExceededError
        # This test documents current behavior
        repos = client._get_starred_graphql()
        assert isinstance(repos, list)  # Should not crash

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_handles_malformed_response(self, mock_ghapi, mock_auth):
        """Test handling of malformed GraphQL responses."""
        # Setup: Malformed response (missing viewer key)
        malformed_response = {"data": {}}

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = malformed_response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify: Returns empty list (graceful degradation)
        assert repos == []


@pytest.mark.graphql
class TestGraphQLDateParsing:
    """Test datetime parsing from GraphQL responses."""

    @patch("ganger.core.github_client.GhApi")
    def test_parse_iso8601_datetime(self, mock_ghapi, mock_auth):
        """Test parsing of ISO 8601 datetime strings."""
        # Setup: Repo with various date fields
        response = MockGraphQLResponse.create_starred_response([
            {
                "id": "R_1",
                "nameWithOwner": "user/repo",
                "createdAt": "2020-01-15T10:30:00Z",
                "updatedAt": "2025-11-08T12:00:00Z",
                "starredAt": "2025-01-01T00:00:00Z",
            }
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert repos[0].created_at.year == 2020
        assert repos[0].created_at.month == 1
        assert repos[0].created_at.day == 15
        assert repos[0].updated_at.year == 2025
        assert repos[0].starred_at.year == 2025


@pytest.mark.graphql
@pytest.mark.slow
class TestGraphQLStressTest:
    """Stress tests for GraphQL operations with large datasets."""

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_handles_500_repos(self, mock_ghapi, mock_auth):
        """Test fetching 500+ starred repos (5 pages)."""
        # Setup: 5 pages of 100 repos each
        pages = []
        for page_num in range(5):
            is_last_page = (page_num == 4)
            next_cursor = None if is_last_page else f"cursor_page{page_num+2}"

            page_repos = [
                {
                    "id": f"R_{page_num*100 + i}",
                    "nameWithOwner": f"user/repo{page_num*100 + i}",
                    "stargazerCount": 1000 - (page_num*100 + i),
                }
                for i in range(100)
            ]

            page_response = MockGraphQLResponse.create_starred_response(
                page_repos,
                has_next_page=not is_last_page,
                end_cursor=next_cursor
            )
            pages.append(page_response)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.side_effect = pages
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client._get_starred_graphql()

        # Verify
        assert len(repos) == 500
        assert repos[0].full_name == "user/repo0"
        assert repos[499].full_name == "user/repo499"
        assert mock_ghapi_instance.graphql.query.call_count == 5

    @patch("ganger.core.github_client.GhApi")
    def test_graphql_rate_limiter_tracks_bulk_queries(self, mock_ghapi, mock_auth):
        """Test that rate limiter tracks GraphQL bulk queries."""
        # Setup: 2 pages of results
        page1 = MockGraphQLResponse.create_starred_response([
            {"id": f"R_{i}", "nameWithOwner": f"user/repo{i}"}
            for i in range(100)
        ], has_next_page=True, end_cursor="cursor2")

        page2 = MockGraphQLResponse.create_starred_response([
            {"id": f"R_{i}", "nameWithOwner": f"user/repo{i}"}
            for i in range(100, 150)
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.side_effect = [page1, page2]
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        initial_quota = client.rate_limiter.quota_used
        repos = client._get_starred_graphql()

        # Verify: Rate limiter tracked 2 requests
        assert client.rate_limiter.quota_used == initial_quota + 2


@pytest.mark.graphql
class TestGraphQLIntegration:
    """Integration tests for GraphQL with get_starred_repos()."""

    @patch("ganger.core.github_client.GhApi")
    def test_get_starred_repos_uses_graphql_by_default(self, mock_ghapi, mock_auth):
        """Test that get_starred_repos uses GraphQL for bulk fetch."""
        # Setup
        response = MockGraphQLResponse.create_starred_response([
            {"id": "R_1", "nameWithOwner": "user/repo1"},
            {"id": "R_2", "nameWithOwner": "user/repo2"},
        ], has_next_page=False)

        mock_ghapi_instance = Mock()
        mock_ghapi_instance.graphql.query.return_value = response
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client.get_starred_repos(use_graphql=True)

        # Verify: GraphQL was used
        assert len(repos) == 2
        mock_ghapi_instance.graphql.query.assert_called()

    @patch("ganger.core.github_client.GhApi")
    def test_get_starred_repos_can_use_rest_explicitly(self, mock_ghapi, mock_auth):
        """Test that get_starred_repos can use REST API when specified."""
        # Setup REST mock
        mock_repo = Mock()
        mock_repo.id = 1
        mock_repo.full_name = "user/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "user"
        mock_repo.description = "Test"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 10
        mock_repo.watchers_count = 50
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = []
        mock_repo.archived = False
        mock_repo.private = False
        mock_repo.fork = False
        mock_repo.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        mock_repo.updated_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
        mock_repo.pushed_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
        mock_repo.html_url = "https://github.com/user/repo"
        mock_repo.clone_url = "https://github.com/user/repo.git"
        mock_repo.homepage = None
        mock_repo.default_branch = "main"
        mock_repo.license = None

        mock_user = Mock()
        mock_user.get_starred.return_value = [mock_repo]
        mock_auth.get_github_client.return_value.get_user.return_value = mock_user

        mock_ghapi_instance = Mock()
        mock_ghapi.return_value = mock_ghapi_instance

        # Execute
        client = GitHubAPIClient(mock_auth)
        repos = client.get_starred_repos(use_graphql=False)

        # Verify: REST was used, GraphQL was not
        assert len(repos) == 1
        assert repos[0].full_name == "user/repo"
        mock_ghapi_instance.graphql.query.assert_not_called()
