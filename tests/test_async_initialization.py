"""
Test async initialization to verify TUI doesn't hang.

Tests that blocking operations are properly wrapped in asyncio.to_thread().

Created: 2025-11-08
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import inspect


@pytest.mark.asyncio
async def test_data_loader_initialization_nonblocking():
    """Test that DataLoader.load_starred_repos() doesn't block the event loop."""
    from ganger.core.data_loader import DataLoader
    from ganger.core.models import StarredRepo

    # Create mocks
    mock_api_client = Mock()

    # Simulate slow API call (should be run in thread pool)
    def slow_get_starred():
        import time
        time.sleep(0.1)  # Simulate network delay
        return [
            StarredRepo(
                id="1",
                full_name="test/repo",
                name="repo",
                owner="test",
                description="Test repo",
                stars_count=100,
                forks_count=10,
                language="Python",
                topics=["test"],
                is_archived=False,
                is_private=False,
                url="https://github.com/test/repo",
                clone_url="git@github.com:test/repo.git"
            )
        ]
    mock_api_client.get_starred_repos = slow_get_starred

    mock_cache = AsyncMock()
    mock_cache.get_starred_repos.return_value = None  # Force API fetch
    mock_cache.set_starred_repos = AsyncMock()

    mock_folder_manager = AsyncMock()
    mock_settings = Mock()
    mock_settings.behavior.auto_categorize = False

    # Create data loader
    loader = DataLoader(
        mock_api_client,
        mock_cache,
        mock_folder_manager,
        mock_settings
    )

    # Test: Verify load_starred_repos completes
    start = asyncio.get_event_loop().time()
    repos = await loader.load_starred_repos(force_refresh=True)
    elapsed = asyncio.get_event_loop().time() - start

    assert len(repos) == 1
    assert repos[0].name == "repo"
    # Should complete (asyncio.to_thread allows event loop to run)
    assert elapsed < 1.0  # Generous timeout
    print(f"✓ load_starred_repos completed in {elapsed:.3f}s")


@pytest.mark.asyncio
async def test_authenticate_wrapped_in_thread():
    """Test that GitHubAuth.authenticate() can be run with asyncio.to_thread()."""
    from ganger.core.auth import GitHubAuth

    # Verify authenticate is synchronous
    assert not inspect.iscoroutinefunction(GitHubAuth.authenticate)

    # Mock token file to avoid real auth
    with patch.dict('os.environ', {'GITHUB_TOKEN': 'ghp_test_token_1234567890'}):
        with patch('ganger.core.auth.GitHubAuth._verify_token', return_value=True):
            auth = GitHubAuth()

            # Should work with asyncio.to_thread
            await asyncio.to_thread(auth.authenticate)

            # Verify authenticated
            token = auth.get_token()
            assert token == 'ghp_test_token_1234567890'
            print("✓ authenticate() works with asyncio.to_thread()")


def test_clipboard_methods_are_not_async():
    """Test that clipboard methods are synchronous (not async)."""
    from ganger.core.folder_manager import FolderManager

    # Create mock cache
    cache = AsyncMock()
    manager = FolderManager(cache)

    # Verify methods are NOT async
    assert not inspect.iscoroutinefunction(manager.clipboard_status)
    assert not inspect.iscoroutinefunction(manager.clipboard_copy)
    assert not inspect.iscoroutinefunction(manager.clipboard_cut)

    # clipboard_paste IS async
    assert inspect.iscoroutinefunction(manager.clipboard_paste)

    # Test clipboard_status works synchronously
    status = manager.clipboard_status()
    assert isinstance(status, dict)
    assert "is_empty" in status
    assert status["is_empty"] is True
    print("✓ Clipboard methods are correctly sync/async")


def test_get_folder_repos_exists():
    """Test that get_folder_repos exists (not get_repos_in_folder)."""
    from ganger.core.folder_manager import FolderManager

    cache = AsyncMock()
    manager = FolderManager(cache)

    # Verify method exists and is async
    assert hasattr(manager, 'get_folder_repos')
    assert inspect.iscoroutinefunction(manager.get_folder_repos)

    # Verify old method doesn't exist
    assert not hasattr(manager, 'get_repos_in_folder')
    print("✓ get_folder_repos exists and is async")


@pytest.mark.asyncio
async def test_full_initialization_flow():
    """Test complete initialization flow with mocked components."""
    from ganger.core.data_loader import DataLoader
    from ganger.core.models import StarredRepo, VirtualFolder

    # Mock API client
    mock_api_client = Mock()
    mock_api_client.get_starred_repos = lambda: [
        StarredRepo(
            id="1",
            full_name="python/cpython",
            name="cpython",
            owner="python",
            description="The Python programming language",
            stars_count=50000,
            forks_count=20000,
            language="Python",
            topics=["python", "cpython"],
            is_archived=False,
            is_private=False,
            url="https://github.com/python/cpython",
            clone_url="git@github.com:python/cpython.git"
        )
    ]

    # Mock cache
    mock_cache = AsyncMock()
    mock_cache.get_starred_repos.return_value = None
    mock_cache.set_starred_repos = AsyncMock()
    mock_cache.get_virtual_folders.return_value = []
    mock_cache.create_virtual_folder = AsyncMock()

    # Mock folder manager
    mock_folder_manager = AsyncMock()

    # Mock settings
    mock_settings = Mock()
    mock_settings.behavior.auto_categorize = False
    mock_settings.folders.default_folders = []

    # Create and run data loader
    loader = DataLoader(
        mock_api_client,
        mock_cache,
        mock_folder_manager,
        mock_settings
    )

    # This should complete without hanging
    repos = await loader.load_starred_repos(force_refresh=True)
    assert len(repos) == 1

    folders = await loader.ensure_default_folders()
    # Should create "All Stars" folder
    assert mock_cache.create_virtual_folder.called

    print("✓ Full initialization flow completes successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
