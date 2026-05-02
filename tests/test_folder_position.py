"""Tests for folder_repos.position helpers.

Covers:
- set_folder_repo_position writes a single value.
- reorder_folder_repos applies positions 0..N-1 in order.
- Curated/hybrid folders respect the position in get_folder_repos output.
- Rule folders ignore folder_repos rows (and therefore position).
- Adding a new repo via add_repo_to_folder leaves position NULL until set;
  NULL-position rows sort after positioned ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from ganger.core.cache import PersistentCache
from ganger.core.models import StarredRepo, VirtualFolder


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> PersistentCache:
    db = PersistentCache(db_path=tmp_path / "pos.db")
    await db.initialize()
    return db


@pytest_asyncio.fixture
async def folder_with_repos(cache: PersistentCache) -> tuple[PersistentCache, str]:
    """A curated folder with three repos linked, no positions set."""
    repos = [
        StarredRepo(id="a", full_name="o/a", name="a", owner="o", stars_count=100),
        StarredRepo(id="b", full_name="o/b", name="b", owner="o", stars_count=300),
        StarredRepo(id="c", full_name="o/c", name="c", owner="o", stars_count=200),
    ]
    await cache.set_starred_repos(repos)
    f = VirtualFolder(id="cur", name="Cur", kind="curated")
    await cache.create_virtual_folder(f)
    for r in repos:
        await cache.add_repo_to_folder(r.id, "cur", is_manual=True)
    return cache, "cur"


@pytest.mark.asyncio
async def test_set_folder_repo_position_single(
    folder_with_repos: tuple[PersistentCache, str],
) -> None:
    cache, fid = folder_with_repos
    await cache.set_folder_repo_position(fid, "a", 0)
    repos = await cache.get_folder_repos(fid)
    # a is now position 0; b and c have NULL position so they sort after by stars
    assert repos[0].id == "a"
    # remaining two: b (300) before c (200) by stars DESC
    assert [r.id for r in repos[1:]] == ["b", "c"]


@pytest.mark.asyncio
async def test_reorder_folder_repos_sets_0_to_n_minus_1(
    folder_with_repos: tuple[PersistentCache, str],
) -> None:
    cache, fid = folder_with_repos
    await cache.reorder_folder_repos(fid, ["c", "a", "b"])
    repos = await cache.get_folder_repos(fid)
    assert [r.id for r in repos] == ["c", "a", "b"]


@pytest.mark.asyncio
async def test_reorder_folder_repos_partial_keeps_others_null(
    folder_with_repos: tuple[PersistentCache, str],
) -> None:
    """Reordering only a subset positions those rows; unmentioned rows
    keep their existing (NULL) position and sort after by stars."""
    cache, fid = folder_with_repos
    await cache.reorder_folder_repos(fid, ["c", "a"])
    repos = await cache.get_folder_repos(fid)
    # c then a (positions 0,1), then b (NULL position, sorts last)
    assert [r.id for r in repos] == ["c", "a", "b"]


@pytest.mark.asyncio
async def test_null_position_rows_sort_after_positioned(
    folder_with_repos: tuple[PersistentCache, str],
) -> None:
    cache, fid = folder_with_repos
    await cache.set_folder_repo_position(fid, "a", 5)
    repos = await cache.get_folder_repos(fid)
    # a is the only positioned row -> first; b/c by stars DESC after
    assert repos[0].id == "a"
    assert {r.id for r in repos[1:]} == {"b", "c"}


@pytest.mark.asyncio
async def test_rule_folder_ignores_position(
    cache: PersistentCache,
) -> None:
    """Rule folders dispatch by topic match, not by folder_repos rows.
    Position never enters the picture."""
    repos = [
        StarredRepo(
            id="x",
            full_name="o/x",
            name="x",
            owner="o",
            stars_count=10,
            topics=["python"],
        ),
        StarredRepo(
            id="y",
            full_name="o/y",
            name="y",
            owner="o",
            stars_count=200,
            topics=["python"],
        ),
    ]
    await cache.set_starred_repos(repos)
    f = VirtualFolder(
        id="py-rule", name="Py", auto_tags=["python"], kind="rule"
    )
    await cache.create_virtual_folder(f)
    # Even if we add folder_repos rows with positions, rule branch ignores them
    await cache.add_repo_to_folder("x", "py-rule", is_manual=True)
    await cache.set_folder_repo_position("py-rule", "x", 0)

    out = await cache.get_folder_repos("py-rule")
    # rule sorts by stars_count DESC, ignoring position entirely
    assert [r.id for r in out] == ["y", "x"]


@pytest.mark.asyncio
async def test_reorder_empty_list_is_noop(
    folder_with_repos: tuple[PersistentCache, str],
) -> None:
    cache, fid = folder_with_repos
    await cache.reorder_folder_repos(fid, [])
    # Nothing should have moved; default ordering by stars DESC for NULL pos
    repos = await cache.get_folder_repos(fid)
    assert {r.id for r in repos} == {"a", "b", "c"}
