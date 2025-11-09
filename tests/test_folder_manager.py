"""
Tests for FolderManager.

Modified: 2025-11-07
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from ganger.core.cache import PersistentCache
from ganger.core.folder_manager import FolderManager
from ganger.core.models import StarredRepo, VirtualFolder
from ganger.core.exceptions import CacheError


@pytest_asyncio.fixture
async def cache(tmp_path):
    """Create a temporary cache for testing."""
    db_path = tmp_path / "test.db"
    cache = PersistentCache(db_path=db_path, ttl_seconds=3600)
    await cache.initialize()
    return cache


@pytest_asyncio.fixture
async def folder_manager(cache):
    """Create a FolderManager instance."""
    return FolderManager(cache)


@pytest.fixture
def sample_repos():
    """Create sample repos with different languages and topics."""
    return [
        StarredRepo(
            id="1",
            full_name="pytorch/pytorch",
            name="pytorch",
            owner="pytorch",
            description="PyTorch machine learning framework",
            stars_count=50000,
            language="Python",
            topics=["python", "machine-learning", "deep-learning"],
        ),
        StarredRepo(
            id="2",
            full_name="facebook/react",
            name="react",
            owner="facebook",
            description="React JavaScript library",
            stars_count=180000,
            language="JavaScript",
            topics=["javascript", "react", "frontend"],
        ),
        StarredRepo(
            id="3",
            full_name="scikit-learn/scikit-learn",
            name="scikit-learn",
            owner="scikit-learn",
            description="Machine learning in Python",
            stars_count=45000,
            language="Python",
            topics=["python", "machine-learning", "data-science"],
        ),
    ]


class TestFolderManagerBasics:
    """Test basic folder operations."""

    @pytest.mark.asyncio
    async def test_create_folder(self, folder_manager):
        """Test creating a folder."""
        folder = await folder_manager.create_folder(
            name="Python Projects", auto_tags=["python"], description="Python repos"
        )

        assert folder.name == "Python Projects"
        assert "python" in folder.auto_tags
        assert folder.description == "Python repos"

    @pytest.mark.asyncio
    async def test_create_duplicate_folder(self, folder_manager):
        """Test creating a folder with duplicate name."""
        await folder_manager.create_folder(name="Test Folder")

        with pytest.raises(CacheError):
            await folder_manager.create_folder(name="Test Folder")

    @pytest.mark.asyncio
    async def test_get_all_folders(self, folder_manager):
        """Test getting all folders."""
        await folder_manager.create_folder(name="Folder 1")
        await folder_manager.create_folder(name="Folder 2")

        folders = await folder_manager.get_all_folders()

        assert len(folders) == 2

    @pytest.mark.asyncio
    async def test_delete_folder(self, folder_manager):
        """Test deleting a folder."""
        folder = await folder_manager.create_folder(name="Temp Folder")

        folders = await folder_manager.get_all_folders()
        assert len(folders) == 1

        await folder_manager.delete_folder(folder.id)

        folders = await folder_manager.get_all_folders()
        assert len(folders) == 0


class TestRepoFolderOperations:
    """Test repo-folder operations."""

    @pytest.mark.asyncio
    async def test_add_repo_to_folder(self, folder_manager, cache, sample_repos):
        """Test adding repos to folders."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder = await folder_manager.create_folder(name="Test Folder")

        # Add repo
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder.id)

        # Verify
        repos = await folder_manager.get_folder_repos(folder.id)
        assert len(repos) == 1
        assert repos[0].full_name == "pytorch/pytorch"

    @pytest.mark.asyncio
    async def test_remove_repo_from_folder(self, folder_manager, cache, sample_repos):
        """Test removing repos from folders."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder = await folder_manager.create_folder(name="Test Folder")
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder.id)

        # Remove
        await folder_manager.remove_repo_from_folder(sample_repos[0].id, folder.id)

        # Verify
        repos = await folder_manager.get_folder_repos(folder.id)
        assert len(repos) == 0

    @pytest.mark.asyncio
    async def test_move_repo(self, folder_manager, cache, sample_repos):
        """Test moving a repo between folders."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder1 = await folder_manager.create_folder(name="Folder 1")
        folder2 = await folder_manager.create_folder(name="Folder 2")
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder1.id)

        # Move
        await folder_manager.move_repo(sample_repos[0].id, folder1.id, folder2.id)

        # Verify
        repos1 = await folder_manager.get_folder_repos(folder1.id)
        repos2 = await folder_manager.get_folder_repos(folder2.id)

        assert len(repos1) == 0
        assert len(repos2) == 1
        assert repos2[0].full_name == "pytorch/pytorch"

    @pytest.mark.asyncio
    async def test_copy_repo(self, folder_manager, cache, sample_repos):
        """Test copying a repo to another folder."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder1 = await folder_manager.create_folder(name="Folder 1")
        folder2 = await folder_manager.create_folder(name="Folder 2")
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder1.id)

        # Copy
        await folder_manager.copy_repo(sample_repos[0].id, folder2.id)

        # Verify - repo should be in both folders
        repos1 = await folder_manager.get_folder_repos(folder1.id)
        repos2 = await folder_manager.get_folder_repos(folder2.id)

        assert len(repos1) == 1
        assert len(repos2) == 1


class TestAutoCategorization:
    """Test auto-categorization features."""

    @pytest.mark.asyncio
    async def test_auto_categorize_all(self, folder_manager, cache, sample_repos):
        """Test auto-categorizing all repos."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        await folder_manager.create_folder(
            name="Python Projects", auto_tags=["python"]
        )
        await folder_manager.create_folder(
            name="ML Projects", auto_tags=["machine-learning"]
        )
        await folder_manager.create_folder(
            name="JavaScript Projects", auto_tags=["javascript"]
        )

        # Auto-categorize
        stats = await folder_manager.auto_categorize_all(sample_repos)

        # Verify - Python folder should have 2 repos (pytorch, scikit-learn)
        folders = await folder_manager.get_all_folders()
        python_folder = next(f for f in folders if f.name == "Python Projects")
        python_repos = await folder_manager.get_folder_repos(python_folder.id)

        assert len(python_repos) == 2

    @pytest.mark.asyncio
    async def test_auto_categorize_repo(self, folder_manager, cache, sample_repos):
        """Test auto-categorizing a single repo."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        python_folder = await folder_manager.create_folder(
            name="Python Projects", auto_tags=["python"]
        )

        # Auto-categorize single repo
        matched = await folder_manager.auto_categorize_repo(sample_repos[0])

        assert len(matched) == 1
        assert matched[0] == python_folder.id

    @pytest.mark.asyncio
    async def test_suggest_folders_for_repo(self, folder_manager, sample_repos):
        """Test suggesting folders for a repo."""
        # Setup
        await folder_manager.create_folder(name="Python", auto_tags=["python"])
        await folder_manager.create_folder(name="ML", auto_tags=["machine-learning"])
        await folder_manager.create_folder(name="JS", auto_tags=["javascript"])

        # Get suggestions for pytorch (has python and machine-learning)
        suggestions = await folder_manager.suggest_folders_for_repo(sample_repos[0])

        assert len(suggestions) == 2
        folder_names = [f.name for f in suggestions]
        assert "Python" in folder_names
        assert "ML" in folder_names

    @pytest.mark.asyncio
    async def test_create_default_folders(self, folder_manager):
        """Test creating default folders from config."""
        default_config = [
            {"name": "Python Projects", "auto_tags": ["python"]},
            {"name": "AI/ML", "auto_tags": ["machine-learning", "ai"]},
        ]

        created = await folder_manager.create_default_folders(default_config)

        assert len(created) == 2
        assert created[0].name == "Python Projects"


class TestClipboardOperations:
    """Test clipboard operations."""

    @pytest.mark.asyncio
    async def test_clipboard_copy_paste(self, folder_manager, cache, sample_repos):
        """Test copying and pasting repos."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder1 = await folder_manager.create_folder(name="Folder 1")
        folder2 = await folder_manager.create_folder(name="Folder 2")
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder1.id)

        # Copy to clipboard
        folder_manager.clipboard_copy([sample_repos[0]], folder1.id)

        status = folder_manager.clipboard_status()
        assert status["count"] == 1
        assert status["operation"] == "copy"

        # Paste
        pasted = await folder_manager.clipboard_paste(folder2.id)
        assert pasted == 1

        # Verify - repo should be in both folders (copy)
        repos1 = await folder_manager.get_folder_repos(folder1.id)
        repos2 = await folder_manager.get_folder_repos(folder2.id)

        assert len(repos1) == 1
        assert len(repos2) == 1

    @pytest.mark.asyncio
    async def test_clipboard_cut_paste(self, folder_manager, cache, sample_repos):
        """Test cutting and pasting repos."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder1 = await folder_manager.create_folder(name="Folder 1")
        folder2 = await folder_manager.create_folder(name="Folder 2")
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder1.id)

        # Cut to clipboard
        folder_manager.clipboard_cut([sample_repos[0]], folder1.id)

        status = folder_manager.clipboard_status()
        assert status["count"] == 1
        assert status["operation"] == "cut"

        # Paste
        pasted = await folder_manager.clipboard_paste(folder2.id)
        assert pasted == 1

        # Verify - repo should only be in folder2 (cut = move)
        repos1 = await folder_manager.get_folder_repos(folder1.id)
        repos2 = await folder_manager.get_folder_repos(folder2.id)

        assert len(repos1) == 0
        assert len(repos2) == 1

    @pytest.mark.asyncio
    async def test_clipboard_clear(self, folder_manager, sample_repos):
        """Test clearing clipboard."""
        folder_manager.clipboard_copy([sample_repos[0]])

        assert not folder_manager.clipboard_status()["is_empty"]

        folder_manager.clipboard_clear()

        assert folder_manager.clipboard_status()["is_empty"]


class TestStatistics:
    """Test statistics and analysis."""

    @pytest.mark.asyncio
    async def test_get_folder_stats(self, folder_manager, cache, sample_repos):
        """Test getting folder statistics."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder = await folder_manager.create_folder(
            name="Python Projects", auto_tags=["python"]
        )

        # Add Python repos
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder.id)
        await folder_manager.add_repo_to_folder(sample_repos[2].id, folder.id)

        # Get stats
        stats = await folder_manager.get_folder_stats(folder.id)

        assert stats["repo_count"] == 2
        assert stats["total_stars"] == 95000  # 50000 + 45000
        assert stats["top_language"] == "Python"


class TestFolderManagerErrorHandling:
    """Test error handling in folder manager."""

    @pytest.mark.asyncio
    async def test_auto_categorize_with_none_repos(self, folder_manager):
        """Test auto_categorize_all when repos is None (lines 167-169)."""
        # Call with repos=None, should fetch from cache (which is empty)
        stats = await folder_manager.auto_categorize_all(repos=None)

        # Should return empty stats (no repos to categorize)
        assert stats == {}

    @pytest.mark.asyncio
    async def test_auto_categorize_all_duplicate_repo(self, folder_manager, cache, sample_repos):
        """Test auto_categorize_all handles repo already in folder (lines 188-190)."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder = await folder_manager.create_folder(name="Python", auto_tags=["python"])

        # Manually add repo to folder first
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder.id)

        # Auto-categorize should handle the duplicate silently
        stats = await folder_manager.auto_categorize_all(sample_repos)

        # Should succeed without raising exception
        assert "Python" in [f.name for f in await folder_manager.get_all_folders()]

    @pytest.mark.asyncio
    async def test_auto_categorize_repo_duplicate(self, folder_manager, cache, sample_repos):
        """Test auto_categorize_repo handles repo already in folder (lines 218-220)."""
        # Setup
        await cache.set_starred_repos(sample_repos)
        folder = await folder_manager.create_folder(name="Python", auto_tags=["python"])

        # Manually add repo to folder first
        await folder_manager.add_repo_to_folder(sample_repos[0].id, folder.id)

        # Auto-categorize single repo should handle duplicate silently
        matched_ids = await folder_manager.auto_categorize_repo(sample_repos[0])

        # Should succeed, may return empty list or folder ID depending on implementation
        assert isinstance(matched_ids, list)

    @pytest.mark.asyncio
    async def test_create_default_folders_duplicate(self, folder_manager):
        """Test create_default_folders handles duplicates (lines 246-248)."""
        # Create a folder first
        await folder_manager.create_folder(name="Python Projects", auto_tags=["python"])

        # Try to create default folders with same name
        default_config = [
            {"name": "Python Projects", "auto_tags": ["python"]},
            {"name": "AI/ML", "auto_tags": ["machine-learning"]},
        ]

        # Should handle duplicate gracefully
        created = await folder_manager.create_default_folders(default_config)

        # Should only create the AI/ML folder (Python Projects already exists)
        assert len(created) == 1
        assert created[0].name == "AI/ML"
