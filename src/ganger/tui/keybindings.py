"""Central keybinding registry for Ganger.

Provides a single source of truth for all keybindings and commands.

Modified: 2025-11-08
Adapted from yanger/keybindings.py
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Callable
from enum import Enum


class KeyContext(Enum):
    """Context where a keybinding is active."""
    GLOBAL = "global"
    FOLDER = "folder"
    REPO = "repo"
    PREVIEW = "preview"
    VISUAL = "visual"
    SEARCH = "search"
    COMMAND = "command"


@dataclass
class Keybinding:
    """Represents a single keybinding."""
    key: str  # The key or key combination
    description: str  # Human-readable description
    context: KeyContext = KeyContext.GLOBAL  # Where this binding is active
    category: str = "General"  # Category for grouping in help
    hidden: bool = False  # Whether to show in help menu


@dataclass
class Command:
    """Represents a command (accessible via : mode)."""
    name: str  # Command name (e.g., "sort", "filter")
    description: str  # Human-readable description
    syntax: str  # Command syntax (e.g., ":sort [field] [order]")
    examples: List[str]  # Usage examples
    handler: Optional[Callable] = None  # Function to handle the command


class KeybindingRegistry:
    """Central registry for all keybindings and commands."""

    def __init__(self):
        self.keybindings: Dict[str, Keybinding] = {}
        self.commands: Dict[str, Command] = {}
        self._initialize_default_bindings()
        self._initialize_default_commands()

    def _initialize_default_bindings(self):
        """Initialize default keybindings."""

        # Global bindings
        self.register("q", "Quit application", KeyContext.GLOBAL, "Application")
        self.register("?", "Show this help", KeyContext.GLOBAL, "Application")
        self.register(":", "Enter command mode", KeyContext.GLOBAL, "Application")
        self.register("ctrl+r", "Refresh current view", KeyContext.GLOBAL, "Application")
        self.register("ctrl+shift+r", "Refresh all repos", KeyContext.GLOBAL, "Application")
        self.register("ctrl+q", "Force quit", KeyContext.GLOBAL, "Application", hidden=True)

        # Navigation
        self.register("h", "Move to left column", KeyContext.GLOBAL, "Navigation")
        self.register("j", "Move down", KeyContext.GLOBAL, "Navigation")
        self.register("k", "Move up", KeyContext.GLOBAL, "Navigation")
        self.register("l", "Move to right column", KeyContext.GLOBAL, "Navigation")
        self.register("gg", "Jump to top", KeyContext.GLOBAL, "Navigation")
        self.register("G", "Jump to bottom", KeyContext.GLOBAL, "Navigation")
        self.register("H", "History back", KeyContext.GLOBAL, "Navigation")
        self.register("L", "History forward", KeyContext.GLOBAL, "Navigation")
        self.register("enter", "Select item", KeyContext.GLOBAL, "Navigation")

        # Repo column specific
        self.register("space", "Toggle mark on current repo", KeyContext.REPO, "Selection")
        self.register("V", "Visual mode (range selection)", KeyContext.REPO, "Selection")
        self.register("v", "Invert selection", KeyContext.REPO, "Selection")
        self.register("uv", "Unmark all repos", KeyContext.REPO, "Selection")
        self.register("uV", "Visual unmark mode", KeyContext.REPO, "Selection")

        # Ranger commands (double-key)
        self.register("dd", "Cut selected/marked repos", KeyContext.REPO, "Operations")
        self.register("yy", "Copy selected/marked repos", KeyContext.REPO, "Operations")
        self.register("pp", "Paste repos from clipboard", KeyContext.REPO, "Operations")
        self.register("dD", "Unstar repo permanently", KeyContext.REPO, "Operations")

        # Undo/Redo
        self.register("u", "Undo last operation", KeyContext.GLOBAL, "Operations")
        self.register("U", "Redo last undone operation", KeyContext.GLOBAL, "Operations")

        # Search
        self.register("/", "Search in current list", KeyContext.GLOBAL, "Search")
        self.register("n", "Next search result", KeyContext.SEARCH, "Search")
        self.register("N", "Previous search result", KeyContext.SEARCH, "Search")
        self.register("escape", "Cancel search/visual mode", KeyContext.SEARCH, "Search")

        # Folder operations
        self.register("gn", "Create new virtual folder", KeyContext.GLOBAL, "Folder")
        self.register("gd", "Delete empty folder", KeyContext.FOLDER, "Folder")
        self.register("gm", "Merge folders", KeyContext.FOLDER, "Folder")
        self.register("cw", "Rename folder/repo", KeyContext.GLOBAL, "Operations")
        self.register("o", "Open sort menu", KeyContext.REPO, "Operations")

        # GitHub operations
        self.register("gb", "Open repo in browser", KeyContext.REPO, "GitHub")
        self.register("gc", "Clone repository", KeyContext.REPO, "GitHub")
        self.register("gi", "View issues", KeyContext.REPO, "GitHub")
        self.register("gp", "View pull requests", KeyContext.REPO, "GitHub")
        self.register("gr", "View README", KeyContext.REPO, "GitHub")
        self.register("gf", "Refresh repo metadata", KeyContext.REPO, "GitHub")
        self.register("gs", "Star/unstar toggle", KeyContext.REPO, "GitHub")
        self.register("gR", "Refresh all repos", KeyContext.GLOBAL, "GitHub")

        # Tag/categorization operations
        self.register("gt", "Manage tags/topics", KeyContext.REPO, "Tags")
        self.register("ga", "Auto-categorize by language/topic", KeyContext.GLOBAL, "Tags")

    def _initialize_default_commands(self):
        """Initialize default commands."""

        self.register_command(
            "move",
            "Move repo to folder",
            ":move <repo> <folder>",
            [
                ":move awesome-python 'Python Projects'",
                ":move 5-10 'AI/ML'"
            ]
        )

        self.register_command(
            "tag",
            "Add tags to repo",
            ":tag <repo> <tags...>",
            [
                ":tag pytorch machine-learning ai",
                ":tag textual python tui"
            ]
        )

        self.register_command(
            "sort",
            "Sort repos by field",
            ":sort <field> [order]",
            [
                ":sort stars desc",
                ":sort updated",
                ":sort created desc",
                ":sort name asc",
                ":sort language"
            ]
        )

        self.register_command(
            "filter",
            "Filter repos by criteria",
            ":filter <criteria>",
            [
                ":filter language:python",
                ":filter stars>1000",
                ":filter topic:machine-learning"
            ]
        )

        self.register_command(
            "export",
            "Export starred repos",
            ":export <format> [filename]",
            [
                ":export json stars.json",
                ":export markdown awesome-list.md",
                ":export csv repos.csv",
                ":export yaml stars.yaml",
                ":export html bookmarks.html"
            ]
        )

        self.register_command(
            "import",
            "Import from Awesome list or file",
            ":import <source>",
            [
                ":import awesome-python",
                ":import ~/Downloads/stars.json"
            ]
        )

        self.register_command(
            "clone",
            "Clone marked repos",
            ":clone <directory>",
            [
                ":clone ~/repos/",
                ":clone /workspace/github-stars/"
            ]
        )

        self.register_command(
            "clear",
            "Clear marks/filters",
            ":clear <what>",
            [
                ":clear marks",
                ":clear filter",
                ":clear search"
            ]
        )

        self.register_command(
            "refresh",
            "Refresh repo data",
            ":refresh [all]",
            [
                ":refresh",
                ":refresh all"
            ]
        )

        self.register_command(
            "cache",
            "Manage cache",
            ":cache <status|clear>",
            [
                ":cache status",
                ":cache clear"
            ]
        )

        self.register_command(
            "rate",
            "Show GitHub API rate limit",
            ":rate",
            [":rate"]
        )

        self.register_command(
            "help",
            "Show help for commands",
            ":help [command]",
            [
                ":help",
                ":help sort",
                ":help filter"
            ]
        )

        self.register_command(
            "stats",
            "Show folder/repo statistics",
            ":stats",
            [":stats"]
        )

        self.register_command(
            "auto",
            "Auto-categorize repos",
            ":auto",
            [":auto"]
        )

        self.register_command(
            "quit",
            "Quit application",
            ":quit",
            [":quit", ":q"]
        )

    def register(self, key: str, description: str,
                 context: KeyContext = KeyContext.GLOBAL,
                 category: str = "General",
                 hidden: bool = False) -> None:
        """Register a keybinding."""
        self.keybindings[key] = Keybinding(
            key=key,
            description=description,
            context=context,
            category=category,
            hidden=hidden
        )

    def register_command(self, name: str, description: str,
                        syntax: str, examples: List[str],
                        handler: Optional[Callable] = None) -> None:
        """Register a command."""
        self.commands[name] = Command(
            name=name,
            description=description,
            syntax=syntax,
            examples=examples,
            handler=handler
        )

    def get_bindings_by_category(self) -> Dict[str, List[Keybinding]]:
        """Get keybindings organized by category."""
        result = {}
        for binding in self.keybindings.values():
            if not binding.hidden:
                if binding.category not in result:
                    result[binding.category] = []
                result[binding.category].append(binding)
        return result

    def get_bindings_for_context(self, context: KeyContext) -> List[Keybinding]:
        """Get keybindings active in a specific context."""
        result = []
        for binding in self.keybindings.values():
            if not binding.hidden and (
                binding.context == context or
                binding.context == KeyContext.GLOBAL
            ):
                result.append(binding)
        return result

    def get_command(self, name: str) -> Optional[Command]:
        """Get a command by name."""
        return self.commands.get(name)

    def get_all_commands(self) -> List[Command]:
        """Get all registered commands."""
        return list(self.commands.values())

    def format_help_text(self) -> str:
        """Format help text for display."""
        lines = []
        lines.append("Ganger - GitHub Stars Manager\n")
        lines.append("=" * 40 + "\n")

        # Group by category
        categories = self.get_bindings_by_category()
        for category in sorted(categories.keys()):
            lines.append(f"\n{category}:")
            lines.append("-" * len(category) + "-")

            bindings = sorted(categories[category], key=lambda b: b.key)
            for binding in bindings:
                # Format key with padding
                key_str = binding.key.ljust(12)
                lines.append(f"  {key_str} {binding.description}")

        # Add commands section
        lines.append("\n\nCommands (access with ':'):")
        lines.append("-" * 28)

        for cmd in sorted(self.commands.values(), key=lambda c: c.name):
            lines.append(f"  :{cmd.name.ljust(10)} {cmd.description}")

        lines.append("\n" + "=" * 40)
        lines.append("Press '?' to toggle this help")

        return "\n".join(lines)


# Global registry instance
registry = KeybindingRegistry()
