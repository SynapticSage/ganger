"""Data loading service for Ganger.

Centralizes logic for loading and synchronizing GitHub data.

Modified: 2025-11-08
"""

import asyncio
import logging
from typing import List, Optional
from pathlib import Path

from .github_client import GitHubAPIClient
from .exceptions import CacheError
from .cache import PersistentCache
from .folder_manager import FolderManager
from .models import StarredRepo, VirtualFolder
from ..config.settings import Settings

logger = logging.getLogger(__name__)


class DataLoader:
    """Handles loading and synchronizing GitHub data."""

    def __init__(
        self,
        api_client: GitHubAPIClient,
        cache: PersistentCache,
        folder_manager: FolderManager,
        settings: Settings,
    ):
        """Initialize data loader.

        Args:
            api_client: GitHub API client
            cache: Persistent cache
            folder_manager: Folder manager
            settings: Application settings
        """
        self.api_client = api_client
        self.cache = cache
        self.folder_manager = folder_manager
        self.settings = settings

    async def load_starred_repos(self, force_refresh: bool = False) -> List[StarredRepo]:
        """Load starred repos from cache or GitHub API.

        Args:
            force_refresh: Force fetch from API even if cache is valid

        Returns:
            List of starred repositories
        """
        try:
            # Try cache first unless force refresh
            if not force_refresh:
                cached_repos = await self.cache.get_starred_repos()
                if cached_repos:
                    logger.info(f"Loaded {len(cached_repos)} repos from cache")
                    return cached_repos

            # Fetch from GitHub API (run in thread pool to avoid blocking)
            logger.info("Fetching starred repos from GitHub API...")
            repos = await asyncio.to_thread(self.api_client.get_starred_repos)

            logger.info(f"Fetched {len(repos)} starred repos from GitHub")

            # Store in cache
            await self.cache.set_starred_repos(repos)

            return repos

        except Exception as e:
            logger.error(f"Error loading starred repos: {e}", exc_info=True)
            # Try cache as fallback
            cached_repos = await self.cache.get_starred_repos()
            if cached_repos:
                logger.warning(f"Using {len(cached_repos)} repos from cache (API failed)")
                return cached_repos
            raise

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
                # Create "All Stars" folder
                all_stars = VirtualFolder(
                    id="all-stars",
                    name="All Stars",
                    auto_tags=[],  # No auto-tags, manually synced
                    repo_count=0,
                )
                try:
                    await self.cache.create_virtual_folder(all_stars)
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
                        folder = VirtualFolder(
                            id=name.lower().replace(" ", "-"),
                            name=name,
                            auto_tags=auto_tags,
                            repo_count=0,
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
        """Ensure All Stars folder contains all repos.

        Args:
            all_repos: All starred repositories
        """
        try:
            all_stars_id = "all-stars"

            # Get current repos in All Stars
            current_repo_ids = set()
            try:
                current_repos = await self.cache.get_folder_repos(all_stars_id)
                current_repo_ids = {r["id"] for r in current_repos}
            except Exception:
                # Folder might not exist yet
                pass

            # Add any missing repos
            added = 0
            for repo in all_repos:
                if repo.id not in current_repo_ids:
                    await self.cache.add_repo_to_folder(
                        repo_id=repo.id,
                        folder_id=all_stars_id,
                        is_manual=False,  # Auto-managed
                    )
                    added += 1

            if added > 0:
                logger.info(f"Added {added} repos to 'All Stars' folder")

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

            logger.info(f"Auto-categorizing {len(repos)} repos...")

            # Use folder manager's categorization
            categorized = await self.folder_manager.auto_categorize_all(repos)

            total_categorized = sum(len(repos) for repos in categorized.values())
            logger.info(f"Auto-categorized {total_categorized} repos into {len(categorized)} folders")

        except Exception as e:
            logger.error(f"Error auto-categorizing: {e}", exc_info=True)
            # Don't raise - this is non-critical
