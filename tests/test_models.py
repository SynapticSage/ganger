"""
Tests for core data models.

Modified: 2025-11-09
"""

from datetime import datetime, timezone, timedelta
import json
import pytest
from ganger.core.models import (
    StarredRepo,
    VirtualFolder,
    Clipboard,
    ClipboardItem,
    RepoMetadata,
    FolderRepoLink,
)


class TestStarredRepo:
    """Test StarredRepo model."""

    def test_create_repo(self):
        """Test creating a StarredRepo."""
        repo = StarredRepo(
            id="12345",
            full_name="octocat/Hello-World",
            name="Hello-World",
            owner="octocat",
            description="My first repository",
            language="Python",
            topics=["python", "github"],
        )

        assert repo.id == "12345"
        assert repo.full_name == "octocat/Hello-World"
        assert repo.language == "Python"
        assert "python" in repo.topics

    def test_to_dict_from_dict(self):
        """Test serialization round-trip."""
        repo = StarredRepo(
            id="12345",
            full_name="octocat/Hello-World",
            name="Hello-World",
            owner="octocat",
            topics=["python", "ml"],
            created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        # Convert to dict and back
        data = repo.to_dict()
        repo2 = StarredRepo.from_dict(data)

        assert repo2.id == repo.id
        assert repo2.full_name == repo.full_name
        assert repo2.topics == repo.topics
        assert repo2.created_at == repo.created_at

    def test_format_stars(self):
        """Test star count formatting."""
        repo1 = StarredRepo(
            id="1", full_name="test/repo1", name="repo1", owner="test", stars_count=500
        )
        assert repo1.format_stars() == "500"

        repo2 = StarredRepo(
            id="2", full_name="test/repo2", name="repo2", owner="test", stars_count=1500
        )
        assert repo2.format_stars() == "1.5k"

        repo3 = StarredRepo(
            id="3", full_name="test/repo3", name="repo3", owner="test", stars_count=45200
        )
        assert repo3.format_stars() == "45.2k"

    def test_format_updated(self):
        """Test updated time formatting."""
        now = datetime.now(timezone.utc)

        # Recent update
        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=now,
        )
        assert "just now" in repo.format_updated() or "0h ago" in repo.format_updated()


class TestVirtualFolder:
    """Test VirtualFolder model."""

    def test_create_folder(self):
        """Test creating a VirtualFolder."""
        folder = VirtualFolder(
            id="folder1",
            name="Python Projects",
            auto_tags=["python", "py"],
            description="Python-related repos",
        )

        assert folder.id == "folder1"
        assert folder.name == "Python Projects"
        assert "python" in folder.auto_tags

    def test_matches_repo(self):
        """Test repo matching logic."""
        folder = VirtualFolder(
            id="folder1", name="Python Projects", auto_tags=["python", "machine-learning"]
        )

        # Should match by topic
        repo1 = StarredRepo(
            id="1",
            full_name="test/repo1",
            name="repo1",
            owner="test",
            topics=["python", "web"],
        )
        assert folder.matches_repo(repo1)

        # Should match by language
        repo2 = StarredRepo(
            id="2",
            full_name="test/repo2",
            name="repo2",
            owner="test",
            language="Python",
            topics=["other"],
        )
        assert folder.matches_repo(repo2)

        # Should not match
        repo3 = StarredRepo(
            id="3",
            full_name="test/repo3",
            name="repo3",
            owner="test",
            language="JavaScript",
            topics=["js", "web"],
        )
        assert not folder.matches_repo(repo3)

    def test_to_dict_from_dict(self):
        """Test folder serialization."""
        folder = VirtualFolder(
            id="folder1",
            name="AI/ML",
            auto_tags=["ai", "machine-learning"],
            created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        data = folder.to_dict()
        folder2 = VirtualFolder.from_dict(data)

        assert folder2.id == folder.id
        assert folder2.name == folder.name
        assert folder2.auto_tags == folder.auto_tags


class TestClipboard:
    """Test Clipboard model."""

    def test_copy(self):
        """Test copying repos."""
        clipboard = Clipboard()
        repos = [
            StarredRepo(id="1", full_name="test/repo1", name="repo1", owner="test"),
            StarredRepo(id="2", full_name="test/repo2", name="repo2", owner="test"),
        ]

        clipboard.copy(repos)

        assert clipboard.count() == 2
        assert clipboard.get_operation() == "copy"
        assert not clipboard.is_empty()

    def test_cut(self):
        """Test cutting repos."""
        clipboard = Clipboard()
        repos = [
            StarredRepo(id="1", full_name="test/repo1", name="repo1", owner="test"),
        ]

        clipboard.cut(repos, source_folder_id="folder1")

        assert clipboard.count() == 1
        assert clipboard.get_operation() == "cut"
        items = clipboard.paste()
        assert items[0].source_folder_id == "folder1"

    def test_clear(self):
        """Test clearing clipboard."""
        clipboard = Clipboard()
        repos = [
            StarredRepo(id="1", full_name="test/repo1", name="repo1", owner="test"),
        ]

        clipboard.copy(repos)
        assert not clipboard.is_empty()

        clipboard.clear()
        assert clipboard.is_empty()
        assert clipboard.get_operation() is None


class TestRepoMetadata:
    """Test RepoMetadata model."""

    def test_create_metadata(self):
        """Test creating RepoMetadata."""
        metadata = RepoMetadata(
            repo_id="12345",
            readme_content="# Hello World",
            has_issues=True,
            open_issues_count=5,
        )

        assert metadata.repo_id == "12345"
        assert metadata.readme_content == "# Hello World"
        assert metadata.open_issues_count == 5

    def test_serialization(self):
        """Test metadata serialization."""
        metadata = RepoMetadata(
            repo_id="12345",
            readme_content="# Test",
            cached_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        data = metadata.to_dict()
        metadata2 = RepoMetadata.from_dict(data)

        assert metadata2.repo_id == metadata.repo_id
        assert metadata2.readme_content == metadata.readme_content
        assert metadata2.cached_at == metadata.cached_at


class TestStarredRepoFormatting:
    """Test StarredRepo formatting methods."""

    def test_format_updated_hours_ago(self):
        """Test format_updated with hours ago (line 166)."""
        now = datetime.now(timezone.utc)
        two_hours_ago = now - timedelta(hours=2)

        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=two_hours_ago
        )

        assert repo.format_updated() == "2h ago"

    def test_format_updated_days_ago(self):
        """Test format_updated with days ago (line 168)."""
        now = datetime.now(timezone.utc)
        three_days_ago = now - timedelta(days=3)

        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=three_days_ago
        )

        assert repo.format_updated() == "3d ago"

    def test_format_updated_weeks_ago(self):
        """Test format_updated with weeks ago (line 171)."""
        now = datetime.now(timezone.utc)
        two_weeks_ago = now - timedelta(days=14)

        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=two_weeks_ago
        )

        assert repo.format_updated() == "2w ago"

    def test_format_updated_months_ago(self):
        """Test format_updated with months ago (line 174)."""
        now = datetime.now(timezone.utc)
        two_months_ago = now - timedelta(days=60)

        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=two_months_ago
        )

        assert repo.format_updated() == "2mo ago"

    def test_format_updated_years_ago(self):
        """Test format_updated with years ago (line 177)."""
        now = datetime.now(timezone.utc)
        two_years_ago = now - timedelta(days=730)

        repo = StarredRepo(
            id="1",
            full_name="test/repo",
            name="repo",
            owner="test",
            updated_at=two_years_ago
        )

        assert repo.format_updated() == "2y ago"


class TestFolderRepoLink:
    """Test FolderRepoLink model."""

    def test_create_link(self):
        """Test creating a folder-repo link."""
        link = FolderRepoLink(
            folder_id="folder1",
            repo_id="repo1",
            is_manual=True,
            added_at=datetime.now(timezone.utc),
        )

        assert link.folder_id == "folder1"
        assert link.repo_id == "repo1"
        assert link.is_manual is True

    def test_serialization(self):
        """Test link serialization."""
        link = FolderRepoLink(
            folder_id="folder1",
            repo_id="repo1",
            is_manual=False,
            added_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        data = link.to_dict()
        link2 = FolderRepoLink.from_dict(data)

        assert link2.folder_id == link.folder_id
        assert link2.is_manual == link.is_manual
        assert link2.added_at == link.added_at
