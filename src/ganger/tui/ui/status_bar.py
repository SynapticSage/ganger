"""Status bar widget for Ganger.

Shows current context, rate limit usage, and keyboard hints.

Modified: 2025-11-08
Adapted from yanger/ui/status_bar.py
"""

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static
from textual.widget import Widget
from textual.reactive import reactive


class StatusBar(Widget):
    """Status bar showing context and rate limit information."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text;
        dock: bottom;
    }

    StatusBar > Horizontal {
        width: 100%;
        height: 1;
    }

    StatusBar .status-left {
        width: 1fr;
        padding: 0 1;
    }

    StatusBar .status-center {
        width: 2fr;
        text-align: center;
        padding: 0 1;
        color: $text-muted;
    }

    StatusBar .status-right {
        width: 1fr;
        text-align: right;
        padding: 0 1;
    }

    StatusBar .rate-limit-warning {
        color: $warning;
        text-style: bold;
    }

    StatusBar .rate-limit-critical {
        color: $error;
        text-style: bold;
    }
    """

    # Reactive properties
    context = reactive("")
    status = reactive("")
    rate_limit = reactive("")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.left_widget: Optional[Static] = None
        self.center_widget: Optional[Static] = None
        self.right_widget: Optional[Static] = None

    def compose(self) -> ComposeResult:
        """Create status bar layout."""
        with Horizontal():
            self.left_widget = Static("", classes="status-left")
            self.center_widget = Static("", classes="status-center")
            self.right_widget = Static("", classes="status-right")

            yield self.left_widget
            yield self.center_widget
            yield self.right_widget

    def on_mount(self) -> None:
        """Initialize status bar with default values."""
        self.update_hints()

    def update_context(self, context: str, selected_count: int = 0) -> None:
        """Update the current context (left side).

        Args:
            context: Context string to display
            selected_count: Number of selected repos
        """
        self.context = context
        display_text = context

        # Add Sel indicator if repos are selected
        if selected_count > 0:
            display_text = f"[yellow]Sel[/yellow] {selected_count} | {context}"

        if self.left_widget:
            self.left_widget.update(display_text)

    def update_status(self, status: str, rate_limit: str = "") -> None:
        """Update status message and rate limit info.

        Args:
            status: Status message to display
            rate_limit: Rate limit string (e.g., "4500/5000")
        """
        self.status = status
        self.rate_limit = rate_limit

        if self.center_widget:
            self.center_widget.update(status)

        if self.right_widget and rate_limit:
            # Parse rate limit to add warning colors
            if "/" in rate_limit:
                remaining, total = rate_limit.split("/")
                try:
                    remaining_int = int(remaining)
                    total_int = int(total)
                    used = total_int - remaining_int
                    percentage = (used / total_int) * 100

                    if percentage >= 90:
                        self.right_widget.add_class("rate-limit-critical")
                        self.right_widget.remove_class("rate-limit-warning")
                    elif percentage >= 75:
                        self.right_widget.add_class("rate-limit-warning")
                        self.right_widget.remove_class("rate-limit-critical")
                    else:
                        self.right_widget.remove_class("rate-limit-warning")
                        self.right_widget.remove_class("rate-limit-critical")
                except ValueError:
                    pass

            self.right_widget.update(f"Rate: {rate_limit}")

    def update_hints(self, custom_hints: Optional[str] = None) -> None:
        """Update keyboard hints based on current mode.

        Args:
            custom_hints: Custom hint text to display
        """
        if custom_hints:
            hints = custom_hints
        else:
            # Default hints for ganger
            hints = "q:quit /:search v:visual space:mark yy:copy dd:cut pp:paste gb:browser"

        if self.center_widget:
            self.center_widget.update(hints)

    def show_message(self, message: str, duration: int = 3) -> None:
        """Show a temporary message in the center.

        Args:
            message: Message to display
            duration: Duration in seconds
        """
        if self.center_widget:
            original = self.center_widget.renderable
            self.center_widget.update(message)

            # Reset after duration
            def reset():
                if self.center_widget:
                    self.center_widget.update(original)

            self.set_timer(duration, reset)
