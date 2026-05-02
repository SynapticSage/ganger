"""Data loading service for Ganger.

Centralizes logic for loading and synchronizing GitHub data.

Modified: 2025-11-08
"""

import asyncio
import logging
from typing import List, Optional, Callable, Awaitable

from .github_client import GitHubAPIClient
from .exceptions import CacheError
from .cache import PersistentCache
from .folder_manager import FolderManager
from .models import StarredRepo, VirtualFolder
from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Type alias for progress callback: (label, current, total) -> None
ProgressCallback = Callable[[str, int, int], Awaitable[None]]
RepoSyncCallback = Callable[[int, Optional[int]], Awaitable[None]]


class DataLoader:
    """Handles loading and synchronizing GitHub data."""

    def __init__(
        self,
        api_client: GitHubAPIClient,
        cache: PersistentCache,
        folder_manager: FolderManager,
        settings: Settings,
        progress_callback: Optional[ProgressCallback] = None,
        repo_sync_callback: Optional[RepoSyncCallback] = None,
    ):
        """Initialize data loader.

        Args:
            api_client: GitHub API client
            cache: Persistent cache
            folder_manager: Folder manager
            settings: Application settings
            progress_callback: Optional async callback(label, current, total) for progress
            repo_sync_callback: Optional async callback(cached_count, total_count)
                                fired as repo pages are written to cache
        """
        self.api_client = api_client
        self.cache = cache
        self.folder_manager = folder_manager
        self.settings = settings
        self.progress_callback = progress_callback
        self.repo_sync_callback = repo_sync_callback

    async def _report_progress(self, label: str, current: int, total: int) -> None:
        """Report progress if callback is set."""
        if self.progress_callback:
            try:
                await self.progress_callback(label, current, total)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    async def _report_repo_sync(self, cached_count: int, total_count: Optional[int]) -> None:
        """Report incremental repo-cache updates if a callback is set."""
        if self.repo_sync_callback:
            try:
                await self.repo_sync_callback(cached_count, total_count)
            except Exception as e:
                logger.warning(f"Repo sync callback failed: {e}")

    async def load_starred_repos(self, force_refresh: bool = False) -> List[StarredRepo]:
        """Load starred repos from cache or GitHub API.

        Args:
            force_refresh: Force fetch from API even if cache is valid

        Returns:
            List of starred repositories
        """
        try:
            # Try cache first unless force refresh
            sync_state = await self.cache.get_starred_sync_state()
            if not force_refresh:
                cached_repos = await self.cache.get_starred_repos()
                if cached_repos:
                    can_resume_incrementally = hasattr(type(self.api_client), "get_starred_repos_page")
                    if sync_state["complete"] or not can_resume_incrementally:
                        logger.info(f"Loaded {len(cached_repos)} repos from cache")
                        return cached_repos

                    logger.info(
                        "Resuming starred repo sync from cached snapshot at %s/%s",
                        len(cached_repos),
                        sync_state["total_count"] or "?",
                    )
                    repos = await self._load_starred_repos_incrementally(
                        start_cursor=sync_state["cursor"],
                        existing_repos=cached_repos,
                        total_count=sync_state["total_count"],
                    )
                    logger.info(f"Fetched {len(repos)} starred repos from GitHub")
                    return repos

            await self.cache.set_starred_sync_state(
                cached_count=0,
                total_count=None,
                cursor=None,
                complete=False,
            )

            used_incremental_cache = False
            if hasattr(type(self.api_client), "get_starred_repos_page"):
                try:
                    logger.info("Fetching starred repos from GitHub API incrementally...")
                    repos = await self._load_starred_repos_incrementally()
                    used_incremental_cache = True
                except Exception as incremental_error:
                    logger.warning(
                        "Incremental starred repo sync failed, falling back to full fetch: %s",
                        incremental_error,
                    )
                    repos = await asyncio.to_thread(self.api_client.get_starred_repos)
            else:
                # Fetch from GitHub API (run in thread pool to avoid blocking)
                logger.info("Fetching starred repos from GitHub API...")
                repos = await asyncio.to_thread(self.api_client.get_starred_repos)

            logger.info(f"Fetched {len(repos)} starred repos from GitHub")

            if not used_incremental_cache:
                # Incremental GraphQL sync populates the cache as it goes.
                await self.cache.set_starred_repos(repos)
                await self._report_repo_sync(len(repos), len(repos))

            return repos

        except Exception as e:
            logger.error(f"Error loading starred repos: {e}", exc_info=True)
            # Try cache as fallback
            cached_repos = await self.cache.get_starred_repos()
            if cached_repos:
                logger.warning(f"Using {len(cached_repos)} repos from cache (API failed)")
                return cached_repos
            raise

    async def _load_starred_repos_incrementally(
        self,
        start_cursor: Optional[str] = None,
        existing_repos: Optional[List[StarredRepo]] = None,
        total_count: Optional[int] = None,
    ) -> List[StarredRepo]:
        """Fetch starred repos page by page so the TUI can update mid-sync."""
        repo_map = {repo.id: repo for repo in (existing_repos or [])}
        repo_ids = set(repo_map)
        cursor = start_cursor

        if repo_ids:
            await self._report_repo_sync(len(repo_ids), total_count)

        while True:
            page = await asyncio.to_thread(
                self.api_client.get_starred_repos_page,
                cursor,
            )

            page_repos = page["repos"]
            total_count = page.get("total_count")

            if page_repos:
                await self.cache.upsert_starred_repos(page_repos)
                for repo in page_repos:
                    repo_map[repo.id] = repo
                    repo_ids.add(repo.id)

            await self.cache.set_starred_sync_state(
                cached_count=len(repo_ids),
                total_count=total_count,
                cursor=page["end_cursor"],
                complete=not page["has_next_page"],
            )

            if total_count and total_count > 0:
                await self._report_progress("Syncing", len(repo_ids), total_count)
            await self._report_repo_sync(len(repo_ids), total_count)

            if not page["has_next_page"]:
                break

            cursor = page["end_cursor"]

        await self.cache.prune_starred_repos(repo_ids)
        await self.cache.set_starred_sync_state(
            cached_count=len(repo_ids),
            total_count=total_count or len(repo_ids),
            cursor=None,
            complete=True,
        )

        refreshed_repos = await self.cache.get_starred_repos(force_refresh=True)
        return refreshed_repos or []

    async def ensure_default_folders(self) -> List[VirtualFolder]:
        """Create default folders if they don't exist.

        Creates:
        - "All Stars" folder (special folder with all repos)
        - Language/topic folders from config

        Returns:
            List of all virtual folders
        """
        try:
            # Check if "All Stars" folder exists
            existing_folders = await self.cache.get_virtual_folders()
            all_stars_exists = any(f.name == "All Stars" for f in existing_folders)

            if not all_stars_exists:
                # Create "All Stars" folder. ``_internal=True`` is required
                # because kind="system" is reserved for cache-internal callers.
                all_stars = VirtualFolder(
                    id="all-stars",
                    name="All Stars",
                    auto_tags=[],
                    repo_count=0,
                    kind="system",
                )
                try:
                    await self.cache.create_virtual_folder(all_stars, _internal=True)
                    logger.info("Created 'All Stars' folder")
                except CacheError as e:
                    # Folder already exists (race condition or concurrent creation)
                    logger.debug(f"All Stars folder already exists: {e}")

            # Create language/topic folders from config
            if self.settings.folders.default_folders:
                for folder_config in self.settings.folders.default_folders:
                    name = folder_config.get("name")
                    auto_tags = folder_config.get("auto_tags", [])

                    # Check if folder already exists
                    exists = any(f.name == name for f in existing_folders)
                    if not exists:
                        # Default folders from config are auto-tag-driven, so
                        # they're "rule" folders. The startup repair pass
                        # would correct this anyway, but emitting the right
                        # kind up front avoids the round trip.
                        kind = folder_config.get("kind") or (
                            "rule" if auto_tags else "curated"
                        )
                        folder = VirtualFolder(
                            id=name.lower().replace(" ", "-"),
                            name=name,
                            auto_tags=auto_tags,
                            repo_count=0,
                            kind=kind,
                        )
                        try:
                            await self.cache.create_virtual_folder(folder)
                            logger.info(f"Created folder '{name}' with tags {auto_tags}")
                        except CacheError as e:
                            # Folder already exists (race condition or concurrent creation)
                            logger.debug(f"Folder '{name}' already exists: {e}")

            # Return all folders
            return await self.cache.get_virtual_folders()

        except Exception as e:
            logger.error(f"Error ensuring default folders: {e}", exc_info=True)
            raise

    async def sync_all_stars_folder(self, all_repos: List[StarredRepo]) -> None:
        """Refresh progress for the special All Stars folder.

        Args:
            all_repos: All starred repositories
        """
        try:
            total = len(all_repos)
            if total > 0:
                await self._report_progress("Syncing", total, total)
            logger.info("All Stars uses the starred repo cache directly; no folder sync needed")

        except Exception as e:
            logger.error(f"Error syncing All Stars folder: {e}", exc_info=True)
            # Don't raise - this is non-critical

    async def auto_categorize_all(self, repos: List[StarredRepo]) -> None:
        """Auto-categorize repos into folders based on tags.

        Args:
            repos: Repositories to categorize
        """
        try:
            if not self.settings.behavior.auto_categorize:
                logger.info("Auto-categorization disabled in settings")
                return

            total = len(repos)
            logger.info(f"Auto-categorizing {total} repos...")

            # Report start of categorization
            await self._report_progress("Categorizing", 0, total)

            # Use folder manager's categorization
            categorized = await self.folder_manager.auto_categorize_all(repos)

            # Report completion
            await self._report_progress("Categorizing", total, total)

            total_categorized = sum(len(r) for r in categorized.values())
            logger.info(f"Auto-categorized {total_categorized} repos into {len(categorized)} folders")

        except Exception as e:
            logger.error(f"Error auto-categorizing: {e}", exc_info=True)
            # Don't raise - this is non-critical
