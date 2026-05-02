# Tags

Ganger has two distinct tag concepts. Knowing which is which prevents
confusion later when you import/export or write filters.

## Two kinds of tags

| Field | Source | Mutable? | Storage |
|---|---|---|---|
| `topics` | GitHub | Read-only (mirrored from the API) | `starred_repos.topics` (JSON column) |
| `user_tags` | You | Yes — local-only | `user_tags` table (many-to-many) |

**`topics`** are GitHub's repository topics — the labels owners attach to
their repos under the description. They reflect what the *project* is
about, not what *you* think of it. Ganger surfaces them in the preview
pane, uses them for `kind="rule"` folder matching, and treats them as
read-only.

**`user_tags`** are private notes you attach to a repo. They never leave
your machine unless you export them. Use them for things like:

- `to-read`, `to-try`, `archived-mentally`
- `work`, `personal`, `homelab`
- `production`, `experimental`, `dropped`
- `tutorial`, `reference`, `book`

`user_tags` are the underpinning for personal organization that doesn't
fit GitHub's notion of what a repo "is."

## Data model

```
starred_repos
  id                     TEXT PK
  full_name              TEXT UNIQUE
  topics                 TEXT  -- JSON list, GitHub-sourced
  ...
  is_stub                BOOLEAN  -- 1 if added by import, not yet starred

user_tags
  repo_id                TEXT  -> starred_repos.id  (CASCADE delete)
  tag                    TEXT
  added_at               TEXT  -- ISO timestamp
  PRIMARY KEY (repo_id, tag)
```

The `(repo_id, tag)` primary key makes adding the same tag twice a
no-op rather than a duplicate row. The `ON DELETE CASCADE` means
unstarring a repo (which prunes the `starred_repos` row) automatically
removes its tags.

## Tag identity is case-insensitive

Every tag is normalized at write time:

- Lowercased
- Stripped of leading and trailing whitespace
- Empty / whitespace-only tags rejected with `CacheError`

So these all collapse to the single tag `"python"`:

```python
await cache.add_user_tag("repo-1", "Python")
await cache.add_user_tag("repo-1", "  python  ")
await cache.add_user_tag("repo-1", "PYTHON")
# get_user_tags("repo-1") -> ["python"]
```

The `set_user_tags` bulk replace also dedupes:

```python
await cache.set_user_tags("repo-1", ["Python", "python", " PYTHON "])
# -> stored as ["python"]
```

## Reading tags from code

```python
# Single repo
tags = await cache.get_user_tags(repo_id)        # -> List[str]

# All tags with usage counts (good for autocomplete UIs)
counts = await cache.list_all_tags()             # -> Dict[str, int]
# {"work": 12, "to-read": 47, "ml": 8}
```

When you fetch a repo via `cache.get_repo(...)` or `cache.get_starred_repos()`,
the returned `StarredRepo` already has `user_tags` populated as a list:

```python
repo = await cache.get_repo("12345")
print(repo.topics)      # ["python", "ml"]            (from GitHub)
print(repo.user_tags)   # ["to-read", "work"]         (from your tags)
```

The same applies to `cache.get_folder_repos(folder_id)` — every kind
branch (rule, curated, hybrid, system) hydrates `user_tags` for the
returned repos via a single keyed query, not a per-row lookup, so the
cost is one extra round trip regardless of folder size.

## Writing tags from code

The four CRUD operations mirror typical many-to-many ergonomics:

```python
# Add one tag (idempotent — duplicate adds are no-ops)
await cache.add_user_tag("repo-1", "to-read")

# Remove one tag (no-op if not present)
await cache.remove_user_tag("repo-1", "to-read")

# Replace the entire tag set on a repo (atomic delete-then-insert)
await cache.set_user_tags("repo-1", ["work", "ml", "active"])
```

`set_user_tags` runs in a single transaction. If the insert step fails
for any reason, the previous tags are restored — you cannot end up with
a half-replaced tag set.

## TUI surface (status: in flight)

The data layer is complete as of slice 2A. The TUI bindings ship in
slice 3:

| Surface | Slice | What it does |
|---|---|---|
| `gt` keybinding | 3 | Opens a tag modal: list current tags as removable chips, free-text input with autocomplete from `list_all_tags()`. Bulk-applies to all marked repos when more than one is selected. |
| `:tag <names...>` | 3 | Adds tags to focused (or marked) repos. Comma-separated. |
| `:untag <name>` | 3 | Removes a tag from focused (or marked) repos. |
| Preview pane "Tags" block | 3 | Renders `user_tags` under `topics`, in a different color so the distinction is visible. |
| `:filter tag:<name>` | 3 | Filters the repo column to repos that have the named user_tag. |

Until slice 3 lands, there is no in-app way to view or edit user_tags;
the cache layer methods above are the only access path.

## Import / export semantics (status: in flight)

User tags are part of the canonical export envelope:

```jsonc
{
  "ganger_export_version": 3,
  "repos": [
    {
      "id": "12345",
      "full_name": "vinta/awesome-python",
      "topics": ["python", "awesome", "list"],     // from GitHub
      "user_tags": ["to-read", "reference"],       // from you
      "is_stub": false
    }
  ]
}
```

`topics` and `user_tags` are emitted as **native JSON arrays** (not
JSON-encoded strings) by `to_export_dict()`. The cache-internal
`to_dict()` shape uses strings — that's a SQLite storage detail that
should never leak into the public contract.

Import semantics:

- **Merge mode** (default): incoming `user_tags` are unioned with what
  you already have. Tags on the import side do not override yours.
- **Replace mode**: tags are replaced wholesale per repo.

If an import references a repo you haven't actually starred, Ganger
inserts a **stub** row (`is_stub=1`) so the tags can attach to *something*
before the next API sync. When you next star the real repo, the stub
identity-upgrade path (slice 2B) reparents the `user_tags` rows
transactionally to the real repo id, with no loss.

The full import schema lives at `docs/IMPORT_SCHEMA.md` (ships in slice 4
alongside the export feature).

## How tags interact with folders

User tags are orthogonal to folders:

- A repo can have any number of tags AND be in any number of folders.
- Folder kinds (`rule`, `curated`, `hybrid`, `system`) do not touch
  `user_tags`. A `kind="rule"` folder matches on GitHub `topics` and
  language only; tags don't enter the picture.
- `:filter tag:<name>` (slice 3) is a *view* filter on top of whatever
  the current folder displays — it doesn't move the repo or change
  membership.

If you want a folder that's defined by a user tag — say "everything
I've tagged `to-read`" — you'll create that as a curated folder (in
slice 6+) and use `:filter tag:to-read` to populate it interactively.
There's no `kind="tag-rule"` enum value; the design intentionally keeps
tags decoupled from folder definition so you can re-tag without
restructuring folders.

## Practical workflow examples

**Triage incoming stars**: tag everything new with `to-review`, then
filter and burn through them; remove the tag once you've decided.

**Time-bound projects**: tag with the project name (`acme-q3-2026`).
When the project ends, `:filter tag:acme-q3-2026` to find them all,
either delete the tag or move them to an archive folder.

**Cross-folder marking**: a repo in your "Python" folder might also
deserve `infra` and `homelab` tags. Folders pick *one* organizing axis;
tags are the orthogonal one.

**Public/private split**: tag truly personal stuff `private`. When you
export to share with someone, set the export filter to exclude
`tag:private` (slice 4 will support this).

## Reserved tag names

None — Ganger does not reserve any tag names. You can use anything that
survives normalization (lowercase + strip + non-empty). If a future
feature ever needs a sentinel tag, it will live in a separate `system_tags`
table, not in `user_tags`.

## Cleanup

- Removing a starred repo (unstar + sync) cascades and removes its tags.
- A tag with zero references is *not* automatically deleted because
  there's no top-level `tags` table — tag rows live entirely as
  `(repo_id, tag)` pairs. `list_all_tags()` aggregates dynamically and
  simply omits unused tag names from the count.
- To rename a tag, use `set_user_tags` per repo (or wait for the bulk
  rename feature, which isn't on the rollout yet).
