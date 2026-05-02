"""Tests for kind-based dispatch in cache.get_folder_repos.

Each kind has different semantics for repo membership and ordering:
- rule    -> repos matching auto_tags via topics, ORDER BY stars DESC
            (folder_repos rows are ignored)
- curated -> repos in folder_repos only, ORDER BY position ASC NULLS LAST
            (auto_tags are ignored)
- hybrid  -> manual links first (by position), then auto-tag matches not
            already manually present; deduped by repo id
- system  -> dispatch by id; "all-stars" returns all repos; unknown raises

All branches must hydrate user_tags as List[str].
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from ganger.core.cache import PersistentCache
from ganger.core.exceptions import CacheError
from ganger.core.models import StarredRepo, VirtualFolder


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> PersistentCache:
    db = PersistentCache(db_path=tmp_path / "dispatch.db")
    await db.initialize()
    return db


@pytest_asyncio.fixture
async def populated(cache: PersistentCache) -> PersistentCache:
    """Cache with a mix of repos covering language/topic match cases."""
    repos = [
        StarredRepo(
            id="py-high",
            full_name="o/py-high",
            name="py-high",
            owner="o",
            stars_count=900,
            language="Python",
            topics=["python", "ml"],
        ),
        StarredRepo(
            id="py-low",
            full_name="o/py-low",
            name="py-low",
            owner="o",
            stars_count=10,
            language="Python",
            topics=["python"],
        ),
        StarredRepo(
            id="js-high",
            full_name="o/js-high",
            name="js-high",
            owner="o",
            stars_count=500,
            language="JavaScript",
            topics=["javascript"],
        ),
        StarredRepo(
            id="rust-high",
            full_name="o/rust-high",
            name="rust-high",
            owner="o",
            stars_count=300,
            language="Rust",
            topics=["rust"],
        ),
    ]
    await cache.set_starred_repos(repos)
    return cache


# ---------- rule ----------


@pytest.mark.asyncio
async def test_rule_matches_topics_and_orders_by_stars(
    populated: PersistentCache,
) -> None:
    rule_folder = VirtualFolder(
        id="py-rule",
        name="Python Rule",
        auto_tags=["python"],
        kind="rule",
    )
    await populated.create_virtual_folder(rule_folder)

    repos = await populated.get_folder_repos("py-rule")
    assert [r.id for r in repos] == ["py-high", "py-low"]


@pytest.mark.asyncio
async def test_rule_ignores_folder_repos_rows(populated: PersistentCache) -> None:
    """Even if someone slips a folder_repos row into a rule folder, the
    rule branch ignores them — only auto_tags matches show up."""
    rule_folder = VirtualFolder(
        id="rust-rule", name="Rust", auto_tags=["rust"], kind="rule"
    )
    await populated.create_virtual_folder(rule_folder)
    # Add a Python repo to folder_repos for the rust rule folder
    await populated.add_repo_to_folder("py-high", "rust-rule", is_manual=True)

    repos = await populated.get_folder_repos("rust-rule")
    assert [r.id for r in repos] == ["rust-high"]
    assert "py-high" not in {r.id for r in repos}


@pytest.mark.asyncio
async def test_rule_matches_language(populated: PersistentCache) -> None:
    """``language`` is also matched (parity with VirtualFolder.matches_repo)."""
    rule_folder = VirtualFolder(
        id="js-rule", name="JS", auto_tags=["javascript"], kind="rule"
    )
    await populated.create_virtual_folder(rule_folder)
    repos = await populated.get_folder_repos("js-rule")
    assert [r.id for r in repos] == ["js-high"]


# ---------- curated ----------


@pytest.mark.asyncio
async def test_curated_only_returns_folder_repos(
    populated: PersistentCache,
) -> None:
    """Curated folders never auto-match; only folder_repos rows count."""
    f = VirtualFolder(id="faves", name="Faves", kind="curated")
    await populated.create_virtual_folder(f)
    await populated.add_repo_to_folder("rust-high", "faves", is_manual=True)

    repos = await populated.get_folder_repos("faves")
    assert [r.id for r in repos] == ["rust-high"]


@pytest.mark.asyncio
async def test_curated_orders_by_position_then_stars(
    populated: PersistentCache,
) -> None:
    f = VirtualFolder(id="ranked", name="Ranked", kind="curated")
    await populated.create_virtual_folder(f)
    await populated.add_repo_to_folder("py-low", "ranked", is_manual=True)
    await populated.add_repo_to_folder("py-high", "ranked", is_manual=True)
    await populated.add_repo_to_folder("js-high", "ranked", is_manual=True)
    # Set explicit positions: js-high first, py-low second; py-high left NULL
    await populated.set_folder_repo_position("ranked", "js-high", 0)
    await populated.set_folder_repo_position("ranked", "py-low", 1)

    repos = await populated.get_folder_repos("ranked")
    # Positioned rows first, then NULL-position rows by stars DESC
    assert [r.id for r in repos] == ["js-high", "py-low", "py-high"]


# ---------- hybrid ----------


@pytest.mark.asyncio
async def test_hybrid_dedups_manual_and_auto(populated: PersistentCache) -> None:
    """Hybrid: a repo that is both manually linked AND auto-tag matched
    appears once, in the manual position."""
    f = VirtualFolder(
        id="py-hybrid",
        name="Py Hybrid",
        auto_tags=["python"],
        kind="hybrid",
    )
    await populated.create_virtual_folder(f)
    await populated.add_repo_to_folder("py-high", "py-hybrid", is_manual=True)
    await populated.set_folder_repo_position("py-hybrid", "py-high", 0)
    # Auto-match would also include py-low (topic=python)

    repos = await populated.get_folder_repos("py-hybrid")
    ids = [r.id for r in repos]
    assert ids[0] == "py-high"  # manual is first
    assert ids.count("py-high") == 1  # not duplicated
    assert "py-low" in ids  # auto-match still included


@pytest.mark.asyncio
async def test_hybrid_includes_manual_for_non_matching(
    populated: PersistentCache,
) -> None:
    """A manually-linked repo that does NOT match auto_tags still shows up."""
    f = VirtualFolder(
        id="py-hybrid-2",
        name="Py Hybrid 2",
        auto_tags=["python"],
        kind="hybrid",
    )
    await populated.create_virtual_folder(f)
    # Manually add a Rust repo despite the python rule
    await populated.add_repo_to_folder("rust-high", "py-hybrid-2", is_manual=True)
    await populated.set_folder_repo_position("py-hybrid-2", "rust-high", 0)

    repos = await populated.get_folder_repos("py-hybrid-2")
    ids = {r.id for r in repos}
    assert "rust-high" in ids  # manual respected
    assert "py-high" in ids and "py-low" in ids  # auto matches still there


# ---------- system ----------


@pytest.mark.asyncio
async def test_system_all_stars_returns_all_repos(
    populated: PersistentCache,
) -> None:
    f = VirtualFolder(id="all-stars", name="All Stars")  # auto-coerced to system
    await populated.create_virtual_folder(f)
    repos = await populated.get_folder_repos("all-stars")
    assert {r.id for r in repos} == {"py-high", "py-low", "js-high", "rust-high"}


@pytest.mark.asyncio
async def test_system_unknown_id_raises(populated: PersistentCache) -> None:
    """A system-kind folder with an id we don't recognize must raise — not
    silently return empty."""
    f = VirtualFolder(id="bogus-sys", name="BogusSys", kind="system")
    await populated.create_virtual_folder(f, _internal=True)
    with pytest.raises(CacheError):
        await populated.get_folder_repos("bogus-sys")


# ---------- user_tags hydration in dispatch ----------


@pytest.mark.asyncio
async def test_dispatch_hydrates_user_tags_in_all_kinds(
    populated: PersistentCache,
) -> None:
    """Every kind branch must populate StarredRepo.user_tags as a list."""
    await populated.add_user_tag("py-high", "fave")

    rule_f = VirtualFolder(
        id="py-rule", name="Py", auto_tags=["python"], kind="rule"
    )
    await populated.create_virtual_folder(rule_f)
    rule_repos = await populated.get_folder_repos("py-rule")
    assert next(r for r in rule_repos if r.id == "py-high").user_tags == ["fave"]
    assert all(isinstance(r.user_tags, list) for r in rule_repos)

    curated_f = VirtualFolder(id="cur", name="Cur", kind="curated")
    await populated.create_virtual_folder(curated_f)
    await populated.add_repo_to_folder("py-high", "cur", is_manual=True)
    cur_repos = await populated.get_folder_repos("cur")
    assert cur_repos[0].user_tags == ["fave"]

    hybrid_f = VirtualFolder(
        id="hyb", name="Hyb", auto_tags=["python"], kind="hybrid"
    )
    await populated.create_virtual_folder(hybrid_f)
    hyb_repos = await populated.get_folder_repos("hyb")
    assert next(r for r in hyb_repos if r.id == "py-high").user_tags == ["fave"]

    sys_f = VirtualFolder(id="all-stars", name="All Stars")
    await populated.create_virtual_folder(sys_f)
    sys_repos = await populated.get_folder_repos("all-stars")
    assert next(r for r in sys_repos if r.id == "py-high").user_tags == ["fave"]


# ---------- non-existent folder ----------


@pytest.mark.asyncio
async def test_unknown_folder_returns_empty_unless_all_stars(
    cache: PersistentCache,
) -> None:
    """For backward compat, querying ``all-stars`` without a virtual_folders
    row succeeds (treats it as the implicit system folder). Other unknown ids
    return [] silently — same as the pre-v3 behavior."""
    assert await cache.get_folder_repos("all-stars") == []
    assert await cache.get_folder_repos("nope") == []
