"""Tests for the v3 kind-repair pass that runs every initialize().

The repair catches folders inserted by code paths that didn't (or don't)
set ``kind`` correctly: legacy v2 rows already migrated, OR — more
importantly — rows created by slice-1-aware code with default
``kind='curated'`` because slice 2A hadn't shipped yet.

Repair rules (idempotent):
- id == 'all-stars'                                 -> 'system'
- has auto_tags AND any manual link AND not system  -> 'hybrid'
- has auto_tags AND no manual links AND curated     -> 'rule'

Each UPDATE is gated by ``kind <> target`` so re-runs touch nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest

from ganger.core.cache import PersistentCache


async def _kind_of(db_path: Path, folder_id: str) -> str:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT kind FROM virtual_folders WHERE id = ?", (folder_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else ""


async def _seed_post_v3_curated(
    db_path: Path,
    folder_id: str,
    name: str,
    auto_tags: str = "[]",
) -> None:
    """Insert a virtual_folders row directly with kind='curated' even if it
    has auto_tags. Simulates what slice-1-aware code (which doesn't pass
    kind to create_virtual_folder) produces."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO virtual_folders
                (id, name, auto_tags, description, created_at, updated_at, kind)
            VALUES (?, ?, ?, '', ?, ?, 'curated')
            """,
            (folder_id, name, auto_tags, now, now),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_repair_all_stars_to_system(tmp_path: Path) -> None:
    """An all-stars row inserted with kind='curated' is repaired to 'system'."""
    db_path = tmp_path / "repair.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    # Bypass the auto-coercion in create_virtual_folder by writing directly:
    await _seed_post_v3_curated(db_path, "all-stars", "All Stars")
    assert await _kind_of(db_path, "all-stars") == "curated"

    # Re-initialize to trigger repair
    await cache.initialize()
    assert await _kind_of(db_path, "all-stars") == "system"


@pytest.mark.asyncio
async def test_repair_auto_tags_only_to_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "repair.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    await _seed_post_v3_curated(
        db_path, "py-folder", "Python", auto_tags='["python"]'
    )
    await cache.initialize()  # repair runs
    assert await _kind_of(db_path, "py-folder") == "rule"


@pytest.mark.asyncio
async def test_repair_auto_tags_with_manual_link_to_hybrid(tmp_path: Path) -> None:
    """Folder has auto_tags AND a manual link → hybrid."""
    db_path = tmp_path / "repair.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    # Seed a curated folder + a starred repo + a manual link
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """INSERT INTO virtual_folders
               (id, name, auto_tags, description, created_at, updated_at, kind)
               VALUES (?, ?, ?, '', ?, ?, 'curated')""",
            ("ml", "ML", '["ml"]', now, now),
        )
        await db.execute(
            """INSERT INTO starred_repos (id, full_name, name, owner, cached_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("repo-1", "octo/ml", "ml", "octo", now),
        )
        await db.execute(
            """INSERT INTO folder_repos (folder_id, repo_id, is_manual, added_at)
               VALUES (?, ?, 1, ?)""",
            ("ml", "repo-1", now),
        )
        await db.commit()

    await cache.initialize()  # repair
    assert await _kind_of(db_path, "ml") == "hybrid"


@pytest.mark.asyncio
async def test_repair_does_not_touch_correct_rows(tmp_path: Path) -> None:
    """Curated folders without auto_tags must remain curated; rule and
    hybrid folders must remain unchanged on a second init."""
    db_path = tmp_path / "repair.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        for fid, kind, tags in [
            ("plain", "curated", "[]"),
            ("py", "rule", '["python"]'),
            ("hyb", "hybrid", '["ml"]'),
        ]:
            await db.execute(
                """INSERT INTO virtual_folders
                   (id, name, auto_tags, description, created_at, updated_at, kind)
                   VALUES (?, ?, ?, '', ?, ?, ?)""",
                (fid, fid, tags, now, now, kind),
            )
        await db.commit()

    await cache.initialize()
    assert await _kind_of(db_path, "plain") == "curated"
    assert await _kind_of(db_path, "py") == "rule"
    assert await _kind_of(db_path, "hyb") == "hybrid"


@pytest.mark.asyncio
async def test_repair_is_idempotent(tmp_path: Path) -> None:
    """Running initialize() twice produces identical state."""
    db_path = tmp_path / "repair.db"
    cache = PersistentCache(db_path=db_path)
    await cache.initialize()

    await _seed_post_v3_curated(db_path, "all-stars", "All Stars")
    await _seed_post_v3_curated(db_path, "py", "Python", '["python"]')

    await cache.initialize()
    after_first = (
        await _kind_of(db_path, "all-stars"),
        await _kind_of(db_path, "py"),
    )
    await cache.initialize()
    after_second = (
        await _kind_of(db_path, "all-stars"),
        await _kind_of(db_path, "py"),
    )
    assert after_first == after_second == ("system", "rule")
