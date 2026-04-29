# Ganger TUI Testing Guide

## Phase 2A Complete ✅

The TUI foundation is now complete and functional!

## Running the TUI

### Using the CLI (Recommended)

```bash
# Launch the TUI (uses existing authentication)
poetry run ganger tui

# Or with custom config directory
poetry run ganger tui --config-dir ~/.config/ganger-dev
```

### Development Mode

```bash
# Run with textual dev mode for debugging
poetry run textual run --dev test_tui.py

# Or run test script directly
poetry run python test_tui.py
```

### Setup GitHub Authentication

The TUI requires GitHub authentication. You can use either:

**Option 1: Personal Access Token (Recommended for testing)**
```bash
export GITHUB_TOKEN=ghp_your_token_here
poetry run python test_tui.py
```

**Option 2: OAuth Flow** (automatic if no token is set)
```bash
poetry run python test_tui.py
# Follow the OAuth prompts
```

## Current Status

### ✅ Implemented (Phase 2A)

1. **TUI Infrastructure**
   - Main GangerApp with Textual
   - Three-column MillerView layout
   - Keybinding registry (40+ bindings)
   - Custom message system (15 messages)
   - Global stylesheet

2. **UI Components**
   - StatusBar (bottom status with rate limits)
   - CommandInput (`:` command mode)
   - SearchInput (`/` search mode)
   - HelpOverlay (`?` for help)

3. **Navigation**
   - `hjkl` - vim-style navigation
   - `gg` / `G` - jump to top/bottom
   - `space` - toggle mark
   - `?` - help
   - `:` - command mode
   - `/` - search mode
   - `q` - quit

4. **Columns**
   - Left: Virtual folders (with selection)
   - Middle: Starred repos (with marking)
   - Right: Repo preview (metadata, description, topics)

### 🚧 Not Yet Implemented (Phase 2B+)

- Real GitHub data loading (currently shows "Initializing...")
- Cut/copy/paste operations (dd/yy/pp)
- Auto-categorization
- Search functionality
- Folder creation/management
- README fetching for preview

## Testing Navigation

Once authenticated, you can test:

```
h/j/k/l - Navigate between columns and items
gg      - Jump to top
G       - Jump to bottom
space   - Mark repo (in middle column)
?       - Show help overlay
:       - Command mode (try :quit, :help)
/       - Search mode
q       - Quit
```

## Architecture Overview

```
src/ganger/tui/
├── app.py              # Main GangerApp
├── app.tcss            # Global styles
├── keybindings.py      # 40+ keybindings, 15 commands
├── messages.py         # Custom Textual messages
└── ui/
    ├── miller_view.py  # 3-column layout
    ├── status_bar.py   # Bottom status
    ├── command_input.py # Command mode
    ├── search_input.py  # Search overlay
    └── help_overlay.py  # Help screen
```

## Known Issues

- Authentication required - no offline test mode yet
- No test data - needs real GitHub connection
- Preview pane doesn't fetch READMEs yet
- Cut/copy/paste operations not wired up

## Next Steps (Phase 2B)

1. Wire up real GitHub data loading
2. Implement folder → repos data flow
3. Add cut/copy/paste operations
4. Implement search within folders/repos
5. Add folder creation modal
6. Connect auto-categorization

---

**Modified**: 2025-11-08
**Phase**: 2A Complete, 2B Ready to Start
