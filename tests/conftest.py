"""Shared test fixtures for Ganger tests.

Created: 2025-11-08
"""

import pytest
import pytest_asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from ganger.core.auth import GitHubAuth
from ganger.core.cache import PersistentCache
from ganger.core.models import StarredRepo, VirtualFolder
from ganger.config.settings import Settings


@pytest.fixture
def mock_github_auth():
    """Mock authenticated GitHubAuth instance."""
    auth = Mock(spec=GitHubAuth)
    auth.get_token.return_value = "ghp_test_token_1234567890"

    # Mock GitHub client
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.login = "test_user"
    mock_user.name = "Test User"
    mock_client.get_user.return_value = mock_user
    auth.get_github_client.return_value = mock_client

    return auth


@pytest.fixture
def mock_github_client():
    """Mock PyGithub client."""
    client = MagicMock()

    # Mock user
    mock_user = MagicMock()
    mock_user.login = "test_user"
    mock_user.name = "Test User"
    client.get_user.return_value = mock_user

    return client


@pytest.fixture
def mock_ghapi():
    """Mock GhApi GraphQL client."""
    api = MagicMock()

    # Default GraphQL response structure
    api.graphql.return_value = {
        "viewer": {
            "starredRepositories": {
                "edges": [],
                "pageInfo": {
                    "hasNextPage": False,
                    "endCursor": None
                }
            }
        }
    }

    return api


@pytest_asyncio.fixture
async def temp_cache():
    """Temporary cache database with automatic cleanup."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_cache.db"
        cache = PersistentCache(db_path=db_path, ttl_seconds=3600)
        await cache.initialize()

        yield cache

        # Cleanup is automatic via context manager


@pytest.fixture
def sample_repos():
    """Standard set of test repos."""
    return [
        StarredRepo(
            id="1",
            full_name="python/cpython",
            name="cpython",
            owner="python",
            description="The Python programming language",
            stars_count=50000,
            forks_count=20000,
            language="Python",
            topics=["python", "cpython", "interpreter"],
            is_archived=False,
            is_private=False,
            created_at=datetime(2017, 3, 21, tzinfo=timezone.utc),
            updated_at=datetime(2025, 11, 1, tzinfo=timezone.utc),
            starred_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
            url="https://github.com/python/cpython",
            clone_url="https://github.com/python/cpython.git"
        ),
        StarredRepo(
            id="2",
            full_name="Textualize/textual",
            name="textual",
            owner="Textualize",
            description="TUI framework for Python",
            stars_count=25000,
            forks_count=5000,
            language="Python",
            topics=["python", "tui", "terminal"],
            is_archived=False,
            is_private=False,
            created_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2025, 11, 5, tzinfo=timezone.utc),
            starred_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
            url="https://github.com/Textualize/textual",
            clone_url="https://github.com/Textualize/textual.git"
        ),
        StarredRepo(
            id="3",
            full_name="rust-lang/rust",
            name="rust",
            owner="rust-lang",
            description="A language empowering everyone to build reliable and efficient software",
            stars_count=90000,
            forks_count=12000,
            language="Rust",
            topics=["rust", "compiler", "systems-programming"],
            is_archived=False,
            is_private=False,
            created_at=datetime(2010, 6, 16, tzinfo=timezone.utc),
            updated_at=datetime(2025, 11, 7, tzinfo=timezone.utc),
            starred_at=datetime(2025, 3, 10, tzinfo=timezone.utc),
            url="https://github.com/rust-lang/rust",
            clone_url="https://github.com/rust-lang/rust.git"
        ),
        StarredRepo(
            id="4",
            full_name="openai/whisper",
            name="whisper",
            owner="openai",
            description="Robust Speech Recognition via Large-Scale Weak Supervision",
            stars_count=60000,
            forks_count=7000,
            language="Python",
            topics=["machine-learning", "speech-recognition", "ai"],
            is_archived=False,
            is_private=False,
            created_at=datetime(2022, 9, 16, tzinfo=timezone.utc),
            updated_at=datetime(2025, 10, 20, tzinfo=timezone.utc),
            starred_at=datetime(2025, 4, 5, tzinfo=timezone.utc),
            url="https://github.com/openai/whisper",
            clone_url="https://github.com/openai/whisper.git"
        ),
    ]


@pytest.fixture
def sample_folders():
    """Standard set of test folders."""
    return [
        VirtualFolder(
            id="all-stars",
            name="All Stars",
            auto_tags=[],
            repo_count=4
        ),
        VirtualFolder(
            id="python",
            name="Python Projects",
            auto_tags=["python"],
            repo_count=3
        ),
        VirtualFolder(
            id="rust",
            name="Rust Projects",
            auto_tags=["rust"],
            repo_count=1
        ),
        VirtualFolder(
            id="ai-ml",
            name="AI/ML",
            auto_tags=["machine-learning", "ai", "ml"],
            repo_count=1
        ),
    ]


@pytest.fixture
def mock_settings():
    """Mock Settings object with sensible defaults."""
    settings = Mock(spec=Settings)

    # GitHub settings
    settings.github = Mock()
    settings.github.auth_method = "token"
    settings.github.rate_limit_buffer = 100

    # Cache settings
    settings.cache = Mock()
    settings.cache.db_path = ":memory:"
    settings.cache.repos_ttl = 3600
    settings.cache.metadata_ttl = 86400
    settings.cache.readme_ttl = 604800
    settings.cache.load_on_startup = False

    # Behavior settings
    settings.behavior = Mock()
    settings.behavior.confirm_unstar = True
    settings.behavior.auto_refresh = False
    settings.behavior.sort_order = "stars"
    settings.behavior.auto_categorize = True

    # Folder settings
    settings.folders = Mock()
    settings.folders.default_folders = []

    return settings


@pytest.fixture
def freezer(monkeypatch):
    """Freeze time for TTL tests.

    Usage:
        freezer.set(datetime(2025, 11, 8, 12, 0, 0))
        # Time is now frozen
        freezer.advance(hours=2)
        # Time advances by 2 hours
    """
    class TimeFreezer:
        def __init__(self):
            self._frozen_time = None

        def set(self, dt: datetime):
            """Freeze time at specific datetime."""
            self._frozen_time = dt
            monkeypatch.setattr("ganger.core.cache.datetime", self._mock_datetime)

        def advance(self, **kwargs):
            """Advance frozen time by timedelta."""
            if self._frozen_time:
                self._frozen_time += timedelta(**kwargs)

        def _mock_datetime(self):
            """Mock datetime class."""
            class MockDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return self._frozen_time or datetime.now(tz=tz)
            return MockDatetime

    return TimeFreezer()


@pytest.fixture
def graphql_starred_response():
    """Sample GraphQL response for starred repositories."""
    return {
        "viewer": {
            "starredRepositories": {
                "edges": [
                    {
                        "starredAt": "2025-01-15T10:30:00Z",
                        "node": {
                            "id": "R_1",
                            "nameWithOwner": "python/cpython",
                            "description": "The Python programming language",
                            "stargazerCount": 50000,
                            "forkCount": 20000,
                            "primaryLanguage": {"name": "Python"},
                            "repositoryTopics": {
                                "nodes": [
                                    {"topic": {"name": "python"}},
                                    {"topic": {"name": "cpython"}},
                                ]
                            },
                            "isArchived": False,
                            "isPrivate": False,
                            "createdAt": "2017-03-21T00:00:00Z",
                            "updatedAt": "2025-11-01T12:00:00Z",
                            "url": "https://github.com/python/cpython",
                            "sshUrl": "git@github.com:python/cpython.git"
                        }
                    }
                ],
                "pageInfo": {
                    "hasNextPage": False,
                    "endCursor": None
                }
            }
        }
    }
