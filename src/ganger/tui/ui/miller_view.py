"""Miller column view implementation for Ganger.

Three-column layout inspired by ranger and macOS Finder's column view.

Modified: 2025-11-08
Adapted from yanger/ui/miller_view.py
"""

from typing import List, Optional
import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.widgets import Static, LoadingIndicator
from textual.reactive import reactive
from textual.widget import Widget
from textual import events

from ...core.models import VirtualFolder, StarredRepo
from ..messages import FolderSelected, RepoSelected, RangerCommand, SelectionChanged
from .search_input import SearchHighlighter


class FolderColumn(ScrollableContainer):
    """Left column showing virtual folders."""

    DEFAULT_CSS = """
    FolderColumn {
        width: 1fr;
        height: 100%;
        border-right: solid $accent;
        padding: 0 1;
    }

    FolderColumn > .folder-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    FolderColumn > .folder-item.selected {
        background: $primary;
        color: $text;
    }

    FolderColumn > .folder-item.focused {
        background: $accent;
        text-style: bold;
    }

    FolderColumn > .folder-item.search-match {
        background: $warning-darken-2;
    }

    FolderColumn > .loading {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """

    selected_index = reactive(0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folders: List[VirtualFolder] = []
        self.can_focus = True
        self.search_query = ""
        self.search_matches: List[int] = []

    def compose(self) -> ComposeResult:
        """Initial composition."""
        yield Static("Loading folders...", classes="loading")

    async def set_folders(self, folders: List[VirtualFolder]) -> None:
        """Set the folders to display."""
        self.folders = folders
        await self.refresh_display()

    async def refresh_display(self) -> None:
        """Refresh the folder display."""
        # Clear existing content
        await self.remove_children()

        if not self.folders:
            await self.mount(Static("No folders", classes="loading"))
            return

        # Add folder items
        for i, folder in enumerate(self.folders):
            classes = ["folder-item"]
            if i == self.selected_index:
                classes.append("selected")
            if i in self.search_matches:
                classes.append("search-match")

            item = Static(
                f"📁 {folder.name} ({folder.repo_count})",
                classes=" ".join(classes)
            )
            item.folder = folder  # Attach folder data
            await self.mount(item)

    def watch_selected_index(self, old_value: int, new_value: int) -> None:
        """React to selection changes."""
        # Update visual selection
        items = self.query(".folder-item")
        for i, item in enumerate(items):
            if i == old_value:
                item.remove_class("selected")
            if i == new_value:
                item.add_class("selected")

        # Notify parent
        if 0 <= new_value < len(self.folders):
            self.post_message(
                FolderSelected(self.folders[new_value])
            )

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.folders:
            return

        new_index = self.selected_index + delta
        new_index = max(0, min(new_index, len(self.folders) - 1))
        self.selected_index = new_index

        # Scroll to show selected item
        items = self.query(".folder-item")
        if items and 0 <= new_index < len(items):
            self.scroll_to_widget(items[new_index])

    def select_first(self) -> None:
        """Select first folder (gg)."""
        self.selected_index = 0
        self.scroll_home()

    def select_last(self) -> None:
        """Select last folder (G)."""
        if self.folders:
            self.selected_index = len(self.folders) - 1
            self.scroll_end()

    def get_selected_folder(self) -> Optional[VirtualFolder]:
        """Get the currently selected folder."""
        if 0 <= self.selected_index < len(self.folders):
            return self.folders[self.selected_index]
        return None


class RepoColumn(ScrollableContainer):
    """Middle column showing repos in the selected folder."""

    DEFAULT_CSS = """
    RepoColumn {
        width: 1fr;
        height: 100%;
        border-right: solid $accent;
        padding: 0 1;
    }

    RepoColumn > .repo-item {
        width: 100%;
        height: 3;
        padding: 0 1;
    }

    RepoColumn > .repo-item.selected {
        background: $primary;
        color: $text;
    }

    RepoColumn > .repo-item.focused {
        background: $accent;
        text-style: bold;
    }

    RepoColumn > .repo-item.marked {
        color: $warning;
    }

    RepoColumn > .repo-item.search-match {
        background: $warning-darken-2;
    }

    RepoColumn > .loading {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }

    RepoColumn .repo-name {
        text-style: bold;
    }

    RepoColumn .repo-meta {
        color: $text-muted;
    }
    """

    selected_index = reactive(0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.repos: List[StarredRepo] = []
        self.marked_repos: set[str] = set()
        self.can_focus = True
        self.visual_mode = False
        self.visual_start_index: Optional[int] = None
        self.search_query = ""
        self.search_matches: List[int] = []

    def compose(self) -> ComposeResult:
        """Initial composition."""
        yield Static("Select a folder", classes="loading")

    async def set_repos(self, repos: List[StarredRepo]) -> None:
        """Set the repos to display."""
        self.repos = repos
        await self.refresh_display()

    async def refresh_display(self) -> None:
        """Refresh the repo display."""
        # Clear existing content
        await self.remove_children()

        if not self.repos:
            await self.mount(Static("No repos in this folder", classes="loading"))
            return

        # Add repo items
        for i, repo in enumerate(self.repos):
            classes = ["repo-item"]
            if i == self.selected_index:
                classes.append("selected")
            if repo.id in self.marked_repos:
                classes.append("marked")
            if i in self.search_matches:
                classes.append("search-match")

            # Format repo display
            mark = "✓" if repo.id in self.marked_repos else " "
            stars = f"⭐ {repo.stars_count:,}" if repo.stars_count else ""
            language = f"[{repo.language}]" if repo.language else ""

            # Line 1: Mark + Name + Stars
            line1 = f"{mark} {repo.name} {stars}"
            # Line 2: Owner + Language
            line2 = f"  @{repo.owner} {language}"

            content = f"{line1}\n{line2}"

            item = Static(content, classes=" ".join(classes))
            item.repo = repo  # Attach repo data
            await self.mount(item)

    def watch_selected_index(self, old_value: int, new_value: int) -> None:
        """React to selection changes."""
        # Update visual selection
        items = self.query(".repo-item")
        for i, item in enumerate(items):
            if i == old_value:
                item.remove_class("selected")
            if i == new_value:
                item.add_class("selected")

        # Notify parent
        if 0 <= new_value < len(self.repos):
            self.post_message(
                RepoSelected(self.repos[new_value])
            )

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.repos:
            return

        new_index = self.selected_index + delta
        new_index = max(0, min(new_index, len(self.repos) - 1))
        self.selected_index = new_index

        # Scroll to show selected item
        items = self.query(".repo-item")
        if items and 0 <= new_index < len(items):
            self.scroll_to_widget(items[new_index])

    def select_first(self) -> None:
        """Select first repo (gg)."""
        self.selected_index = 0
        self.scroll_home()

    def select_last(self) -> None:
        """Select last repo (G)."""
        if self.repos:
            self.selected_index = len(self.repos) - 1
            self.scroll_end()

    def toggle_mark(self) -> None:
        """Toggle mark on current repo."""
        if 0 <= self.selected_index < len(self.repos):
            repo = self.repos[self.selected_index]
            if repo.id in self.marked_repos:
                self.marked_repos.remove(repo.id)
            else:
                self.marked_repos.add(repo.id)

            # Update display
            items = self.query(".repo-item")
            if 0 <= self.selected_index < len(items):
                item = items[self.selected_index]
                if repo.id in self.marked_repos:
                    item.add_class("marked")
                else:
                    item.remove_class("marked")

            # Notify parent
            self.post_message(SelectionChanged(len(self.marked_repos)))

    def get_marked_repos(self) -> List[StarredRepo]:
        """Get list of marked repos."""
        return [repo for repo in self.repos if repo.id in self.marked_repos]

    def get_selected_repo(self) -> Optional[StarredRepo]:
        """Get the currently selected repo."""
        if 0 <= self.selected_index < len(self.repos):
            return self.repos[self.selected_index]
        return None


class PreviewPane(ScrollableContainer):
    """Right column showing repo preview."""

    DEFAULT_CSS = """
    PreviewPane {
        width: 2fr;
        height: 100%;
        padding: 1 2;
    }

    PreviewPane .preview-header {
        text-style: bold;
        margin-bottom: 1;
    }

    PreviewPane .preview-meta {
        color: $text-muted;
        margin-bottom: 1;
    }

    PreviewPane .preview-section {
        margin-top: 1;
        margin-bottom: 1;
    }

    PreviewPane .loading {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_repo: Optional[StarredRepo] = None

    def compose(self) -> ComposeResult:
        """Initial composition."""
        yield Static("Select a repo to preview", classes="loading")

    async def show_repo(self, repo: StarredRepo) -> None:
        """Display repo information."""
        self.current_repo = repo

        # Clear existing content
        await self.remove_children()

        # Build preview content
        lines = []

        # Header
        lines.append(f"[bold]{repo.name}[/bold]")
        lines.append(f"@{repo.owner}/{repo.name}")
        lines.append("")

        # Metadata
        stars = f"⭐ {repo.stars_count:,}" if repo.stars_count else ""
        forks = f"🍴 {repo.forks_count:,}" if repo.forks_count else ""
        language = f"📝 {repo.language}" if repo.language else ""
        lines.append(f"{stars}  {forks}  {language}")
        lines.append("")

        # Description
        if repo.description:
            lines.append("[bold]Description[/bold]")
            lines.append(repo.description)
            lines.append("")

        # Topics
        if repo.topics:
            lines.append("[bold]Topics[/bold]")
            topics_str = ", ".join(f"#{topic}" for topic in repo.topics[:5])
            lines.append(topics_str)
            lines.append("")

        # Dates
        lines.append("[bold]Info[/bold]")
        if repo.created_at:
            lines.append(f"Created: {repo.created_at.strftime('%Y-%m-%d')}")
        if repo.updated_at:
            lines.append(f"Updated: {repo.updated_at.strftime('%Y-%m-%d')}")
        if repo.starred_at:
            lines.append(f"Starred: {repo.starred_at.strftime('%Y-%m-%d')}")
        lines.append("")

        # URL
        lines.append(f"[link={repo.url}]{repo.url}[/link]")

        # TODO: Fetch and display README

        content = "\n".join(lines)
        await self.mount(Static(content, markup=True))


class MillerView(Widget):
    """Three-column Miller view container."""

    DEFAULT_CSS = """
    MillerView {
        layout: horizontal;
        width: 100%;
        height: 100%;
    }
    """

    # Track which column has focus (0=folders, 1=repos, 2=preview)
    focused_column = reactive(0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folder_column: Optional[FolderColumn] = None
        self.repo_column: Optional[RepoColumn] = None
        self.preview_pane: Optional[PreviewPane] = None

    def compose(self) -> ComposeResult:
        """Create the three columns."""
        self.folder_column = FolderColumn(id="folder-column")
        self.repo_column = RepoColumn(id="repo-column")
        self.preview_pane = PreviewPane(id="preview-pane")

        # Three columns
        with Horizontal():
            yield self.folder_column
            yield self.repo_column
            yield self.preview_pane

    async def set_folders(self, folders: List[VirtualFolder]) -> None:
        """Set folders in the left column."""
        if self.folder_column:
            await self.folder_column.set_folders(folders)

    async def set_repos(self, repos: List[StarredRepo]) -> None:
        """Set repos in the middle column."""
        if self.repo_column:
            await self.repo_column.set_repos(repos)

    async def update_preview(self, repo: StarredRepo) -> None:
        """Update preview pane with repo info."""
        if self.preview_pane:
            await self.preview_pane.show_repo(repo)

    def get_marked_count(self) -> int:
        """Get count of marked repos."""
        if self.repo_column:
            return len(self.repo_column.marked_repos)
        return 0

    def watch_focused_column(self, old_value: int, new_value: int) -> None:
        """Update focus styling when column focus changes."""
        columns = [self.folder_column, self.repo_column, self.preview_pane]

        # Remove focus from old column
        if 0 <= old_value < len(columns) and columns[old_value]:
            columns[old_value].remove_class("focused")

        # Add focus to new column
        if 0 <= new_value < len(columns) and columns[new_value]:
            columns[new_value].add_class("focused")
            columns[new_value].focus()

    async def handle_navigation(self, key: str) -> bool:
        """Handle vim-style navigation keys.

        Returns:
            True if key was handled, False otherwise
        """
        if key == "h":
            # Move left
            if self.focused_column > 0:
                self.focused_column -= 1
            return True

        elif key == "l":
            # Move right
            if self.focused_column < 2:
                self.focused_column += 1
            return True

        elif key == "j":
            # Move down in current column
            if self.focused_column == 0 and self.folder_column:
                self.folder_column.move_selection(1)
            elif self.focused_column == 1 and self.repo_column:
                self.repo_column.move_selection(1)
            return True

        elif key == "k":
            # Move up in current column
            if self.focused_column == 0 and self.folder_column:
                self.folder_column.move_selection(-1)
            elif self.focused_column == 1 and self.repo_column:
                self.repo_column.move_selection(-1)
            return True

        elif key == "space":
            # Toggle mark (only in repo column)
            if self.focused_column == 1 and self.repo_column:
                self.repo_column.toggle_mark()
            return True

        return False

    # Message handlers

    async def on_folder_selected(self, message: FolderSelected) -> None:
        """Handle folder selection."""
        # TODO: Load repos for the selected folder
        pass

    async def on_repo_selected(self, message: RepoSelected) -> None:
        """Handle repo selection."""
        # Update preview
        await self.update_preview(message.repo)
