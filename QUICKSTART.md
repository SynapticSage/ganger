# Ganger Quickstart

**GitHub Stars Manager** - A ranger-inspired TUI for managing your GitHub starred repositories.

## Quick Start (3 Steps)

### 1. Install Dependencies

```bash
poetry install
```

### 2. Authenticate with GitHub

```bash
# Option A: Use existing token
export GITHUB_TOKEN=ghp_your_token_here
poetry run ganger auth

# Option B: OAuth flow (interactive)
poetry run ganger auth
```

### 3. Launch the TUI

```bash
poetry run ganger tui
```

## Available Commands

```bash
# Show status and authentication info
poetry run ganger status

# Authenticate with GitHub
poetry run ganger auth

# Launch the TUI interface
poetry run ganger tui

# Start MCP server (for LLM integration)
poetry run ganger mcp

# Logout
poetry run ganger logout
```

## Current Status (Phase 2A Complete ✅)

### ✅ Working Features

- **Authentication**: OAuth + Personal Access Token
- **TUI Interface**: Three-column Miller view
- **Navigation**: Vim-style hjkl navigation
- **Keybindings**: 40+ shortcuts (press `?` for help)
- **Command Mode**: `:` for commands
- **Search Mode**: `/` for search
- **MCP Server**: 15 tools for LLM orchestration

### 🚧 In Progress (Phase 2B)

- Loading starred repos from GitHub
- Virtual folder management
- Cut/copy/paste operations (dd/yy/pp)
- Auto-categorization by language/topic
- README preview

## TUI Keybindings

Once in the TUI, use these keys:

```
Navigation:
  h/j/k/l    - Navigate left/down/up/right
  gg/G       - Jump to top/bottom
  space      - Mark/unmark repo

Actions:
  ?          - Show help
  :          - Command mode
  /          - Search mode
  q          - Quit

Coming Soon:
  dd         - Cut repo
  yy         - Copy repo
  pp         - Paste repo
  gn         - New folder
  ga         - Auto-categorize
```

## Architecture

```
ganger/
├── src/ganger/
│   ├── core/           # Business logic (auth, cache, models)
│   ├── mcp/            # MCP server (15 tools)
│   ├── tui/            # Terminal UI (Phase 2A ✅)
│   │   ├── app.py      # Main TUI application
│   │   ├── keybindings.py  # 40+ keybindings
│   │   └── ui/         # UI components
│   └── cli.py          # CLI entry point
├── tests/              # 90 tests (63% coverage)
└── config/             # Configuration files
```

## Testing

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=ganger

# Run specific test file
poetry run pytest tests/test_models.py -v
```

## Development

```bash
# Run TUI in dev mode with debugging
poetry run textual run --dev test_tui.py

# Run TUI normally
poetry run ganger tui

# Check authentication status
poetry run ganger status
```

## Project Status

- **Phase 1**: Core Foundation ✅ (90 tests, 63% coverage)
  - Models, Auth, GitHub API, Cache, Folder Manager, MCP Server

- **Phase 2A**: TUI Foundation ✅ (Just Completed!)
  - Three-column layout, Navigation, Keybindings, Commands

- **Phase 2B**: Data Integration 🚧 (Next)
  - Load GitHub data, Operations (dd/yy/pp), Search, Modals

- **Phase 3**: Advanced Features 📋 (Planned)
  - Auto-categorization, Import/Export, Clone repos

## Documentation

- [TUI Testing Guide](TUI_TESTING.md) - Detailed TUI testing instructions
- [CLAUDE.md](CLAUDE.md) - Full project specification
- [Phase 1 Tests](tests/) - Core functionality tests

## Support

For issues or questions:
- Check existing tests for usage examples
- Run `poetry run ganger --help` for CLI help
- Press `?` in the TUI for keyboard shortcuts

---

**Modified**: 2025-11-08
**Version**: v0.1.0
**Phase**: 2A Complete, 2B Ready
