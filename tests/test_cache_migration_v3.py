"""Tests for the v2->v3 cache schema migration.

Covers:
- Fresh DB lands at v3 directly via base CREATE definitions.
- v2 DB upgrades to v3 with correct kind backfill across all four kinds
  (rule / curated / hybrid / system).
- v1 DB walks through both v1->v2 and v2->v3 in a single initialize().
- Re-running initialize() on a v3 DB is a no-op (idempotent).
- _safe_add_column adds the column if missing and is a no-op if present.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite
import pytest

from ganger.core.cache import PersistentCache


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cursor.fetchall()}


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return (await cursor.fetchone()) is not None


async def _schema_version(db_path: Path) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


@pytest.mark.asyncio
async def test_fresh_db_lands_at_v3(tmp_path: Path) -> None:
    """A brand-new DB never enters the migration path; base CREATE must
    already include kind/position/is_stub/user_tags."""
    db_path = tmp_path / "fresh.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    assert await _schema_version(db_path) == 3
    async with aiosqlite.connect(db_path) as db:
        assert "kind" in await _columns(db, "virtual_folders")
        assert "position" in await _columns(db, "folder_repos")
        assert "is_stub" in await _columns(db, "starred_repos")
        assert await _table_exists(db, "user_tags")


async def _build_v2_db(db_path: Path) -> None:
    """Create a hand-rolled v2 DB without any v3 columns/tables."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE starred_repos (
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
        await db.execute("""
            CREATE TABLE virtual_folders (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                auto_tags TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE folder_repos (
                folder_id TEXT NOT NULL,
                repo_id TEXT NOT NULL,
                is_manual BOOLEAN DEFAULT 0,
                added_at TEXT NOT NULL,
                PRIMARY KEY (folder_id, repo_id),
                FOREIGN KEY (folder_id) REFERENCES virtual_folders(id) ON DELETE CASCADE,
                FOREIGN KEY (repo_id) REFERENCES starred_repos(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE repo_metadata (
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
        await db.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)"
        )
        await db.execute(
            "INSERT INTO metadata (key, value) VALUES ('schema_version', '2')"
        )
        await db.commit()


async def _seed_repo(db: aiosqlite.Connection, repo_id: str, full_name: str) -> None:
    now = datetime.now().isoformat()
    await db.execute(
        """
        INSERT INTO starred_repos
            (id, full_name, name, owner, cached_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (repo_id, full_name, full_name.split("/")[-1], full_name.split("/")[0], now),
    )


async def _seed_folder(
    db: aiosqlite.Connection, folder_id: str, name: str, auto_tags: list[str]
) -> None:
    now = datetime.now().isoformat()
    await db.execute(
        "INSERT INTO virtual_folders (id, name, auto_tags, created_at) VALUES (?,?,?,?)",
        (folder_id, name, json.dumps(auto_tags), now),
    )


async def _link(
    db: aiosqlite.Connection, folder_id: str, repo_id: str, is_manual: bool
) -> None:
    now = datetime.now().isoformat()
    await db.execute(
        "INSERT INTO folder_repos (folder_id, repo_id, is_manual, added_at) VALUES (?,?,?,?)",
        (folder_id, repo_id, 1 if is_manual else 0, now),
    )


@pytest.mark.asyncio
async def test_v2_to_v3_kind_backfill(tmp_path: Path) -> None:
    """Migration must backfill kind across all four cases:
    - non-empty auto_tags + manual link    -> 'hybrid'
    - non-empty auto_tags + no manual link -> 'rule'
    - id == 'all-stars'                    -> 'system'
    - empty/null auto_tags                 -> 'curated' (column DEFAULT)
    """
    db_path = tmp_path / "v2.db"
    await _build_v2_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await _seed_repo(db, "1", "octo/hello")
        await _seed_repo(db, "2", "octo/world")

        # Case 1: rule (auto_tags, no manual links)
        await _seed_folder(db, "f-rule", "Python", ["python"])
        await _link(db, "f-rule", "1", is_manual=False)

        # Case 2: hybrid (auto_tags + at least one manual link)
        await _seed_folder(db, "f-hybrid", "AI/ML", ["ml"])
        await _link(db, "f-hybrid", "1", is_manual=False)
        await _link(db, "f-hybrid", "2", is_manual=True)

        # Case 3: curated (no auto_tags)
        await _seed_folder(db, "f-curated", "Favorites", [])

        # Case 4: system (the all-stars special id)
        await _seed_folder(db, "all-stars", "All Stars", [])

        await db.commit()

    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    assert await _schema_version(db_path) == 3
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT id, kind FROM virtual_folders ORDER BY id")
        rows = {row[0]: row[1] for row in await cursor.fetchall()}
    assert rows == {
        "all-stars": "system",
        "f-curated": "curated",
        "f-hybrid": "hybrid",
        "f-rule": "rule",
    }


@pytest.mark.asyncio
async def test_v2_to_v3_adds_columns_and_user_tags(tmp_path: Path) -> None:
    db_path = tmp_path / "v2.db"
    await _build_v2_db(db_path)
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    async with aiosqlite.connect(db_path) as db:
        assert "kind" in await _columns(db, "virtual_folders")
        assert "position" in await _columns(db, "folder_repos")
        assert "is_stub" in await _columns(db, "starred_repos")
        assert await _table_exists(db, "user_tags")


@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    """Running initialize() twice on the same DB must not error or
    duplicate columns. This is what catches non-idempotent ALTERs."""
    db_path = tmp_path / "v2.db"
    await _build_v2_db(db_path)
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()
    await cache.initialize()  # second run must be a no-op

    assert await _schema_version(db_path) == 3
    async with aiosqlite.connect(db_path) as db:
        # Column counts should be exactly what v3 specifies.
        cols = await _columns(db, "virtual_folders")
        assert "kind" in cols
        # SQLite would not allow duplicate columns, but PRAGMA table_info
        # returns one row per column — so the test is implicit in the fact
        # that the second initialize() didn't raise.


@pytest.mark.asyncio
async def test_v1_db_walks_through_both_migrations(tmp_path: Path) -> None:
    """A v1 DB must run v1->v2 (drops repo_metadata FK) then v2->v3."""
    db_path = tmp_path / "v1.db"
    await _build_v2_db(db_path)
    # Downgrade: rewrite repo_metadata with the old FK and stamp v1.
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute("DROP TABLE repo_metadata")
        await db.execute("""
            CREATE TABLE repo_metadata (
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
        await db.execute(
            "UPDATE metadata SET value='1' WHERE key='schema_version'"
        )
        await db.commit()

    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    assert await _schema_version(db_path) == 3
    async with aiosqlite.connect(db_path) as db:
        assert "kind" in await _columns(db, "virtual_folders")
        assert await _table_exists(db, "user_tags")


@pytest.mark.asyncio
async def test_safe_add_column_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "safe.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute("CREATE TABLE t (id INTEGER)")
        added_first = await PersistentCache._safe_add_column(
            db, "t", "extra", "TEXT"
        )
        added_second = await PersistentCache._safe_add_column(
            db, "t", "extra", "TEXT"
        )
    assert added_first is True
    assert added_second is False
