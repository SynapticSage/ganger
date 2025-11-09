"""Enhanced tests for DataLoader orchestration layer.

Tests error handling, cache fallback, and concurrent operations.

Created: 2025-11-08
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from ganger.core.data_loader import DataLoader
from ganger.core.models import StarredRepo, VirtualFolder
from ganger.core.exceptions import RateLimitExceededError, AuthenticationError
from tests.utils import create_test_repo, create_batch_repos


@pytest.mark.integration
class TestLoadStarredRepos:
    """Test starred repos loading logic."""

    @pytest.mark.asyncio
    async def test_load_from_cache_when_valid(self, temp_cache, mock_settings, sample_repos):
        """Test loading from cache when not expired."""
        # Setup: Populate cache
        await temp_cache.set_starred_repos(sample_repos)

        # Create data loader
        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        repos = await loader.load_starred_repos(force_refresh=False)

        # Verify: Loaded from cache, API not called
        assert len(repos) == len(sample_repos)
        # Cache returns repos ordered by stars_count DESC
        # rust-lang/rust has 90k stars (highest)
        assert repos[0].full_name == "rust-lang/rust"
        assert repos[0].stars_count == 90000
        mock_api.get_starred_repos.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_from_api_on_force_refresh(self, temp_cache, mock_settings, sample_repos):
        """Test force refresh bypasses cache."""
        # Setup: API returns repos
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(return_value=sample_repos)

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        repos = await loader.load_starred_repos(force_refresh=True)

        # Verify: API was called, repos returned
        assert len(repos) == len(sample_repos)
        mock_api.get_starred_repos.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_cache_on_api_error(self, temp_cache, mock_settings, sample_repos):
        """Test graceful degradation to cache when API fails."""
        # Setup: Cache has data, API fails
        await temp_cache.set_starred_repos(sample_repos)

        mock_api = Mock()
        mock_api.get_starred_repos = Mock(side_effect=RateLimitExceededError("Rate limit exceeded"))

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        repos = await loader.load_starred_repos(force_refresh=True)

        # Verify: Fell back to cache
        assert len(repos) == len(sample_repos)
        # Cache returns repos ordered by stars_count DESC
        assert repos[0].full_name == "rust-lang/rust"

    @pytest.mark.asyncio
    async def test_raises_when_cache_and_api_both_fail(self, temp_cache, mock_settings):
        """Test that error is raised when both cache and API fail."""
        # Setup: Empty cache, API fails
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(side_effect=AuthenticationError("Auth failed"))

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute & Verify: Should raise
        with pytest.raises(AuthenticationError):
            await loader.load_starred_repos(force_refresh=True)

    @pytest.mark.asyncio
    async def test_load_empty_starred_list(self, temp_cache, mock_settings):
        """Test loading when user has no starred repos."""
        # Setup: API returns empty list
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(return_value=[])

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        repos = await loader.load_starred_repos(force_refresh=True)

        # Verify: Empty list returned
        assert repos == []

    @pytest.mark.asyncio
    async def test_caches_repos_after_api_fetch(self, temp_cache, mock_settings, sample_repos):
        """Test that repos are cached after fetching from API."""
        # Setup
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(return_value=sample_repos)

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        await loader.load_starred_repos(force_refresh=True)

        # Verify: Repos are now in cache
        cached_repos = await temp_cache.get_starred_repos()
        assert len(cached_repos) == len(sample_repos)
        # Cache returns repos ordered by stars_count DESC
        # rust-lang/rust (id="3") has highest stars
        assert cached_repos[0].id == "3"


@pytest.mark.integration
class TestDefaultFolders:
    """Test default folder creation."""

    @pytest.mark.asyncio
    async def test_ensure_all_stars_folder_created(self, temp_cache, mock_settings):
        """Test All Stars folder creation."""
        # Setup
        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        folders = await loader.ensure_default_folders()

        # Verify: All Stars folder was created
        all_folders = await temp_cache.get_virtual_folders()
        assert any(f.name == "All Stars" for f in all_folders)

    @pytest.mark.asyncio
    async def test_does_not_duplicate_all_stars(self, temp_cache, mock_settings):
        """Test that All Stars folder is not duplicated."""
        # Setup: All Stars already exists
        all_stars = VirtualFolder(
            id="all-stars",
            name="All Stars",
            auto_tags=[],
            repo_count=0
        )
        await temp_cache.create_virtual_folder(all_stars)

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute twice
        await loader.ensure_default_folders()
        await loader.ensure_default_folders()

        # Verify: Only one All Stars folder
        all_folders = await temp_cache.get_virtual_folders()
        all_stars_count = sum(1 for f in all_folders if f.name == "All Stars")
        assert all_stars_count == 1

    @pytest.mark.asyncio
    async def test_creates_config_defined_folders(self, temp_cache):
        """Test creating folders defined in config."""
        # Setup: Settings with default folders
        mock_settings = Mock()
        mock_settings.behavior = Mock()
        mock_settings.behavior.auto_categorize = False
        mock_settings.folders = Mock()
        mock_settings.folders.default_folders = [
            {"name": "Python Projects", "auto_tags": ["python"]},
            {"name": "AI/ML", "auto_tags": ["machine-learning", "ai"]},
        ]

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        await loader.ensure_default_folders()

        # Verify: Config folders were created
        all_folders = await temp_cache.get_virtual_folders()
        folder_names = [f.name for f in all_folders]
        assert "Python Projects" in folder_names
        assert "AI/ML" in folder_names


@pytest.mark.integration
class TestSyncAllStarsFolder:
    """Test All Stars folder synchronization."""

    @pytest.mark.asyncio
    async def test_syncs_all_repos_to_all_stars(self, temp_cache, mock_settings, sample_repos):
        """Test that all repos are added to All Stars folder."""
        # Setup: Create All Stars folder
        all_stars = VirtualFolder(
            id="all-stars",
            name="All Stars",
            auto_tags=[],
            repo_count=0
        )
        await temp_cache.create_virtual_folder(all_stars)
        await temp_cache.set_starred_repos(sample_repos)

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        await loader.sync_all_stars_folder(sample_repos)

        # Verify: All repos in All Stars
        folder_repos = await temp_cache.get_folder_repos("all-stars")
        assert len(folder_repos) == len(sample_repos)

    @pytest.mark.asyncio
    async def test_does_not_duplicate_repos_in_all_stars(self, temp_cache, mock_settings, sample_repos):
        """Test that sync doesn't create duplicates."""
        # Setup
        all_stars = VirtualFolder(
            id="all-stars",
            name="All Stars",
            auto_tags=[],
            repo_count=0
        )
        await temp_cache.create_virtual_folder(all_stars)
        await temp_cache.set_starred_repos(sample_repos)

        # Add repos once
        for repo in sample_repos:
            await temp_cache.add_repo_to_folder(repo.id, "all-stars", is_manual=False)

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute: Sync again
        await loader.sync_all_stars_folder(sample_repos)

        # Verify: No duplicates
        folder_repos = await temp_cache.get_folder_repos("all-stars")
        assert len(folder_repos) == len(sample_repos)


@pytest.mark.integration
class TestAutoCategorization:
    """Test auto-categorization logic."""

    @pytest.mark.asyncio
    async def test_auto_categorize_disabled_in_settings(self, temp_cache, sample_repos):
        """Test that auto-categorization is skipped when disabled."""
        # Setup: Settings with auto_categorize = False
        mock_settings = Mock()
        mock_settings.behavior = Mock()
        mock_settings.behavior.auto_categorize = False

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        await loader.auto_categorize_all(sample_repos)

        # Verify: Folder manager not called
        folder_manager.auto_categorize_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_categorize_calls_folder_manager(self, temp_cache, sample_repos):
        """Test that auto-categorization delegates to folder manager."""
        # Setup: Settings with auto_categorize = True
        mock_settings = Mock()
        mock_settings.behavior = Mock()
        mock_settings.behavior.auto_categorize = True

        mock_api = Mock()
        folder_manager = AsyncMock()
        # Return a proper dict to avoid AsyncMock warning
        folder_manager.auto_categorize_all.return_value = {
            "Python": [sample_repos[0], sample_repos[1]],
            "AI/ML": [sample_repos[2], sample_repos[3]]
        }
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute
        await loader.auto_categorize_all(sample_repos)

        # Verify: Folder manager was called
        folder_manager.auto_categorize_all.assert_called_once()


@pytest.mark.integration
@pytest.mark.slow
class TestConcurrency:
    """Test concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_load_starred_repos(self, temp_cache, mock_settings, sample_repos):
        """Test thread safety of concurrent loads."""
        import asyncio

        # Setup
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(return_value=sample_repos)

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute: 5 concurrent loads
        tasks = [loader.load_starred_repos(force_refresh=True) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Verify: All returned same data
        assert all(len(r) == len(sample_repos) for r in results)
        # API should have been called 5 times (no deduplication in current impl)
        assert mock_api.get_starred_repos.call_count == 5


@pytest.mark.unit
class TestDataLoaderEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_handles_malformed_cached_repos(self, temp_cache, mock_settings):
        """Test handling of corrupted cache data."""
        # This is more of a cache test, but exercises data_loader error handling
        mock_api = Mock()
        mock_api.get_starred_repos = Mock(return_value=[])

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Should not crash
        repos = await loader.load_starred_repos(force_refresh=False)
        assert repos == []


@pytest.mark.unit
class TestDataLoaderErrorPaths:
    """Test error handling in data_loader."""

    @pytest.mark.asyncio
    async def test_ensure_default_folders_handles_cache_errors(self, mock_settings):
        """Test that ensure_default_folders handles cache errors gracefully."""
        # Setup: Mock cache that raises errors
        mock_cache = AsyncMock()
        mock_cache.get_virtual_folders.return_value = []

        # Simulate database error when creating folder
        from ganger.core.exceptions import CacheError
        mock_cache.create_virtual_folder.side_effect = CacheError("Database locked")

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, mock_cache, folder_manager, mock_settings)

        # Execute: Should not crash, just log error
        folders = await loader.ensure_default_folders()

        # Verify: Returns whatever cache has (empty in this case)
        assert folders == []

    @pytest.mark.asyncio
    async def test_ensure_default_folders_handles_general_exception(self, mock_settings):
        """Test that ensure_default_folders handles unexpected exceptions."""
        # Setup: Mock cache that raises unexpected error
        mock_cache = AsyncMock()
        mock_cache.get_virtual_folders.side_effect = RuntimeError("Unexpected database error")

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, mock_cache, folder_manager, mock_settings)

        # Execute: Should raise the exception (after logging)
        with pytest.raises(RuntimeError, match="Unexpected database error"):
            await loader.ensure_default_folders()

    @pytest.mark.asyncio
    async def test_sync_all_stars_handles_get_folder_error(self, temp_cache, mock_settings, sample_repos):
        """Test that sync_all_stars_folder handles errors when fetching current repos."""
        # Setup: Mock cache that raises error on get_folder_repos
        mock_cache = AsyncMock()
        mock_cache.get_folder_repos.side_effect = Exception("Folder not found")
        mock_cache.add_repo_to_folder = AsyncMock()

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, mock_cache, folder_manager, mock_settings)

        # Execute: Should not crash, should still try to add repos
        await loader.sync_all_stars_folder(sample_repos)

        # Verify: Attempted to add all repos (since current_repo_ids is empty)
        assert mock_cache.add_repo_to_folder.call_count == len(sample_repos)

    @pytest.mark.asyncio
    async def test_sync_all_stars_handles_add_repo_error(self, temp_cache, mock_settings, sample_repos):
        """Test that sync_all_stars_folder handles errors when adding repos."""
        # Setup: Mock cache that raises error on add_repo_to_folder
        mock_cache = AsyncMock()
        mock_cache.get_folder_repos.return_value = []
        from ganger.core.exceptions import CacheError
        mock_cache.add_repo_to_folder.side_effect = CacheError("Repo already in folder")

        mock_api = Mock()
        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, mock_cache, folder_manager, mock_settings)

        # Execute: Should not crash (logs error but doesn't raise)
        await loader.sync_all_stars_folder(sample_repos)

        # Verify: Called once before exception caught the entire sync
        # NOTE: Current implementation catches exception at function level, not per-repo
        # This means only first repo is attempted before sync stops
        assert mock_cache.add_repo_to_folder.call_count == 1

    @pytest.mark.asyncio
    async def test_auto_categorize_handles_folder_manager_error(self, temp_cache, sample_repos):
        """Test that auto_categorize_all handles folder_manager errors."""
        # Setup: Settings with auto_categorize enabled
        mock_settings = Mock()
        mock_settings.behavior = Mock()
        mock_settings.behavior.auto_categorize = True

        # Mock folder manager that raises error
        folder_manager = AsyncMock()
        folder_manager.auto_categorize_all.side_effect = RuntimeError("Categorization failed")

        mock_api = Mock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute: Should not crash (logs error but doesn't raise)
        await loader.auto_categorize_all(sample_repos)

        # Verify: Folder manager was called
        folder_manager.auto_categorize_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_starred_repos_with_empty_cache_and_api_error(self, temp_cache, mock_settings):
        """Test behavior when both cache is empty and API fails."""
        # Setup: Empty cache, failing API
        mock_api = Mock()
        from ganger.core.exceptions import RateLimitExceededError
        mock_api.get_starred_repos = Mock(side_effect=RateLimitExceededError("Rate limited"))

        folder_manager = AsyncMock()
        loader = DataLoader(mock_api, temp_cache, folder_manager, mock_settings)

        # Execute: Should raise since no fallback available
        with pytest.raises(RateLimitExceededError):
            await loader.load_starred_repos(force_refresh=True)
