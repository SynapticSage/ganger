"""
GitHub API client with REST and GraphQL support.

Service layer consumed by both TUI and MCP interfaces.

Modified: 2025-11-07
"""

import base64
from typing import List, Optional, Dict, Any
from datetime import datetime

from github import Github, GithubException
from github.Repository import Repository
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

                # Get starred_at timestamp if available
                starred_at = None
                try:
                    # PyGithub doesn't directly expose starred_at, but we can approximate
                    starred_at = datetime.now()  # Fallback to now
                except Exception:
                    pass

                starred_repo = StarredRepo.from_github_response(repo, starred_at=starred_at)
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
        query = """
        query($cursor: String) {
          viewer {
            starredRepositories(first: 100, after: $cursor) {
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

        repos = []
        cursor = None
        has_next_page = True

        try:
            while has_next_page:
                variables = {"cursor": cursor} if cursor else {}
                result = self.graphql_api.graphql.query(query, variables=variables)

                data = result.get("viewer", {}).get("starredRepositories", {})
                edges = data.get("edges", [])

                for edge in edges:
                    node = edge["node"]
                    starred_at_str = edge.get("starredAt")

                    # Extract topics
                    topics = []
                    topic_nodes = node.get("repositoryTopics", {}).get("nodes", [])
                    for topic_node in topic_nodes:
                        topic_name = topic_node.get("topic", {}).get("name")
                        if topic_name:
                            topics.append(topic_name)

                    # Parse dates
                    created_at = self._parse_datetime(node.get("createdAt"))
                    updated_at = self._parse_datetime(node.get("updatedAt"))
                    pushed_at = self._parse_datetime(node.get("pushedAt"))
                    starred_at = self._parse_datetime(starred_at_str)

                    # Extract language
                    language = None
                    if node.get("primaryLanguage"):
                        language = node["primaryLanguage"]["name"]

                    # Extract license
                    license_name = None
                    if node.get("licenseInfo"):
                        license_name = node["licenseInfo"]["name"]

                    # Extract default branch
                    default_branch = "main"
                    if node.get("defaultBranchRef"):
                        default_branch = node["defaultBranchRef"]["name"]

                    repo = StarredRepo(
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
                        created_at=created_at,
                        updated_at=updated_at,
                        pushed_at=pushed_at,
                        starred_at=starred_at,
                        url=node.get("url", ""),
                        clone_url=node.get("sshUrl", ""),
                        homepage=node.get("homepageUrl"),
                        default_branch=default_branch,
                        license=license_name,
                    )
                    repos.append(repo)

                # Pagination
                page_info = data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                self.rate_limiter.track_request("bulk_graphql")

            return repos

        except Exception as e:
            # Fallback to REST if GraphQL fails
            print(f"⚠ GraphQL query failed ({e}), falling back to REST API")
            return self._get_starred_rest()

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
                starred_repo = StarredRepo.from_github_response(repo)
                repos.append(starred_repo)

            self.rate_limiter.track_request("search", count=len(repos))
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

            return {
                "limit": core.limit,
                "remaining": core.remaining,
                "reset": core.reset.isoformat() if core.reset else None,
                "used": core.limit - core.remaining,
            }
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
