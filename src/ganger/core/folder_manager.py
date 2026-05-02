"""
Virtual folder manager with auto-categorization.

Service layer for managing virtual folders and organizing repos by tags.

Modified: 2025-11-07
"""

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional

from ganger.core.cache import PersistentCache
from ganger.core.models import VirtualFolder, StarredRepo, Clipboard, ClipboardItem
from ganger.core.exceptions import FolderNotFoundError, CacheError


class FolderManager:
    """
    Manages virtual folders for organizing starred repositories.

    Virtual folders are tag-based categorizations that don't exist on GitHub.
    Repos can belong to multiple folders, and folders can auto-match repos
    based on language and topics.
    """

    def __init__(self, cache: PersistentCache):
        """
        Initialize folder manager.

        Args:
            cache: PersistentCache instance for storage
        """
        self.cache = cache
        self.clipboard = Clipboard()

    async def get_all_folders(self) -> List[VirtualFolder]:
        """
        Get all virtual folders.

        Returns:
            List of VirtualFolder objects
        """
        return await self.cache.get_virtual_folders()

    async def create_folder(
        self,
        name: str,
        auto_tags: Optional[List[str]] = None,
        description: str = "",
        kind: Optional[str] = None,
    ) -> VirtualFolder:
        """
        Create a new virtual folder with kind-specific validation.

        Validation rules:
        - ``rule`` / ``hybrid`` require non-empty ``auto_tags``.
        - ``curated`` rejects ``auto_tags`` (must be empty or None).
        - ``system`` is reserved for internal use; external callers cannot
          create system folders. The cache layer enforces this independently.

        ``kind`` may be omitted; in that case it's inferred from ``auto_tags``
        (non-empty -> ``rule``, otherwise ``curated``). This preserves the
        legacy two-arg signature ``create_folder(name, auto_tags=...)``.

        Args:
            name: Folder name
            auto_tags: Tags for auto-matching repos. Required for rule/hybrid,
                forbidden for curated.
            description: Optional folder description
            kind: Folder kind - "rule", "curated", or "hybrid". If None,
                inferred from auto_tags.

        Returns:
            Created VirtualFolder object

        Raises:
            CacheError: If folder with same name exists, kind is invalid, or
                kind/auto_tags combination violates the rules above.
        """
        tags = auto_tags or []

        if kind is None:
            kind = "rule" if tags else "curated"

        if kind == "system":
            raise CacheError(
                "Cannot create system folders from the service layer. "
                "They are managed internally (e.g. all-stars)."
            )
        if kind not in ("rule", "curated", "hybrid"):
            raise CacheError(
                f"Invalid folder kind '{kind}'. "
                f"Allowed for create_folder: rule, curated, hybrid"
            )

        if kind in ("rule", "hybrid") and not tags:
            raise CacheError(
                f"kind='{kind}' folders require non-empty auto_tags"
            )
        if kind == "curated" and tags:
            raise CacheError(
                "kind='curated' folders cannot have auto_tags. "
                "Use kind='hybrid' if you want both manual and auto entries."
            )

        folder = VirtualFolder(
            id=str(uuid.uuid4()),
            name=name,
            auto_tags=tags,
            description=description,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            kind=kind,
        )

        return await self.cache.create_virtual_folder(folder)

    async def list_folders_by_kind(self, kind: str) -> List[VirtualFolder]:
        """Return folders filtered by kind."""
        all_folders = await self.cache.get_virtual_folders()
        return [f for f in all_folders if f.kind == kind]

    async def delete_folder(self, folder_id: str) -> None:
        """
        Delete a virtual folder.

        Args:
            folder_id: Folder ID to delete

        Note:
            This only deletes the folder, not the repos themselves
        """
        await self.cache.delete_virtual_folder(folder_id)

    async def get_folder_repos(self, folder_id: str) -> List[StarredRepo]:
        """
        Get all repos in a folder.

        Args:
            folder_id: Folder ID

        Returns:
            List of StarredRepo objects in this folder
        """
        return await self.cache.get_folder_repos(folder_id)

    async def add_repo_to_folder(
        self, repo_id: str, folder_id: str, is_manual: bool = True
    ) -> None:
        """
        Add a repo to a folder.

        Args:
            repo_id: Repository ID
            folder_id: Folder ID
            is_manual: True if manually added, False if auto-matched
        """
        await self.cache.add_repo_to_folder(repo_id, folder_id, is_manual)

    async def remove_repo_from_folder(self, repo_id: str, folder_id: str) -> None:
        """
        Remove a repo from a folder.

        Args:
            repo_id: Repository ID
            folder_id: Folder ID
        """
        await self.cache.remove_repo_from_folder(repo_id, folder_id)

    async def move_repo(
        self, repo_id: str, from_folder_id: str, to_folder_id: str
    ) -> None:
        """
        Move a repo from one folder to another.

        Args:
            repo_id: Repository ID
            from_folder_id: Source folder ID
            to_folder_id: Destination folder ID
        """
        # Remove from source
        await self.cache.remove_repo_from_folder(repo_id, from_folder_id)
        # Add to destination
        await self.cache.add_repo_to_folder(repo_id, to_folder_id, is_manual=True)

    async def copy_repo(self, repo_id: str, to_folder_id: str) -> None:
        """
        Copy a repo to another folder (repo remains in source folder).

        Args:
            repo_id: Repository ID
            to_folder_id: Destination folder ID
        """
        await self.cache.add_repo_to_folder(repo_id, to_folder_id, is_manual=True)

    async def auto_categorize_all(
        self, repos: Optional[List[StarredRepo]] = None
    ) -> Dict[str, int]:
        """
        Auto-categorize all repos into folders based on auto_tags.

        This will:
        1. Get all repos (if not provided)
        2. Get all folders with auto_tags
        3. Match repos to folders
        4. Add repos to matching folders (as non-manual)

        Args:
            repos: Optional list of repos to categorize (fetches from cache if None)

        Returns:
            Dictionary mapping folder_id -> number of repos added
        """
        # Get repos
        if repos is None:
            repos = await self.cache.get_starred_repos()
            if repos is None:
                repos = []

        # Auto-categorization only applies to rule/hybrid folders. Curated
        # folders are user-curated by definition; system folders manage their
        # own membership.
        folders = await self.cache.get_virtual_folders()
        folders_with_tags = [
            f for f in folders if f.auto_tags and f.kind in ("rule", "hybrid")
        ]

        stats = {}

        for folder in folders_with_tags:
            added_count = 0

            for repo in repos:
                if folder.matches_repo(repo):
                    # Add to folder (non-manual)
                    try:
                        await self.cache.add_repo_to_folder(
                            repo.id, folder.id, is_manual=False
                        )
                        added_count += 1
                    except Exception:
                        # Repo might already be in folder
                        pass

            stats[folder.id] = added_count

        return stats

    async def auto_categorize_repo(self, repo: StarredRepo) -> List[str]:
        """
        Auto-categorize a single repo into matching folders.

        Args:
            repo: StarredRepo to categorize

        Returns:
            List of folder IDs the repo was added to
        """
        folders = await self.cache.get_virtual_folders()
        folders_with_tags = [
            f for f in folders if f.auto_tags and f.kind in ("rule", "hybrid")
        ]

        matched_folder_ids = []

        for folder in folders_with_tags:
            if folder.matches_repo(repo):
                try:
                    await self.cache.add_repo_to_folder(
                        repo.id, folder.id, is_manual=False
                    )
                    matched_folder_ids.append(folder.id)
                except Exception:
                    # Repo might already be in folder
                    pass

        return matched_folder_ids

    async def create_default_folders(
        self, default_folders: List[Dict[str, any]]
    ) -> List[VirtualFolder]:
        """
        Create default folders from configuration.

        Args:
            default_folders: List of folder configs with 'name' and 'auto_tags'

        Returns:
            List of created VirtualFolder objects
        """
        created = []

        for folder_config in default_folders:
            tags = folder_config.get("auto_tags", []) or []
            # Default-folder configs from config.yaml are auto-tag-driven, so
            # they're "rule" folders unless explicitly overridden. The "kind"
            # key in a folder_config is honored if present.
            kind = folder_config.get("kind") or ("rule" if tags else "curated")
            try:
                folder = await self.create_folder(
                    name=folder_config["name"],
                    kind=kind,
                    auto_tags=tags,
                    description=folder_config.get("description", ""),
                )
                created.append(folder)
            except CacheError:
                # Folder already exists, skip
                pass

        return created

    # ==================== Clipboard Operations ====================

    def clipboard_copy(
        self, repos: List[StarredRepo], source_folder_id: Optional[str] = None
    ) -> None:
        """
        Copy repos to clipboard.

        Args:
            repos: List of repos to copy
            source_folder_id: Optional source folder ID
        """
        self.clipboard.copy(repos, source_folder_id)

    def clipboard_cut(self, repos: List[StarredRepo], source_folder_id: str) -> None:
        """
        Cut repos to clipboard (will be removed from source on paste).

        Args:
            repos: List of repos to cut
            source_folder_id: Source folder ID (required)
        """
        self.clipboard.cut(repos, source_folder_id)

    async def clipboard_paste(self, target_folder_id: str) -> int:
        """
        Paste repos from clipboard to target folder.

        Args:
            target_folder_id: Destination folder ID

        Returns:
            Number of repos pasted
        """
        items = self.clipboard.paste()

        for item in items:
            if item.operation == "cut" and item.source_folder_id:
                # Move (remove from source, add to target)
                await self.move_repo(
                    item.repo.id, item.source_folder_id, target_folder_id
                )
            else:
                # Copy (just add to target)
                await self.copy_repo(item.repo.id, target_folder_id)

        pasted_count = len(items)

        # Clear clipboard after paste (cut operation)
        if items and items[0].operation == "cut":
            self.clipboard.clear()

        return pasted_count

    def clipboard_clear(self) -> None:
        """Clear the clipboard."""
        self.clipboard.clear()

    def clipboard_status(self) -> Dict[str, any]:
        """
        Get clipboard status.

        Returns:
            Dictionary with clipboard info
        """
        return {
            "count": self.clipboard.count(),
            "operation": self.clipboard.get_operation(),
            "is_empty": self.clipboard.is_empty(),
        }

    # ==================== Statistics and Analysis ====================

    async def get_folder_stats(self, folder_id: str) -> Dict[str, any]:
        """
        Get statistics for a folder.

        Args:
            folder_id: Folder ID

        Returns:
            Dictionary with folder statistics
        """
        repos = await self.get_folder_repos(folder_id)

        # Calculate stats
        total_stars = sum(repo.stars_count for repo in repos)
        languages = {}
        for repo in repos:
            if repo.language:
                languages[repo.language] = languages.get(repo.language, 0) + 1

        return {
            "folder_id": folder_id,
            "repo_count": len(repos),
            "total_stars": total_stars,
            "avg_stars": total_stars // len(repos) if repos else 0,
            "languages": languages,
            "top_language": max(languages.items(), key=lambda x: x[1])[0]
            if languages
            else None,
        }

    async def suggest_folders_for_repo(self, repo: StarredRepo) -> List[VirtualFolder]:
        """
        Suggest folders for a repo based on auto_tags.

        Args:
            repo: StarredRepo to find folders for

        Returns:
            List of matching VirtualFolder objects
        """
        folders = await self.cache.get_virtual_folders()
        suggestions = []

        for folder in folders:
            if folder.auto_tags and folder.matches_repo(repo):
                suggestions.append(folder)

        return suggestions
