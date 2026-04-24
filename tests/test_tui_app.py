"""Targeted tests for TUI configuration resolution."""

from pathlib import Path

import yaml

from ganger.tui.app import GangerApp


class TestGangerAppConfig:
    """Test non-interactive TUI configuration helpers."""

    def test_uses_config_dir_for_settings_and_token_file(self, tmp_path):
        """A custom config dir should drive the config file and token file locations."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "github": {
                        "auth_method": "pat",
                        "token": "cfg_token",
                    },
                    "cache": {
                        "db_path": "cache/custom.db",
                    },
                }
            )
        )

        app = GangerApp(config_dir=tmp_path)

        assert app.settings.github.auth_method == "pat"
        assert app.settings.github.token == "cfg_token"
        assert app._resolve_token_file() == tmp_path / "token.json"
        assert app._resolve_cache_path() == tmp_path / "cache" / "custom.db"

    def test_custom_config_dir_defaults_cache_into_that_root(self, tmp_path):
        """Without an explicit cache override, a custom config dir gets its own cache db."""
        app = GangerApp(config_dir=tmp_path)

        assert app._resolve_cache_path() == tmp_path / "cache.db"
