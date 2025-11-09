"""
Persistent cache for GitHub starred repos using SQLite.

Provides offline browsing, reduces API calls, and enables virtual folder persistence.
Shared state between TUI and MCP interfaces.

Modified: 2025-11-07
"""

import json
import aiosqlite
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from ganger.core.models import StarredRepo, VirtualFolder, RepoMetadata, FolderRepoLink
from ganger.core.exceptions import CacheError


class PersistentCache:
    """
    SQLite-based persistent cache for starred repos and virtual folders.

    Schema:
    - starred_repos: Cached repository data
    - virtual_folders: User-created virtual folders
    - folder_repos: Many-to-many relationship (folders <-> repos)
    - repo_metadata: Extended metadata (README, issues, etc.)
    """

    # Schema version for migrations
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None, ttl_seconds: int = 3600):
        """
        Initialize persistent cache.

        Args:
            db_path: Path to SQLite database (default: ~/.cache/ganger/ganger.db)
            ttl_seconds: Time-to-live for cached data in seconds (default: 1 hour)
        """
        if db_path is None:
            cache_dir = Path.home() / ".cache" / "ganger"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "ganger.db"

        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """
        Initialize database schema.

        Creates all tables if they don't exist.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")

            # Table: starred_repos
            await db.execute("""
                CREATE TABLE IF NOT EXISTS starred_repos (
                    id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    description TEXT,
                    stars_count INTEGER DEFAULT 0,
                    forks_count INTEGER DEFAULT 0,
                    watchers_count INTEGER DEFAULT 0,
                    language TEXT,
                    topics TEXT,
                    is_archived BOOLEAN DEFAULT 0,
                    is_private BOOLEAN DEFAULT 0,
                    is_fork BOOLEAN DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    pushed_at TEXT,
                    starred_at TEXT,
                    url TEXT,
                    clone_url TEXT,
                    homepage TEXT,
                    default_branch TEXT DEFAULT 'main',
                    license TEXT,
                    cached_at TEXT NOT NULL,
                    accessed_at TEXT
                )
            """)

            # Table: virtual_folders
            await db.execute("""
                CREATE TABLE IF NOT EXISTS virtual_folders (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    auto_tags TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)

            # Table: folder_repos (many-to-many relationship)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS folder_repos (
                    folder_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    is_manual BOOLEAN DEFAULT 0,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (folder_id, repo_id),
                    FOREIGN KEY (folder_id) REFERENCES virtual_folders(id) ON DELETE CASCADE,
                    FOREIGN KEY (repo_id) REFERENCES starred_repos(id) ON DELETE CASCADE
                )
            """)

            # Table: repo_metadata (extended data like README)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS repo_metadata (
                    repo_id TEXT PRIMARY KEY,
                    readme_content TEXT,
                    readme_format TEXT DEFAULT 'markdown',
                    has_issues BOOLEAN DEFAULT 1,
                    open_issues_count INTEGER DEFAULT 0,
                    has_wiki BOOLEAN DEFAULT 0,
                    has_projects BOOLEAN DEFAULT 0,
                    has_pages BOOLEAN DEFAULT 0,
                    cached_at TEXT NOT NULL,
                    FOREIGN KEY (repo_id) REFERENCES starred_repos(id) ON DELETE CASCADE
                )
            """)

            # Indexes for performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_repo_language ON starred_repos(language)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_repo_updated ON starred_repos(updated_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_repo_stars ON starred_repos(stars_count)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_folder_repo ON folder_repos(folder_id, repo_id)")

            # Metadata table for schema version
            await db.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await db.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

            await db.commit()

    # ==================== Starred Repos Operations ====================

    async def get_starred_repos(self, force_refresh: bool = False) -> Optional[List[StarredRepo]]:
        """
        Get all starred repos from cache.

        Args:
            force_refresh: Ignore TTL and force fresh data

        Returns:
            List of StarredRepo objects, or None if cache expired/empty
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Check if cache is expired
            if not force_refresh:
                cursor = await db.execute(
                    "SELECT MIN(cached_at) as oldest FROM starred_repos"
                )
                row = await cursor.fetchone()
                if row and row["oldest"]:
                    oldest_time = datetime.fromisoformat(row["oldest"])
                    if datetime.now() - oldest_time > timedelta(seconds=self.ttl_seconds):
                        return None  # Cache expired

            # Get all repos
            cursor = await db.execute("SELECT * FROM starred_repos ORDER BY stars_count DESC")
            rows = await cursor.fetchall()

            if not rows:
                return None

            repos = []
            for row in rows:
                repo_dict = dict(row)
                repos.append(StarredRepo.from_dict(repo_dict))

            return repos

    async def set_starred_repos(self, repos: List[StarredRepo]) -> None:
        """
        Cache starred repos.

        Args:
            repos: List of StarredRepo objects to cache
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Clear existing repos
            await db.execute("DELETE FROM starred_repos")

            # Insert new repos
            for repo in repos:
                data = repo.to_dict()
                data["cached_at"] = datetime.now().isoformat()
                data["accessed_at"] = datetime.now().isoformat()

                await db.execute("""
                    INSERT OR REPLACE INTO starred_repos (
                        id, full_name, name, owner, description, stars_count, forks_count,
                        watchers_count, language, topics, is_archived, is_private, is_fork,
                        created_at, updated_at, pushed_at, starred_at, url, clone_url,
                        homepage, default_branch, license, cached_at, accessed_at
                    ) VALUES (
                        :id, :full_name, :name, :owner, :description, :stars_count, :forks_count,
                        :watchers_count, :language, :topics, :is_archived, :is_private, :is_fork,
                        :created_at, :updated_at, :pushed_at, :starred_at, :url, :clone_url,
                        :homepage, :default_branch, :license, :cached_at, :accessed_at
                    )
                """, data)

            await db.commit()

    async def get_repo(self, repo_id: str) -> Optional[StarredRepo]:
        """
        Get a single repo by ID.

        Args:
            repo_id: Repository ID

        Returns:
            StarredRepo object, or None if not found
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("SELECT * FROM starred_repos WHERE id = ?", (repo_id,))
            row = await cursor.fetchone()

            if not row:
                return None

            # Update accessed_at
            await db.execute(
                "UPDATE starred_repos SET accessed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), repo_id),
            )
            await db.commit()

            return StarredRepo.from_dict(dict(row))

    async def invalidate_repos(self) -> None:
        """Invalidate (clear) all starred repos from cache."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM starred_repos")
            await db.commit()

    # ==================== Virtual Folders Operations ====================

    async def get_virtual_folders(self) -> List[VirtualFolder]:
        """
        Get all virtual folders.

        Returns:
            List of VirtualFolder objects
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT * FROM virtual_folders ORDER BY created_at ASC"
            )
            rows = await cursor.fetchall()

            folders = []
            for row in rows:
                folder_dict = dict(row)

                # Get repo count for this folder
                count_cursor = await db.execute(
                    "SELECT COUNT(*) as count FROM folder_repos WHERE folder_id = ?",
                    (row["id"],),
                )
                count_row = await count_cursor.fetchone()
                folder_dict["repo_count"] = count_row["count"] if count_row else 0

                folders.append(VirtualFolder.from_dict(folder_dict))

            return folders

    async def create_virtual_folder(
        self, folder: VirtualFolder
    ) -> VirtualFolder:
        """
        Create a new virtual folder.

        Args:
            folder: VirtualFolder object to create

        Returns:
            Created VirtualFolder object

        Raises:
            CacheError: If folder with same name exists
        """
        async with aiosqlite.connect(self.db_path) as db:
            data = folder.to_dict()

            # Set created_at/updated_at if not provided
            now = datetime.now().isoformat()
            if data["created_at"] is None:
                data["created_at"] = now
            if data["updated_at"] is None:
                data["updated_at"] = now

            try:
                await db.execute("""
                    INSERT INTO virtual_folders (id, name, auto_tags, description, created_at, updated_at)
                    VALUES (:id, :name, :auto_tags, :description, :created_at, :updated_at)
                """, data)
                await db.commit()
            except aiosqlite.IntegrityError:
                raise CacheError(f"Folder with name '{folder.name}' already exists")

            return folder

    async def delete_virtual_folder(self, folder_id: str) -> None:
        """
        Delete a virtual folder.

        Args:
            folder_id: Folder ID to delete
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM virtual_folders WHERE id = ?", (folder_id,))
            # folder_repos entries are deleted automatically via CASCADE
            await db.commit()

    async def get_folder_repos(self, folder_id: str) -> List[StarredRepo]:
        """
        Get all repos in a virtual folder.

        Args:
            folder_id: Folder ID

        Returns:
            List of StarredRepo objects in this folder
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT r.* FROM starred_repos r
                JOIN folder_repos fr ON r.id = fr.repo_id
                WHERE fr.folder_id = ?
                ORDER BY r.stars_count DESC
            """, (folder_id,))
            rows = await cursor.fetchall()

            return [StarredRepo.from_dict(dict(row)) for row in rows]

    async def add_repo_to_folder(
        self, repo_id: str, folder_id: str, is_manual: bool = True
    ) -> None:
        """
        Add a repo to a virtual folder.

        Args:
            repo_id: Repository ID
            folder_id: Folder ID
            is_manual: True if manually added, False if auto-matched
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO folder_repos (folder_id, repo_id, is_manual, added_at)
                VALUES (?, ?, ?, ?)
            """, (folder_id, repo_id, is_manual, datetime.now().isoformat()))
            await db.commit()

    async def remove_repo_from_folder(self, repo_id: str, folder_id: str) -> None:
        """
        Remove a repo from a virtual folder.

        Args:
            repo_id: Repository ID
            folder_id: Folder ID
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM folder_repos WHERE folder_id = ? AND repo_id = ?",
                (folder_id, repo_id),
            )
            await db.commit()

    # ==================== Repo Metadata Operations ====================

    async def get_repo_metadata(self, repo_id: str) -> Optional[RepoMetadata]:
        """
        Get extended metadata for a repo.

        Args:
            repo_id: Repository ID

        Returns:
            RepoMetadata object, or None if not cached
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT * FROM repo_metadata WHERE repo_id = ?", (repo_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return RepoMetadata.from_dict(dict(row))

    async def set_repo_metadata(self, metadata: RepoMetadata) -> None:
        """
        Cache extended metadata for a repo.

        Args:
            metadata: RepoMetadata object to cache
        """
        async with aiosqlite.connect(self.db_path) as db:
            data = metadata.to_dict()

            await db.execute("""
                INSERT OR REPLACE INTO repo_metadata (
                    repo_id, readme_content, readme_format, has_issues, open_issues_count,
                    has_wiki, has_projects, has_pages, cached_at
                ) VALUES (
                    :repo_id, :readme_content, :readme_format, :has_issues, :open_issues_count,
                    :has_wiki, :has_projects, :has_pages, :cached_at
                )
            """, data)
            await db.commit()

    # ==================== Utility Operations ====================

    async def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        cutoff_time = datetime.now() - timedelta(seconds=self.ttl_seconds)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as count FROM starred_repos WHERE cached_at < ?",
                (cutoff_time.isoformat(),),
            )
            row = await cursor.fetchone()
            count = row[0] if row else 0

            if count > 0:
                await db.execute(
                    "DELETE FROM starred_repos WHERE cached_at < ?",
                    (cutoff_time.isoformat(),),
                )
                await db.commit()

            return count

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Count repos
            cursor = await db.execute("SELECT COUNT(*) as count FROM starred_repos")
            row = await cursor.fetchone()
            repo_count = row["count"] if row else 0

            # Count folders
            cursor = await db.execute("SELECT COUNT(*) as count FROM virtual_folders")
            row = await cursor.fetchone()
            folder_count = row["count"] if row else 0

            # Count metadata entries
            cursor = await db.execute("SELECT COUNT(*) as count FROM repo_metadata")
            row = await cursor.fetchone()
            metadata_count = row["count"] if row else 0

            # Get oldest cached repo
            cursor = await db.execute("SELECT MIN(cached_at) as oldest FROM starred_repos")
            row = await cursor.fetchone()
            oldest_cache = row["oldest"] if row else None

            return {
                "repos_count": repo_count,
                "folders_count": folder_count,
                "metadata_count": metadata_count,
                "oldest_cache": oldest_cache,
                "db_path": str(self.db_path),
                "ttl_seconds": self.ttl_seconds,
            }
