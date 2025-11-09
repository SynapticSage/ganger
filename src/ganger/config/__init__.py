"""
Configuration management for Ganger.

Handles loading and merging configuration from multiple sources:
- Default settings
- User config file (~/.config/ganger/config.yaml)
- Environment variables

Modified: 2025-11-07
"""

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

__all__ = [
    "Settings",
    "GitHubSettings",
    "CacheSettings",
    "FolderSettings",
    "BehaviorSettings",
    "MCPSettings",
    "get_config_dir",
    "get_cache_dir",
]
