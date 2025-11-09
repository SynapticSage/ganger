"""Main Ganger TUI application.

Coordinates the overall application flow and UI components.

Modified: 2025-11-08
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Static
from textual.reactive import reactive
from textual import events

from ..core.auth import GitHubAuth
from ..core.github_client import GitHubAPIClient
from ..core.cache import PersistentCache
from ..core.folder_manager import FolderManager
from ..core.models import VirtualFolder, StarredRepo, Clipboard

from .ui.status_bar import StatusBar
from .ui.help_overlay import HelpOverlay
from .ui.command_input import CommandInput, parse_command
from .ui.search_input import SearchInput
from .ui.miller_view import MillerView

from .messages import (
    FolderSelected,
    RepoSelected,
    RangerCommand,
    SearchQuery,
    RefreshRequested,
    ClipboardOperation,
    SelectionChanged,
    StatusMessage,
    ErrorMessage,
    RateLimitUpdate,
)
from .ui.modals import FolderCreationModal, FolderCreated

from .keybindings import registry
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class GangerApp(App):
    """Main application class for Ganger."""

    CSS_PATH = "app.tcss"
    TITLE = "Ganger"
    SUB_TITLE = "GitHub Stars Manager"

    # Keybindings
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("?", "help", "Help"),
        Binding(":", "command_mode", "Command"),
        Binding("/", "search", "Search"),
        Binding("u", "undo", "Undo"),
        Binding("U", "redo", "Redo"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+shift+r", "refresh_all", "Refresh All"),
        Binding("ctrl+q", "force_quit", "Force Quit", show=False),
    ]

    # Note: gn (create folder) and gd (delete folder) are handled in on_key() as double-key commands

    # Reactive attributes
    show_help = reactive(False)
    command_mode = reactive(False)

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        use_cache: bool = True,
    ):
        """Initialize the application.

        Args:
            config_dir: Configuration directory path
            use_cache: Whether to use offline cache
        """
        super().__init__()

        self.config_dir = config_dir or Path.home() / ".config" / "ganger"
        self.use_cache = use_cache

        # Core components (initialized in on_mount)
        self.auth: Optional[GitHubAuth] = None
        self.api_client: Optional[GitHubAPIClient] = None
        self.cache: Optional[PersistentCache] = None
        self.folder_manager: Optional[FolderManager] = None
        self._clipboard = Clipboard()

        # Data
        self.folders: List[VirtualFolder] = []
        self.current_folder: Optional[VirtualFolder] = None
        self.current_repos: List[StarredRepo] = []
        self.current_repo: Optional[StarredRepo] = None
        self.folders_loaded: bool = False

        # Settings
        self.settings = Settings.load()

        # Ranger command state
        self._pending_command: Optional[str] = None

        # UI components
        self.miller_view: Optional[MillerView] = None
        self.status_bar: Optional[StatusBar] = None
        self.help_overlay: Optional[HelpOverlay] = None
        self.command_input: Optional[CommandInput] = None
        self.search_input: Optional[SearchInput] = None

    def compose(self) -> ComposeResult:
        """Create the application layout."""
        yield Header()

        # Main content area (MillerView will be added here)
        with Container(id="main-container"):
            yield Static("Initializing...", id="loading-message")

        # Search input (hidden by default, docked at top)
        self.search_input = SearchInput(
            on_search=lambda query: self.post_message(SearchQuery(query)),
            on_cancel=self.cancel_search,
            id="search-input"
        )
        yield self.search_input

        # Command input (hidden by default, docked at bottom)
        self.command_input = CommandInput(
            on_submit=lambda cmd: self.call_later(self.execute_command, cmd),
            on_cancel=self.cancel_command,
            id="command-input"
        )
        yield self.command_input

        # Status bar at bottom
        yield StatusBar(id="status-bar")

        # Help overlay (hidden by default)
        self.help_overlay = HelpOverlay()
        yield self.help_overlay

    async def on_mount(self) -> None:
        """Initialize the application after mounting."""
        try:
            # Load CSS
            await self._load_stylesheet()

            # Setup authentication
            await self.setup_authentication()

            # Initialize cache
            cache_path = self.config_dir / "cache.db"
            self.cache = PersistentCache(
                db_path=cache_path,
                ttl_seconds=self.settings.cache.repos_ttl
            )
            await self.cache.initialize()

            # Initialize folder manager
            self.folder_manager = FolderManager(self.cache)

            # Create and mount MillerView
            loading_msg = self.query_one("#loading-message")
            await loading_msg.remove()

            container = self.query_one("#main-container")
            self.miller_view = MillerView(id="miller-view")
            await container.mount(self.miller_view)

            # Get status bar reference
            self.status_bar = self.query_one("#status-bar", StatusBar)

            # Load initial data
            if self.api_client:
                # Always load data if authenticated
                await self.initialize_data()
            else:
                # Offline mode - just load cached folders
                await self.load_folders()
                if self.status_bar:
                    self.status_bar.update_status(
                        "Offline mode - Ctrl+R to sync",
                        ""
                    )
                self.notify("Offline mode. Press Ctrl+R when authenticated.", timeout=5)

        except Exception as e:
            logger.error(f"Error during initialization: {e}", exc_info=True)
            self.notify(f"Initialization error: {e}", severity="error")
            self.exit(1)

    async def _load_stylesheet(self) -> None:
        """Load application stylesheet."""
        try:
            from pathlib import Path as _Path
            candidates = [
                _Path(__file__).with_name("app.tcss"),
                _Path.cwd() / "src" / "ganger" / "tui" / "app.tcss",
                _Path.cwd() / "app.tcss",
            ]
            for css_path in candidates:
                if css_path.is_file():
                    self.stylesheet.read(css_path)
                    logger.info(f"Loaded stylesheet from {css_path}")
                    break
        except Exception as e:
            logger.warning(f"Could not load stylesheet: {e}")

    async def setup_authentication(self) -> None:
        """Setup GitHub API authentication."""
        try:
            self.auth = GitHubAuth()
            # Run blocking authentication in thread pool to avoid blocking event loop
            await asyncio.to_thread(self.auth.authenticate)
            token = self.auth.get_token()

            if not token:
                raise ValueError("Authentication failed")

            self.api_client = GitHubAPIClient(
                auth=self.auth,
                rate_limit_buffer=self.settings.github.rate_limit_buffer
            )

            logger.info("GitHub authentication successful")

        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            self.notify(
                f"GitHub authentication failed: {e}.\n"
                "Running in offline mode. Press Ctrl+C to exit.",
                severity="warning",
                timeout=10
            )
            # Don't raise - continue in offline mode
            # User can still view help, keybindings, etc.

    async def initialize_data(self, force_refresh: bool = False) -> None:
        """Load initial data (starred repos, folders).

        Args:
            force_refresh: Force fetch from GitHub API
        """
        try:
            if not self.api_client or not self.folder_manager:
                logger.error("API client or folder manager not initialized")
                return

            self.notify("Loading starred repositories...", timeout=2)

            # Create data loader
            from ..core.data_loader import DataLoader
            loader = DataLoader(
                self.api_client,
                self.cache,
                self.folder_manager,
                self.settings
            )

            # Load starred repos (from cache or API)
            repos = await loader.load_starred_repos(force_refresh=force_refresh)
            self.notify(f"Loaded {len(repos)} starred repos", timeout=2)

            # Ensure default folders exist
            folders = await loader.ensure_default_folders()
            logger.info(f"Ensured {len(folders)} default folders exist")

            # Sync "All Stars" folder
            await loader.sync_all_stars_folder(repos)

            # Auto-categorize if enabled
            if self.settings.behavior.auto_categorize:
                self.notify("Auto-categorizing repos...", timeout=1)
                await loader.auto_categorize_all(repos)

            # Load folders into UI
            await self.load_folders()

            # Auto-select "All Stars" folder
            if self.miller_view and self.miller_view.folder_column:
                # Select first folder (should be "All Stars")
                self.miller_view.folder_column.selected_index = 0
                # Trigger folder selection to load repos
                if self.folders:
                    self.post_message(FolderSelected(self.folders[0]))

            self.notify("Ready!", timeout=1)

        except Exception as e:
            logger.error(f"Error loading data: {e}", exc_info=True)
            self.notify(f"Error loading data: {e}", severity="error", timeout=10)

    async def load_folders(self) -> None:
        """Load virtual folders and starred repos."""
        try:
            if not self.folder_manager:
                logger.error("Folder manager not initialized")
                return

            # Get all folders
            self.folders = await self.folder_manager.get_all_folders()

            # Update MillerView with folders
            if self.miller_view:
                await self.miller_view.set_folders(self.folders)

            self.folders_loaded = True

            if self.status_bar:
                self.status_bar.update_status(
                    f"Loaded {len(self.folders)} folders",
                    ""
                )

            logger.info(f"Loaded {len(self.folders)} folders")

        except Exception as e:
            logger.error(f"Error loading folders: {e}", exc_info=True)
            self.notify(f"Error loading folders: {e}", severity="error")

    # Action handlers

    def action_help(self) -> None:
        """Toggle help overlay."""
        if self.help_overlay:
            if self.show_help:
                self.help_overlay.hide()
            else:
                self.help_overlay.show()
            self.show_help = not self.show_help

    def action_command_mode(self) -> None:
        """Enter command mode."""
        if self.command_input:
            self.command_input.show()
            self.command_mode = True

    def action_search(self) -> None:
        """Enter search mode."""
        if self.search_input:
            self.search_input.show()

    def action_refresh(self) -> None:
        """Refresh current view."""
        self.post_message(RefreshRequested(refresh_all=False))

    def action_refresh_all(self) -> None:
        """Refresh all data."""
        self.post_message(RefreshRequested(refresh_all=True))

    def action_undo(self) -> None:
        """Undo last operation."""
        # TODO: Implement undo/redo
        self.notify("Undo not yet implemented", timeout=2)

    def action_redo(self) -> None:
        """Redo last undone operation."""
        # TODO: Implement undo/redo
        self.notify("Redo not yet implemented", timeout=2)

    def action_force_quit(self) -> None:
        """Force quit the application."""
        self.exit()

    async def action_create_folder(self) -> None:
        """Show folder creation modal."""
        await self.push_screen(FolderCreationModal())

    async def action_delete_folder(self) -> None:
        """Delete the currently selected folder if empty."""
        try:
            if not self.current_folder or not self.folder_manager:
                return

            # Check if folder is empty
            repos = await self.folder_manager.get_folder_repos(self.current_folder.id)
            if repos:
                self.notify(
                    f"Cannot delete '{self.current_folder.name}': folder contains {len(repos)} repo(s)",
                    severity="warning",
                    timeout=3
                )
                return

            # Don't allow deleting "All Stars"
            if self.current_folder.id == "all-stars":
                self.notify("Cannot delete 'All Stars' folder", severity="warning")
                return

            # Delete folder
            await self.cache.delete_virtual_folder(self.current_folder.id)

            # Refresh folders
            await self.load_folders()

            # Auto-select first folder
            if self.miller_view and self.miller_view.folder_column and self.folders:
                self.miller_view.folder_column.selected_index = 0
                self.post_message(FolderSelected(self.folders[0]))

            self.notify(f"Deleted folder '{self.current_folder.name}'", timeout=2)
            self.current_folder = None

        except Exception as e:
            logger.error(f"Error deleting folder: {e}", exc_info=True)
            self.notify(f"Error deleting folder: {e}", severity="error")

    # Command execution

    def cancel_command(self) -> None:
        """Cancel command mode."""
        self.command_mode = False

    def cancel_search(self) -> None:
        """Cancel search mode."""
        pass  # Search input handles hiding itself

    async def execute_command(self, command: str) -> None:
        """Execute a command from command mode.

        Args:
            command: Command string (e.g., ':sort stars desc')
        """
        try:
            cmd_name, args = parse_command(command)

            if not cmd_name:
                return

            # Look up command handler
            cmd = registry.get_command(cmd_name)
            if not cmd:
                self.notify(f"Unknown command: {cmd_name}", severity="error")
                return

            # Handle built-in commands
            if cmd_name == "quit" or cmd_name == "q":
                self.exit()
            elif cmd_name == "help":
                self.action_help()
            else:
                # TODO: Implement command handlers
                self.notify(f"Command '{cmd_name}' not yet implemented", timeout=2)

        except Exception as e:
            logger.error(f"Error executing command '{command}': {e}", exc_info=True)
            self.notify(f"Error: {e}", severity="error")

    # Message handlers

    async def on_status_message(self, message: StatusMessage) -> None:
        """Handle status messages."""
        if self.status_bar:
            self.status_bar.show_message(message.message, duration=message.duration)

    async def on_error_message(self, message: ErrorMessage) -> None:
        """Handle error messages."""
        self.notify(message.message, severity="error", timeout=5)

    async def on_rate_limit_update(self, message: RateLimitUpdate) -> None:
        """Handle rate limit updates."""
        if self.status_bar:
            rate_str = f"{message.remaining}/{message.total}"
            self.status_bar.update_status("", rate_str)

    async def on_refresh_requested(self, message: RefreshRequested) -> None:
        """Handle refresh requests."""
        try:
            if message.refresh_all:
                # Force refresh from GitHub API
                self.notify("Syncing with GitHub...", timeout=2)
                await self.initialize_data(force_refresh=True)
            else:
                # Just refresh current view
                if self.current_folder:
                    repos = await self.folder_manager.get_folder_repos(self.current_folder.id)
                    if self.miller_view:
                        await self.miller_view.set_repos(repos)

                self.notify("Refreshed", timeout=1)

        except Exception as e:
            logger.error(f"Refresh error: {e}", exc_info=True)
            self.notify(f"Refresh error: {e}", severity="error")

    async def on_folder_selected(self, message: FolderSelected) -> None:
        """Handle folder selection - load repos for the folder."""
        try:
            if not self.folder_manager:
                return

            self.current_folder = message.folder

            # Get repos in this folder
            self.current_repos = await self.folder_manager.get_folder_repos(message.folder.id)

            # Update MillerView
            if self.miller_view:
                await self.miller_view.set_repos(self.current_repos)

            # Update status bar
            if self.status_bar:
                self.status_bar.update_context(
                    message.folder.name,
                    selected_count=self.miller_view.get_marked_count() if self.miller_view else 0
                )

        except Exception as e:
            logger.error(f"Error loading repos for folder: {e}", exc_info=True)
            self.notify(f"Error loading repos: {e}", severity="error")

    async def on_repo_selected(self, message: RepoSelected) -> None:
        """Handle repo selection - update preview."""
        self.current_repo = message.repo

        # MillerView handles updating the preview pane itself

    async def on_selection_changed(self, message: SelectionChanged) -> None:
        """Handle selection count changes."""
        if self.status_bar and self.current_folder:
            self.status_bar.update_context(
                self.current_folder.name,
                selected_count=message.selected_count
            )

    async def on_folder_created(self, message: FolderCreated) -> None:
        """Handle folder creation."""
        try:
            if not self.folder_manager:
                return

            # Create folder ID from name
            folder_id = message.name.lower().replace(" ", "-")

            # Create virtual folder
            folder = VirtualFolder(
                id=folder_id,
                name=message.name,
                auto_tags=message.auto_tags,
                repo_count=0,
            )

            await self.cache.create_virtual_folder(folder)

            # Auto-categorize if tags provided
            if message.auto_tags and self.settings.behavior.auto_categorize:
                # Get all repos and categorize into this folder
                all_repos = await self.cache.get_starred_repos()
                if all_repos:
                    for repo in all_repos:
                        # Check if repo matches folder tags
                        if folder.auto_tags and repo.topics:
                            if any(tag in repo.topics for tag in folder.auto_tags):
                                await self.cache.add_repo_to_folder(
                                    repo_id=repo.id,
                                    folder_id=folder.id,
                                    is_manual=False
                                )

            # Refresh folders
            await self.load_folders()

            self.notify(f"Created folder '{folder.name}'", timeout=2)

        except Exception as e:
            logger.error(f"Error creating folder: {e}", exc_info=True)
            self.notify(f"Error creating folder: {e}", severity="error")

    async def on_search_query(self, message: SearchQuery) -> None:
        """Handle search query."""
        try:
            query = message.query.lower()

            if not query or not self.miller_view:
                # Clear search
                if self.miller_view:
                    if self.miller_view.folder_column:
                        self.miller_view.folder_column.search_matches = []
                        await self.miller_view.folder_column.refresh_display()
                    if self.miller_view.repo_column:
                        self.miller_view.repo_column.search_matches = []
                        await self.miller_view.repo_column.refresh_display()
                return

            # Search in current context
            if self.miller_view.focused_column == 0:
                # Search folders
                matches = []
                for i, folder in enumerate(self.folders):
                    if query in folder.name.lower():
                        matches.append(i)

                if self.miller_view.folder_column:
                    self.miller_view.folder_column.search_matches = matches
                    await self.miller_view.folder_column.refresh_display()

                self.notify(f"Found {len(matches)} folder(s)", timeout=2)

            elif self.miller_view.focused_column == 1:
                # Search repos
                matches = []
                for i, repo in enumerate(self.current_repos):
                    if (query in repo.name.lower() or
                        (repo.description and query in repo.description.lower()) or
                        query in repo.owner.lower()):
                        matches.append(i)

                if self.miller_view.repo_column:
                    self.miller_view.repo_column.search_matches = matches
                    await self.miller_view.repo_column.refresh_display()

                self.notify(f"Found {len(matches)} repo(s)", timeout=2)

        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            self.notify(f"Search error: {e}", severity="error")

    async def on_ranger_command(self, message: RangerCommand) -> None:
        """Handle ranger-style commands (dd, yy, pp)."""
        try:
            if not self.miller_view or not self.folder_manager:
                return

            repo_column = self.miller_view.repo_column
            if not repo_column:
                return

            if message.command == "copy":
                # yy - Copy marked repos (or current if none marked)
                repos = repo_column.get_marked_repos()
                if not repos:
                    selected = repo_column.get_selected_repo()
                    repos = [selected] if selected else []

                if repos:
                    self.folder_manager.clipboard_copy(
                        repos,
                        source_folder_id=self.current_folder.id if self.current_folder else None
                    )
                    self.notify(f"Copied {len(repos)} repo(s)", timeout=2)
                else:
                    self.notify("No repos to copy", timeout=2)

            elif message.command == "cut":
                # dd - Cut marked repos (or current if none marked)
                repos = repo_column.get_marked_repos()
                if not repos:
                    selected = repo_column.get_selected_repo()
                    repos = [selected] if selected else []

                if repos and self.current_folder:
                    self.folder_manager.clipboard_cut(repos, self.current_folder.id)
                    self.notify(f"Cut {len(repos)} repo(s)", timeout=2)
                elif not self.current_folder:
                    self.notify("Cannot cut: no folder selected", severity="warning")
                else:
                    self.notify("No repos to cut", timeout=2)

            elif message.command == "paste":
                # pp - Paste from clipboard
                if not self.current_folder:
                    self.notify("Cannot paste: no folder selected", severity="warning")
                    return

                status = self.folder_manager.clipboard_status()
                if status["is_empty"]:
                    self.notify("Clipboard is empty", timeout=2)
                    return

                count = await self.folder_manager.clipboard_paste(self.current_folder.id)

                # Refresh folder display
                await self.load_folders()

                # Refresh current folder's repos
                if self.current_folder:
                    repos = await self.folder_manager.get_folder_repos(self.current_folder.id)
                    if self.miller_view:
                        await self.miller_view.set_repos(repos)

                operation = status["operation"]
                self.notify(f"{operation.capitalize()}d {count} repo(s)", timeout=2)

        except Exception as e:
            logger.error(f"Error handling ranger command '{message.command}': {e}", exc_info=True)
            self.notify(f"Error: {e}", severity="error")

    async def on_key(self, event: events.Key) -> None:
        """Handle keyboard events."""
        # Let MillerView handle navigation keys
        if self.miller_view:
            handled = await self.miller_view.handle_navigation(event.key)
            if handled:
                event.stop()
                return

        # Handle ranger double-key commands (gg, dd, yy, pp, etc.)
        if self._pending_command:
            command = self._pending_command + event.key
            self._pending_command = None

            if command == "gg":
                # Jump to top
                if self.miller_view:
                    if self.miller_view.focused_column == 0 and self.miller_view.folder_column:
                        self.miller_view.folder_column.select_first()
                    elif self.miller_view.focused_column == 1 and self.miller_view.repo_column:
                        self.miller_view.repo_column.select_first()
            elif command == "gn":
                # Create new folder
                await self.action_create_folder()
            elif command == "gd":
                # Delete folder (only if in folder column and folder is empty)
                if self.miller_view and self.miller_view.focused_column == 0:
                    await self.action_delete_folder()
            elif command == "dd":
                # Cut repos
                self.post_message(RangerCommand("cut"))
            elif command == "yy":
                # Copy repos
                self.post_message(RangerCommand("copy"))
            elif command == "pp":
                # Paste repos
                self.post_message(RangerCommand("paste"))

            event.stop()
            return

        # Check for first key of double-key commands
        if event.key in ["g", "d", "y", "p"]:
            self._pending_command = event.key
            event.stop()
            return


async def run_app(config_dir: Optional[Path] = None) -> None:
    """Run the Ganger TUI application.

    Args:
        config_dir: Optional configuration directory path
    """
    app = GangerApp(config_dir=config_dir)
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(run_app())
