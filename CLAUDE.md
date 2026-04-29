# GitHub Ranger (Ganger) - Claude File

**Created**: 2025-11-07

## Project Overview
A terminal-based file manager for GitHub starred repositories, inspired by ranger. Navigate, organize, and manage GitHub stars with vim-like keybindings and a multi-pane interface. Organize starred repos into virtual folders as easily as moving files between directories.

## Core Features
- Three-column miller view (folders/tags | starred repos | preview)
- Vim-style navigation (hjkl, gg, G)
- Cut/copy/paste repos between virtual folders
- Bulk operations and visual selection mode
- Virtual folder creation with tags/labels
- Search and filter across starred repos
- Preview pane with README and repo metadata
- Auto-categorization by language, topic, and activity

## Key Commands (Ranger-style)
```
Navigation:
  h/j/k/l    - left/down/up/right
  gg/G       - go to top/bottom
  H/L        - history back/forward
  /          - search
  n/N        - next/previous search result

Selection:
  Space      - toggle mark
  v          - visual mode
  uv         - unselect all
  V          - invert selection

Operations:
  yy         - copy (yank) repo
  dd         - cut repo
  pp         - paste repo
  dD         - unstar permanently
  cw         - rename folder
  o          - sort options
  :          - command mode

GitHub Operations:
  gb         - open repo in browser
  gc         - clone repository
  gi         - view issues
  gp         - view pull requests
  gr         - view README
  gf         - refresh repo metadata
  gs         - star/unstar toggle

Folder Operations:
  gn         - create new virtual folder
  gd         - delete empty folder
  gt         - manage tags/topics
  gR         - refresh all repos
  ga         - auto-categorize by language/topic
  gm         - merge folders
```

## Technical Stack
- **Language**: Python 3.10+
- **TUI Framework**: Textual
- **GitHub API**: PyGithub + GraphQL (ghapi)
- **Config**: YAML/TOML
- **Cache**: SQLite for offline browsing
- **OAuth**: GitHub OAuth2 + Personal Access Tokens

## Project Structure
```
ganger/
├── src/
│   ├── ganger/
│   │   ├── __init__.py
│   │   ├── app.py              # Main application
│   │   ├── ui/
│   │   │   ├── __init__.py
│   │   │   ├── miller_columns.py
│   │   │   ├── preview_pane.py
│   │   │   ├── status_bar.py
│   │   │   └── command_line.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── github_client.py
│   │   │   ├── folder_manager.py
│   │   │   ├── repo_item.py
│   │   │   ├── clipboard.py
│   │   │   └── readme_fetcher.py
│   │   ├── commands/
│   │   │   ├── __init__.py
│   │   │   ├── navigation.py
│   │   │   ├── selection.py
│   │   │   ├── operations.py
│   │   │   └── custom_commands.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── settings.py
│   │   │   └── keybindings.py
│   │   └── cache/
│   │       ├── __init__.py
│   │       └── offline_store.py
├── config/
│   ├── config.yaml
│   ├── keybindings.yaml
│   └── colorschemes/
│       ├── default.yaml
│       └── nord.yaml
├── scripts/
│   └── install.sh
├── tests/
├── README.md
└── requirements.txt
```

## Configuration
```yaml
# config.yaml
github:
  # OAuth or Personal Access Token
  auth_method: oauth  # oauth | token
  token: ${GITHUB_TOKEN}  # For token auth
  cache_enabled: true
  cache_ttl: 3600  # 1 hour
  rate_limit_buffer: 100  # Reserve 100 requests

ui:
  colorscheme: default
  show_archived: false  # Archived repos
  show_private: true
  preview_lines: 30
  column_ratios: [0.25, 0.35, 0.4]

behavior:
  confirm_unstar: true
  auto_refresh: false
  sort_order: stars  # stars, updated, created, name, language
  auto_categorize: true  # Auto-tag by language/topic

folders:
  # Virtual folder definitions (tag-based)
  default_folders:
    - name: "Python Projects"
      auto_tags: ["python", "py"]
    - name: "JavaScript/TypeScript"
      auto_tags: ["javascript", "typescript", "js", "ts"]
    - name: "AI/ML"
      auto_tags: ["machine-learning", "ai", "deep-learning"]
    - name: "DevOps"
      auto_tags: ["docker", "kubernetes", "ci-cd"]

keybindings:
  # Can be customized in keybindings.yaml
  quit: ['q', 'Q']
  help: ['?']
  command: [':']
```

## UI Layout
```
┌─[Folders]────────┬─[Starred Repos]───────┬─[Preview]─────────┐
│ All Stars      ⟩ │ ★ awesome-python      │ awesome-python    │
│ Python         ⟩ │ • textual             │ @psf              │
│ JavaScript       │ • rich                │ ⭐ 45.2k  🍴 2.1k │
│ ▶ AI/ML          │ • fastapi             │ Updated: 2d ago   │
│ DevOps           │ • pytorch             │ Language: Python  │
│ Archived         │ • tensorflow          │                   │
│                  │                       │ Description:      │
│                  │                       │ A curated list of │
│                  │                       │ awesome Python... │
│                  │                       │                   │
│                  │                       │ README:           │
│                  │                       │ # Awesome Python  │
│                  │                       │ ...               │
├──────────────────┴───────────────────────┴───────────────────┤
│ 127 stars | AI/ML (25) | ★4.2k | yy to copy, pp to paste    │
└───────────────────────────────────────────────────────────────┘
```

## Core Classes
```python
class GitHubRanger:
    def __init__(self):
        self.github_client = GitHubClient()
        self.ui = MillerUI()
        self.clipboard = Clipboard()
        self.command_handler = CommandHandler()

class FolderManager:
    """Manage virtual folders using tags/labels"""
    def get_folders(self) -> List[VirtualFolder]
    def get_repos(self, folder_id: str) -> List[StarredRepo]
    def move_repo(self, repo_id: str, from_folder: str, to_folder: str)
    def copy_repo(self, repo_id: str, to_folder: str)
    def unstar_repo(self, repo_id: str)
    def create_folder(self, name: str, auto_tags: List[str])
    def auto_categorize(self) -> Dict[str, List[StarredRepo]]

class GitHubClient:
    """GitHub API wrapper with rate limiting"""
    def __init__(self, auth_method: str = "oauth"):
        self.rest_api = Github(...)  # PyGithub
        self.graphql = ghapi.GhApi(...)  # GraphQL for bulk queries
        self.rate_limiter = RateLimiter(buffer=100)

    def get_starred_repos(self, limit: int = None) -> List[StarredRepo]
    def star_repo(self, repo_full_name: str)
    def unstar_repo(self, repo_full_name: str)
    def get_repo_metadata(self, repo_full_name: str) -> RepoMetadata
    def get_readme(self, repo_full_name: str) -> str
    def search_stars(self, query: str) -> List[StarredRepo]

    # GraphQL bulk queries for efficiency
    def bulk_fetch_metadata(self, repo_ids: List[str]) -> List[RepoMetadata]

class Clipboard:
    def copy(self, items: List[StarredRepo])
    def cut(self, items: List[StarredRepo], source_folder: str)
    def paste(self, target_folder: str)
    def clear(self)
```

## Data Models
```python
@dataclass
class StarredRepo:
    """Represents a starred repository"""
    id: str
    full_name: str  # owner/repo
    name: str
    owner: str
    description: str
    stars_count: int
    forks_count: int
    language: str
    topics: List[str]
    is_archived: bool
    is_private: bool
    created_at: datetime
    updated_at: datetime
    starred_at: datetime
    url: str
    clone_url: str

    # UI state
    is_selected: bool = False
    is_focused: bool = False

    @classmethod
    def from_github_response(cls, repo: Dict) -> 'StarredRepo':
        # Factory from GitHub API response

@dataclass
class VirtualFolder:
    """Virtual folder based on tags/topics"""
    id: str
    name: str
    auto_tags: List[str]  # Auto-match repos with these topics
    manual_repos: List[str]  # Manually added repo IDs
    repo_count: int
    is_selected: bool = False
    is_focused: bool = False

    def matches_repo(self, repo: StarredRepo) -> bool:
        """Check if repo matches folder criteria"""
        return any(tag in repo.topics for tag in self.auto_tags)

@dataclass
class RepoMetadata:
    """Extended metadata from GraphQL"""
    has_issues: bool
    open_issues_count: int
    has_wiki: bool
    has_projects: bool
    default_branch: str
    license: str
    homepage: str
    readme_content: str  # Cached README
```

## Advanced Features

### Bulk Operations
```python
# Visual mode selection
with visual_mode():
    select_range(start=5, end=15)
    clipboard.cut(selected_items)
    navigate_to_folder("AI/ML")
    clipboard.paste()
```

### Custom Commands
```
:move 5-10 to "AI/ML"           # Move range to folder
:sort stars desc                # Sort by star count
:filter language:python         # Filter by language
:export starred.json            # Export stars organization
:import awesome-python          # Import from Awesome list
:clone marked ~/repos/          # Clone all marked repos
:auto-tag                       # Auto-categorize all repos
```

### Auto-Categorization
```python
def auto_categorize(repos: List[StarredRepo]) -> Dict[str, List[StarredRepo]]:
    """
    Automatically organize repos into folders based on:
    - Primary language
    - Topics/tags
    - Activity level (last updated)
    - Star count (trending vs established)
    """
    categories = {
        "Python": [],
        "JavaScript": [],
        "AI/ML": [],
        "DevOps": [],
        "Archived": [],  # Not updated in 2+ years
        "Trending": [],  # High recent activity
    }

    for repo in repos:
        if repo.is_archived or days_since_update(repo) > 730:
            categories["Archived"].append(repo)
        elif repo.language == "Python":
            categories["Python"].append(repo)
        # ... more logic

    return categories
```

### Macro Support (Same as yanger)
```
qa         # Start recording macro 'a'
5j         # Move down 5
dd         # Cut repo
h          # Go to folders
5j         # Navigate to target
l          # Enter folder
pp         # Paste
q          # Stop recording
@a         # Play macro 'a'
10@a       # Play macro 10 times
```

## GitHub API Integration

### Rate Limiting
GitHub API limits:
- **Authenticated REST**: 5,000 requests/hour
- **GraphQL**: 5,000 points/hour (query cost varies)
- **Search**: 30 requests/minute

Strategy:
```python
class RateLimiter:
    def __init__(self, buffer: int = 100):
        self.buffer = buffer

    def check_and_wait(self):
        remaining = self.get_remaining_requests()
        if remaining < self.buffer:
            reset_time = self.get_reset_time()
            self.show_warning(f"Rate limit low. Waiting until {reset_time}")
            time.sleep(reset_time - time.time())
```

### GraphQL Optimization
Fetch multiple repos in a single query:
```graphql
query GetStarredRepos($cursor: String) {
  viewer {
    starredRepositories(first: 100, after: $cursor) {
      edges {
        starredAt
        node {
          id
          nameWithOwner
          description
          stargazerCount
          forkCount
          primaryLanguage { name }
          repositoryTopics(first: 10) {
            nodes { topic { name } }
          }
          updatedAt
          createdAt
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
```

### OAuth Setup
```python
class GitHubAuth:
    SCOPES = [
        "user",           # Read user profile
        "repo",           # Full repo access (for private repos)
        "read:org",       # Read org info
    ]

    def authenticate(self) -> str:
        """OAuth device flow"""
        # 1. Request device code
        # 2. Show user code and URL
        # 3. Poll for authorization
        # 4. Store access token

    def refresh_token(self):
        # GitHub tokens don't expire, but can be revoked

    def get_token(self) -> str:
        # Read from keyring/config
```

## Development Phases

### Phase 1: Core Navigation (Week 1-2)
- [ ] Basic TUI with three columns
- [ ] GitHub API integration (REST + GraphQL)
- [ ] OAuth authentication
- [ ] Simple navigation (hjkl)
- [ ] Folder and repo listing
- [ ] SQLite cache setup

### Phase 2: Basic Operations (Week 3-4)
- [ ] Virtual folder creation
- [ ] Add/remove repos from folders
- [ ] Star/unstar functionality
- [ ] Repo selection
- [ ] Basic search across stars

### Phase 3: Advanced Features (Week 5-6)
- [ ] Visual mode
- [ ] Bulk operations
- [ ] Command line mode
- [ ] Sorting and filtering
- [ ] README preview
- [ ] Auto-categorization

### Phase 4: Polish (Week 7-8)
- [ ] Offline cache optimization
- [ ] Macros
- [ ] Custom keybindings
- [ ] Colorschemes
- [ ] Import from Awesome lists
- [ ] Export to various formats
- [ ] Clone integration

## Performance Optimizations
- Lazy loading of repo lists (pagination)
- Asynchronous API calls
- Local caching of repo metadata (SQLite)
- GraphQL bulk queries to reduce API calls
- Diff-based updates (only sync changes)
- README caching with TTL

## Error Handling
```python
try:
    self.github_client.add_to_folder(repo_id, target_folder)
except RateLimitExceeded:
    self.show_error("API rate limit exceeded. Try again later.")
except RepoNotFound:
    self.show_error("Repository not found or no longer accessible")
except PermissionError:
    self.show_error("Cannot access this repository (may be private)")
except NetworkError:
    self.show_warning("Network error. Using cached data.")
```

## Cache Schema
```sql
CREATE TABLE starred_repos (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    name TEXT,
    owner TEXT,
    description TEXT,
    stars_count INTEGER,
    forks_count INTEGER,
    language TEXT,
    topics TEXT,  -- JSON array
    is_archived BOOLEAN,
    is_private BOOLEAN,
    created_at TEXT,
    updated_at TEXT,
    starred_at TEXT,
    url TEXT,
    clone_url TEXT,
    cached_at TEXT,
    UNIQUE(full_name)
);

CREATE TABLE virtual_folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    auto_tags TEXT,  -- JSON array
    created_at TEXT
);

CREATE TABLE folder_repos (
    folder_id TEXT,
    repo_id TEXT,
    added_at TEXT,
    is_manual BOOLEAN,  -- Manually added or auto-matched
    PRIMARY KEY (folder_id, repo_id),
    FOREIGN KEY (folder_id) REFERENCES virtual_folders(id),
    FOREIGN KEY (repo_id) REFERENCES starred_repos(id)
);

CREATE TABLE repo_metadata (
    repo_id TEXT PRIMARY KEY,
    readme_content TEXT,
    readme_format TEXT,  -- markdown, rst, txt
    has_issues BOOLEAN,
    open_issues_count INTEGER,
    license TEXT,
    homepage TEXT,
    cached_at TEXT,
    FOREIGN KEY (repo_id) REFERENCES starred_repos(id)
);

CREATE INDEX idx_language ON starred_repos(language);
CREATE INDEX idx_updated_at ON starred_repos(updated_at);
CREATE INDEX idx_stars_count ON starred_repos(stars_count);
CREATE INDEX idx_folder_repos ON folder_repos(folder_id, repo_id);
```

## Future Enhancements
- Folder merge/split operations
- Duplicate detection across folders
- Smart folders (dynamic queries)
- Integration with `gh` CLI for advanced operations
- Clone repo directly from UI
- Open issues/PRs in browser
- Repo statistics and analytics
- Trending stars detection
- Dependency graph visualization
- Import from other bookmark services
- Export to Awesome list format (Markdown)
- Undo/redo functionality (Command pattern from yanger)
- Plugin system for extensions
- Multi-account support
- Sync across devices

## Import/Export Formats

### Import Sources
- GitHub API (sync all stars)
- Awesome lists (Markdown parsing)
- GitHub stars export JSON
- Bookmark HTML files

### Export Formats
```python
class StarExporter:
    def export_all(self, output_path: str, format: str = 'json'):
        """
        Formats:
        - JSON: Full metadata
        - YAML: Structured hierarchy
        - Markdown: Awesome list style
        - CSV: Spreadsheet compatible
        - HTML: Bookmarks format
        """
```

Example Markdown export (Awesome list format):
```markdown
# My GitHub Stars

## Python
- [awesome-python](https://github.com/vinta/awesome-python) - A curated list of awesome Python frameworks
- [textual](https://github.com/Textualize/textual) - TUI framework for Python

## AI/ML
- [pytorch](https://github.com/pytorch/pytorch) - Tensors and Dynamic neural networks
...
```

## Integration with `gh` CLI
```bash
# Use GitHub CLI for operations ganger can't do
ganger shell gh issue list --repo {repo}
ganger shell gh pr create --repo {repo}
```

## Testing Strategy
- Unit tests for core logic (API client, folder manager)
- Integration tests for GitHub API (with mocking)
- UI tests with Textual's testing framework
- Cache persistence tests
- Rate limiting tests
- Authentication flow tests

## Differences from Yanger

### Conceptual Differences
| Yanger (YouTube) | Ganger (GitHub) |
|------------------|-----------------|
| Playlists (native) | Virtual folders (tags) |
| Videos | Starred repos |
| Move between playlists | Add/remove folder tags |
| YouTube quota (10k/day) | GitHub rate limit (5k/hour) |
| OAuth only | OAuth or PAT |
| Video playback | Clone/browse repo |
| Transcripts | READMEs |

### Technical Differences
- **API**: REST + GraphQL hybrid (GitHub) vs REST only (YouTube)
- **Rate limiting**: Per-hour (GitHub) vs daily quota (YouTube)
- **Caching**: More aggressive (GitHub data changes less frequently)
- **Virtual folders**: Core concept (GitHub) vs optional tags (YouTube)
- **Auto-categorization**: Essential (GitHub) vs nice-to-have (YouTube)

### Unique GitHub Features
- Language-based auto-categorization
- Topic/tag matching for folders
- README preview with Markdown rendering
- Integration with `gh` CLI
- Clone repo directly
- View issues/PRs counts
- Trending detection (recent activity spikes)
- Dependency analysis (future)

---

**Ganger v1.0 | GitHub Stars Manager | Inspired by ranger and yanger**

## Architecture Notes (From Yanger)

Ganger will reuse the proven architecture from yanger:

1. **Data Model Pattern**: `StarredRepo`, `VirtualFolder`, `Clipboard` (from `models.py`)
2. **API Client Pattern**: `GitHubAPIClient` with rate limiting (from `api_client.py`)
3. **Authentication**: OAuth2 flow (from `auth.py`)
4. **Cache**: SQLite persistence (from `cache.py`)
5. **Miller View**: Three-column layout (from `ui/miller_view.py`)
6. **Keybinding Registry**: Context-aware bindings (from `keybindings.py`)
7. **Command Pattern**: Undo/redo operations (from `operation_history.py`)
8. **Settings**: Dataclass-based config (from `config/settings.py`)
9. **CLI**: Click-based subcommands (from `cli.py`)
10. **Export**: Multi-format export (from `export.py`)

Reference yanger source code at `/Users/ryoung/Code/repos/NewCliProjects/yanger/` for implementation patterns.
