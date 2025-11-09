"""
MCP server for Ganger.

Exposes GitHub star management operations as MCP tools for LLM orchestration.

Modified: 2025-11-07
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server

from ganger.core.auth import GitHubAuth
from ganger.core.github_client import GitHubAPIClient
from ganger.core.cache import PersistentCache
from ganger.core.folder_manager import FolderManager
from ganger.core.exceptions import GangerError, AuthenticationError


class GangerMCPServer:
    """
    MCP server for Ganger.

    Provides tools for managing GitHub starred repositories via MCP.
    """

    def __init__(
        self,
        auth: Optional[GitHubAuth] = None,
        cache_path: Optional[Path] = None,
        cache_ttl: int = 3600,
    ):
        """
        Initialize Ganger MCP server.

        Args:
            auth: GitHubAuth instance (will create if None)
            cache_path: Path to cache database
            cache_ttl: Cache TTL in seconds
        """
        # Initialize core components
        if auth is None:
            auth = GitHubAuth()
            try:
                auth.authenticate()
            except AuthenticationError as e:
                raise GangerError(f"Authentication required: {e}")

        self.auth = auth
        self.github_client = GitHubAPIClient(auth)

        # Initialize cache and folder manager
        self.cache = PersistentCache(db_path=cache_path, ttl_seconds=cache_ttl)
        self.folder_manager: Optional[FolderManager] = None

        # MCP server
        self.server = Server("ganger")

    async def initialize(self):
        """Initialize async components (cache, folder manager)."""
        await self.cache.initialize()
        self.folder_manager = FolderManager(self.cache)

    def run(self):
        """Run the MCP server."""
        async def _run():
            await self.initialize()

            # Import and register tools
            from ganger.mcp.tools import register_tools
            register_tools(self.server, self)

            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream, write_stream, self.server.create_initialization_options()
                )

        asyncio.run(_run())


def create_server(
    cache_path: Optional[Path] = None,
    cache_ttl: int = 3600,
) -> GangerMCPServer:
    """
    Create and configure a Ganger MCP server.

    Args:
        cache_path: Optional cache database path
        cache_ttl: Cache TTL in seconds

    Returns:
        Configured GangerMCPServer instance
    """
    return GangerMCPServer(cache_path=cache_path, cache_ttl=cache_ttl)


def main():
    """Main entry point for MCP server."""
    # Get cache path from env or use default
    cache_path_str = os.getenv("GANGER_CACHE_PATH")
    cache_path = Path(cache_path_str) if cache_path_str else None

    # Get cache TTL from env or use default
    cache_ttl = int(os.getenv("GANGER_CACHE_TTL", "3600"))

    server = create_server(cache_path=cache_path, cache_ttl=cache_ttl)
    server.run()


if __name__ == "__main__":
    main()
