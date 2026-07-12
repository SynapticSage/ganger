"""Key dispatch: the two-key ranger chord state machine (`on_key`).

These drive `GangerApp.on_key` directly with a stub MillerView, so no mount, no auth
and no network is needed. That is sound *because* every assertion here is about state
`on_key` owns (`_pending_command`) or calls it makes — never about whether a BINDING
fired. Binding dispatch is emergent from Textual's MRO walk and cannot be observed by
calling a handler directly; anything asserting on that must use the pilot harness.
"""

from pathlib import Path

import pytest
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from ganger.tui.app import GangerApp
from ganger.tui.keybindings import registry
from ganger.tui.messages import RangerCommand

# pytest-asyncio runs strict: without this every test here skips silently.
pytestmark = pytest.mark.asyncio

# What MillerView.handle_navigation() actually claims (miller_view.py:539-579).
NAV_KEYS = {"h", "j", "k", "l", "space"}


async def _noop():
    """Awaitable stand-in for the async action_* methods, which on_key awaits."""
    return None


class StubColumn:
    def __init__(self):
        self.select_first_calls = 0

    def select_first(self):
        self.select_first_calls += 1


class StubMillerView:
    """Stands in for MillerView: handles only navigation keys."""

    def __init__(self, focused_column: int = 1):
        self.focused_column = focused_column
        self.folder_column = StubColumn()
        self.repo_column = StubColumn()

    async def handle_navigation(self, key: str) -> bool:
        # The real handle_navigation moves focus between columns on h/l; the
        # column-dependent chords (gg, gd) read that, so the stub must move it too.
        if key == "l":
            self.focused_column = min(self.focused_column + 1, 2)
        elif key == "h":
            self.focused_column = max(self.focused_column - 1, 0)
        return key in NAV_KEYS


@pytest.fixture
def app(tmp_path: Path):
    app = GangerApp(config_dir=tmp_path)
    app.miller_view = StubMillerView()
    app.notifications = []
    app.posted = []
    app.notify = lambda msg, **kw: app.notifications.append(msg)
    app.post_message = lambda msg: app.posted.append(msg)
    return app


async def press(app: GangerApp, key: str) -> events.Key:
    """Feed one key to on_key. Textual delivers key NAMES ('question_mark'), not chars."""
    event = events.Key(key=key, character=key if len(key) == 1 else None)
    await app.on_key(event)
    return event


def was_consumed(event: events.Key) -> bool:
    """True if the key was fully consumed, i.e. no binding will also fire for it.

    Reads `_no_default_action` because Textual exposes no public getter: `stop()` only
    halts bubbling, and this App is the root of the chain, so `prevent_default()` is the
    only thing that suppresses `App._on_key`'s `check_bindings()` call.
    """
    return event._no_default_action


class TestPrefixIsClearedOnEveryPath:
    async def test_navigation_key_clears_a_pending_prefix(self, app):
        """The bug: nav used to early-return, leaving the prefix armed."""
        await press(app, "d")
        assert app._pending_command == "d"

        await press(app, "j")
        assert app._pending_command is None

    async def test_stale_prefix_does_not_complete_a_chord_the_user_never_finished(self, app):
        """Regression: `d`, `j`, then a SINGLE `d` used to fire `dd` (a clipboard cut)."""
        await press(app, "d")
        await press(app, "j")
        await press(app, "d")

        assert app.posted == [], "a lone `d` after navigating must not cut"
        assert app._pending_command == "d", "it should merely arm the chord"

    async def test_chords_do_not_desynchronise_after_navigating(self, app):
        """Regression: `d`, `j`, `g`, `g` used to need a THIRD `g` to jump to top."""
        await press(app, "d")
        await press(app, "j")
        await press(app, "g")
        await press(app, "g")

        assert app.miller_view.repo_column.select_first_calls == 1


class TestChordOutcomes:
    async def test_implemented_chords_still_work(self, app):
        for keys, expected in [("dd", "cut"), ("yy", "copy"), ("pp", "paste")]:
            app.posted.clear()
            for key in keys:
                await press(app, key)

            assert len(app.posted) == 1
            assert isinstance(app.posted[0], RangerCommand)
            assert app.posted[0].command == expected

    async def test_advertised_but_unimplemented_chord_says_so(self, app):
        """`gb` is in the help overlay; it used to eat the `b` in silence."""
        await press(app, "g")
        event = await press(app, "b")

        assert app.notifications == ["gb: not yet implemented"]
        assert was_consumed(event)
        assert app._pending_command is None

    async def test_gn_invokes_folder_creation(self, app):
        called = []
        app.action_create_folder = lambda: called.append(True) or _noop()

        await press(app, "g")
        await press(app, "n")

        assert called == [True]

    async def test_gd_deletes_a_folder_from_the_folder_column(self, app):
        app.miller_view.focused_column = 0
        called = []
        app.action_delete_folder = lambda: called.append(True) or _noop()

        await press(app, "g")
        await press(app, "d")

        assert called == [True]

    async def test_recognised_chord_whose_guard_declines_says_why(self, app):
        """`gd` outside the folder column is recognized but not applicable.

        It must NOT claim to be unimplemented (it is implemented), and it must not
        swallow the keystroke in silence either — silence is the very bug being fixed.
        """
        app.miller_view.focused_column = 1  # repo column, so gd's guard declines

        await press(app, "g")
        await press(app, "d")

        assert app.notifications == ["gd: only in the folder column"]
        assert "not yet implemented" not in " ".join(app.notifications)

    async def test_escape_cancels_a_pending_prefix(self, app):
        """The only way to abandon a half-typed chord."""
        await press(app, "d")
        event = await press(app, "escape")

        assert app._pending_command is None
        assert not was_consumed(event), "escape must keep its normal meaning"

    async def test_second_key_that_is_itself_a_prefix_rearms(self, app):
        """`g` then `y` is not a chord: the `y` should start a fresh one, so `gyy` copies."""
        await press(app, "g")
        await press(app, "y")
        assert app._pending_command == "y"

        await press(app, "y")
        assert [m.command for m in app.posted] == ["copy"]

    async def test_the_destructive_dD_chord_is_inert_and_says_so(self, app):
        """`dD` (unstar on GitHub) is advertised and unimplemented. It must NOT cut."""
        await press(app, "d")
        await press(app, "D")

        assert app.notifications == ["dD: not yet implemented"]
        assert app.posted == [], "dD must not fall through to dd's cut"

    async def test_non_chord_second_key_falls_through_unconsumed(self, app):
        """`d` + `?` is not a chord: `?` must keep its normal meaning (open help).

        Consuming it is what would break the binding — so assert it is NOT consumed.
        """
        await press(app, "d")
        event = await press(app, "question_mark")

        assert not was_consumed(event), "'?' must reach App._on_key so the ? binding fires"
        assert app.notifications == []
        assert app._pending_command is None


class TestConsumedPathsSuppressBindings:
    """`stop()` does not suppress a binding — only `prevent_default()` does.

    This guards a live landmine for G2: `u` is bound to undo (app.py:77) *and* the
    registry advertises `uv`/`uV`. If `u` is ever added to `_CHORD_PREFIXES`, arming the
    prefix must not also fire undo.
    """

    async def test_arming_a_prefix_suppresses_any_binding_on_that_key(self, app):
        event = await press(app, "d")
        assert was_consumed(event)

    async def test_navigation_suppresses_any_binding_on_that_key(self, app):
        event = await press(app, "j")
        assert was_consumed(event)


async def test_chord_prefixes_cover_every_advertised_chord_but_two():
    """`_CHORD_PREFIXES` is a hand-maintained projection of the registry.

    A chord whose first key is not a prefix can never even enter the state machine, so
    it stays a silent dead key — the exact thing G0 exists to eliminate. Pin the two
    known exceptions so that registering a chord under a *new* prefix fails loudly here
    instead of silently doing nothing forever.
    """
    advertised = {key[0] for key in registry.keybindings if len(key) == 2}

    assert advertised - GangerApp._CHORD_PREFIXES == {"u", "c"}, (
        "u: `uv`/`uV` collide with the `u`=undo binding (app.py:77) — arming a `u` "
        "prefix needs a chord timeout first. c: `cw` (rename) is unimplemented."
    )


class HeadlessGangerApp(GangerApp):
    """The real app minus its mount-time data load, for driving real Textual dispatch.

    Needed because binding dispatch is emergent: `stop()` vs `prevent_default()` and the
    MRO walk decide whether a key reaches `App._on_key`. Calling `on_key` directly (as
    the tests above do) cannot see any of that.
    """

    CSS_PATH = None  # resolves relative to the defining module; irrelevant to key tests

    async def on_mount(self, event) -> None:
        # A subclass handler does NOT replace the parent's — Textual dispatches every
        # on_mount in the MRO. prevent_default() is the only way to stop GangerApp's
        # data-load/auth from also running.
        event.prevent_default()
        self.miller_view = StubMillerView()
        self.ranger_commands = []
        self.help_opened = False

    def compose(self) -> ComposeResult:
        yield Static("body")

    def action_help(self) -> None:
        self.help_opened = True

    async def on_ranger_command(self, message: RangerCommand) -> None:
        self.ranger_commands.append(message.command)


class TestThroughRealDispatch:
    """Version-proof counterparts to the unit tests above: no private attributes.

    These are the tests that survive the Textual bump in roadmap item G7.
    """

    async def test_a_lone_d_after_navigating_does_not_cut(self, tmp_path):
        app = HeadlessGangerApp(config_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("d", "j", "d")
            await pilot.pause()

            assert app.ranger_commands == []

    async def test_gg_still_fires_after_navigating(self, tmp_path):
        app = HeadlessGangerApp(config_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("d", "j", "g", "g")
            await pilot.pause()

            assert app.miller_view.repo_column.select_first_calls == 1

    async def test_chords_do_not_fire_through_an_open_modal(self, tmp_path):
        """Textual scopes BINDINGS to the active screen — but not HANDLERS.

        Keys still bubble to `App.on_key` from a pushed modal, so without the screen
        guard `gn` inside the folder-creation modal opens a SECOND one, and `dd` mutates
        the clipboard behind it.
        """
        app = HeadlessGangerApp(config_dir=tmp_path)
        async with app.run_test() as pilot:
            await app.push_screen(ModalScreen())
            await pilot.pause()

            await pilot.press("d", "d")
            await pilot.press("g", "g")
            await pilot.pause()

            assert app.ranger_commands == [], "dd must not cut while a modal is open"
            assert app.miller_view.repo_column.select_first_calls == 0

    async def test_a_modal_drops_a_half_typed_chord(self, tmp_path):
        """The screen guard must clear the prefix, not just bail.

        Otherwise a chord armed before a screen is pushed survives it, and the first key
        after it closes completes the chord — the original bug, across a screen boundary.
        """
        app = HeadlessGangerApp(config_dir=tmp_path)
        async with app.run_test() as pilot:
            app._pending_command = "d"  # armed, then something pushes a screen
            await app.push_screen(ModalScreen())
            await pilot.pause()

            await pilot.press("x")
            await pilot.pause()

            assert app._pending_command is None

    async def test_arming_a_prefix_does_not_also_fire_that_keys_binding(self, tmp_path):
        """The G2 landmine, made falsifiable.

        `u` is bound to undo (app.py:77) and the registry advertises `uv`/`uV`. If `u`
        ever becomes a chord prefix, arming it must not ALSO run undo. This fails if
        `_consume_key` is ever weakened from `prevent_default()` back to a bare `stop()`.
        """

        class UPrefixApp(HeadlessGangerApp):
            _CHORD_PREFIXES = frozenset({"g", "d", "y", "p", "u"})

            def action_undo(self) -> None:
                self.undo_fired = True

        app = UPrefixApp(config_dir=tmp_path)
        app.undo_fired = False
        async with app.run_test() as pilot:
            await pilot.press("u")
            await pilot.pause()

            assert app._pending_command == "u", "u should merely arm the chord"
            assert not app.undo_fired, "arming the prefix must not also trigger undo"

    async def test_help_binding_still_fires_through_a_pending_prefix(self, tmp_path):
        """The `?` binding must survive a pending chord prefix.

        `event.stop()` never suppressed this (it only halts bubbling, and the App is the
        root of the chain) — so `?` was never actually broken. This pins that the fix's
        `prevent_default()` is applied ONLY to consumed paths and does not start
        swallowing it.
        """
        app = HeadlessGangerApp(config_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("d", "question_mark")
            await pilot.pause()

            assert app.help_opened
