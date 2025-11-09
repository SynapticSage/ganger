# Ganger - GitHub Ranger

**Created**: 2025-11-07
**Version**: 0.1.0

A terminal-based file manager for GitHub starred repositories, inspired by ranger. Navigate, organize, and manage GitHub stars with vim-like keybindings and a multi-pane interface.

## Features

- **Dual Interface**: TUI (Textual) and MCP (Model Context Protocol) server
- **Miller Columns**: Three-column ranger-style view (folders | repos | preview)
- **Virtual Folders**: Organize stars using tag-based virtual folders
- **Auto-categorization**: Automatically categorize repos by language, topic, and activity
- **Vim Keybindings**: hjkl navigation, visual mode, cut/copy/paste
- **Smart Caching**: SQLite cache for offline browsing and reduced API calls
- **Dual Authentication**: OAuth device flow or Personal Access Token

## Installation

### Prerequisites

- Python 3.10 or higher
- Poetry (for dependency management)
- GitHub account

### Install with Poetry

```bash
# Clone the repository
git clone https://github.com/yourusername/ganger.git
cd ganger

# Install dependencies
poetry install

# Activate the virtual environment
poetry shell

# Run authentication setup
ganger auth

# Start the TUI
ganger tui

# Or start the MCP server
ganger mcp
```

## Quick Start

### Authentication

Ganger supports two authentication methods:

1. **OAuth Device Flow** (recommended):
   ```bash
   ganger auth
   # Follow the prompts to authenticate via browser
   ```

2. **Personal Access Token**:
   ```bash
   export GITHUB_TOKEN=your_token_here
   ganger tui
   ```

### MCP Server

The MCP server allows LLM agents to orchestrate GitHub star management:

```bash
# Start MCP server
ganger mcp

# The server exposes tools like:
# - list_starred_repos
# - create_virtual_folder
# - move_repo_to_folder
# - star_repository
# - get_repo_details
```

## Configuration

Configuration file: `~/.config/ganger/config.yaml`

See `config/config.yaml` for default settings and available options.

## Project Status

**Phase 1 (In Progress)**: Core Foundation
- [x] Project structure and dependencies
- [ ] Core data models
- [ ] GitHub authentication (OAuth + PAT)
- [ ] GitHub API client (REST + GraphQL)
- [ ] SQLite cache
- [ ] Folder manager with auto-categorization
- [ ] MCP server
- [ ] Configuration system
- [ ] Unit tests

**Phase 2 (Planned)**: TUI Interface
**Phase 3 (Planned)**: Advanced Features

## Architecture

Ganger uses a clean service layer architecture that both the TUI and MCP interfaces consume:

```
ganger/
├── core/          # Business logic (shared)
│   ├── models.py
│   ├── github_client.py
│   ├── cache.py
│   ├── auth.py
│   └── folder_manager.py
├── mcp/           # MCP server interface
│   ├── server.py
│   └── tools.py
└── tui/           # TUI interface (Phase 2)
    └── app.py
```

## Development

### Run Tests

```bash
poetry run pytest
```

### Code Quality

```bash
# Format code
poetry run black src/ tests/

# Lint
poetry run ruff check src/ tests/

# Type checking
poetry run mypy src/
```

## License

MIT

## Credits

- Inspired by [ranger](https://github.com/ranger/ranger) file manager
- Architecture patterns from [yanger](https://github.com/yourusername/yanger)
- Built with [Textual](https://github.com/Textualize/textual) and [MCP](https://modelcontextprotocol.io)
