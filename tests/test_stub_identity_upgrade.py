"""Tests for stub identity-upgrade and stub-aware prune.

Stubs are placeholder rows inserted by the import path when a list
references a repo the user hasn't actually starred. They use the
sentinel id = full_name and is_stub=1. When the real GitHub id arrives
via upsert_starred_repos, the stub is upgraded:

  - Plain upgrade   : id replaced, is_stub cleared, folder_repos and
                      user_tags references reparented.
  - Collision merge : if a separate row with the inbound real id ALSO
                      exists, the real row wins; stub's children are
                      reparented (deduped via INSERT OR IGNORE) and the
                      stub is deleted.

prune_starred_repos must skip is_stub=1 rows in both the explicit
"stale" path and the "wipe everything" path (called with no keep ids).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from ganger.core.cache import PersistentCache
from ganger.core.exceptions import CacheError
from ganger.core.models import StarredRepo, VirtualFolder


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> PersistentCache:
    db = PersistentCache(db_path=tmp_path / "stub.db")
    await db.initialize()
    return db


# ---------- insert_stub helper ----------


@pytest.mark.asyncio
async def test_insert_stub_creates_stub_row(cache: PersistentCache) -> None:
    sid = await cache.insert_stub("octo/world")
    assert sid == "octo/world"
    repo = await cache.get_repo(sid)
    assert repo is not None
    assert repo.is_stub is True
    assert repo.full_name == "octo/world"
    assert repo.owner == "octo"
    assert repo.name == "world"


@pytest.mark.asyncio
async def test_insert_stub_is_idempotent(cache: PersistentCache) -> None:
    """Re-inserting the same stub doesn't error or duplicate."""
    await cache.insert_stub("octo/world")
    await cache.insert_stub("octo/world")  # second insert is a no-op
    repo = await cache.get_repo("octo/world")
    assert repo is not None and repo.is_stub is True


@pytest.mark.asyncio
async def test_insert_stub_rejects_empty_full_name(cache: PersistentCache) -> None:
    with pytest.raises(CacheError):
        await cache.insert_stub("")


# ---------- plain upgrade ----------


@pytest.mark.asyncio
async def test_upgrade_replaces_stub_id_and_clears_flag(
    cache: PersistentCache,
) -> None:
    await cache.insert_stub("octo/world")
    real = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo", stars_count=99
    )
    await cache.upsert_starred_repos([real])

    # Stub row gone; real row present.
    assert await cache.get_repo("octo/world") is None
    repo = await cache.get_repo("42")
    assert repo is not None
    assert repo.is_stub is False
    assert repo.stars_count == 99


@pytest.mark.asyncio
async def test_upgrade_reparents_folder_repos(cache: PersistentCache) -> None:
    """The stub's folder membership migrates atomically."""
    await cache.insert_stub("octo/world")
    folder = VirtualFolder(id="picks", name="Picks", kind="curated")
    await cache.create_virtual_folder(folder)
    await cache.add_repo_to_folder("octo/world", "picks", is_manual=True)

    real = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo"
    )
    await cache.upsert_starred_repos([real])

    repos = await cache.get_folder_repos("picks")
    assert [r.id for r in repos] == ["42"]


@pytest.mark.asyncio
async def test_upgrade_reparents_user_tags(cache: PersistentCache) -> None:
    await cache.insert_stub("octo/world")
    await cache.add_user_tag("octo/world", "to-read")
    await cache.add_user_tag("octo/world", "ml")

    real = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo"
    )
    await cache.upsert_starred_repos([real])

    assert sorted(await cache.get_user_tags("42")) == ["ml", "to-read"]
    # Old stub id no longer has any tags.
    assert await cache.get_user_tags("octo/world") == []


@pytest.mark.asyncio
async def test_upgrade_passes_foreign_key_check(
    tmp_path: Path, cache: PersistentCache
) -> None:
    """No orphan rows after an upgrade — verified via PRAGMA foreign_key_check."""
    await cache.insert_stub("octo/world")
    folder = VirtualFolder(id="picks", name="Picks", kind="curated")
    await cache.create_virtual_folder(folder)
    await cache.add_repo_to_folder("octo/world", "picks", is_manual=True)
    await cache.add_user_tag("octo/world", "alpha")

    real = StarredRepo(id="42", full_name="octo/world", name="world", owner="octo")
    await cache.upsert_starred_repos([real])

    async with aiosqlite.connect(cache.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute("PRAGMA foreign_key_check")
        violations = await cursor.fetchall()
    assert violations == []


# ---------- collision merge ----------


@pytest.mark.asyncio
async def test_collision_merge_on_repo_rename(
    cache: PersistentCache,
) -> None:
    """The collision case is reachable in the wild only via repo rename:

    1. User stars id=42 at full_name=octo/old. Real row exists.
    2. User imports a list referencing octo/world. Stub inserted with
       id=octo/world, full_name=octo/world. (No conflict — different
       full_name from the real row.)
    3. Owner renames the repo on GitHub: octo/old -> octo/world.
    4. Next sync emits id=42, full_name=octo/world.

    Now the cache has both a real row (id=42) AND a stub (id=octo/world)
    with the same full_name. The stub-upgrade path detects this and runs
    the merge: reparent stub's children to id=42, delete stub.
    """
    real = StarredRepo(
        id="42",
        full_name="octo/old",  # original name
        name="old",
        owner="octo",
        stars_count=500,
    )
    await cache.upsert_starred_repos([real])

    # Independent import inserts a stub with a different full_name.
    await cache.insert_stub("octo/world")
    folder = VirtualFolder(id="picks", name="Picks", kind="curated")
    await cache.create_virtual_folder(folder)
    await cache.add_repo_to_folder("octo/world", "picks", is_manual=True)
    await cache.add_user_tag("octo/world", "imported-tag")
    # Real row also has a tag (already starred long ago).
    await cache.add_user_tag("42", "personal-tag")

    # Now the rename: emit id=42 with the new full_name. This triggers
    # the merge because both rows now share the same full_name.
    renamed = StarredRepo(
        id="42",
        full_name="octo/world",
        name="world",
        owner="octo",
        stars_count=500,
    )
    await cache.upsert_starred_repos([renamed])

    # Stub gone, real row survives with full_name updated by upsert.
    assert await cache.get_repo("octo/world") is None or (
        (await cache.get_repo("octo/world")).id == "42"
    )
    survivor = await cache.get_repo("42")
    assert survivor is not None
    assert survivor.stars_count == 500
    assert survivor.full_name == "octo/world"

    # Folder membership reparented.
    repos = await cache.get_folder_repos("picks")
    assert [r.id for r in repos] == ["42"]

    # Tags merged.
    tags = sorted(await cache.get_user_tags("42"))
    assert tags == ["imported-tag", "personal-tag"]

    # No orphans.
    async with aiosqlite.connect(cache.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute("PRAGMA foreign_key_check")
        violations = await cursor.fetchall()
    assert violations == []


@pytest.mark.asyncio
async def test_collision_merge_dedups_overlapping_children(
    cache: PersistentCache,
) -> None:
    """If the stub and the real row are BOTH manually linked to the same
    folder, INSERT OR IGNORE must collapse them to one row, not error."""
    real = StarredRepo(
        id="42", full_name="octo/old", name="old", owner="octo"
    )
    await cache.upsert_starred_repos([real])

    # Stub for the (eventually-colliding) name.
    await cache.insert_stub("octo/world")

    folder = VirtualFolder(id="overlap", name="Overlap", kind="curated")
    await cache.create_virtual_folder(folder)
    # Both the real and the stub are in the same folder + same tag.
    await cache.add_repo_to_folder("42", "overlap", is_manual=True)
    await cache.add_repo_to_folder("octo/world", "overlap", is_manual=True)
    await cache.add_user_tag("42", "shared-tag")
    await cache.add_user_tag("octo/world", "shared-tag")

    # Trigger the rename → merge.
    renamed = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo"
    )
    await cache.upsert_starred_repos([renamed])

    # Single folder link for id=42, single user_tag.
    repos = await cache.get_folder_repos("overlap")
    assert [r.id for r in repos] == ["42"]
    assert await cache.get_user_tags("42") == ["shared-tag"]
    # No orphans.
    async with aiosqlite.connect(cache.db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute("PRAGMA foreign_key_check")
        violations = await cursor.fetchall()
    assert violations == []


# ---------- prune stub-awareness ----------


@pytest.mark.asyncio
async def test_prune_preserves_stubs(cache: PersistentCache) -> None:
    """A stub row survives prune even when its id is not in keep_ids."""
    await cache.insert_stub("octo/imported")
    real = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo"
    )
    await cache.upsert_starred_repos([real])

    await cache.prune_starred_repos(["42"])  # stub is NOT in keep set

    assert await cache.get_repo("42") is not None
    assert await cache.get_repo("octo/imported") is not None  # stub survived


@pytest.mark.asyncio
async def test_prune_empty_keep_preserves_stubs(cache: PersistentCache) -> None:
    """The "wipe everything" branch (empty keep_repo_ids) must still keep
    stubs — they predate the empty snapshot and represent imports waiting
    for sync."""
    await cache.insert_stub("octo/imported")
    real = StarredRepo(
        id="42", full_name="octo/world", name="world", owner="octo"
    )
    await cache.upsert_starred_repos([real])

    await cache.prune_starred_repos([])  # wipe-everything branch

    assert await cache.get_repo("42") is None  # non-stub gone
    assert await cache.get_repo("octo/imported") is not None  # stub kept
