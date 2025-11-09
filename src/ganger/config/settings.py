"""
Configuration management for Ganger.

Hierarchical settings loading: defaults → config file → environment variables

Modified: 2025-11-07
"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional


@dataclass
class GitHubSettings:
    """GitHub API settings."""

    auth_method: str = "auto"  # auto, oauth, pat
    token: Optional[str] = None
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour
    rate_limit_buffer: int = 100


@dataclass
class CacheSettings:
    """Cache settings."""

    db_path: str = "~/.cache/ganger/ganger.db"
    repos_ttl: int = 3600  # 1 hour
    metadata_ttl: int = 86400  # 24 hours
    readme_ttl: int = 604800  # 7 days
    load_on_startup: bool = False  # Whether to load starred repos on startup


@dataclass
class FolderConfig:
    """Virtual folder configuration."""

    name: str
    auto_tags: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class FolderSettings:
    """Folder management settings."""

    default_folders: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BehaviorSettings:
    """Behavior settings."""

    confirm_unstar: bool = True
    auto_refresh: bool = False
    sort_order: str = "stars"  # stars, updated, created, name, language
    auto_categorize: bool = True


@dataclass
class MCPSettings:
    """MCP server settings."""

    name: str = "ganger"
    enable_session_state: bool = True
    max_history: int = 50


@dataclass
class Settings:
    """Main settings container."""

    github: GitHubSettings = field(default_factory=GitHubSettings)
    cache: CacheSettings = field(default_factory=CacheSettings)
    folders: FolderSettings = field(default_factory=FolderSettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)
    mcp: MCPSettings = field(default_factory=MCPSettings)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Settings":
        """
        Load settings from file and environment variables.

        Priority:
        1. Default values (defined in dataclasses)
        2. Config file (~/.config/ganger/config.yaml)
        3. Environment variables (override everything)

        Args:
            config_path: Optional path to config file

        Returns:
            Settings instance
        """
        settings = cls()

        # Load from config file
        if config_path is None:
            config_dir = Path.home() / ".config" / "ganger"
            config_path = config_dir / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}

            # GitHub settings
            if "github" in config_data:
                gh = config_data["github"]
                settings.github = GitHubSettings(
                    auth_method=gh.get("auth_method", "auto"),
                    token=gh.get("token"),
                    cache_enabled=gh.get("cache_enabled", True),
                    cache_ttl=gh.get("cache_ttl", 3600),
                    rate_limit_buffer=gh.get("rate_limit_buffer", 100),
                )

            # Cache settings
            if "cache" in config_data:
                cache = config_data["cache"]
                settings.cache = CacheSettings(
                    db_path=cache.get("db_path", "~/.cache/ganger/ganger.db"),
                    repos_ttl=cache.get("repos_ttl", 3600),
                    metadata_ttl=cache.get("metadata_ttl", 86400),
                    readme_ttl=cache.get("readme_ttl", 604800),
                    load_on_startup=cache.get("load_on_startup", False),
                )

            # Folder settings
            if "folders" in config_data:
                folders = config_data["folders"]
                settings.folders = FolderSettings(
                    default_folders=folders.get("default_folders", [])
                )

            # Behavior settings
            if "behavior" in config_data:
                behavior = config_data["behavior"]
                settings.behavior = BehaviorSettings(
                    confirm_unstar=behavior.get("confirm_unstar", True),
                    auto_refresh=behavior.get("auto_refresh", False),
                    sort_order=behavior.get("sort_order", "stars"),
                    auto_categorize=behavior.get("auto_categorize", True),
                )

            # MCP settings
            if "mcp" in config_data:
                mcp = config_data["mcp"]
                settings.mcp = MCPSettings(
                    name=mcp.get("name", "ganger"),
                    enable_session_state=mcp.get("enable_session_state", True),
                    max_history=mcp.get("max_history", 50),
                )

        # Override with environment variables
        github_token = os.getenv("GITHUB_TOKEN")
        if github_token:
            settings.github.token = github_token

        cache_path_env = os.getenv("GANGER_CACHE_PATH")
        if cache_path_env:
            settings.cache.db_path = cache_path_env

        cache_ttl_env = os.getenv("GANGER_CACHE_TTL")
        if cache_ttl_env:
            settings.cache.repos_ttl = int(cache_ttl_env)

        return settings

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            "github": {
                "auth_method": self.github.auth_method,
                "cache_enabled": self.github.cache_enabled,
                "cache_ttl": self.github.cache_ttl,
                "rate_limit_buffer": self.github.rate_limit_buffer,
            },
            "cache": {
                "db_path": self.cache.db_path,
                "repos_ttl": self.cache.repos_ttl,
                "metadata_ttl": self.cache.metadata_ttl,
                "readme_ttl": self.cache.readme_ttl,
            },
            "folders": {"default_folders": self.folders.default_folders},
            "behavior": {
                "confirm_unstar": self.behavior.confirm_unstar,
                "auto_refresh": self.behavior.auto_refresh,
                "sort_order": self.behavior.sort_order,
                "auto_categorize": self.behavior.auto_categorize,
            },
            "mcp": {
                "name": self.mcp.name,
                "enable_session_state": self.mcp.enable_session_state,
                "max_history": self.mcp.max_history,
            },
        }


def get_config_dir() -> Path:
    """Get configuration directory, creating if needed."""
    config_dir = Path.home() / ".config" / "ganger"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_cache_dir() -> Path:
    """Get cache directory, creating if needed."""
    cache_dir = Path.home() / ".cache" / "ganger"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
