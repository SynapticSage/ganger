"""Test utilities and helper functions.

Created: 2025-11-08
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from ganger.core.models import StarredRepo, VirtualFolder


def create_test_repo(
    id: str,
    full_name: str,
    **overrides
) -> StarredRepo:
    """Factory for creating test repos with sensible defaults.

    Args:
        id: Repository ID
        full_name: Full name (owner/repo)
        **overrides: Override any default fields

    Returns:
        StarredRepo instance

    Example:
        repo = create_test_repo("1", "user/repo", stars_count=1000)
    """
    owner, name = full_name.split("/")

    defaults = {
        "id": id,
        "full_name": full_name,
        "name": name,
        "owner": owner,
        "description": f"Test repository {name}",
        "stars_count": 100,
        "forks_count": 10,
        "language": "Python",
        "topics": ["test"],
        "is_archived": False,
        "is_private": False,
        "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 11, 1, tzinfo=timezone.utc),
        "starred_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "url": f"https://github.com/{full_name}",
        "clone_url": f"https://github.com/{full_name}.git"
    }

    # Merge overrides
    defaults.update(overrides)

    return StarredRepo(**defaults)


def create_test_folder(
    id: str,
    name: str,
    **overrides
) -> VirtualFolder:
    """Factory for creating test folders with sensible defaults.

    Args:
        id: Folder ID
        name: Folder name
        **overrides: Override any default fields

    Returns:
        VirtualFolder instance

    Example:
        folder = create_test_folder("python", "Python Projects", auto_tags=["python"])
    """
    defaults = {
        "id": id,
        "name": name,
        "auto_tags": [],
        "repo_count": 0
    }

    # Merge overrides
    defaults.update(overrides)

    return VirtualFolder(**defaults)


def assert_repo_equals(
    repo1: StarredRepo,
    repo2: StarredRepo,
    ignore_fields: Optional[List[str]] = None
) -> None:
    """Compare two repos for equality, optionally ignoring certain fields.

    Args:
        repo1: First repo
        repo2: Second repo
        ignore_fields: List of field names to ignore in comparison

    Raises:
        AssertionError: If repos are not equal

    Example:
        assert_repo_equals(repo1, repo2, ignore_fields=["updated_at", "cached_at"])
    """
    ignore_fields = ignore_fields or []

    dict1 = repo1.to_dict()
    dict2 = repo2.to_dict()

    # Remove ignored fields
    for field in ignore_fields:
        dict1.pop(field, None)
        dict2.pop(field, None)

    assert dict1 == dict2, f"Repos differ: {dict1} != {dict2}"


def assert_folder_equals(
    folder1: VirtualFolder,
    folder2: VirtualFolder,
    ignore_fields: Optional[List[str]] = None
) -> None:
    """Compare two folders for equality, optionally ignoring certain fields.

    Args:
        folder1: First folder
        folder2: Second folder
        ignore_fields: List of field names to ignore in comparison

    Raises:
        AssertionError: If folders are not equal
    """
    ignore_fields = ignore_fields or []

    dict1 = folder1.__dict__.copy()
    dict2 = folder2.__dict__.copy()

    # Remove ignored fields
    for field in ignore_fields:
        dict1.pop(field, None)
        dict2.pop(field, None)

    assert dict1 == dict2, f"Folders differ: {dict1} != {dict2}"


class MockGraphQLResponse:
    """Mock GraphQL response structure for starred repos query."""

    @staticmethod
    def create_starred_response(
        repos: List[Dict[str, Any]],
        has_next_page: bool = False,
        end_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a mock GraphQL response for starred repositories query.

        Args:
            repos: List of repo data dicts with minimal fields
            has_next_page: Whether there are more pages
            end_cursor: Cursor for next page

        Returns:
            GraphQL response structure

        Example:
            response = MockGraphQLResponse.create_starred_response([
                {
                    "id": "R_1",
                    "nameWithOwner": "python/cpython",
                    "stargazerCount": 50000,
                    "primaryLanguage": {"name": "Python"}
                }
            ])
        """
        edges = []
        for repo_data in repos:
            # Extract owner and name from nameWithOwner
            name_with_owner = repo_data["nameWithOwner"]
            if "/" in name_with_owner:
                owner_login, repo_name = name_with_owner.split("/", 1)
            else:
                owner_login = "unknown"
                repo_name = name_with_owner

            edge = {
                "starredAt": repo_data.get("starredAt", "2025-01-01T00:00:00Z"),
                "node": {
                    "id": repo_data.get("id", "R_unknown"),
                    "nameWithOwner": name_with_owner,
                    "name": repo_data.get("name", repo_name),
                    "owner": {"login": repo_data.get("owner", owner_login)},
                    "description": repo_data.get("description", ""),
                    "stargazerCount": repo_data.get("stargazerCount", 0),
                    "forkCount": repo_data.get("forkCount", 0),
                    "watchers": {"totalCount": repo_data.get("watchersCount", 0)},
                    "primaryLanguage": repo_data.get("primaryLanguage"),
                    "repositoryTopics": {
                        "nodes": [
                            {"topic": {"name": topic}}
                            for topic in repo_data.get("topics", [])
                        ]
                    },
                    "isArchived": repo_data.get("isArchived", False),
                    "isPrivate": repo_data.get("isPrivate", False),
                    "isFork": repo_data.get("isFork", False),
                    "createdAt": repo_data.get("createdAt", "2020-01-01T00:00:00Z"),
                    "updatedAt": repo_data.get("updatedAt", "2025-11-01T00:00:00Z"),
                    "pushedAt": repo_data.get("pushedAt", "2025-11-01T00:00:00Z"),
                    "url": repo_data.get("url", f"https://github.com/{name_with_owner}"),
                    "sshUrl": repo_data.get("sshUrl", f"git@github.com:{name_with_owner}.git"),
                    "homepageUrl": repo_data.get("homepageUrl"),
                    "defaultBranchRef": repo_data.get("defaultBranchRef", {"name": "main"}),
                    "licenseInfo": repo_data.get("licenseInfo")
                }
            }
            edges.append(edge)

        return {
            "viewer": {
                "starredRepositories": {
                    "edges": edges,
                    "pageInfo": {
                        "hasNextPage": has_next_page,
                        "endCursor": end_cursor
                    }
                }
            }
        }

    @staticmethod
    def create_error_response(error_message: str, error_type: str = "INTERNAL") -> Dict[str, Any]:
        """Create a mock GraphQL error response.

        Args:
            error_message: Error message
            error_type: Error type (INTERNAL, RATE_LIMITED, etc.)

        Returns:
            GraphQL error response structure
        """
        return {
            "errors": [
                {
                    "type": error_type,
                    "message": error_message
                }
            ]
        }


def create_batch_repos(count: int, prefix: str = "repo", **common_overrides) -> List[StarredRepo]:
    """Create a batch of test repos with sequential IDs.

    Args:
        count: Number of repos to create
        prefix: Prefix for repo names
        **common_overrides: Common overrides applied to all repos

    Returns:
        List of StarredRepo instances

    Example:
        repos = create_batch_repos(10, prefix="test", language="Rust")
    """
    repos = []
    for i in range(count):
        repo_id = str(i + 1)
        full_name = f"test/{prefix}{i+1}"
        repo = create_test_repo(repo_id, full_name, **common_overrides)
        repos.append(repo)
    return repos


def create_batch_folders(count: int, prefix: str = "folder") -> List[VirtualFolder]:
    """Create a batch of test folders with sequential IDs.

    Args:
        count: Number of folders to create
        prefix: Prefix for folder names

    Returns:
        List of VirtualFolder instances

    Example:
        folders = create_batch_folders(5, prefix="category")
    """
    folders = []
    for i in range(count):
        folder_id = f"{prefix}{i+1}"
        name = f"{prefix.capitalize()} {i+1}"
        folder = create_test_folder(folder_id, name)
        folders.append(folder)
    return folders
