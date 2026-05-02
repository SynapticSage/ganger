"""Tests for folder kind validation in the cache and folder_manager.

Covers:
- Cache: ALLOWED_FOLDER_KINDS enforced; kind="system" rejected from external
  callers (no _internal=True); reserved id "all-stars" auto-coerces to system.
- FolderManager.create_folder: kind defaults inferred from auto_tags; explicit
  kind validation rejects mismatched combinations; system rejected outright.
- FolderManager.list_folders_by_kind filters correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from ganger.core.cache import PersistentCache
from ganger.core.exceptions import CacheError
from ganger.core.folder_manager import FolderManager
from ganger.core.models import VirtualFolder


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> PersistentCache:
    db = PersistentCache(db_path=tmp_path / "kind.db")
    await db.initialize()
    return db


@pytest_asyncio.fixture
async def manager(cache: PersistentCache) -> FolderManager:
    return FolderManager(cache)


# ---------- cache layer ----------


@pytest.mark.asyncio
async def test_cache_rejects_invalid_kind(cache: PersistentCache) -> None:
    with pytest.raises(CacheError):
        await cache.create_virtual_folder(
            VirtualFolder(id="bad", name="Bad", kind="bogus")
        )


@pytest.mark.asyncio
async def test_cache_rejects_system_kind_from_external(
    cache: PersistentCache,
) -> None:
    with pytest.raises(CacheError):
        await cache.create_virtual_folder(
            VirtualFolder(id="some-sys", name="SomeSys", kind="system")
        )


@pytest.mark.asyncio
async def test_cache_accepts_system_kind_when_internal(
    cache: PersistentCache,
) -> None:
    folder = await cache.create_virtual_folder(
        VirtualFolder(id="future-sys", name="FutureSys", kind="system"),
        _internal=True,
    )
    assert folder.kind == "system"


@pytest.mark.asyncio
async def test_all_stars_id_coerces_to_system(cache: PersistentCache) -> None:
    """The reserved id 'all-stars' is auto-coerced to kind='system'.

    This protects the data invariant even when callers (legacy code, tests)
    construct the folder without specifying kind.
    """
    folder = await cache.create_virtual_folder(
        VirtualFolder(id="all-stars", name="All Stars")  # default kind=curated
    )
    assert folder.kind == "system"
    fetched = await cache.get_virtual_folders()
    assert next(f for f in fetched if f.id == "all-stars").kind == "system"


# ---------- folder_manager layer ----------


@pytest.mark.asyncio
async def test_manager_default_kind_inferred_from_auto_tags(
    manager: FolderManager,
) -> None:
    rule_folder = await manager.create_folder(name="Py", auto_tags=["python"])
    assert rule_folder.kind == "rule"

    curated = await manager.create_folder(name="Faves")
    assert curated.kind == "curated"


@pytest.mark.asyncio
async def test_manager_curated_rejects_auto_tags(manager: FolderManager) -> None:
    with pytest.raises(CacheError):
        await manager.create_folder(
            name="Mixed", auto_tags=["python"], kind="curated"
        )


@pytest.mark.asyncio
async def test_manager_rule_requires_auto_tags(manager: FolderManager) -> None:
    with pytest.raises(CacheError):
        await manager.create_folder(name="EmptyRule", kind="rule")


@pytest.mark.asyncio
async def test_manager_hybrid_requires_auto_tags(manager: FolderManager) -> None:
    with pytest.raises(CacheError):
        await manager.create_folder(name="EmptyHybrid", kind="hybrid")


@pytest.mark.asyncio
async def test_manager_rejects_system(manager: FolderManager) -> None:
    with pytest.raises(CacheError):
        await manager.create_folder(name="SysAttempt", kind="system")


@pytest.mark.asyncio
async def test_list_folders_by_kind(manager: FolderManager) -> None:
    await manager.create_folder(name="Py", auto_tags=["python"])
    await manager.create_folder(name="JS", auto_tags=["javascript"], kind="hybrid")
    await manager.create_folder(name="Faves")

    rules = await manager.list_folders_by_kind("rule")
    hybrids = await manager.list_folders_by_kind("hybrid")
    curated = await manager.list_folders_by_kind("curated")

    assert {f.name for f in rules} == {"Py"}
    assert {f.name for f in hybrids} == {"JS"}
    assert {f.name for f in curated} == {"Faves"}
