"""Tests for user_tag CRUD methods on PersistentCache.

Covers:
- add/remove/get/set/list_all_tags happy paths
- Tag normalization: lowercase + strip + dedupe
- Empty/whitespace tags rejected
- set_user_tags is atomic (delete-then-insert in one transaction)
- Cascade delete on repo removal removes user_tags rows
- Hydration: get_starred_repos and get_repo populate StarredRepo.user_tags
- list_all_tags returns counts
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from ganger.core.cache import PersistentCache
from ganger.core.exceptions import CacheError
from ganger.core.models import StarredRepo


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> PersistentCache:
    db = PersistentCache(db_path=tmp_path / "tags.db")
    await db.initialize()
    return db


@pytest_asyncio.fixture
async def seeded_cache(cache: PersistentCache) -> PersistentCache:
    """A cache with two starred repos already inserted."""
    repos = [
        StarredRepo(
            id="1",
            full_name="octo/one",
            name="one",
            owner="octo",
            stars_count=10,
            topics=["python"],
        ),
        StarredRepo(
            id="2",
            full_name="octo/two",
            name="two",
            owner="octo",
            stars_count=5,
            topics=["javascript"],
        ),
    ]
    await cache.set_starred_repos(repos)
    return cache


@pytest.mark.asyncio
async def test_add_and_get_user_tag(seeded_cache: PersistentCache) -> None:
    await seeded_cache.add_user_tag("1", "favorite")
    tags = await seeded_cache.get_user_tags("1")
    assert tags == ["favorite"]


@pytest.mark.asyncio
async def test_add_user_tag_normalizes_case_and_whitespace(
    seeded_cache: PersistentCache,
) -> None:
    await seeded_cache.add_user_tag("1", "  Favorite  ")
    await seeded_cache.add_user_tag("1", "FAVORITE")  # dup after normalize
    tags = await seeded_cache.get_user_tags("1")
    assert tags == ["favorite"]


@pytest.mark.asyncio
async def test_add_user_tag_rejects_empty(seeded_cache: PersistentCache) -> None:
    with pytest.raises(CacheError):
        await seeded_cache.add_user_tag("1", "")
    with pytest.raises(CacheError):
        await seeded_cache.add_user_tag("1", "   ")


@pytest.mark.asyncio
async def test_remove_user_tag(seeded_cache: PersistentCache) -> None:
    await seeded_cache.add_user_tag("1", "ml")
    await seeded_cache.add_user_tag("1", "tools")
    await seeded_cache.remove_user_tag("1", "ml")
    assert await seeded_cache.get_user_tags("1") == ["tools"]


@pytest.mark.asyncio
async def test_remove_user_tag_is_idempotent(seeded_cache: PersistentCache) -> None:
    """Removing a non-existent tag is a no-op, not an error."""
    await seeded_cache.remove_user_tag("1", "ghost")  # nothing inserted
    assert await seeded_cache.get_user_tags("1") == []


@pytest.mark.asyncio
async def test_set_user_tags_replaces_atomically(
    seeded_cache: PersistentCache,
) -> None:
    await seeded_cache.add_user_tag("1", "old")
    await seeded_cache.set_user_tags("1", ["new1", "new2"])
    assert sorted(await seeded_cache.get_user_tags("1")) == ["new1", "new2"]


@pytest.mark.asyncio
async def test_set_user_tags_to_empty_clears_all(
    seeded_cache: PersistentCache,
) -> None:
    await seeded_cache.add_user_tag("1", "a")
    await seeded_cache.add_user_tag("1", "b")
    await seeded_cache.set_user_tags("1", [])
    assert await seeded_cache.get_user_tags("1") == []


@pytest.mark.asyncio
async def test_set_user_tags_dedupes_and_normalizes(
    seeded_cache: PersistentCache,
) -> None:
    await seeded_cache.set_user_tags("1", ["Python", "python", " PYTHON "])
    assert await seeded_cache.get_user_tags("1") == ["python"]


@pytest.mark.asyncio
async def test_set_user_tags_rejects_empty_in_list(
    seeded_cache: PersistentCache,
) -> None:
    with pytest.raises(CacheError):
        await seeded_cache.set_user_tags("1", ["good", ""])


@pytest.mark.asyncio
async def test_list_all_tags_returns_counts(seeded_cache: PersistentCache) -> None:
    await seeded_cache.add_user_tag("1", "shared")
    await seeded_cache.add_user_tag("2", "shared")
    await seeded_cache.add_user_tag("1", "unique")
    counts = await seeded_cache.list_all_tags()
    assert counts == {"shared": 2, "unique": 1}


@pytest.mark.asyncio
async def test_user_tags_cascade_on_repo_delete(
    seeded_cache: PersistentCache,
) -> None:
    """When a repo is pruned, its user_tags rows go with it (FK CASCADE)."""
    await seeded_cache.add_user_tag("1", "doomed")
    # Re-set starred_repos to a snapshot that excludes id=1, triggering prune
    await seeded_cache.set_starred_repos(
        [
            StarredRepo(
                id="2",
                full_name="octo/two",
                name="two",
                owner="octo",
            )
        ]
    )
    assert await seeded_cache.get_user_tags("1") == []
    counts = await seeded_cache.list_all_tags()
    assert "doomed" not in counts


@pytest.mark.asyncio
async def test_get_starred_repos_hydrates_user_tags(
    seeded_cache: PersistentCache,
) -> None:
    await seeded_cache.add_user_tag("1", "alpha")
    await seeded_cache.add_user_tag("1", "beta")
    repos = await seeded_cache.get_starred_repos(force_refresh=True)
    assert repos is not None
    by_id = {r.id: r for r in repos}
    assert by_id["1"].user_tags == ["alpha", "beta"]
    # repo without tags should hydrate to []
    assert by_id["2"].user_tags == []


@pytest.mark.asyncio
async def test_get_repo_hydrates_user_tags(seeded_cache: PersistentCache) -> None:
    await seeded_cache.add_user_tag("1", "single")
    repo = await seeded_cache.get_repo("1")
    assert repo is not None
    assert repo.user_tags == ["single"]
