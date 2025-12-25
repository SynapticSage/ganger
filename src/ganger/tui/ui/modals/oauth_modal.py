"""Modal dialog for OAuth device flow authentication.

Displays the verification code and URL during OAuth authentication.

Modified: 2025-11-08
"""

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, Button, ProgressBar
from textual.screen import ModalScreen
from textual.message import Message


class OAuthCancelled(Message):
    """Message sent when OAuth is cancelled by user."""
    pass


class OAuthModal(ModalScreen):
    """Modal dialog for OAuth device flow authentication.

    Shows the user code and verification URL while waiting for
    the user to authorize in their browser.
    """

    DEFAULT_CSS = """
    OAuthModal {
        align: center middle;
    }

    OAuthModal > Container {
        width: 70;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    OAuthModal Container#header {
        height: 3;
        margin-bottom: 1;
    }

    OAuthModal Static#title {
        text-align: center;
        text-style: bold;
        color: $primary;
    }

    OAuthModal Static.instruction {
        margin: 1 0;
    }

    OAuthModal Static#user-code {
        text-align: center;
        text-style: bold;
        color: $success;
        background: $surface-darken-2;
        padding: 1 2;
        margin: 1 0;
    }

    OAuthModal Static#url {
        text-align: center;
        color: $accent;
        margin: 1 0;
    }

    OAuthModal Static#status {
        text-align: center;
        color: $text-muted;
        text-style: italic;
        margin: 1 0;
    }

    OAuthModal ProgressBar {
        margin: 1 0;
    }

    OAuthModal Container#buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    OAuthModal Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        user_code: str,
        verification_url: str,
        expires_in: int = 900,
        **kwargs
    ) -> None:
        """Initialize the OAuth modal.

        Args:
            user_code: The code to enter on GitHub
            verification_url: The URL to visit
            expires_in: Seconds until the code expires
        """
        super().__init__(**kwargs)
        self.user_code = user_code
        self.verification_url = verification_url
        self.expires_in = expires_in
        self._status_text = "Waiting for authorization..."

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            with Container(id="header"):
                yield Static("GitHub Authentication", id="title")

            with Vertical():
                yield Static(
                    "1. A browser window has been opened.",
                    classes="instruction"
                )
                yield Static(
                    "2. Enter this code on GitHub:",
                    classes="instruction"
                )

                yield Static(self.user_code, id="user-code")

                yield Static(
                    f"Or visit: {self.verification_url}",
                    id="url"
                )

                yield Static(self._status_text, id="status")
                yield ProgressBar(total=100, show_eta=False, id="progress")

                with Horizontal(id="buttons"):
                    yield Button("Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        """Start the progress animation."""
        self.query_one("#progress", ProgressBar).update(progress=0)
        # Start animation
        self.set_interval(1.0, self._update_progress)

    def _update_progress(self) -> None:
        """Update progress bar and status."""
        progress_bar = self.query_one("#progress", ProgressBar)
        current = progress_bar.progress or 0
        if current < 100:
            progress_bar.advance(100 / self.expires_in)

    def update_status(self, status: str) -> None:
        """Update the status text.

        Args:
            status: New status message
        """
        self._status_text = status
        try:
            self.query_one("#status", Static).update(status)
        except Exception:
            pass  # Modal might be dismissed

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel":
            self.post_message(OAuthCancelled())
            self.dismiss()

    def on_key(self, event) -> None:
        """Handle escape key."""
        if event.key == "escape":
            self.post_message(OAuthCancelled())
            self.dismiss()
