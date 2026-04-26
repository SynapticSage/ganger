"""
GitHub API client with REST and GraphQL support.

Service layer consumed by both TUI and MCP interfaces.

Modified: 2025-11-07
"""

import base64
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from github import Github, GithubException
from ghapi.all import GhApi

from ganger.core.auth import GitHubAuth
from ganger.core.models import StarredRepo, RepoMetadata
from ganger.core.exceptions import (
    GangerError,
    RateLimitExceededError,
    RepoNotFoundError,
    AuthenticationError,
)
from ganger.utils.rate_limiter import RateLimiter


logger = logging.getLogger(__name__)


class GitHubAPIClient:
    """
    GitHub API client providing high-level operations for starred repos.

    Combines PyGithub (REST) for mutations and ghapi (GraphQL) for efficient
    bulk queries. This class is the main service layer used by both TUI and MCP.
    """

    def __init__(self, auth: GitHubAuth, rate_limit_buffer: int = 100):
        """
        Initialize GitHub API client.

        Args:
            auth: Authenticated GitHubAuth instance
            rate_limit_buffer: Reserve this many requests before warning
        """
        self.auth = auth
        self.rest_api: Github = auth.get_github_client()
        self.graphql_api: GhApi = GhApi(token=auth.get_token())
        self.rate_limiter = RateLimiter(buffer=rate_limit_buffer)

        # Cache for current user
        self._user = None

    def get_starred_repos(
        self, max_count: Optional[int] = None, use_graphql: bool = True
    ) -> List[StarredRepo]:
        """
        Get all starred repositories for the authenticated user.

        Args:
            max_count: Maximum number of repos to fetch (None = all)
            use_graphql: Use GraphQL for bulk fetch (faster)

        Returns:
            List of StarredRepo objects

        Raises:
            RateLimitExceededError: If rate limit is exceeded
            AuthenticationError: If not authenticated
        """
        self.rate_limiter.wait_if_needed()

        if use_graphql and max_count is None:
            # Use GraphQL for efficient bulk query
            return self._get_starred_graphql()
        else:
            # Use REST API
            return self._get_starred_rest(max_count)

    def _get_starred_rest(self, max_count: Optional[int] = None) -> List[StarredRepo]:
        """Get starred repos using REST API (PyGithub)."""
        try:
            user = self.rest_api.get_user()
            starred = user.get_starred()

            repos = []
            for i, repo in enumerate(starred):
                if max_count and i >= max_count:
                    break

                # REST does not expose starred_at; leave it unset instead of inventing a value.
                starred_repo = StarredRepo.from_github_response(
                    repo,
                    starred_at=None,
                    include_topics=False,
                )
                repos.append(starred_repo)

            self.rate_limiter.track_request("list_starred")

            return repos

        except GithubException as e:
            if e.status == 401:
                raise AuthenticationError("GitHub authentication failed")
            elif e.status == 403 and "rate limit" in str(e).lower():
                raise RateLimitExceededError(str(e))
            else:
                raise GangerError(f"GitHub API error: {e}")

    def _get_starred_graphql(self) -> List[StarredRepo]:
        """Get starred repos using GraphQL (faster for bulk operations)."""
        repos = []
        cursor = None
        has_next_page = True

        try:
            while has_next_page:
                page = self.get_starred_repos_page(cursor=cursor)
                repos.extend(page["repos"])
                has_next_page = page["has_next_page"]
                cursor = page["end_cursor"]

            return repos

        except (AuthenticationError, GangerError, RateLimitExceededError):
            raise
        except Exception as e:
            # Fallback to REST if GraphQL fails
            logger.warning("GraphQL query failed, falling back to REST API: %s", e)
            return self._get_starred_rest()

    def get_starred_repos_page(
        self,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """Fetch a single GraphQL page of starred repositories."""
        query = """
        query($cursor: String, $pageSize: Int!) {
          viewer {
            starredRepositories(first: $pageSize, after: $cursor) {
              totalCount
              edges {
                starredAt
                node {
                  id
                  nameWithOwner
                  name
                  owner { login }
                  description
                  stargazerCount
                  forkCount
                  watchers { totalCount }
                  primaryLanguage { name }
                  repositoryTopics(first: 10) {
                    nodes { topic { name } }
                  }
                  isArchived
                  isPrivate
                  isFork
                  createdAt
                  updatedAt
                  pushedAt
                  url
                  sshUrl
                  homepageUrl
                  defaultBranchRef { name }
                  licenseInfo { name }
                }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
        }
        """
        variables: Dict[str, Any] = {"pageSize": page_size}
        if cursor:
            variables["cursor"] = cursor

        result = self._execute_graphql_query(query, variables)
        data = self._extract_starred_repositories_payload(result)
        edges = data.get("edges", [])

        repos = [self._build_starred_repo_from_graphql_edge(edge) for edge in edges]
        page_info = data.get("pageInfo", {})

        self.rate_limiter.track_request("bulk_graphql")

        return {
            "repos": repos,
            "total_count": data.get("totalCount"),
            "has_next_page": page_info.get("hasNextPage", False),
            "end_cursor": page_info.get("endCursor"),
        }

    def _execute_graphql_query(self, query: str, variables: Dict[str, Any]) -> Any:
        """Execute a GitHub GraphQL query.

        ghapi doesn't expose a stable `.graphql.query(...)` surface across versions.
        Prefer the explicit `/graphql` endpoint, but keep compatibility with tests
        and any older wrapper that may still provide a `graphql.query` helper.
        """
        graphql_group = getattr(self.graphql_api, "graphql", None)
        if graphql_group is not None and hasattr(graphql_group, "query"):
            return graphql_group.query(query, variables=variables)

        return self.graphql_api(
            "/graphql",
            verb="POST",
            data={"query": query, "variables": variables},
        )

    def _extract_starred_repositories_payload(self, result: Any) -> Dict[str, Any]:
        """Normalize a GraphQL response to the `starredRepositories` payload."""
        if not hasattr(result, "get"):
            raise GangerError("GitHub GraphQL response was not a JSON object")

        errors = result.get("errors", [])
        if errors:
            error_messages = ", ".join(
                error.get("message", "Unknown GraphQL error") for error in errors
            )
            if any(
                error.get("type") == "RATE_LIMITED"
                or "rate limit" in error.get("message", "").lower()
                for error in errors
            ):
                raise RateLimitExceededError(error_messages)
            if any("bad credentials" in error.get("message", "").lower() for error in errors):
                raise AuthenticationError("GitHub authentication failed")
            raise GangerError(f"GitHub GraphQL error: {error_messages}")

        payload = result.get("data", result)
        viewer = payload.get("viewer")
        if viewer is None:
            logger.warning("GitHub GraphQL response missing 'viewer'; treating as empty result")
            return {}

        return viewer.get("starredRepositories", {})

    def _build_starred_repo_from_graphql_edge(self, edge: Dict[str, Any]) -> StarredRepo:
        """Build a `StarredRepo` from a GraphQL edge."""
        node = edge["node"]
        topics = []
        topic_nodes = node.get("repositoryTopics", {}).get("nodes", [])
        for topic_node in topic_nodes:
            topic_name = topic_node.get("topic", {}).get("name")
            if topic_name:
                topics.append(topic_name)

        language = None
        if node.get("primaryLanguage"):
            language = node["primaryLanguage"]["name"]

        license_name = None
        if node.get("licenseInfo"):
            license_name = node["licenseInfo"]["name"]

        default_branch = "main"
        if node.get("defaultBranchRef"):
            default_branch = node["defaultBranchRef"]["name"]

        return StarredRepo(
            id=node["id"],
            full_name=node["nameWithOwner"],
            name=node["name"],
            owner=node["owner"]["login"],
            description=node.get("description") or "",
            stars_count=node.get("stargazerCount", 0),
            forks_count=node.get("forkCount", 0),
            watchers_count=node.get("watchers", {}).get("totalCount", 0),
            language=language,
            topics=topics,
            is_archived=node.get("isArchived", False),
            is_private=node.get("isPrivate", False),
            is_fork=node.get("isFork", False),
            created_at=self._parse_datetime(node.get("createdAt")),
            updated_at=self._parse_datetime(node.get("updatedAt")),
            pushed_at=self._parse_datetime(node.get("pushedAt")),
            starred_at=self._parse_datetime(edge.get("starredAt")),
            url=node.get("url", ""),
            clone_url=node.get("sshUrl", ""),
            homepage=node.get("homepageUrl"),
            default_branch=default_branch,
            license=license_name,
        )

    def get_repo(self, full_name: str) -> StarredRepo:
        """
        Get a specific repository by full name (owner/repo).

        Args:
            full_name: Repository full name (e.g., "octocat/Hello-World")

        Returns:
            StarredRepo object

        Raises:
            RepoNotFoundError: If repository not found
        """
        self.rate_limiter.wait_if_needed()

        try:
            repo = self.rest_api.get_repo(full_name)
            self.rate_limiter.track_request("get_repo")
            return StarredRepo.from_github_response(repo)
        except GithubException as e:
            if e.status == 404:
                raise RepoNotFoundError(f"Repository not found: {full_name}")
            raise GangerError(f"Error fetching repo: {e}")

    def star_repo(self, full_name: str) -> None:
        """
        Star a repository.

        Args:
            full_name: Repository full name (e.g., "octocat/Hello-World")

        Raises:
            RepoNotFoundError: If repository not found
        """
        self.rate_limiter.wait_if_needed()

        try:
            repo = self.rest_api.get_repo(full_name)
            user = self.rest_api.get_user()
            user.add_to_starred(repo)
            self.rate_limiter.track_request("star_repo")
        except GithubException as e:
            if e.status == 404:
                raise RepoNotFoundError(f"Repository not found: {full_name}")
            raise GangerError(f"Error starring repo: {e}")

    def unstar_repo(self, full_name: str) -> None:
        """
        Unstar a repository.

        Args:
            full_name: Repository full name (e.g., "octocat/Hello-World")

        Raises:
            RepoNotFoundError: If repository not found
        """
        self.rate_limiter.wait_if_needed()

        try:
            repo = self.rest_api.get_repo(full_name)
            user = self.rest_api.get_user()
            user.remove_from_starred(repo)
            self.rate_limiter.track_request("unstar_repo")
        except GithubException as e:
            if e.status == 404:
                raise RepoNotFoundError(f"Repository not found: {full_name}")
            raise GangerError(f"Error unstarring repo: {e}")

    def get_readme(self, full_name: str) -> Optional[RepoMetadata]:
        """
        Get README and metadata for a repository.

        Args:
            full_name: Repository full name (e.g., "octocat/Hello-World")

        Returns:
            RepoMetadata object with README content, or None if no README

        Raises:
            RepoNotFoundError: If repository not found
        """
        self.rate_limiter.wait_if_needed()

        try:
            repo = self.rest_api.get_repo(full_name)

            # Get README
            readme_content = None
            readme_format = "markdown"
            try:
                readme = repo.get_readme()
                # Decode base64 content
                content_bytes = base64.b64decode(readme.content)
                readme_content = content_bytes.decode("utf-8")

                # Determine format from file extension
                if readme.name.lower().endswith(".rst"):
                    readme_format = "rst"
                elif readme.name.lower().endswith(".txt"):
                    readme_format = "txt"
            except GithubException:
                # No README found
                pass

            metadata = RepoMetadata(
                repo_id=str(repo.id),
                readme_content=readme_content,
                readme_format=readme_format,
                has_issues=repo.has_issues,
                open_issues_count=repo.open_issues_count,
                has_wiki=repo.has_wiki,
                has_projects=repo.has_projects,
                has_pages=repo.has_pages if hasattr(repo, "has_pages") else False,
                cached_at=datetime.now(),
            )

            self.rate_limiter.track_request("get_readme")
            return metadata

        except GithubException as e:
            if e.status == 404:
                raise RepoNotFoundError(f"Repository not found: {full_name}")
            raise GangerError(f"Error fetching README: {e}")

    def search_repos(self, query: str, max_results: int = 100) -> List[StarredRepo]:
        """
        Search for repositories (not limited to starred repos).

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of StarredRepo objects

        Raises:
            RateLimitExceededError: If rate limit exceeded
        """
        self.rate_limiter.wait_if_needed()

        try:
            results = self.rest_api.search_repositories(query)
            repos = []

            for i, repo in enumerate(results):
                if i >= max_results:
                    break
                starred_repo = StarredRepo.from_github_response(repo, include_topics=False)
                repos.append(starred_repo)

            self.rate_limiter.track_request("search")
            return repos

        except GithubException as e:
            if e.status == 403 and "rate limit" in str(e).lower():
                raise RateLimitExceededError(str(e))
            raise GangerError(f"Search error: {e}")

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """
        Get current rate limit status from GitHub.

        Returns:
            Dictionary with rate limit information
        """
        try:
            rate_limit = self.rest_api.get_rate_limit()
            core = rate_limit.core

            status = {
                "limit": core.limit,
                "remaining": core.remaining,
                "reset": core.reset.isoformat() if core.reset else None,
                "used": core.limit - core.remaining,
            }
            self.rate_limiter.hourly_quota = status["limit"]
            self.rate_limiter.quota_used = status["used"]
            self.rate_limiter.reset_time = core.reset
            self.rate_limiter.last_check = datetime.now()
            return status
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to datetime object."""
        if not dt_str:
            return None
        try:
            from dateutil import parser

            return parser.parse(dt_str)
        except Exception:
            return None
