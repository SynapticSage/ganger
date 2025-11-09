"""
MCP (Model Context Protocol) interface for Ganger.

Exposes Ganger's core functionality as MCP tools, allowing LLM agents
to orchestrate GitHub star management operations.

Modified: 2025-11-07
"""

from ganger.mcp.server import GangerMCPServer, create_server, main

__all__ = ["GangerMCPServer", "create_server", "main", "server", "tools"]
