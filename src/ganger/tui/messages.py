"""Custom Textual messages for Ganger.

Defines custom messages for communication between TUI components.

Modified: 2025-11-08
"""

from textual.message import Message
from typing import Optional

from ..core.models import VirtualFolder, StarredRepo


class FolderSelected(Message):
    """Message sent when a virtual folder is selected."""

    def __init__(self, folder: VirtualFolder):
        super().__init__()
        self.folder = folder


class RepoSelected(Message):
    """Message sent when a repo is selected."""

    def __init__(self, repo: StarredRepo):
        super().__init__()
        self.repo = repo


class RangerCommand(Message):
    """Message sent when a ranger-style command is executed.

    Examples: dd (cut), yy (copy), pp (paste), gg (top), etc.
    """

    def __init__(self, command: str):
        super().__init__()
        self.command = command


class SearchQuery(Message):
    """Message sent when a search is initiated."""

    def __init__(self, query: str):
        super().__init__()
        self.query = query


class SearchNext(Message):
    """Message sent to navigate to next search result."""

    pass


class SearchPrevious(Message):
    """Message sent to navigate to previous search result."""

    pass


class RefreshRequested(Message):
    """Message sent when refresh is requested."""

    def __init__(self, refresh_all: bool = False):
        super().__init__()
        self.refresh_all = refresh_all


class ClipboardOperation(Message):
    """Message sent when clipboard operation is performed."""

    def __init__(self, operation: str, repo_ids: list[str]):
        """Initialize clipboard operation message.

        Args:
            operation: Operation type ('copy', 'cut', 'paste')
            repo_ids: List of repo IDs involved
        """
        super().__init__()
        self.operation = operation
        self.repo_ids = repo_ids


class FolderCreated(Message):
    """Message sent when a new folder is created."""

    def __init__(self, folder: VirtualFolder):
        super().__init__()
        self.folder = folder


class FolderDeleted(Message):
    """Message sent when a folder is deleted."""

    def __init__(self, folder_id: str):
        super().__init__()
        self.folder_id = folder_id


class RepoMoved(Message):
    """Message sent when a repo is moved to a different folder."""

    def __init__(self, repo_id: str, from_folder_id: str, to_folder_id: str):
        super().__init__()
        self.repo_id = repo_id
        self.from_folder_id = from_folder_id
        self.to_folder_id = to_folder_id


class RepoUnstarred(Message):
    """Message sent when a repo is unstarred."""

    def __init__(self, repo_id: str):
        super().__init__()
        self.repo_id = repo_id


class VisualModeToggled(Message):
    """Message sent when visual mode is toggled."""

    def __init__(self, enabled: bool):
        super().__init__()
        self.enabled = enabled


class SelectionChanged(Message):
    """Message sent when repo selection changes."""

    def __init__(self, selected_count: int):
        super().__init__()
        self.selected_count = selected_count


class StatusMessage(Message):
    """Message sent to display a status message."""

    def __init__(self, message: str, duration: int = 3):
        super().__init__()
        self.message = message
        self.duration = duration


class ErrorMessage(Message):
    """Message sent to display an error message."""

    def __init__(self, message: str, error: Optional[Exception] = None):
        super().__init__()
        self.message = message
        self.error = error


class RateLimitUpdate(Message):
    """Message sent when rate limit information is updated."""

    def __init__(self, remaining: int, total: int, reset_time: Optional[int] = None):
        super().__init__()
        self.remaining = remaining
        self.total = total
        self.reset_time = reset_time
