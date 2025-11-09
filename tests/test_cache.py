"""
Tests for persistent cache.

Modified: 2025-11-07
"""

import pytest
import pytest_asyncio
from pathlib import Path
from datetime import datetime, timezone
from ganger.core.cache import PersistentCache
from ganger.core.models import StarredRepo, VirtualFolder, RepoMetadata
from ganger.core.exceptions import CacheError


@pytest_asyncio.fixture
async def cache(tmp_path):
    """Create a temporary cache for testing."""
    db_path = tmp_path / "test.db"
    cache = PersistentCache(db_path=db_path, ttl_seconds=3600)
    await cache.initialize()
    return cache


@pytest.fixture
def sample_repos():
    """Create sample repos for testing."""
    return [
        StarredRepo(
            id="1",
            full_name="octocat/Hello-World",
            name="Hello-World",
            owner="octocat",
            description="Test repo 1",
            stars_count=1000,
            language="Python",
            topics=["python", "test"],
        ),
        StarredRepo(
            id="2",
            full_name="test/repo2",
            name="repo2",
            owner="test",
            description="Test repo 2",
            stars_count=500,
            language="JavaScript",
            topics=["javascript", "web"],
        ),
    ]


@pytest.fixture
def sample_folder():
    """Create a sample virtual folder."""
    return VirtualFolder(
        id="folder1",
        name="Python Projects",
        auto_tags=["python"],
        description="Python-related repos",
        created_at=datetime.now(timezone.utc),
    )


class TestCacheInitialization:
    """Test cache initialization."""

    @pytest.mark.asyncio
    async def test_init_creates_tables(self, tmp_path):
        """Test that initialization creates all tables."""
        db_path = tmp_path / "test.db"
        cache = PersistentCache(db_path=db_path)
        await cache.initialize()

        assert db_path.exists()

        # Verify tables exist
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in await cursor.fetchall()]

            assert "starred_repos" in tables
            assert "virtual_folders" in tables
            assert "folder_repos" in tables
            assert "repo_metadata" in tables
            assert "metadata" in tables


class TestStarredReposOperations:
    """Test starred repos operations."""

    @pytest.mark.asyncio
    async def test_set_and_get_starred_repos(self, cache, sample_repos):
        """Test caching and retrieving starred repos."""
        await cache.set_starred_repos(sample_repos)

        repos = await cache.get_starred_repos()

        assert repos is not None
        assert len(repos) == 2
        assert repos[0].full_name == "octocat/Hello-World"
        assert repos[1].full_name == "test/repo2"

    @pytest.mark.asyncio
    async def test_get_starred_repos_empty(self, cache):
        """Test getting repos when cache is empty."""
        repos = await cache.get_starred_repos()
        assert repos is None

    @pytest.mark.asyncio
    async def test_get_single_repo(self, cache, sample_repos):
        """Test getting a single repo by ID."""
        await cache.set_starred_repos(sample_repos)

        repo = await cache.get_repo("1")

        assert repo is not None
        assert repo.full_name == "octocat/Hello-World"
        assert repo.language == "Python"

    @pytest.mark.asyncio
    async def test_get_repo_not_found(self, cache):
        """Test getting a non-existent repo."""
        repo = await cache.get_repo("nonexistent")
        assert repo is None

    @pytest.mark.asyncio
    async def test_invalidate_repos(self, cache, sample_repos):
        """Test invalidating repos cache."""
        await cache.set_starred_repos(sample_repos)

        repos = await cache.get_starred_repos()
        assert repos is not None

        await cache.invalidate_repos()

        repos = await cache.get_starred_repos()
        assert repos is None


class TestVirtualFoldersOperations:
    """Test virtual folders operations."""

    @pytest.mark.asyncio
    async def test_create_virtual_folder(self, cache, sample_folder):
        """Test creating a virtual folder."""
        created = await cache.create_virtual_folder(sample_folder)

        assert created.id == sample_folder.id
        assert created.name == sample_folder.name

        folders = await cache.get_virtual_folders()
        assert len(folders) == 1
        assert folders[0].name == "Python Projects"

    @pytest.mark.asyncio
    async def test_create_duplicate_folder(self, cache, sample_folder):
        """Test creating a folder with duplicate name."""
        await cache.create_virtual_folder(sample_folder)

        # Try to create another with same name
        duplicate = VirtualFolder(
            id="folder2",
            name="Python Projects",  # Same name
            auto_tags=["py"],
            created_at=datetime.now(timezone.utc),
        )

        with pytest.raises(CacheError, match="already exists"):
            await cache.create_virtual_folder(duplicate)

    @pytest.mark.asyncio
    async def test_delete_virtual_folder(self, cache, sample_folder):
        """Test deleting a virtual folder."""
        await cache.create_virtual_folder(sample_folder)

        folders = await cache.get_virtual_folders()
        assert len(folders) == 1

        await cache.delete_virtual_folder(sample_folder.id)

        folders = await cache.get_virtual_folders()
        assert len(folders) == 0

    @pytest.mark.asyncio
    async def test_add_repo_to_folder(self, cache, sample_repos, sample_folder):
        """Test adding repos to folders."""
        await cache.set_starred_repos(sample_repos)
        await cache.create_virtual_folder(sample_folder)

        await cache.add_repo_to_folder(sample_repos[0].id, sample_folder.id)

        folder_repos = await cache.get_folder_repos(sample_folder.id)
        assert len(folder_repos) == 1
        assert folder_repos[0].full_name == "octocat/Hello-World"

    @pytest.mark.asyncio
    async def test_remove_repo_from_folder(self, cache, sample_repos, sample_folder):
        """Test removing repos from folders."""
        await cache.set_starred_repos(sample_repos)
        await cache.create_virtual_folder(sample_folder)

        await cache.add_repo_to_folder(sample_repos[0].id, sample_folder.id)

        folder_repos = await cache.get_folder_repos(sample_folder.id)
        assert len(folder_repos) == 1

        await cache.remove_repo_from_folder(sample_repos[0].id, sample_folder.id)

        folder_repos = await cache.get_folder_repos(sample_folder.id)
        assert len(folder_repos) == 0

    @pytest.mark.asyncio
    async def test_get_empty_folder_repos(self, cache, sample_folder):
        """Test getting repos from empty folder."""
        await cache.create_virtual_folder(sample_folder)

        repos = await cache.get_folder_repos(sample_folder.id)
        assert len(repos) == 0


class TestRepoMetadataOperations:
    """Test repo metadata operations."""

    @pytest.mark.asyncio
    async def test_set_and_get_metadata(self, cache):
        """Test caching and retrieving metadata."""
        metadata = RepoMetadata(
            repo_id="1",
            readme_content="# Hello World",
            readme_format="markdown",
            has_issues=True,
            open_issues_count=5,
            cached_at=datetime.now(timezone.utc),
        )

        await cache.set_repo_metadata(metadata)

        retrieved = await cache.get_repo_metadata("1")

        assert retrieved is not None
        assert retrieved.repo_id == "1"
        assert retrieved.readme_content == "# Hello World"
        assert retrieved.open_issues_count == 5

    @pytest.mark.asyncio
    async def test_get_metadata_not_found(self, cache):
        """Test getting metadata for non-existent repo."""
        metadata = await cache.get_repo_metadata("nonexistent")
        assert metadata is None


class TestCacheUtilities:
    """Test cache utility functions."""

    @pytest.mark.asyncio
    async def test_get_stats(self, cache, sample_repos, sample_folder):
        """Test getting cache statistics."""
        await cache.set_starred_repos(sample_repos)
        await cache.create_virtual_folder(sample_folder)

        metadata = RepoMetadata(
            repo_id="1",
            readme_content="# Test",
            cached_at=datetime.now(timezone.utc),
        )
        await cache.set_repo_metadata(metadata)

        stats = await cache.get_stats()

        assert stats["repos_count"] == 2
        assert stats["folders_count"] == 1
        assert stats["metadata_count"] == 1
        assert stats["ttl_seconds"] == 3600


class TestCacheCleanup:
    """Test cache cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_repos(self, tmp_path, sample_repos):
        """Test cleanup of expired repos."""
        from datetime import datetime, timedelta

        # Create cache with very short TTL (1 second)
        db_path = tmp_path / "test.db"
        cache = PersistentCache(db_path=db_path, ttl_seconds=1)
        await cache.initialize()

        # Add repos
        await cache.set_starred_repos(sample_repos)

        # Wait for TTL to expire
        import asyncio
        await asyncio.sleep(1.1)

        # Cleanup expired
        count = await cache.cleanup_expired()

        # Should have cleaned up the repos
        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_nonexistent_folder(self, cache):
        """Test deleting a folder that doesn't exist."""
        # Should not raise error
        await cache.delete_virtual_folder("nonexistent-folder-id")

        # Verify folders list is still empty
        folders = await cache.get_virtual_folders()
        assert len(folders) == 0
