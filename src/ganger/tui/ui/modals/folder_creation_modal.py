"""Modal dialog for creating new virtual folders.

Provides a form for entering folder details.

Modified: 2025-11-08
Adapted from yanger/ui/playlist_creation_modal.py
"""

from typing import List
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, Input, Button
from textual.screen import ModalScreen
from textual.message import Message
from textual.validation import Length


class FolderCreated(Message):
    """Message sent when a folder is created."""

    def __init__(self, name: str, description: str, auto_tags: List[str]) -> None:
        """Initialize the message.

        Args:
            name: Folder name
            description: Folder description
            auto_tags: Auto-categorization tags
        """
        super().__init__()
        self.name = name
        self.description = description
        self.auto_tags = auto_tags


class FolderCreationModal(ModalScreen):
    """Modal dialog for creating a new virtual folder."""

    DEFAULT_CSS = """
    FolderCreationModal {
        align: center middle;
    }

    FolderCreationModal > Container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    FolderCreationModal Container#header {
        height: 3;
        margin-bottom: 1;
    }

    FolderCreationModal Static#title {
        text-align: center;
        text-style: bold;
        color: $primary;
    }

    FolderCreationModal Input {
        margin: 1 0;
    }

    FolderCreationModal Container#buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    FolderCreationModal Button {
        margin: 0 1;
    }

    FolderCreationModal .label {
        margin-top: 1;
        color: $text-muted;
    }

    FolderCreationModal .help-text {
        color: $text-muted;
        text-style: italic;
        margin-top: 0;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            with Container(id="header"):
                yield Static("Create New Folder", id="title")

            with Vertical():
                yield Static("Name:", classes="label")
                yield Input(
                    placeholder="Enter folder name",
                    id="name_input",
                    validators=[Length(minimum=1, maximum=100)]
                )

                yield Static("Description (optional):", classes="label")
                yield Input(
                    placeholder="Enter folder description",
                    id="description_input",
                    validators=[Length(maximum=500)]
                )

                yield Static("Auto Tags (optional):", classes="label")
                yield Static(
                    "Comma-separated tags for auto-categorization (e.g., python,ml,ai)",
                    classes="help-text"
                )
                yield Input(
                    placeholder="python,javascript,rust",
                    id="tags_input",
                    validators=[Length(maximum=200)]
                )

                with Horizontal(id="buttons"):
                    yield Button("Create", variant="primary", id="create")
                    yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        """Focus the name input when mounted."""
        self.query_one("#name_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "create":
            self.create_folder()
        else:
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if event.input.id == "name_input":
            # Move to description field
            self.query_one("#description_input", Input).focus()
        elif event.input.id == "description_input":
            # Move to tags field
            self.query_one("#tags_input", Input).focus()
        elif event.input.id == "tags_input":
            # Create the folder
            self.create_folder()

    def create_folder(self) -> None:
        """Validate and create the folder."""
        name_input = self.query_one("#name_input", Input)
        description_input = self.query_one("#description_input", Input)
        tags_input = self.query_one("#tags_input", Input)

        # Validate name
        name = name_input.value.strip()
        if not name:
            name_input.focus()
            return

        description = description_input.value.strip()

        # Parse tags
        tags_str = tags_input.value.strip()
        auto_tags = []
        if tags_str:
            # Split by comma and clean up
            auto_tags = [tag.strip().lower() for tag in tags_str.split(",") if tag.strip()]

        # Post message and dismiss
        self.post_message(FolderCreated(name, description, auto_tags))
        self.dismiss()
