"""
MCP tools for Ganger.

Defines all MCP tools that expose Ganger functionality to LLMs.

Modified: 2025-11-07
"""

from typing import Any, Dict, List
from mcp.server import Server
from mcp.types import Tool, TextContent

from ganger.core.exceptions import GangerError


def register_tools(server: Server, ganger_server: Any) -> None:
    """
    Register all Ganger MCP tools with the server.

    Args:
        server: MCP Server instance
        ganger_server: GangerMCPServer instance with initialized components
    """

    # ==================== Repository Tools ====================

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List all available tools."""
        return [
            Tool(
                name="list_starred_repos",
                description="Get all starred repositories for the authenticated user. Returns a list of repos with metadata.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "use_cache": {
                            "type": "boolean",
                            "description": "Use cached data if available (default: true)",
                            "default": True,
                        },
                        "max_count": {
                            "type": "integer",
                            "description": "Maximum number of repos to return (optional)",
                        },
                    },
                },
            ),
            Tool(
                name="get_repo_details",
                description="Get detailed information about a specific repository including README.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "full_name": {
                            "type": "string",
                            "description": "Repository full name (e.g., 'octocat/Hello-World')",
                        },
                    },
                    "required": ["full_name"],
                },
            ),
            Tool(
                name="star_repository",
                description="Star a repository on GitHub.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "full_name": {
                            "type": "string",
                            "description": "Repository full name (e.g., 'octocat/Hello-World')",
                        },
                    },
                    "required": ["full_name"],
                },
            ),
            Tool(
                name="unstar_repository",
                description="Unstar a repository on GitHub.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "full_name": {
                            "type": "string",
                            "description": "Repository full name (e.g., 'octocat/Hello-World')",
                        },
                    },
                    "required": ["full_name"],
                },
            ),
            Tool(
                name="search_repositories",
                description="Search for repositories on GitHub (not limited to starred repos).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'language:python stars:>1000')",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 30)",
                            "default": 30,
                        },
                    },
                    "required": ["query"],
                },
            ),
            # ==================== Folder Tools ====================
            Tool(
                name="list_folders",
                description="Get all virtual folders for organizing starred repos.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="create_virtual_folder",
                description="Create a new virtual folder with optional auto-tagging.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Folder name",
                        },
                        "auto_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for auto-matching repos (e.g., ['python', 'ml'])",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional folder description",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="delete_virtual_folder",
                description="Delete a virtual folder (repos are not deleted).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Folder ID to delete",
                        },
                    },
                    "required": ["folder_id"],
                },
            ),
            Tool(
                name="get_folder_repos",
                description="Get all repositories in a virtual folder.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Folder ID",
                        },
                    },
                    "required": ["folder_id"],
                },
            ),
            # ==================== Repo-Folder Operations ====================
            Tool(
                name="add_repo_to_folder",
                description="Add a repository to a virtual folder.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "Repository ID",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Folder ID",
                        },
                    },
                    "required": ["repo_id", "folder_id"],
                },
            ),
            Tool(
                name="remove_repo_from_folder",
                description="Remove a repository from a virtual folder.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "Repository ID",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Folder ID",
                        },
                    },
                    "required": ["repo_id", "folder_id"],
                },
            ),
            Tool(
                name="move_repo_to_folder",
                description="Move a repository from one folder to another.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "Repository ID",
                        },
                        "from_folder_id": {
                            "type": "string",
                            "description": "Source folder ID",
                        },
                        "to_folder_id": {
                            "type": "string",
                            "description": "Destination folder ID",
                        },
                    },
                    "required": ["repo_id", "from_folder_id", "to_folder_id"],
                },
            ),
            # ==================== Auto-Categorization Tools ====================
            Tool(
                name="auto_categorize_all",
                description="Auto-categorize all starred repos into folders based on tags and topics.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="suggest_folders_for_repo",
                description="Suggest folders for a repository based on its topics and language.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "Repository ID",
                        },
                    },
                    "required": ["repo_id"],
                },
            ),
            # ==================== Statistics Tools ====================
            Tool(
                name="get_folder_stats",
                description="Get statistics for a folder (repo count, stars, languages).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Folder ID",
                        },
                    },
                    "required": ["folder_id"],
                },
            ),
            Tool(
                name="get_cache_stats",
                description="Get cache statistics (repo count, folder count, cache age).",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    # ==================== Tool Implementations ====================

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle tool calls."""
        try:
            result = await _handle_tool_call(name, arguments, ganger_server)
            return [TextContent(type="text", text=str(result))]
        except GangerError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Unexpected error: {str(e)}")]


async def _handle_tool_call(
    name: str, arguments: dict, ganger_server: Any
) -> Dict[str, Any]:
    """
    Handle individual tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        ganger_server: GangerMCPServer instance

    Returns:
        Tool result as dictionary
    """
    github = ganger_server.github_client
    folder_mgr = ganger_server.folder_manager
    cache = ganger_server.cache

    # Repository tools
    if name == "list_starred_repos":
        use_cache = arguments.get("use_cache", True)
        max_count = arguments.get("max_count")

        if use_cache:
            repos = await cache.get_starred_repos()
            if repos is None:
                # Cache miss, fetch from GitHub
                repos = github.get_starred_repos(max_count=max_count)
                await cache.set_starred_repos(repos)
        else:
            repos = github.get_starred_repos(max_count=max_count)
            await cache.set_starred_repos(repos)

        return {
            "count": len(repos),
            "repos": [
                {
                    "id": r.id,
                    "full_name": r.full_name,
                    "description": r.description,
                    "stars": r.stars_count,
                    "language": r.language,
                    "topics": r.topics,
                    "url": r.url,
                }
                for r in repos
            ],
        }

    elif name == "get_repo_details":
        full_name = arguments["full_name"]
        repo = github.get_repo(full_name)
        metadata = github.get_readme(full_name)

        # Cache metadata
        if metadata:
            await cache.set_repo_metadata(metadata)

        return {
            "repo": repo.to_dict(),
            "readme": metadata.readme_content if metadata else None,
            "has_issues": metadata.has_issues if metadata else None,
            "open_issues": metadata.open_issues_count if metadata else None,
        }

    elif name == "star_repository":
        full_name = arguments["full_name"]
        github.star_repo(full_name)
        return {"success": True, "message": f"Starred {full_name}"}

    elif name == "unstar_repository":
        full_name = arguments["full_name"]
        github.unstar_repo(full_name)
        return {"success": True, "message": f"Unstarred {full_name}"}

    elif name == "search_repositories":
        query = arguments["query"]
        max_results = arguments.get("max_results", 30)
        repos = github.search_repos(query, max_results)

        return {
            "count": len(repos),
            "repos": [{"full_name": r.full_name, "stars": r.stars_count} for r in repos],
        }

    # Folder tools
    elif name == "list_folders":
        folders = await folder_mgr.get_all_folders()
        return {
            "count": len(folders),
            "folders": [
                {
                    "id": f.id,
                    "name": f.name,
                    "auto_tags": f.auto_tags,
                    "repo_count": f.repo_count,
                }
                for f in folders
            ],
        }

    elif name == "create_virtual_folder":
        name_arg = arguments["name"]
        auto_tags = arguments.get("auto_tags", [])
        description = arguments.get("description", "")

        folder = await folder_mgr.create_folder(name_arg, auto_tags, description)
        return {
            "success": True,
            "folder": {"id": folder.id, "name": folder.name, "auto_tags": folder.auto_tags},
        }

    elif name == "delete_virtual_folder":
        folder_id = arguments["folder_id"]
        await folder_mgr.delete_folder(folder_id)
        return {"success": True, "message": f"Deleted folder {folder_id}"}

    elif name == "get_folder_repos":
        folder_id = arguments["folder_id"]
        repos = await folder_mgr.get_folder_repos(folder_id)
        return {
            "count": len(repos),
            "repos": [{"id": r.id, "full_name": r.full_name, "stars": r.stars_count} for r in repos],
        }

    # Repo-folder operations
    elif name == "add_repo_to_folder":
        repo_id = arguments["repo_id"]
        folder_id = arguments["folder_id"]
        await folder_mgr.add_repo_to_folder(repo_id, folder_id)
        return {"success": True, "message": "Repo added to folder"}

    elif name == "remove_repo_from_folder":
        repo_id = arguments["repo_id"]
        folder_id = arguments["folder_id"]
        await folder_mgr.remove_repo_from_folder(repo_id, folder_id)
        return {"success": True, "message": "Repo removed from folder"}

    elif name == "move_repo_to_folder":
        repo_id = arguments["repo_id"]
        from_folder_id = arguments["from_folder_id"]
        to_folder_id = arguments["to_folder_id"]
        await folder_mgr.move_repo(repo_id, from_folder_id, to_folder_id)
        return {"success": True, "message": "Repo moved"}

    # Auto-categorization
    elif name == "auto_categorize_all":
        stats = await folder_mgr.auto_categorize_all()
        return {"success": True, "stats": stats}

    elif name == "suggest_folders_for_repo":
        repo_id = arguments["repo_id"]
        repo = await cache.get_repo(repo_id)
        if not repo:
            return {"error": "Repo not found"}

        suggestions = await folder_mgr.suggest_folders_for_repo(repo)
        return {
            "count": len(suggestions),
            "folders": [{"id": f.id, "name": f.name} for f in suggestions],
        }

    # Statistics
    elif name == "get_folder_stats":
        folder_id = arguments["folder_id"]
        stats = await folder_mgr.get_folder_stats(folder_id)
        return stats

    elif name == "get_cache_stats":
        stats = await cache.get_stats()
        return stats

    else:
        return {"error": f"Unknown tool: {name}"}
