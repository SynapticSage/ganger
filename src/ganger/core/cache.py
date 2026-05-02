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
    async def _repair_folder_kinds(db: aiosqlite.Connection) -> None:
        """Idempotent kind repair — runs on every initialize().

        Slice 1 of the v3 rollout shipped the schema migration but did not
        teach create_virtual_folder to set ``kind``, so any folder created by
        the v3-aware code between slice 1 and slice 2A landed at the
        ``DEFAULT 'curated'``. This pass catches those rows. It is safe to
        run on every startup because each UPDATE is gated by ``kind <> ...``
        — already-correct rows are not touched.
        """
        # all-stars (and any other reserved system id) -> system
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'system'
             WHERE id IN ('all-stars')
               AND kind <> 'system'
        """)

        # Has auto_tags AND any manual link -> hybrid
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'hybrid'
             WHERE auto_tags IS NOT NULL
               AND auto_tags <> '[]'
               AND auto_tags <> ''
               AND kind <> 'system'
               AND kind <> 'hybrid'
               AND id IN (SELECT DISTINCT folder_id FROM folder_repos WHERE is_manual = 1)
        """)

        # Has auto_tags, no manual links, not already rule/hybrid/system -> rule
        await db.execute("""
            UPDATE virtual_folders
               SET kind = 'rule'
             WHERE auto_tags IS NOT NULL
               AND auto_tags <> '[]'
               AND auto_tags <> ''
               AND kind = 'curated'
        """)

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

            # Idempotent kind repair — runs every startup. See docstring.
            await self._repair_folder_kinds(db)

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

            repos = [StarredRepo.from_dict(dict(row)) for row in rows]
            await self._hydrate_user_tags(db, repos)
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
        """Insert or update a batch of cached starred repos without pruning.

        Stub identity-upgrade: if any inbound repo has a ``full_name`` that
        already maps to an ``is_stub=1`` row with a different id, the stub is
        upgraded (id replaced, ``folder_repos`` and ``user_tags`` references
        reparented) before the regular upsert runs. This catches the case
        where a user imports a list referencing a repo they hadn't yet
        starred — the stub is created at import time and replaced here when
        the real GitHub id arrives.
        """
        async with self._connect() as db:
            await self._upgrade_stubs_for_batch(db, repos)
            await self._upsert_starred_repos(db, repos)
            await db.commit()

    async def prune_starred_repos(self, keep_repo_ids: Iterable[str]) -> None:
        """Delete cached repos not present in the provided snapshot.

        ``is_stub=1`` rows are always preserved — they represent imports
        referencing repos the user hasn't actually starred yet, and must
        survive prune until the next sync upgrades them in place. This is
        why the SELECT and the bulk-delete branch both filter on
        ``is_stub = 0``.
        """
        async with self._connect() as db:
            keep_repo_ids = tuple(dict.fromkeys(keep_repo_ids))

            # Only consider non-stub rows as candidates for deletion.
            cursor = await db.execute(
                "SELECT id FROM starred_repos WHERE is_stub = 0"
            )
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
                # Wipe non-stubs only. Stubs and their metadata survive.
                cursor = await db.execute(
                    "SELECT id FROM starred_repos WHERE is_stub = 0"
                )
                victims = [row[0] for row in await cursor.fetchall()]
                if victims:
                    await self._delete_repo_metadata(db, victims)
                    await db.execute(
                        "DELETE FROM starred_repos WHERE is_stub = 0"
                    )

            await db.commit()

    @staticmethod
    async def _upgrade_stubs_for_batch(
        db: aiosqlite.Connection,
        repos: List[StarredRepo],
    ) -> None:
        """For each inbound repo whose ``full_name`` matches a stub row with
        a different id, upgrade the stub in place.

        Two cases per inbound repo R with full_name F and id I_real:
          1. Stub S exists (id=I_stub, full_name=F, is_stub=1) and no row
             with id=I_real exists. **Identity upgrade:** rename S's id
             to I_real and clear is_stub. Reparent ``folder_repos`` and
             ``user_tags`` references in the same transaction.
          2. Stub S exists AND a separate real row R' with id=I_real
             also exists (e.g. user starred I_real long before the import,
             then someone imported a list referencing F). **Collision
             merge:** the real row wins. Reparent S's children to I_real
             with INSERT OR IGNORE (deduped on the natural PK), then
             DELETE S.

        FK semantics: ``folder_repos.repo_id`` and ``user_tags.repo_id``
        cascade on DELETE but have no ``ON UPDATE`` action. With
        ``foreign_keys=ON``, plain UPDATEs on the parent PK violate the
        constraint mid-transaction (children orphaned momentarily).
        ``PRAGMA defer_foreign_keys=ON`` defers FK checks until commit
        time, which makes the multi-row update legal. The pragma is
        transaction-scoped — committing resets it to OFF automatically.
        """
        if not repos:
            return

        # Find stubs by full_name in the inbound batch.
        full_names = [r.full_name for r in repos]
        placeholders = ",".join("?" for _ in full_names)
        cursor = await db.execute(
            f"""
            SELECT id, full_name FROM starred_repos
            WHERE full_name IN ({placeholders}) AND is_stub = 1
            """,
            full_names,
        )
        stubs = {row[1]: row[0] for row in await cursor.fetchall()}
        if not stubs:
            return

        # For each match, plan the operation: upgrade or collision-merge.
        # Build the work list outside the transaction to keep it short.
        plans = []  # (stub_id, new_id, mode) where mode in {"upgrade","merge"}
        for repo in repos:
            stub_id = stubs.get(repo.full_name)
            if stub_id is None or stub_id == repo.id:
                continue
            # Check whether the new id already exists as a separate row.
            cursor = await db.execute(
                "SELECT 1 FROM starred_repos WHERE id = ?", (repo.id,)
            )
            real_exists = (await cursor.fetchone()) is not None
            plans.append((stub_id, repo.id, "merge" if real_exists else "upgrade"))

        if not plans:
            return

        # Single transaction with deferred FK checks.
        await db.execute("BEGIN")
        try:
            await db.execute("PRAGMA defer_foreign_keys = ON")
            for stub_id, new_id, mode in plans:
                if mode == "upgrade":
                    # Parent first (PK rename), then children. Order doesn't
                    # matter under defer_foreign_keys; we pick parent-first
                    # for clarity.
                    await db.execute(
                        "UPDATE starred_repos SET id = ?, is_stub = 0 WHERE id = ?",
                        (new_id, stub_id),
                    )
                    await db.execute(
                        "UPDATE folder_repos SET repo_id = ? WHERE repo_id = ?",
                        (new_id, stub_id),
                    )
                    await db.execute(
                        "UPDATE user_tags SET repo_id = ? WHERE repo_id = ?",
                        (new_id, stub_id),
                    )
                else:  # mode == "merge"
                    # Reparent stub's children onto the existing real row.
                    # INSERT OR IGNORE handles the natural-PK dedup
                    # (folder_id, repo_id) and (repo_id, tag).
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO folder_repos
                            (folder_id, repo_id, is_manual, added_at, position)
                        SELECT folder_id, ?, is_manual, added_at, position
                          FROM folder_repos WHERE repo_id = ?
                        """,
                        (new_id, stub_id),
                    )
                    await db.execute(
                        "DELETE FROM folder_repos WHERE repo_id = ?", (stub_id,)
                    )
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO user_tags (repo_id, tag, added_at)
                        SELECT ?, tag, added_at
                          FROM user_tags WHERE repo_id = ?
                        """,
                        (new_id, stub_id),
                    )
                    await db.execute(
                        "DELETE FROM user_tags WHERE repo_id = ?", (stub_id,)
                    )
                    # Stub row is now childless; safe to delete.
                    await db.execute(
                        "DELETE FROM starred_repos WHERE id = ?", (stub_id,)
                    )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def insert_stub(
        self, full_name: str, name: Optional[str] = None, owner: Optional[str] = None
    ) -> str:
        """Insert a placeholder row for a repo referenced by an import but
        not yet present. The id is set to ``full_name`` so subsequent
        upserts (with the real GitHub id) can locate the stub via the
        ``full_name`` UNIQUE constraint and run the identity-upgrade path.

        Returns the stub id (which equals ``full_name``).
        """
        if not full_name:
            raise CacheError("insert_stub requires non-empty full_name")
        if "/" in full_name and (name is None or owner is None):
            o, n = full_name.split("/", 1)
            owner = owner or o
            name = name or n
        elif name is None or owner is None:
            raise CacheError(
                f"insert_stub({full_name!r}): cannot derive owner/name "
                "without a slash; pass them explicitly"
            )
        stub_id = full_name
        now = datetime.now().isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO starred_repos
                    (id, full_name, name, owner, cached_at, is_stub)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (stub_id, full_name, name, owner, now),
            )
            await db.commit()
        return stub_id

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

            repo = StarredRepo.from_dict(dict(row))
            await self._hydrate_user_tags(db, [repo])
            return repo

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
        self,
        folder: VirtualFolder,
        *,
        _internal: bool = False,
    ) -> VirtualFolder:
        """
        Create a new virtual folder.

        Args:
            folder: VirtualFolder object to create
            _internal: True only when this call originates from cache-internal
                code (the v3 migration / startup repair). Required to insert
                ``kind="system"``; external callers always use ``_internal=False``
                and may not create system folders.

        Returns:
            Created VirtualFolder object

        Raises:
            CacheError: If folder with same name exists, kind is not allowed,
                or kind="system" is requested by an external caller.
        """
        # Reserved IDs always land at kind="system". This catches legacy
        # callers that create the all-stars folder without specifying kind,
        # and ensures the data invariant (all-stars is system) holds even if
        # the caller forgets to set kind. The startup repair pass also fixes
        # this, but doing it at insert time avoids an inconsistent window.
        if folder.id in ("all-stars",):
            folder.kind = "system"
            _internal = True

        if folder.kind not in self.ALLOWED_FOLDER_KINDS:
            raise CacheError(
                f"Invalid folder kind '{folder.kind}'. "
                f"Allowed: {self.ALLOWED_FOLDER_KINDS}"
            )
        if folder.kind == "system" and not _internal:
            raise CacheError(
                "kind='system' folders are reserved for internal use "
                "(e.g. all-stars). External callers cannot create them."
            )

        async with self._connect() as db:
            data = folder.to_dict()

            now = datetime.now().isoformat()
            if data["created_at"] is None:
                data["created_at"] = now
            if data["updated_at"] is None:
                data["updated_at"] = now

            try:
                await db.execute("""
                    INSERT INTO virtual_folders
                        (id, name, auto_tags, description, created_at, updated_at, kind)
                    VALUES
                        (:id, :name, :auto_tags, :description, :created_at, :updated_at, :kind)
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
        Get all repos in a virtual folder, dispatching on folder kind.

        - ``rule``    — repos matching ``auto_tags`` via ``topics``, ordered by
          ``stars_count DESC``. ``folder_repos`` rows are ignored.
        - ``curated`` — repos in ``folder_repos`` only, ordered by
          ``position ASC NULLS LAST``, then ``stars_count DESC``.
          ``auto_tags`` is ignored.
        - ``hybrid``  — manually-linked repos first (ordered by ``position``,
          then stars), followed by auto-tag matches not already manually
          present. Dedup by repo id.
        - ``system``  — dispatch by id. ``all-stars`` -> all starred repos.
          Unknown system ids raise ``CacheError``.

        All branches hydrate ``user_tags`` via a single keyed query.
        """
        async with self._connect(row_factory=aiosqlite.Row) as db:
            cursor = await db.execute(
                "SELECT id, auto_tags, kind FROM virtual_folders WHERE id = ?",
                (folder_id,),
            )
            row = await cursor.fetchone()

            # Backward-compat: if the folder doesn't exist as a row but the
            # caller passed "all-stars", treat it as the implicit system folder.
            # This preserves the old behavior where "all-stars" worked even
            # without a row in virtual_folders.
            if row is None:
                if folder_id == "all-stars":
                    repos = await self._get_all_stars(db)
                    await self._hydrate_user_tags(db, repos)
                    return repos
                return []

            kind = row["kind"]
            auto_tags_raw = row["auto_tags"]

            if kind == "system":
                if folder_id == "all-stars":
                    repos = await self._get_all_stars(db)
                else:
                    raise CacheError(f"Unknown system folder id: {folder_id!r}")
            elif kind == "rule":
                repos = await self._get_repos_matching_auto_tags(db, auto_tags_raw)
            elif kind == "curated":
                repos = await self._get_curated_folder_repos(db, folder_id)
            elif kind == "hybrid":
                repos = await self._get_hybrid_folder_repos(
                    db, folder_id, auto_tags_raw
                )
            else:
                # Defensive: should be impossible given the migration's enum
                # restriction, but worth a clear error rather than silent empty.
                raise CacheError(f"Unknown folder kind: {kind!r}")

            await self._hydrate_user_tags(db, repos)
            return repos

    @staticmethod
    async def _get_all_stars(db: aiosqlite.Connection) -> List[StarredRepo]:
        """Return all starred repos ordered by stars_count DESC."""
        cursor = await db.execute(
            "SELECT * FROM starred_repos ORDER BY stars_count DESC"
        )
        rows = await cursor.fetchall()
        return [StarredRepo.from_dict(dict(row)) for row in rows]

    @staticmethod
    async def _get_repos_matching_auto_tags(
        db: aiosqlite.Connection, auto_tags_raw: Optional[str]
    ) -> List[StarredRepo]:
        """Return repos whose ``topics`` intersect with the folder's auto_tags.

        Topics are stored as JSON-encoded lists in ``starred_repos.topics``;
        we use SQLite's ``LIKE`` against the JSON fragment ``"<tag>"`` (with
        quotes) so we don't false-match on substrings of other tags.
        Language is also matched as a special case for parity with
        ``VirtualFolder.matches_repo``.
        """
        import json

        if not auto_tags_raw:
            return []
        try:
            tags = json.loads(auto_tags_raw)
        except (TypeError, ValueError):
            return []
        if not tags:
            return []

        # Build dynamic OR query — one clause per tag for either topics
        # JSON-substring match or language equality.
        topic_clauses = []
        params: List[Any] = []
        for tag in tags:
            tag_lower = tag.lower()
            # JSON list serialization always wraps strings in double quotes,
            # so ``"<tag>"`` is a safe substring marker that won't false-match.
            topic_clauses.append("LOWER(topics) LIKE ?")
            params.append(f'%"{tag_lower}"%')
            topic_clauses.append("LOWER(language) = ?")
            params.append(tag_lower)

        where = " OR ".join(topic_clauses)
        cursor = await db.execute(
            f"SELECT * FROM starred_repos WHERE {where} ORDER BY stars_count DESC",
            params,
        )
        rows = await cursor.fetchall()
        return [StarredRepo.from_dict(dict(row)) for row in rows]

    @staticmethod
    async def _get_curated_folder_repos(
        db: aiosqlite.Connection, folder_id: str
    ) -> List[StarredRepo]:
        """Repos in folder_repos for this folder, ordered by position then stars."""
        cursor = await db.execute(
            """
            SELECT r.* FROM starred_repos r
            JOIN folder_repos fr ON r.id = fr.repo_id
            WHERE fr.folder_id = ?
            ORDER BY
                CASE WHEN fr.position IS NULL THEN 1 ELSE 0 END,
                fr.position ASC,
                r.stars_count DESC
            """,
            (folder_id,),
        )
        rows = await cursor.fetchall()
        return [StarredRepo.from_dict(dict(row)) for row in rows]

    @classmethod
    async def _get_hybrid_folder_repos(
        cls,
        db: aiosqlite.Connection,
        folder_id: str,
        auto_tags_raw: Optional[str],
    ) -> List[StarredRepo]:
        """Manual-linked first (by position), then auto-tag matches not already manual.

        Dedup by repo id — a repo that is BOTH manually linked AND
        auto-tag-matched appears once, with the manual ordering preserved.
        """
        manual = await cls._get_curated_folder_repos(db, folder_id)
        manual_ids = {r.id for r in manual}
        auto = await cls._get_repos_matching_auto_tags(db, auto_tags_raw)
        # Filter out duplicates already covered by manual; preserve auto's
        # stars-DESC ordering for the remainder.
        deduped_auto = [r for r in auto if r.id not in manual_ids]
        return manual + deduped_auto

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

    async def set_folder_repo_position(
        self, folder_id: str, repo_id: str, position: int
    ) -> None:
        """Set the position for a single (folder, repo) link.

        Caller is responsible for ensuring the folder kind permits ordering
        (curated/hybrid). Cache layer does not validate kind here because
        bulk reorder operations would otherwise need to re-fetch the folder
        on every call; the service layer (folder_manager.reorder_folder_repos)
        is the authoritative gate.
        """
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE folder_repos SET position = ?
                WHERE folder_id = ? AND repo_id = ?
                """,
                (position, folder_id, repo_id),
            )
            await db.commit()

    async def reorder_folder_repos(
        self, folder_id: str, ordered_repo_ids: List[str]
    ) -> None:
        """Assign positions 0..N-1 to the given repo_ids in order.

        Repos not present in the list keep their existing position. This is
        intentional: the TUI usually only touches the visible window, not the
        full folder. Use ``set_folder_repo_position`` for individual swaps.
        """
        rows = [(idx, folder_id, repo_id) for idx, repo_id in enumerate(ordered_repo_ids)]
        if not rows:
            return
        async with self._connect() as db:
            await db.executemany(
                """
                UPDATE folder_repos SET position = ?
                WHERE folder_id = ? AND repo_id = ?
                """,
                rows,
            )
            await db.commit()

    # ==================== User Tags Operations ====================

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        """Lowercase + strip a single tag. Raises CacheError if empty after.

        Tag identity is case-insensitive: ``Python`` and ``python`` are the
        same tag. The (repo_id, tag) PRIMARY KEY enforces this once we
        normalize at write time.
        """
        if not isinstance(tag, str):
            raise CacheError(f"Tag must be a string, got {type(tag).__name__}")
        normalized = tag.strip().lower()
        if not normalized:
            raise CacheError("Tag cannot be empty or whitespace-only")
        return normalized

    async def add_user_tag(self, repo_id: str, tag: str) -> None:
        """Add a single tag to a repo. Idempotent on (repo_id, tag) PK."""
        normalized = self._normalize_tag(tag)
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO user_tags (repo_id, tag, added_at)
                VALUES (?, ?, ?)
                """,
                (repo_id, normalized, datetime.now().isoformat()),
            )
            await db.commit()

    async def remove_user_tag(self, repo_id: str, tag: str) -> None:
        """Remove a single tag from a repo. No-op if not present."""
        normalized = self._normalize_tag(tag)
        async with self._connect() as db:
            await db.execute(
                "DELETE FROM user_tags WHERE repo_id = ? AND tag = ?",
                (repo_id, normalized),
            )
            await db.commit()

    async def set_user_tags(self, repo_id: str, tags: List[str]) -> None:
        """Replace all tags on a repo atomically.

        Empty/whitespace tags are rejected; duplicates (after normalization)
        collapse silently.
        """
        normalized = []
        seen = set()
        for tag in tags:
            n = self._normalize_tag(tag)
            if n not in seen:
                normalized.append(n)
                seen.add(n)

        now = datetime.now().isoformat()
        rows = [(repo_id, tag, now) for tag in normalized]

        async with self._connect() as db:
            await db.execute("BEGIN")
            try:
                await db.execute(
                    "DELETE FROM user_tags WHERE repo_id = ?", (repo_id,)
                )
                if rows:
                    await db.executemany(
                        "INSERT INTO user_tags (repo_id, tag, added_at) VALUES (?, ?, ?)",
                        rows,
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def get_user_tags(self, repo_id: str) -> List[str]:
        """Return tags for a single repo, sorted alphabetically."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT tag FROM user_tags WHERE repo_id = ? ORDER BY tag ASC",
                (repo_id,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def list_all_tags(self) -> Dict[str, int]:
        """Return tag -> usage count, sorted by tag name in the dict order."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT tag, COUNT(*) FROM user_tags GROUP BY tag ORDER BY tag ASC"
            )
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    async def _hydrate_user_tags(
        self,
        db: aiosqlite.Connection,
        repos: List[StarredRepo],
    ) -> None:
        """Bulk-fetch user_tags for the given repos and assign in place.

        Uses one keyed query keyed by repo_id (not GROUP_CONCAT — empty or
        forbidden delimiters are too easy to get wrong; one extra round-trip
        for the rare case of a populated user_tags table is fine).
        """
        if not repos:
            return
        ids = [r.id for r in repos]
        placeholders = ",".join("?" for _ in ids)
        cursor = await db.execute(
            f"SELECT repo_id, tag FROM user_tags WHERE repo_id IN ({placeholders}) ORDER BY tag ASC",
            ids,
        )
        rows = await cursor.fetchall()
        bucket: Dict[str, List[str]] = {repo_id: [] for repo_id in ids}
        for repo_id, tag in rows:
            bucket[repo_id].append(tag)
        for repo in repos:
            repo.user_tags = bucket.get(repo.id, [])

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
