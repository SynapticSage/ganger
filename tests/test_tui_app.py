"""Targeted tests for TUI configuration resolution."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from textual.app import App, ComposeResult
from textual.widgets import Static

from ganger.core.models import StarredRepo, VirtualFolder
from ganger.tui.app import GangerApp
from ganger.tui.messages import FolderSelected, RepoSelected
from ganger.tui.ui.miller_view import FolderColumn, PreviewPane, RepoColumn


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


class FolderColumnApp(App[None]):
    def __init__(self):
        super().__init__()
        self.folder_selected_count = 0

    def compose(self) -> ComposeResult:
        yield FolderColumn(id="folder-column")

    async def on_folder_selected(self, message: FolderSelected) -> None:
        self.folder_selected_count += 1


class RepoColumnApp(App[None]):
    def __init__(self):
        super().__init__()
        self.repo_selected_count = 0

    def compose(self) -> ComposeResult:
        yield RepoColumn(id="repo-column")

    async def on_repo_selected(self, message: RepoSelected) -> None:
        self.repo_selected_count += 1


class PreviewPaneApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PreviewPane(id="preview-pane")


@pytest.mark.asyncio
async def test_folder_column_refresh_does_not_emit_selection_messages():
    """Refreshing folder summaries should not resubmit folder-selection events."""
    folders = [VirtualFolder(id="all-stars", name="All Stars", repo_count=10)]

    app = FolderColumnApp()
    async with app.run_test() as pilot:
        column = app.query_one(FolderColumn)
        await column.set_folders(folders)
        await pilot.pause()
        await column.set_folders(folders)
        await pilot.pause()

    assert app.folder_selected_count == 0


@pytest.mark.asyncio
async def test_repo_column_refresh_emits_single_preview_selection():
    """Repo refreshes should emit one `RepoSelected` event, not a watcher duplicate."""
    repos = [
        StarredRepo(
            id="1",
            full_name="octocat/Hello-World",
            name="Hello-World",
            owner="octocat",
            description="Hello world",
            stars_count=42,
        )
    ]

    app = RepoColumnApp()
    async with app.run_test() as pilot:
        column = app.query_one(RepoColumn)
        await column.set_repos(repos)
        await pilot.pause()
        await column.set_repos(repos)
        await pilot.pause()

    assert app.repo_selected_count == 2


@pytest.mark.asyncio
async def test_preview_pane_handles_repo_text_without_markup_crashing():
    """Preview rendering should tolerate repo text that looks like Rich markup."""
    repo = StarredRepo(
        id="1",
        full_name="octocat/Hello-[World]",
        name="Hello-[World]",
        owner="octo[tag]",
        description="Repo with [broken markup] and stray [brackets",
        stars_count=42,
        forks_count=7,
        language="Python",
        topics=["[topic]", "plain"],
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        starred_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        url="https://github.com/octocat/Hello-World",
    )

    app = PreviewPaneApp()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        await pane.show_repo(repo)
        await pilot.pause()

        preview = pane.query_one(Static)
        assert "Repo with [broken markup]" in str(preview.renderable)


@pytest.mark.asyncio
async def test_handle_exception_surfaces_real_error_without_rich_cascade(
    tmp_path, capsys
):
    """GangerApp._handle_exception should write the raw traceback to stderr
    instead of invoking Textual's Rich/Pygments-based renderer, so the real
    error isn't buried under an `uncompilable regex` cascade."""
    app = GangerApp(config_dir=tmp_path)

    try:
        raise RuntimeError("bang from a widget callback")
    except RuntimeError as exc:
        app._handle_exception(exc)

    captured = capsys.readouterr()
    assert "Ganger unhandled exception" in captured.err
    assert "RuntimeError" in captured.err
    assert "bang from a widget callback" in captured.err
    assert "uncompilable regex" not in captured.err
    assert "Pygments" not in captured.err
    assert app._return_code == 1


@pytest.mark.asyncio
async def test_repo_column_handles_repo_text_without_markup_crashing():
    """RepoColumn rows render literal brackets in name/owner/language."""
    repos = [
        StarredRepo(
            id="1",
            full_name="octo[tag]/Hello-[World]",
            name="Hello-[World]",
            owner="octo[tag]",
            description="d",
            stars_count=42,
            language="Python",
        )
    ]

    app = RepoColumnApp()
    async with app.run_test() as pilot:
        column = app.query_one(RepoColumn)
        await column.set_repos(repos)
        await pilot.pause()

        items = list(column.query(".repo-item"))
        assert items, "expected a repo-item Static to be mounted"
        rendered = "\n".join(str(item.renderable) for item in items)
        assert "Hello-[World]" in rendered
        assert "octo[tag]" in rendered
        assert "[Python]" in rendered
