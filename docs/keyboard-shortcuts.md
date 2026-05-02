# Keyboard Shortcuts

Ganger uses vim-style modal navigation. Single keys move and select; chord
keys (`gn`, `dd`, `yy`) trigger actions; `:` opens command mode for things
that need an argument.

This guide tracks **what is implemented today**. Features still in flight
are listed at the bottom under "Coming soon" so you know what NOT to
expect yet.

## Conventions

- A pair like `gg` means "press `g`, then `g`". Don't release between.
- A pair like `Ctrl+R` means hold `Ctrl` while pressing `R`.
- Lowercase vs uppercase letters are different keys (`v` ≠ `V`).
- Bindings are scoped to a column (the active focus). `j/k` in the folder
  column scrolls folders; in the repo column it scrolls repos.

## Application

| Key | Action |
|---|---|
| `?` | Toggle the help overlay |
| `:` | Enter command mode (see below) |
| `q` | Quit |
| `Ctrl+Q` | Force quit (skips confirmations) |
| `Ctrl+R` | Refresh the current view from cache |
| `Ctrl+Shift+R` | Sync from GitHub (force refresh, hits the API) |

## Navigation

| Key | Action |
|---|---|
| `h` | Move focus to the column on the left |
| `j` | Move down one item |
| `k` | Move up one item |
| `l` | Move focus to the column on the right (or enter a folder) |
| `gg` | Jump to the first item in the current column |
| `G` | Jump to the last item in the current column |
| `Enter` | Select the current item (open folder / focus repo) |

`h` and `l` form the cross-column traversal: `l` from the folder column
loads the folder's repos in the middle column; `l` from the repo column
focuses the preview pane on the right; `h` reverses.

## Selecting repos

The repo column supports marking multiple repos for a bulk operation.
Marks are independent of focus — focus follows `j/k`, marks toggle with
`Space`.

| Key | Action |
|---|---|
| `Space` | Toggle the mark on the focused repo |
| `V` | Visual mode (range selection — *not yet wired*) |
| `v` | Invert the current selection (*not yet wired*) |
| `uv` | Unmark all repos |

If you trigger an operation (cut/copy/paste) with no marks set, it acts
on the focused repo only.

## Cut, copy, paste

These are the ranger-style operations that move repos between virtual
folders. They never affect GitHub itself — only the local virtual folder
membership.

| Key | Action |
|---|---|
| `yy` | **Copy** marked (or focused) repos to the clipboard |
| `dd` | **Cut** marked (or focused) repos to the clipboard |
| `pp` | **Paste** clipboard repos into the current folder |
| `dD` | Unstar the focused repo on GitHub (*coming in Phase 3*) |

Cut and paste are local virtual operations — the repo stays starred
either way. Only `dD` actually mutates your GitHub account.

## Folder operations

| Key | Action |
|---|---|
| `gn` | Create a new virtual folder (opens a modal) |
| `gd` | Delete the focused folder if it is empty |
| `gm` | Merge folders (*coming soon*) |
| `cw` | Rename the focused folder (*coming in slice 7*) |

The `gn` modal currently asks for a name, description, and comma-separated
auto-tags. Behind the scenes:

- If you provide auto-tags, the folder is created as `kind="rule"` and
  immediately auto-categorizes any matching repos.
- If you leave auto-tags empty, the folder is `kind="curated"` — a
  hand-curated list with stable ordering (positions are managed via
  paste / future reorder commands).

You cannot create folders of `kind="system"` from the UI. The `all-stars`
folder is the only system folder and is managed automatically.

## Search

| Key | Action |
|---|---|
| `/` | Open the search box |
| `n` | Jump to the next search hit (*partially wired*) |
| `N` | Jump to the previous search hit (*partially wired*) |
| `Esc` | Close search / cancel visual mode |

Search filters folders and repos by name and description in real time.

## GitHub actions on a repo

| Key | Action |
|---|---|
| `gb` | Open the focused repo in your browser |
| `gc` | Clone the repo (*coming soon*) |
| `gi` | View open issues (*coming soon*) |
| `gp` | View open pull requests (*coming soon*) |
| `gr` | View the README in the preview pane |
| `gf` | Refresh metadata for this repo |
| `gs` | Toggle star/unstar (*coming soon*) |
| `gR` | Refresh all repos (same as `Ctrl+Shift+R`) |

## Tags

| Key | Action |
|---|---|
| `gt` | Manage user tags on the focused repo (*coming in slice 3*) |
| `ga` | Auto-categorize all repos by language/topic |

`gt` will open a tag-management modal once slice 3 ships. Until then,
the tag database is reachable through `:tag` / `:untag` and the cache
API. See [tags.md](tags.md) for the data model and how to use tags
without the UI.

## Auto-categorization

| Key | Action |
|---|---|
| `ga` | Re-run auto-categorization across `kind ∈ {rule, hybrid}` folders |

Auto-categorization scans every folder whose `kind` is `rule` or `hybrid`
and adds any starred repos that match the folder's `auto_tags`. Curated
and system folders are never touched.

This runs automatically on app start when `behavior.auto_categorize: true`
in `config.yaml`. The `ga` shortcut just triggers a manual rerun.

## Undo / redo

| Key | Action |
|---|---|
| `u` | Undo the last operation (*not yet wired*) |
| `U` | Redo the last undone operation (*not yet wired*) |

Reserved bindings; the operation history pattern from yanger will be
ported in a later phase.

## Sort

| Key | Action |
|---|---|
| `o` | Open the sort menu (*not yet wired*) |

Until `o` is wired up, use `:sort <field> [order]` from command mode.

## Command mode (`:`)

Press `:` to type a command. The exhaustive list lives in the source of
truth: `src/ganger/tui/keybindings.py`. Snapshot of what's available:

| Command | Purpose |
|---|---|
| `:quit` (`:q`) | Quit |
| `:help [command]` | Show all commands, or details on one |
| `:refresh [all]` | Refresh from cache, or `:refresh all` to sync from GitHub |
| `:cache status` | Show cache stats |
| `:cache clear` | Wipe the local cache |
| `:rate` | Show GitHub API rate-limit headroom |
| `:stats` | Folder/repo statistics |
| `:sort <field> [asc\|desc]` | Sort the repo column |
| `:filter <criteria>` | Filter repos (e.g. `:filter language:python`) |
| `:clear marks\|filter\|search` | Reset state |
| `:auto` | Auto-categorize (same as `ga`) |
| `:move <repo> <folder>` | Move a repo by name or number |
| `:tag <repo> <tags...>` | Add tags to a repo (*coming in slice 3*) |
| `:untag <repo> <tag>` | Remove a tag (*coming in slice 3*) |
| `:export <fmt> [path]` | Export repos in `json`/`md`/`csv`/`yaml` (*coming in slice 4*) |
| `:import <path>` | Import from a file (*coming in slice 5*) |
| `:clone <dir>` | Clone marked repos to a directory (*coming soon*) |
| `:reorder` | Open the reorder modal for curated/hybrid folders (*coming in slice 6*) |
| `:rename <new>` | Rename the focused folder (*coming in slice 7*) |

## Coming soon

Tracked against the rollout plan in
`/Users/ryoung/.claude/plans/okay-let-s-plan-out-curious-meadow.md`:

| Slice | What it ships |
|---|---|
| 2B | Stub identity-upgrade for imported-but-unstarred repos |
| 3 | `gt` tag modal, `:tag`/`:untag`, PreviewPane "Tags" block, `:filter tag:` |
| 4 | `:export <json\|yaml\|md\|csv>` + CLI `ganger export` |
| 5 | `:import` + CLI `ganger import` (json / yaml / awesome-list) |
| 6 | `K`/`J` to reorder repos in curated/hybrid folders, `:reorder` modal |
| 7 | Folder kind selector in `gn` modal, `:rename` modal |

If a binding is listed in the help overlay but appears to do nothing,
check this column — most "missing" features are wired in the registry
but waiting on a later slice for the action handler.
