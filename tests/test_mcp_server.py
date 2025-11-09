"""
Tests for MCP server.

Modified: 2025-11-07
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from ganger.mcp.server import create_server, GangerMCPServer
from ganger.core.auth import GitHubAuth


@patch("ganger.mcp.server.GitHubAuth")
@patch("ganger.mcp.server.GitHubAPIClient")
def test_create_server(mock_api_client, mock_auth, tmp_path):
    """Test creating MCP server."""
    # Mock auth
    mock_auth_instance = Mock(spec=GitHubAuth)
    mock_auth_instance.authenticate.return_value = None
    mock_auth.return_value = mock_auth_instance

    cache_path = tmp_path / "test.db"

    server = create_server(cache_path=cache_path, cache_ttl=1800)

    assert server is not None
    assert isinstance(server, GangerMCPServer)
    assert server.cache.db_path == cache_path
    assert server.cache.ttl_seconds == 1800


@patch("ganger.mcp.server.GitHubAuth")
@patch("ganger.mcp.server.GitHubAPIClient")
def test_server_initialization(mock_api_client, mock_auth, tmp_path):
    """Test MCP server initialization."""
    # Mock auth
    mock_auth_instance = Mock(spec=GitHubAuth)
    mock_auth_instance.authenticate.return_value = None
    mock_auth_instance.get_github_client.return_value = Mock()
    mock_auth_instance.get_token.return_value = "test_token"
    mock_auth.return_value = mock_auth_instance

    cache_path = tmp_path / "test.db"

    server = GangerMCPServer(auth=mock_auth_instance, cache_path=cache_path)

    assert server.auth == mock_auth_instance
    assert server.cache is not None
    assert server.server.name == "ganger"


@pytest.mark.asyncio
@patch("ganger.mcp.server.GitHubAuth")
@patch("ganger.mcp.server.GitHubAPIClient")
async def test_server_async_initialization(mock_api_client, mock_auth, tmp_path):
    """Test async initialization of server components."""
    # Mock auth
    mock_auth_instance = Mock(spec=GitHubAuth)
    mock_auth_instance.authenticate.return_value = None
    mock_auth_instance.get_github_client.return_value = Mock()
    mock_auth_instance.get_token.return_value = "test_token"
    mock_auth.return_value = mock_auth_instance

    cache_path = tmp_path / "test.db"

    server = GangerMCPServer(auth=mock_auth_instance, cache_path=cache_path)
    await server.initialize()

    assert server.folder_manager is not None
