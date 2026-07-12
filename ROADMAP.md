# GitHub Ranger (ganger) — Roadmap

Status: **Phase 2B complete** (solid, tested backend — versioned cache, folder
kinds, user tags, MCP server, 262 passing tests) with a **TUI that is ~70%
stubbed and over-advertised**. This roadmap was synthesized (2026-07-09) from a
two-agent cross-repo study against its sibling **yanger** (YouTube Ranger), which
shares ganger's lineage and has already debugged much of what ganger is about to
hit. Items are proposals, prioritized by leverage. Every claim below was checked
against live source (file:line) — nothing is trusted from transcript alone.

**Legend** — Impact = user-visible value (High / Med / Low). Effort = S (≤ ~½ day) ·
M (~1–3 days) · L (> 3 days). "Velocity unlock" = makes later work cheaper/safer.
Items tagged `[Cn]` / `[Bn]` trace to the cross-repo study's sections.

## Guiding theme

Ganger's biggest risk is **not a feature gap — it's a trust gap**. The backend is
real and tested, but the TUI advertises commands and keys it doesn't implement:
`app.py:718` returns *"Command '…' not yet implemented"* for `:sort`/`:filter`/
`:stats`/`:refresh` while the help text and docs present them as working, and
`action_undo`/`action_redo` (`app.py:630,635`) are `notify("… not yet
implemented")` stubs even though `dd`/`pp` already mutate state. The highest-value
work is therefore **finishing what's already advertised** (backends mostly exist —
these are wiring tasks, not builds), *then* borrowing yanger's paid-for overlay
and UX fixes, *then* the foundational tech-debt yanger's roadmap already mapped.

---

## Just landed — pending human review (uncommitted)

- **TUI input-render bug family — FIXED, awaiting review.** The `border`-inside-a
  `height:1` Input zero-content-row bug (typed text invisible), the white-on-white
  cursor, the `Input.suggestion` Tab-crash, and a ganger-only missing
  `.search-container { layout: horizontal; height: 1 }` rule. Verified on ganger's
  **actual** runtime (Python 3.11.14 / Textual 0.47.1) against composited output,
  not `Input.value`; full suite 262 pass + 3 new regression tests
  (`tests/test_tui_inputs.py`). The 0.47.1-correct cure differs from yanger's:
  `cursor_position = len(initial_text)` (not `select_on_focus=False`, which doesn't
  exist on 0.47.1). Files: `command_input.py`, `search_input.py`. **Not committed —
  diff awaits your review.**

---

## Tier 1 — Finish what's advertised (trust bugs; backends already exist)

- **GQ · `q` is a priority binding, so typing `q` anywhere quits the app — losing the
  user's work.** **Data-loss bug, found 2026-07-12 while reviewing G0. Not introduced
  by it; pre-existing at HEAD.** `app.py:73` is
  `Binding("q", "quit", "Quit", priority=True)`. Textual checks **priority** bindings in
  `App.on_event` *before* the key is forwarded to the focused widget
  (`textual/app.py:2759-2762`), and a `ModalScreen` does not shield it. Reproduced on the
  real runtime:
  ```
  type 'a','q','b' into a focused Input  -> app EXITS, value = 'a'
  type a name into a ModalScreen's Input -> app EXITS, field empty
  ```
  So `gn` → typing any folder name containing `q` (`query-tools`, `quickjs`, `qmk`) kills
  the app with no confirmation. Same for `/` search and `:` command mode — searching for
  "qt" quits.
  **Mechanism** (don't re-derive it): priority bindings are checked on the
  `_binding_chain`, **not** the `_modal_binding_chain`, so a `ModalScreen` gives no
  protection.
  **Fix:** drop `priority=True` at `app.py:73`. Verified on the real runtime — the `Input`
  then receives `'aqb'` and the app stays up, because Textual's `Input` consumes printable
  characters and stops the bubble before `App._on_key` ever runs `check_bindings`.
  `ctrl+q` (`app.py:81`) remains the force-quit escape hatch.
  **The one regression to re-check:** that `q` still quits from the miller columns. It
  does — `FolderColumn`/`RepoColumn` are `ScrollableContainer`s (`miller_view.py:25,170`)
  binding only arrow/home/end/page keys, so `q` bubbles to `App._on_key` and the
  non-priority binding fires. Needs a pilot test typing a `q`-containing string into each
  of the three inputs (search, command, folder-name modal), plus one asserting `q` still
  quits from the columns.
  *Impact High (silent data loss) · Effort S.* **Do this NEXT, above G1** — it is one
  line, and it is user-data loss reachable in three keystrokes from the app's primary
  create path. G1 is a multi-day item that only adds more typing surface.

- **G2 · Wire the advertised-but-dead keybindings.** `[B2/B4]` **24 keys** (not
  ~15) are advertised by the registry and unbound: `G H L enter V v uv uV dD n N
  gm cw o gb gc gi gp gr gf gs gR gt ga`. Ground truth is three dispatch sites —
  `BINDINGS` (`app.py:73-81`, 9 keys), `MillerView.handle_navigation`
  (`miller_view.py:539-579`, only `h/j/k/l/space`), and the chord block
  (only `gg/gn/gd/dd/yy/pp`). Quick wins: `gb` open-in-browser, `ga` auto-categorize,
  `G` jump-to-bottom (`select_last()` exists, never invoked), `gR` refresh alias. Plus
  post the rate-limit meter (`RateLimitUpdate` is defined at `messages.py:152` and
  *handled* at `app.py:735`, but **nothing ever posts it**).
  **The seam is now `_dispatch_chord` (added by G0), not the old inline chord block.**
  Replace its `if/elif` body with a `CHORD_TO_COMMAND: dict[str, str]` → `HANDLERS`
  lookup; **`on_key` must not change**:
  ```python
  async def _dispatch_chord(self, chord: str) -> bool:
      handler = HANDLERS.get(CHORD_TO_COMMAND.get(chord, ""))
      if handler is None:
          return False
      await handler(self, [])       # a chord is a keyboard alias for a command
      return True
  ```
  That call convention (`HANDLERS[name](app, [])`) is what makes `ga` and `:auto`
  *literally the same function* — the "do NOT reimplement inline" rule made mechanical
  rather than aspirational. Two contracts to preserve: `_dispatch_chord` returns
  **recognized**, not *executed* (so context guards must live inside the handler, or a
  declining guard will make the app claim its own feature is unimplemented); and a dict
  is **introspectable** where an `if/elif` is not, which is what lets the help overlay
  derive implemented-ness (see `## Proposed`). Blocked on G0 (state machine) and G1
  (handlers). *Impact Med · Effort S each.*
- **G1 · Wire the `:` command palette.** `[B1]` Only `:quit`/`:help` work;
  everything else hits the `:718` "not yet implemented" fallthrough. Start with
  commands whose backends already exist: `:refresh`, `:cache`, `:stats`, `:auto`
  (auto-categorize), `:rate`. **Blocked on G0.** *Impact High (trust) · Effort M.*
  - **Architecture (ruled 2026-07-12):** do **not** populate the `Command.handler`
    field — `keybindings.py:356` is an import-time singleton, and binding app
    methods into it leaks a `GangerApp` across the multiple app instances the tests
    construct per process. `help_overlay.py:166-176` never reads `handler` anyway.
    Instead add `tui/commands/` exposing `HANDLERS: dict[str, Callable[[GangerApp,
    list[str]], Awaitable[None]]]` — plain async free functions taking `app`
    explicitly. Registry keeps owning *what exists* (names/syntax/help); `HANDLERS`
    owns *what works*. **Delete the dead `Command.handler` field**
    (`keybindings.py:42`, kwarg at `:285`) — dead weight copied from yanger.
  - **`:q` is broken** — `execute_command` gates on `registry.get_command(name)`
    (`app.py:706-709`) *before* the `cmd_name == "q"` branch at `:712`, and the
    registry only has the key `"quit"`. So `:q` → *"Unknown command: q"* even though
    `keybindings.py:267` advertises it. That branch is unreachable dead code. Needs
    an alias mechanism + regression test. Cheapest trust win in the repo.
  - **Blocking prereqs** (a naive wiring ships an `AttributeError` where a polite
    "not yet implemented" used to be — *worse* than the status quo):
    `get_rate_limit_status()` (`github_client.py:451`) is a **sync, blocking network
    call** and swallows every error into `{"error": str(e)}` — wrap in
    `asyncio.to_thread` and check the `"error"` key, don't `try/except`.
    `self.api_client` is `None` on cold start/offline (`app.py:108`, set only at
    `:395`) — guard it. `:auto` has no app-level `DataLoader` and
    `auto_categorize_all(repos)` takes a list — pass **all** starred repos, not
    `current_repos` (that would categorize only the current folder's subset). `:auto`
    and `:cache clear` mutate folder membership → must invalidate
    `_folder_repos_cache` (`app.py:123`).
  - **Scope holds at 7 commands.** `:sort :filter :export :import :clone :move :tag
    :clear` have **no backend at all** (no `sort_repos`/`filter_repos`/`Export`
    anywhere in `src/`, contra `CLAUDE.md`). `:sort` looks like "just sort a list"
    and isn't — it needs persisted sort state plus a re-render path.
  - **In scope, not D1:** mark unimplemented commands in the help overlay. D1 is
    about *docs tone* in two markdown files; the help overlay is **runtime UI** and
    is the exact surface the guiding theme indicts. Wiring 7/15 and leaving 8
    advertised-unmarked would half-close the trust gap and call it done.
- **G3 · README preview in the third Miller column.** `[B3]` `miller_view.py:468`
  is `# TODO: Fetch and display README` — the whole point of the third column is
  stubbed, even though `get_readme()` (`github_client.py:361`) + the cache already
  exist. **Bigger than "wiring":** `PreviewPane` (`miller_view.py:372`) has **no
  `github_client` and no `cache` handle** — zero DI — and `show_repo()` is a sync
  render. Needs a client/cache plumbed down `MillerView → PreviewPane`, async fetch
  with loading/error state, and a Markdown renderer. Copy the async-safe call
  pattern already used at `mcp/tools.py:345`
  (`await asyncio.to_thread(github.get_readme, full_name)`). *Impact High · Effort M.*

## Tier 2 — Overlay correctness + borrowed UX (yanger's paid-for fixes)

- **G4 · Convert CommandInput / HelpOverlay / SearchInput to `ModalScreen`s.**
  `[C1]` The border-render fix already landed (above), but all three are still
  display-toggled `Container`s (`help_overlay.py:18`, `search_input.py:22`,
  `command_input.py:70`), so they don't own the keyboard — HelpOverlay ignores
  arrow/`j`/`k` exactly the way yanger's did before its fix. Copy yanger's
  `ModalScreen` conversion (focus capture, key isolation, top-layer render) and its
  pilot-harness verification. Depends on / pairs well with G7's modern runtime.
  *Impact High · Effort M.*
  - **Also move key handling onto a `GangerScreen(Screen)`.** Key handling currently
    lives on the `App`, which is the root of *every* screen's bubble chain — and that one
    fact is the root cause of both oddities G0 had to work around: modal keys bubble
    through the App (hence G0's `len(self.screen_stack) > 1` guard), and the App is the
    last hop so `event.stop()` is a no-op there (hence `_consume_key` needing
    `prevent_default()`). Move `on_key` / `_dispatch_chord` / `_CHORD_PREFIXES` onto a
    base screen and **both dissolve by construction**: a pushed modal's keys bubble to the
    *modal*, never traversing the base screen, so the guard becomes unnecessary; and a
    bare `event.stop()` at the screen suffices, because the event then never reaches
    `App._on_key`. Not done in G0 because `GangerApp` composes directly into the default
    screen, so this touches `compose`/`on_mount` and every `self.miller_view` reference —
    a refactor that would have swamped G0's evidence. G4 already makes screen-ownership
    the app's operative model, so it belongs here.
  - **This also fixes the in-screen overlays.** Because `HelpOverlay`, `CommandInput` and
    `SearchInput` are `Container`s rather than `Screen`s, G0's `screen_stack` guard does
    **not** cover them: `j`/`k` and chords still drive the miller view *behind* an open
    help overlay. Converting them to `ModalScreen`s (this item's whole point) puts them on
    the screen stack and the guard starts covering them for free.
- **G5 · Port yanger's `less`-style help search.** `[B5]` `/` opens a search box,
  Enter jumps to the first match (all highlighted), `n`/`N` cycle. yanger's
  **worktree branch** (`worktree-roadmap-knockout`, `HelpOverlay`) is a ready-made,
  tested reference — a port, not a net-new design. Best done after G4 (needs the
  modal + a real content row). *Impact Med · Effort M.*
- **G6 · Undo/redo via a core `OperationStack`.** `[B-depth / C5]` `action_undo`/
  `action_redo` are stubs while `dd`/`pp` already mutate. Build the stack in
  **core** (not the TUI) so the MCP server gets undo parity for free — the same
  seam yanger uses. *Impact High · Effort M.*

## Tier 3 — Foundational / velocity unlocks (from yanger's roadmap tech-debt)

- **G7 · Bump Textual off the `^0.47.0` pin.** `[C2]` `pyproject.toml:18` pins
  pre-theme-system Textual (lock = 0.47.1). **Rationale corrected 2026-07-12:** the
  "free `ctrl+p` command palette" claim is **wrong** — 0.47.1 *already ships* the
  command palette (`App.ENABLE_COMMAND_PALETTE` is `True`). The real gain is the
  **theme system** only. And that palette could never replace G1 regardless: it is a
  fuzzy `Provider` API yielding **zero-arg callbacks**, so it cannot express
  `:sort <field> [order]` or `:move <repo> <folder>` — G1's handlers are not wasted
  work, and a future Provider can reuse them *provided* they are free functions and
  not app-bound singleton state.
  **Version bound is a trap:** a literal `>=0.86` resolves to **8.2.8** (current
  latest) — i.e. exactly the `8.x` the roadmap warns against. Use an explicit
  ceiling: `textual = ">=0.86,<1.0"`.
  **Blocked** on the pending input diff being reviewed + committed: that diff is
  calibrated to 0.47.1 semantics (`_suggestion` private reactive; `cursor_position`
  chosen because `select_on_focus` doesn't exist on 0.47.1). A bump would silently
  degrade the Tab handler to a dead no-op — `getattr(w, "_suggestion", "")` swallows
  the change rather than failing loudly. G7 **must** re-verify `tests/test_tui_inputs.py`
  **and `tests/test_tui_keys.py`** — the latter's `was_consumed()` reads the private
  `_no_default_action`, which is the same silent-degradation trap: if Textual renames it,
  the assertion becomes a false *pass*, not a failure. (The `TestThroughRealDispatch`
  class in that file uses no private attributes and is the version-proof half.)
  *Impact Med · Effort M · velocity unlock.*
- **G8 · Custom-command `:run` registry.** `[C3]` Greenfield (no `run_command` in
  `src/` today) — and a bigger win for GitHub than for YouTube (`:run clone`,
  `:run gh-pr`, `:run gh-issue`). **Bake in yanger's CRITICAL injection lesson from
  the start:** validate `owner`/`repo` against a strict charset *before* shell
  substitution — a template that embeds `{id}` inside quotes defeats `shlex.quote`
  and a `$(…)` payload executes. Ship the MCP tool gated + opt-in, mirroring
  yanger's `mcp.allow_custom_commands`. *Impact High · Effort M-L.*
- **G9 · Narrow the 41 broad `except Exception`.** `[C4]` 41 sites in `src/`
  swallow errors; bugs vanish instead of propagating. Replace with specific
  exceptions (GitHub API / rate-limit / IO) per site — the same discipline yanger
  applied to its handlers. *Impact Med (correctness) · Effort M · per-site
  judgment.*
- **G10 · MCP cache-coverage signaling.** `[C6]` `mcp/tools.py` serves cached data
  (`use_cache`, `:307`) but never tells the caller the result is cached or stale.
  Add coverage/freshness fields to tool results so an LLM knows when it's seeing
  cold data. Ganger already tracks the cache metadata (`SCHEMA_VERSION=3`), so this
  is signaling, not new storage. *Impact Low-Med · Effort S.*
- **G11 · MCP elicitation gates for mutating tools.** `[C5]` Parity with yanger's
  gated-mutation approach: destructive MCP tools should elicit confirmation rather
  than act silently. Naturally follows G6 (undo) and G8 (custom commands).
  *Impact Med · Effort M.*

## Changelog (newest first)

- **G0 · Repaired the chord-prefix state machine.** `1dab92f` (2026-07-12) —
  `on_key` delegated to `miller_view.handle_navigation()` *before* checking
  `_pending_command`, and the handled path returned early **without clearing the
  prefix**. A stale prefix therefore survived a navigation key and desynchronized every
  chord that followed: after `d`,`j` a single `d` completed a mutating `dd` (clipboard
  cut) the user never asked for, and `gg` needed a third `g`. `on_key` now resolves a
  live prefix before navigation, clears it on every path (including the new
  modal-screen guard), and has a three-way outcome — implemented → dispatch ·
  advertised-but-unimplemented → honest `notify` · not-a-chord → fall through untouched.
  Also: chords no longer fire *through* an open modal (`gn` used to push a second
  folder-creation modal on top of the first), and `_consume_key()` uses
  `prevent_default()` rather than the decorative `event.stop()`. 20 new tests in
  `tests/test_tui_keys.py`; suite 259 → 279 committed.

  > **A false claim was made and retracted the same day, recorded because the lesson is
  > worth more than the fix.** A discovery agent, an adversarial reviewer, and an initial
  > repro all asserted that a stale prefix "silently disables `?`, `:` and `/`" — which
  > would have made this a High-severity blocker of G1. **It is false.** The repro called
  > `GangerApp.on_key()` *directly*, bypassing Textual's dispatch. A real pilot shows all
  > three still fire: `Message.stop()` only halts **bubbling to a parent**, and the `App`
  > is the root of the chain — `GangerApp.on_key` and `App._on_key` (which runs
  > `check_bindings`) are *both* yielded by the same MRO walk (`message_pump.py:670`) and
  > invoked in one loop with no stop-check between them. Suppressing a binding needs
  > `prevent_default()`. **Never verify TUI behavior by calling a framework hook
  > directly** — handlers compose with their parents rather than replacing them, so
  > behavior is emergent from dispatch. Use `run_test()`.

## Sequencing constraints (added 2026-07-12)

- **G4 and G7 are blocked on committing the pending input diff.** G4 rewrites
  `command_input.py` / `search_input.py` (`Container` → `ModalScreen` changes the
  CSS + `show()`/`hide()` contract the diff just repaired); G7 invalidates the
  diff's 0.47.1-specific semantics. Starting either would invalidate a human review
  in flight.
- **G0 → G1 → G2** is forced. G0 unblocks `:` (G1's only entry point); G2's `ga` /
  `gR` / `gb` must call G1's `HANDLERS` rather than reimplement them inline.
- **Environment footgun:** always run tests via `poetry run pytest`. Bare `pytest`
  resolves to `/opt/homebrew/bin/pytest` (no textual), and the *system* python has a
  stray **textual 8.2.8** — a wrong-interpreter run silently tests against the wrong
  Textual entirely.

## Proposed — needs human review (adds scope)

- **Help overlay should DERIVE implemented-ness from the dispatch tables.** The help
  overlay auto-generates from the registry (`help_overlay.py:134-176`), so it advertises
  everything registered whether or not it works — that is the trust gap, at its source.
  The obvious fix (add `implemented: bool` to `Keybinding`/`Command`) is **rejected**: it
  would be a *fourth* hand-maintained truth table alongside `BINDINGS`,
  `handle_navigation` and `_dispatch_chord`, and it can go stale in the direction that
  matters — claiming "implemented" when it isn't.
  Instead derive it: `key in CHORD_TO_COMMAND or key in NAV_KEYS or key in {b.key for b
  in BINDINGS}`. This is **unblocked by G2**, which turns `_dispatch_chord` into an
  enumerable dict — an `if/elif` cannot be introspected, so the help overlay can never
  ask it what works. Do it after G2, not before. (G0 already does the local version of
  this for chords: an honest `notify` when a chord is advertised but unimplemented.)

## Decisions needed (human calls — not autonomous)

- **D1 · Reconcile the aspirational docs.** `[C8]` `CLAUDE.md` and
  `PHASE_2B_COMPLETE.md` present ganger as "fully functional" while the `:` palette
  is largely a facade and ~15 keys are dead. Decide the tone/scope: mark stubs
  "coming soon" in help, or hold the "complete" claim until G1–G3 land. Also: the
  TUI source carries `Modified:` header lines that violate the global
  "git tracks this" standard — a trivial cleanup gated only on your say-so.
- **D2 · Smart/dynamic folders — keep and deepen (unlike yanger).** yanger
  *deprioritizes* smart/auto playlists (low-fit for YouTube's messy metadata). The
  asymmetry is real and worth stating: GitHub's **structured** topics/language make
  rule-driven folders and auto-categorization a *core-right* fit for ganger. This
  is a "keep investing" note, not a build task — ganger already has the mechanism.

## Explicitly excluded — already banked in ganger (kept honest)

These are on yanger's roadmap but ganger already solved them; **do not re-import**:

- **Versioned cache migrations** — `cache.py:39 SCHEMA_VERSION=3` + migration
  dispatcher (`:413`), `test_cache_migration_v3.py`.
- **Folder kinds + user tags + stub-identity upgrade** in core, with dedicated
  tests. (Ganger's private-tagging subsystem is a *strength yanger lacks* — see
  below.)
- **Pilot test harness** — `tests/test_tui_inputs.py`, `test_tui_app.py`.

## Strengths worth exporting to yanger (reverse direction, for the record)

Recorded here so the cross-pollination isn't lost — these are **yanger** roadmap
candidates, not ganger tasks:

- **Local tags orthogonal to folders** (ganger has a full many-to-many tagging
  subsystem; yanger has no local labels — organization there is 100% playlist
  membership).
- **Markdown / "awesome-list" export** of a folder.
- (Smart folders — noted above; yanger deliberately defers, low-fit for YouTube.)

---

## Appendix — Built vs Intended (snapshot 2026-07-09)

| Area | Built & tested | Advertised but stubbed |
| --- | --- | --- |
| Backend (core) | starred-repo load, cache (v3 + migrations), folder kinds, user tags, auto-categorize, dd/yy/pp mutation | — |
| MCP server | list/get tools, `use_cache` | cache-coverage signaling (G10), elicitation gates (G11) |
| `:` palette | `:quit`, `:help` | `:sort` `:filter` `:refresh` `:cache` `:stats` `:auto` `:rate` (G1) |
| Keybindings | ~6 core chords, dd/yy/pp, `/` search | `gb` `ga` `G` `gR` `v/V` `n/N` `H/L` … (G2) |
| Miller view | folder → repo columns | README preview column (G3, `miller_view.py:468`) |
| Overlays | render correctly (input-fix pending review) | keyboard ownership → ModalScreen (G4); help search (G5) |
| Undo | `dd`/`pp` mutate | `u`/`U` are stubs (G6, `app.py:630,635`) |
| Runtime | Textual `^0.47.0` (pre-theme-system) | modern runtime `>=0.86` (G7) |

_This file is the C8 recommendation made concrete: a living roadmap with a
Built-vs-Intended appendix. Keep it updated as items land; move completed items to
a Changelog section (newest first) with the commit that shipped them._
