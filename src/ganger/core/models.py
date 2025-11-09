"""
Core data models for Ganger.

Adapted from yanger's data model pattern for GitHub stars management.

Modified: 2025-11-07
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from dateutil import parser as date_parser


class PrivacyStatus(Enum):
    """Repository privacy status."""

    PUBLIC = "public"
    PRIVATE = "private"


@dataclass
class StarredRepo:
    """
    Represents a starred GitHub repository.

    Mirrors GitHub's repository data structure with additional UI state.
    """

    # Core GitHub data
    id: str
    full_name: str  # owner/repo
    name: str
    owner: str
    description: str = ""
    stars_count: int = 0
    forks_count: int = 0
    watchers_count: int = 0
    language: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    is_archived: bool = False
    is_private: bool = False
    is_fork: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pushed_at: Optional[datetime] = None
    starred_at: Optional[datetime] = None
    url: str = ""
    clone_url: str = ""
    homepage: Optional[str] = None
    default_branch: str = "main"
    license: Optional[str] = None

    # UI state (not persisted to GitHub)
    is_selected: bool = False
    is_focused: bool = False

    @classmethod
    def from_github_response(cls, repo: Any, starred_at: Optional[datetime] = None) -> "StarredRepo":
        """
        Create a StarredRepo from PyGithub's Repository object.

        Args:
            repo: PyGithub Repository object
            starred_at: When the repo was starred (may not be in API response)

        Returns:
            StarredRepo instance
        """
        return cls(
            id=str(repo.id),
            full_name=repo.full_name,
            name=repo.name,
            owner=repo.owner.login,
            description=repo.description or "",
            stars_count=repo.stargazers_count or 0,
            forks_count=repo.forks_count or 0,
            watchers_count=repo.watchers_count or 0,
            language=repo.language,
            topics=repo.get_topics() if hasattr(repo, "get_topics") else [],
            is_archived=repo.archived,
            is_private=repo.private,
            is_fork=repo.fork,
            created_at=repo.created_at,
            updated_at=repo.updated_at,
            pushed_at=repo.pushed_at,
            starred_at=starred_at,
            url=repo.html_url,
            clone_url=repo.clone_url,
            homepage=repo.homepage,
            default_branch=repo.default_branch or "main",
            license=repo.license.name if repo.license else None,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StarredRepo":
        """Create a StarredRepo from a dictionary (e.g., from cache)."""
        # Make a copy to avoid modifying the original
        data = data.copy()

        # Remove cache-specific fields
        data.pop("cached_at", None)
        data.pop("accessed_at", None)

        # Parse datetime fields
        for field in ["created_at", "updated_at", "pushed_at", "starred_at"]:
            if field in data and data[field] and isinstance(data[field], str):
                data[field] = date_parser.parse(data[field])

        # Ensure topics is a list
        if "topics" in data and isinstance(data["topics"], str):
            import json

            data["topics"] = json.loads(data["topics"])

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization (cache, MCP responses)."""
        import json

        data = {
            "id": self.id,
            "full_name": self.full_name,
            "name": self.name,
            "owner": self.owner,
            "description": self.description,
            "stars_count": self.stars_count,
            "forks_count": self.forks_count,
            "watchers_count": self.watchers_count,
            "language": self.language,
            "topics": json.dumps(self.topics),  # Serialize list as JSON
            "is_archived": self.is_archived,
            "is_private": self.is_private,
            "is_fork": self.is_fork,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "pushed_at": self.pushed_at.isoformat() if self.pushed_at else None,
            "starred_at": self.starred_at.isoformat() if self.starred_at else None,
            "url": self.url,
            "clone_url": self.clone_url,
            "homepage": self.homepage,
            "default_branch": self.default_branch,
            "license": self.license,
        }
        return data

    def format_stars(self) -> str:
        """Format star count for display (e.g., 1.2k, 45.3k)."""
        count = self.stars_count
        if count >= 1000:
            return f"{count / 1000:.1f}k"
        return str(count)

    def format_updated(self) -> str:
        """Format last updated time for display (e.g., 2d ago, 3w ago)."""
        if not self.updated_at:
            return "unknown"

        now = datetime.now(self.updated_at.tzinfo)
        delta = now - self.updated_at

        if delta.days < 1:
            hours = delta.seconds // 3600
            return f"{hours}h ago" if hours > 0 else "just now"
        elif delta.days < 7:
            return f"{delta.days}d ago"
        elif delta.days < 30:
            weeks = delta.days // 7
            return f"{weeks}w ago"
        elif delta.days < 365:
            months = delta.days // 30
            return f"{months}mo ago"
        else:
            years = delta.days // 365
            return f"{years}y ago"


@dataclass
class VirtualFolder:
    """
    Virtual folder for organizing starred repos using tag-based categorization.

    Unlike playlists in yanger (which are real), these are purely organizational
    and based on matching topics/tags.
    """

    id: str
    name: str
    auto_tags: List[str] = field(default_factory=list)  # Auto-match repos with these topics
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Computed fields (not stored)
    repo_count: int = 0
    is_selected: bool = False
    is_focused: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VirtualFolder":
        """Create from dictionary (e.g., from cache)."""
        import json

        # Parse auto_tags if it's a JSON string
        if "auto_tags" in data and isinstance(data["auto_tags"], str):
            data["auto_tags"] = json.loads(data["auto_tags"])

        # Parse datetime fields
        for field in ["created_at", "updated_at"]:
            if field in data and data[field] and isinstance(data[field], str):
                data[field] = date_parser.parse(data[field])

        # Remove computed fields
        data.pop("repo_count", None)
        data.pop("is_selected", None)
        data.pop("is_focused", None)

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        import json

        return {
            "id": self.id,
            "name": self.name,
            "auto_tags": json.dumps(self.auto_tags),
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def matches_repo(self, repo: StarredRepo) -> bool:
        """
        Check if a repo matches this folder's auto-tags.

        Returns True if any of the repo's topics match any of the folder's auto_tags.
        Also checks language as a special case.
        """
        if not self.auto_tags:
            return False

        # Check topics
        repo_topics_lower = [topic.lower() for topic in repo.topics]
        for tag in self.auto_tags:
            tag_lower = tag.lower()
            if tag_lower in repo_topics_lower:
                return True

            # Also check language
            if repo.language and tag_lower == repo.language.lower():
                return True

        return False


@dataclass
class RepoMetadata:
    """
    Extended metadata for a repository (README, issues, etc.).

    This is cached separately from StarredRepo to reduce memory usage.
    """

    repo_id: str
    readme_content: Optional[str] = None
    readme_format: str = "markdown"  # markdown, rst, txt
    has_issues: bool = True
    open_issues_count: int = 0
    has_wiki: bool = False
    has_projects: bool = False
    has_pages: bool = False
    cached_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepoMetadata":
        """Create from dictionary (e.g., from cache)."""
        if "cached_at" in data and data["cached_at"] and isinstance(data["cached_at"], str):
            data["cached_at"] = date_parser.parse(data["cached_at"])

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "repo_id": self.repo_id,
            "readme_content": self.readme_content,
            "readme_format": self.readme_format,
            "has_issues": self.has_issues,
            "open_issues_count": self.open_issues_count,
            "has_wiki": self.has_wiki,
            "has_projects": self.has_projects,
            "has_pages": self.has_pages,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
        }


@dataclass
class ClipboardItem:
    """Item in the clipboard (for copy/cut/paste operations)."""

    repo: StarredRepo
    source_folder_id: Optional[str] = None  # For cut operations
    operation: str = "copy"  # "copy" or "cut"


@dataclass
class Clipboard:
    """
    Manages copy/cut/paste operations for repos between folders.

    Adapted from yanger's Clipboard pattern.
    """

    items: List[ClipboardItem] = field(default_factory=list)

    def copy(self, repos: List[StarredRepo], source_folder_id: Optional[str] = None) -> None:
        """
        Copy repos to clipboard.

        Args:
            repos: List of repos to copy
            source_folder_id: Optional source folder ID
        """
        self.items = [
            ClipboardItem(repo=repo, source_folder_id=source_folder_id, operation="copy")
            for repo in repos
        ]

    def cut(self, repos: List[StarredRepo], source_folder_id: str) -> None:
        """
        Cut repos to clipboard (will be removed from source folder on paste).

        Args:
            repos: List of repos to cut
            source_folder_id: Source folder ID (required for cut)
        """
        self.items = [
            ClipboardItem(repo=repo, source_folder_id=source_folder_id, operation="cut")
            for repo in repos
        ]

    def paste(self) -> List[ClipboardItem]:
        """
        Get items for pasting.

        Returns:
            List of clipboard items (does NOT clear clipboard)
        """
        return self.items.copy()

    def clear(self) -> None:
        """Clear the clipboard."""
        self.items = []

    def is_empty(self) -> bool:
        """Check if clipboard is empty."""
        return len(self.items) == 0

    def get_operation(self) -> Optional[str]:
        """Get the operation type ('copy' or 'cut'), or None if empty."""
        if self.is_empty():
            return None
        return self.items[0].operation

    def count(self) -> int:
        """Get number of items in clipboard."""
        return len(self.items)


@dataclass
class FolderRepoLink:
    """
    Represents the relationship between a folder and a repo.

    Used for tracking manual additions vs auto-categorized repos.
    """

    folder_id: str
    repo_id: str
    is_manual: bool = False  # True if manually added, False if auto-matched
    added_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FolderRepoLink":
        """Create from dictionary."""
        if "added_at" in data and data["added_at"] and isinstance(data["added_at"], str):
            data["added_at"] = date_parser.parse(data["added_at"])

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "folder_id": self.folder_id,
            "repo_id": self.repo_id,
            "is_manual": self.is_manual,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }
