"""
Tests for configuration settings.

Modified: 2025-11-07
"""

import pytest
import yaml
from pathlib import Path
from ganger.config.settings import (
    Settings,
    GitHubSettings,
    CacheSettings,
    FolderSettings,
    BehaviorSettings,
    MCPSettings,
    get_config_dir,
    get_cache_dir,
)


class TestSettings:
    """Test Settings class."""

    def test_default_settings(self):
        """Test default settings initialization."""
        settings = Settings()

        assert settings.github.auth_method == "auto"
        assert settings.github.cache_enabled is True
        assert settings.cache.repos_ttl == 3600
        assert settings.behavior.confirm_unstar is True
        assert settings.mcp.name == "ganger"

    def test_load_from_file(self, tmp_path):
        """Test loading settings from YAML file."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "github": {
                "auth_method": "pat",
                "cache_enabled": False,
                "cache_ttl": 7200,
            },
            "cache": {
                "repos_ttl": 1800,
            },
            "behavior": {
                "auto_categorize": False,
            },
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        settings = Settings.load(config_file)

        assert settings.github.auth_method == "pat"
        assert settings.github.cache_enabled is False
        assert settings.github.cache_ttl == 7200
        assert settings.cache.repos_ttl == 1800
        assert settings.behavior.auto_categorize is False

    def test_load_with_missing_file(self):
        """Test loading with non-existent config file."""
        # Should return defaults
        settings = Settings.load(Path("/nonexistent/config.yaml"))

        assert settings.github.auth_method == "auto"
        assert settings.cache.repos_ttl == 3600

    def test_environment_variable_override(self, monkeypatch, tmp_path):
        """Test that environment variables override config file."""
        # Set up config file
        config_file = tmp_path / "config.yaml"
        config_data = {"github": {"token": "file_token"}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        # Set environment variable
        monkeypatch.setenv("GITHUB_TOKEN", "env_token")
        monkeypatch.setenv("GANGER_CACHE_TTL", "9999")

        settings = Settings.load(config_file)

        # Env var should override file
        assert settings.github.token == "env_token"
        assert settings.cache.repos_ttl == 9999

    def test_to_dict(self):
        """Test converting settings to dictionary."""
        settings = Settings()
        settings_dict = settings.to_dict()

        assert "github" in settings_dict
        assert "cache" in settings_dict
        assert "folders" in settings_dict
        assert "behavior" in settings_dict
        assert "mcp" in settings_dict

        assert settings_dict["github"]["auth_method"] == "auto"
        assert settings_dict["cache"]["repos_ttl"] == 3600

    def test_get_config_dir(self):
        """Test getting config directory."""
        config_dir = get_config_dir()

        assert config_dir.exists()
        assert config_dir.is_dir()
        assert str(config_dir).endswith("ganger")

    def test_get_cache_dir(self):
        """Test getting cache directory."""
        cache_dir = get_cache_dir()

        assert cache_dir.exists()
        assert cache_dir.is_dir()
        assert str(cache_dir).endswith("ganger")


class TestIndividualSettings:
    """Test individual settings dataclasses."""

    def test_github_settings(self):
        """Test GitHubSettings."""
        settings = GitHubSettings(
            auth_method="oauth",
            token="test_token",
            cache_ttl=7200,
        )

        assert settings.auth_method == "oauth"
        assert settings.token == "test_token"
        assert settings.cache_ttl == 7200

    def test_cache_settings(self):
        """Test CacheSettings."""
        settings = CacheSettings(
            db_path="/custom/path.db",
            repos_ttl=1800,
        )

        assert settings.db_path == "/custom/path.db"
        assert settings.repos_ttl == 1800

    def test_folder_settings(self):
        """Test FolderSettings."""
        default_folders = [
            {"name": "Python", "auto_tags": ["python"]},
            {"name": "JS", "auto_tags": ["javascript"]},
        ]

        settings = FolderSettings(default_folders=default_folders)

        assert len(settings.default_folders) == 2
        assert settings.default_folders[0]["name"] == "Python"

    def test_behavior_settings(self):
        """Test BehaviorSettings."""
        settings = BehaviorSettings(
            confirm_unstar=False,
            sort_order="updated",
        )

        assert settings.confirm_unstar is False
        assert settings.sort_order == "updated"

    def test_mcp_settings(self):
        """Test MCPSettings."""
        settings = MCPSettings(
            name="custom_ganger",
            max_history=100,
        )

        assert settings.name == "custom_ganger"
        assert settings.max_history == 100
