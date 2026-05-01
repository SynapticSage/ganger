"""
Persistent cache for GitHub starred repos using SQLite.

Provides offline browsing, reduces API calls, and enables virtual folder persistence.
Shared state between TUI and MCP interfaces.

Modified: 2025-11-07
"""

import aiosqlite
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterable, AsyncIterator
from datetime import datetime, timedelta

from ganger.core.models import StarredRepo, VirtualFolder, RepoMetadata
from ganger.core.exceptions import CacheError


logger = logging.getLogger(__name__)


class PersistentCache:
    """
    SQLite-based persistent cache for starred repos and virtual folders.

    Schema:
    - starred_repos: Cached repository data
    - virtual_folders: User-created virtual folders
    - folder_repos: Many-to-many relationship (folders <-> repos)
    - repo_metadata: Extended metadata (README, issues, etc.)
    """

    # Schema version for migrations.
    # Bumping this triggers a v(N-1)->vN migration step on existing DBs the
    # next time initialize() runs. New steps must be idempotent and added to
    # the dispatcher in initialize().
    SCHEMA_VERSION = 3

    # Allowed VirtualFolder.kind values. "system" is internal-only; cache
    # validation rejects external attempts to create system folders.
    ALLOWED_FOLDER_KINDS = ("rule", "curated", "hybrid", "system")

    STARRED_SYNC_CURSOR_KEY = "starred_sync_cursor"
    STARRED_SYNC_CACHED_COUNT_KEY = "starred_sync_cached_count"
    STARRED_SYNC_TOTAL_COUNT_KEY = "starred_sync_total_count"
    STARRED_SYNC_COMPLETE_KEY = "starred_sync_complete"
    STARRED_SYNC_UPDATED_AT_KEY = "starred_sync_updated_at"

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

    @asynccontextmanager
    async def _connect(
        self,
        *,
        row_factory: Optional[type] = None,
    ) -> AsyncIterator[aiosqlite.Connection]:
        """Open a database connection with foreign keys enabled."""
        db = await aiosqlite.connect(self.db_path)
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            if row_factory is not None:
                db.row_factory = row_factory
            yield db
        finally:
            await db.close()

    @staticmethod
    async def _get_schema_version(db: aiosqlite.Connection) -> int:
        """Read the stored schema version."""
        cursor = await db.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        )
        row = await cursor.fetchone()
        if not row:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0

    @staticmethod
    async def _migrate_v1_to_v2(db: aiosqlite.Connection) -> None:
        """Drop the repo metadata foreign key so metadata can be cached independently."""
        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS repo_metadata_v2 (
                repo_id TEXT PRIMARY KEY,
                readme_content TEXT,
                readme_format TEXT DEFAULT 'markdown',
                has_issues BOOLEAN DEFAULT 1,
                open_issues_count INTEGER DEFAULT 0,
                has_wiki BOOLEAN DEFAULT 0,
                has_projects BOOLEAN DEFAULT 0,
                has_pages BOOLEAN DEFAULT 0,
                cached_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            INSERT OR REPLACE INTO repo_metadata_v2 (
                repo_id, readme_content, readme_format, has_issues, open_issues_count,
                has_wiki, has_projects, has_pages, cached_at
            )
            SELECT
                repo_id, readme_content, readme_format, has_issues, open_issues_count,
                has_wiki, has_projects, has_pages, cached_at
            FROM repo_metadata
        """)
        await db.execute("DROP TABLE repo_metadata")
        await db.execute("ALTER TABLE repo_metadata_v2 RENAME TO repo_metadata")
        await db.execute("PRAGMA foreign_keys = ON")
        logger.info("Migrated cache schema from v1 to v2")

    @staticmethod
    async def _safe_add_column(
        db: aiosqlite.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> bool:
        """Idempotently add a column to a table.

        Returns True if the column was added, False if it already existed.
        Reads PRAGMA table_info first instead of catching OperationalError
        on duplicate column — try/except would silently swallow other
        legitimate failures.
        """
        cursor = await db.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        existing = {row[1] for row in rows}
        if column in existing:
            return False
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return True

    @staticmethod
    async def _migrate_v2_to_v3(db: aiosqlite.Connection) -> None:
        """Add kind/position/is_stub columns and the user_tags table.

        Backfill kind per the richer enum decision (2026-04-28):
          - non-empty auto_tags AND any manual folder_repos link  -> 'hybrid'
          - non-empty auto_tags, no manual links                  -> 'rule'
          - id == 'all-stars' (or any other reserved system id)   -> 'system'
          - everything else (default already 'curated')           -> 'curated'

        All steps are idempotent so a partial migration can be re-run safely.
        """
        # 1. Folder kind discriminator. DEFAULT 'curated' covers fresh inserts;
        #    backfill rules below override for existing rows.
        await PersistentCache._safe_add_column(
            db, "virtual_folders", "kind", "TEXT NOT NULL DEFAULT 'curated'"
        )

        # 2. Hybrid: has auto_tags AND at least one manual folder_repos link.
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'hybrid'
             WHERE auto_tags IS NOT NULL
               AND auto_tags <> '[]'
               AND auto_tags <> ''
               AND id IN (SELECT DISTINCT folder_id FROM folder_repos WHERE is_manual = 1)
        """)

        # 3. Rule: has auto_tags, no manual links (and not already hybrid).
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'rule'
             WHERE auto_tags IS NOT NULL
               AND auto_tags <> '[]'
               AND auto_tags <> ''
               AND kind <> 'hybrid'
        """)

        # 4. System: synthetic folders. Currently just all-stars; the IN clause
        #    is here so future system ids only need to be added once.
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'system'
             WHERE id IN ('all-stars')
        """)

        # 5. Stable ordering for manual links in curated/hybrid folders.
        await PersistentCache._safe_add_column(
            db, "folder_repos", "position", "INTEGER"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_folder_repos_position "
            "ON folder_repos(folder_id, position)"
        )

        # 6. Stub flag: rows inserted from imports referencing repos the user
        #    hasn't actually starred. Sync upgrades these in place.
        await PersistentCache._safe_add_column(
            db, "starred_repos", "is_stub", "BOOLEAN DEFAULT 0"
        )

        # 7. User-defined tags (separate from GitHub-sourced topics).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_tags (
                repo_id  TEXT NOT NULL,
                tag      TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (repo_id, tag),
                FOREIGN KEY (repo_id) REFERENCES starred_repos(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_tags_repo ON user_tags(repo_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_tags_tag ON user_tags(tag)"
        )

        logger.info("Migrated cache schema from v2 to v3")

    @staticmethod
    async def _cleanup_orphaned_folder_links(db: aiosqlite.Connection) -> None:
        """Remove stale folder links left behind by older cache semantics."""
        await db.execute("""
            DELETE FROM folder_repos
            WHERE repo_id NOT IN (SELECT id FROM starred_repos)
               OR folder_id NOT IN (SELECT id FROM virtual_folders)
        """)

    @staticmethod
    async def _delete_repo_metadata(
        db: aiosqlite.Connection,
        repo_ids: Iterable[str],
    ) -> None:
        """Delete cached metadata for the specified repo ids."""
        repo_ids = tuple(repo_ids)
        if not repo_ids:
            return

        placeholders = ", ".join("?" for _ in repo_ids)
        await db.execute(
            f"DELETE FROM repo_metadata WHERE repo_id IN ({placeholders})",
            repo_ids,
        )

    async def initialize(self) -> None:
        """
        Initialize database schema.

        Creates all tables if they don't exist.
        """
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys = ON")

            # Table: starred_repos
            # NOTE: is_stub (added in v3) marks placeholder rows from imports
            # referencing repos the user hasn't actually starred yet. Sync
            # upgrades them in place via upsert_starred_repos.
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
                    accessed_at TEXT,
                    is_stub BOOLEAN DEFAULT 0
                )
            """)

            # Table: virtual_folders
            # NOTE: kind (added in v3) discriminates organization mode.
            # Allowed values defined by ALLOWED_FOLDER_KINDS.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS virtual_folders (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    auto_tags TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    kind TEXT NOT NULL DEFAULT 'curated'
                )
            """)

            # Table: folder_repos (many-to-many relationship)
            # NOTE: position (added in v3) provides stable ordering for
            # curated/hybrid folders. NULL for rule/system links.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS folder_repos (
                    folder_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    is_manual BOOLEAN DEFAULT 0,
                    added_at TEXT NOT NULL,
                    position INTEGER,
                    PRIMARY KEY (folder_id, repo_id),
                    FOREIGN KEY (folder_id) REFERENCES virtual_folders(id) ON DELETE CASCADE,
                    FOREIGN KEY (repo_id) REFERENCES starred_repos(id) ON DELETE CASCADE
                )
            """)

            # Table: user_tags (added in v3)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_tags (
                    repo_id  TEXT NOT NULL,
                    tag      TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (repo_id, tag),
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
                    cached_at TEXT NOT NULL
                )
            """)

            # Indexes for performance. Only v1/v2 indexes here; v3 indexes
            # depend on columns that older DBs gain via _migrate_v2_to_v3, so
            # they're created AFTER the migration loop below.
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
            # Migration dispatcher: walk current_version up to SCHEMA_VERSION,
            # one step at a time. v0 = unstamped (fresh DB or pre-versioning);
            # base CREATE above already populated everything, so it's a no-op
            # bump. Each migration must be idempotent so a retry after a
            # partial failure doesn't double-apply.
            current_version = await self._get_schema_version(db)
            while current_version < self.SCHEMA_VERSION:
                if current_version == 0:
                    pass  # base CREATE handled it
                elif current_version == 1:
                    await self._migrate_v1_to_v2(db)
                elif current_version == 2:
                    await self._migrate_v2_to_v3(db)
                else:
                    logger.warning(
                        "No migration handler for schema_version=%d; aborting",
                        current_version,
                    )
                    break
                current_version += 1

            # v3 indexes — guaranteed safe here because either the base CREATE
            # (fresh DB) or _migrate_v2_to_v3 (existing DB) has now produced
            # the position column and the user_tags table.
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_folder_repos_position "
                "ON folder_repos(folder_id, position)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_tags_repo ON user_tags(repo_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_tags_tag ON user_tags(tag)"
            )

            await self._cleanup_orphaned_folder_links(db)

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
        async with self._connect(row_factory=aiosqlite.Row) as db:
            # Check if cache is expired. Use the sync-completion timestamp as the
            # freshness marker — NOT MAX(cached_at) across rows. Incremental syncs
            # write rows with staggered timestamps, so any single old row would
            # otherwise expire the whole cache. If the metadata key is missing
            # (migrated DB or never-synced state) we trust the cache; the next
            # successful sync will populate the key.
            if not force_refresh:
                sync_updated_at = await self._get_metadata_value(
                    db,
                    self.STARRED_SYNC_UPDATED_AT_KEY,
                )
                if sync_updated_at:
                    newest_time = datetime.fromisoformat(sync_updated_at)
                    if datetime.now() - newest_time > timedelta(seconds=self.ttl_seconds):
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

    async def set_starred_repos(
        self,
        repos: List[StarredRepo],
        prune_missing: bool = True,
    ) -> None:
        """
        Cache starred repos.

        Args:
            repos: List of StarredRepo objects to cache
            prune_missing: Remove repos that are not present in this snapshot
        """
        await self.upsert_starred_repos(repos)
        if prune_missing:
            await self.prune_starred_repos(repo.id for repo in repos)
        await self.set_starred_sync_state(
            cached_count=len(repos),
            total_count=len(repos),
            cursor=None,
            complete=True,
        )

    async def upsert_starred_repos(self, repos: List[StarredRepo]) -> None:
        """Insert or update a batch of cached starred repos without pruning."""
        async with self._connect() as db:
            await self._upsert_starred_repos(db, repos)
            await db.commit()

    async def prune_starred_repos(self, keep_repo_ids: Iterable[str]) -> None:
        """Delete cached repos not present in the provided snapshot."""
        async with self._connect() as db:
            keep_repo_ids = tuple(dict.fromkeys(keep_repo_ids))

            cursor = await db.execute("SELECT id FROM starred_repos")
            existing_repo_ids = {row[0] for row in await cursor.fetchall()}
            stale_repo_ids = existing_repo_ids - set(keep_repo_ids)

            if stale_repo_ids:
                await self._delete_repo_metadata(db, stale_repo_ids)
                placeholders = ", ".join("?" for _ in stale_repo_ids)
                await db.execute(
                    f"DELETE FROM starred_repos WHERE id IN ({placeholders})",
                    tuple(stale_repo_ids),
                )
            elif not keep_repo_ids:
                await db.execute("DELETE FROM starred_repos")
                await db.execute("DELETE FROM repo_metadata")

            await db.commit()

    @staticmethod
    async def _upsert_starred_repos(
        db: aiosqlite.Connection,
        repos: List[StarredRepo],
    ) -> None:
        """Insert or update repo rows on an existing connection."""
        now = datetime.now().isoformat()
        rows = []
        for repo in repos:
            data = repo.to_dict()
            data["cached_at"] = now
            data["accessed_at"] = now
            rows.append(data)

        if not rows:
            return

        await db.executemany("""
            INSERT INTO starred_repos (
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
            ON CONFLICT(id) DO UPDATE SET
                full_name = excluded.full_name,
                name = excluded.name,
                owner = excluded.owner,
                description = excluded.description,
                stars_count = excluded.stars_count,
                forks_count = excluded.forks_count,
                watchers_count = excluded.watchers_count,
                language = excluded.language,
                topics = excluded.topics,
                is_archived = excluded.is_archived,
                is_private = excluded.is_private,
                is_fork = excluded.is_fork,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                pushed_at = excluded.pushed_at,
                starred_at = excluded.starred_at,
                url = excluded.url,
                clone_url = excluded.clone_url,
                homepage = excluded.homepage,
                default_branch = excluded.default_branch,
                license = excluded.license,
                cached_at = excluded.cached_at,
                accessed_at = excluded.accessed_at
        """, rows)

    @staticmethod
    async def _get_metadata_value(
        db: aiosqlite.Connection,
        key: str,
    ) -> Optional[str]:
        """Read a single metadata value using an existing connection."""
        cursor = await db.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if not row:
            return None
        return row[0]

    async def get_starred_sync_state(self) -> Dict[str, Any]:
        """Return resumable sync metadata for starred repo collection."""
        async with self._connect(row_factory=aiosqlite.Row) as db:
            cursor = await db.execute("""
                SELECT key, value FROM metadata
                WHERE key IN (?, ?, ?, ?, ?)
            """, (
                self.STARRED_SYNC_CURSOR_KEY,
                self.STARRED_SYNC_CACHED_COUNT_KEY,
                self.STARRED_SYNC_TOTAL_COUNT_KEY,
                self.STARRED_SYNC_COMPLETE_KEY,
                self.STARRED_SYNC_UPDATED_AT_KEY,
            ))
            rows = await cursor.fetchall()

        values = {row["key"]: row["value"] for row in rows}

        def _to_int(value: Optional[str]) -> Optional[int]:
            if value is None or value == "":
                return None
            return int(value)

        updated_at = values.get(self.STARRED_SYNC_UPDATED_AT_KEY)
        return {
            "cursor": values.get(self.STARRED_SYNC_CURSOR_KEY) or None,
            "cached_count": _to_int(values.get(self.STARRED_SYNC_CACHED_COUNT_KEY)) or 0,
            "total_count": _to_int(values.get(self.STARRED_SYNC_TOTAL_COUNT_KEY)),
            "complete": values.get(self.STARRED_SYNC_COMPLETE_KEY) == "1",
            "updated_at": datetime.fromisoformat(updated_at) if updated_at else None,
        }

    async def set_starred_sync_state(
        self,
        *,
        cached_count: int,
        total_count: Optional[int],
        cursor: Optional[str],
        complete: bool,
    ) -> None:
        """Persist resumable sync metadata for starred repo collection."""
        updated_at = datetime.now().isoformat()
        entries = (
            (self.STARRED_SYNC_CURSOR_KEY, cursor or ""),
            (self.STARRED_SYNC_CACHED_COUNT_KEY, str(cached_count)),
            (
                self.STARRED_SYNC_TOTAL_COUNT_KEY,
                "" if total_count is None else str(total_count),
            ),
            (self.STARRED_SYNC_COMPLETE_KEY, "1" if complete else "0"),
            (self.STARRED_SYNC_UPDATED_AT_KEY, updated_at),
        )

        async with self._connect() as db:
            await db.executemany(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                entries,
            )
            await db.commit()

    async def get_repo(self, repo_id: str) -> Optional[StarredRepo]:
        """
        Get a single repo by ID.

        Args:
            repo_id: Repository ID

        Returns:
            StarredRepo object, or None if not found
        """
        async with self._connect(row_factory=aiosqlite.Row) as db:

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
        async with self._connect() as db:
            await db.execute("DELETE FROM repo_metadata")
            await db.execute("DELETE FROM starred_repos")
            await db.executemany(
                "DELETE FROM metadata WHERE key = ?",
                (
                    (self.STARRED_SYNC_CURSOR_KEY,),
                    (self.STARRED_SYNC_CACHED_COUNT_KEY,),
                    (self.STARRED_SYNC_TOTAL_COUNT_KEY,),
                    (self.STARRED_SYNC_COMPLETE_KEY,),
                    (self.STARRED_SYNC_UPDATED_AT_KEY,),
                ),
            )
            await db.commit()

    # ==================== Virtual Folders Operations ====================

    async def get_virtual_folders(self) -> List[VirtualFolder]:
        """
        Get all virtual folders.

        Returns:
            List of VirtualFolder objects
        """
        async with self._connect(row_factory=aiosqlite.Row) as db:

            cursor = await db.execute(
                "SELECT * FROM virtual_folders ORDER BY created_at ASC"
            )
            rows = await cursor.fetchall()

            folders = []
            for row in rows:
                folder_dict = dict(row)

                if row["id"] == "all-stars":
                    count_cursor = await db.execute(
                        "SELECT COUNT(*) as count FROM starred_repos"
                    )
                else:
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
        async with self._connect() as db:
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
        async with self._connect() as db:
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
        async with self._connect(row_factory=aiosqlite.Row) as db:
            if folder_id == "all-stars":
                cursor = await db.execute("""
                    SELECT * FROM starred_repos
                    ORDER BY stars_count DESC
                """)
                rows = await cursor.fetchall()
                return [StarredRepo.from_dict(dict(row)) for row in rows]

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
        async with self._connect() as db:
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
        async with self._connect() as db:
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
        async with self._connect(row_factory=aiosqlite.Row) as db:

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
        async with self._connect() as db:
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

        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT id FROM starred_repos WHERE cached_at < ?",
                (cutoff_time.isoformat(),),
            )
            repo_ids = [row[0] for row in await cursor.fetchall()]
            count = len(repo_ids)

            if count > 0:
                await self._delete_repo_metadata(db, repo_ids)
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
        async with self._connect(row_factory=aiosqlite.Row) as db:

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
