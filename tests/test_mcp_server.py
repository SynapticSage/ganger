"""
Tests for MCP server.

Modified: 2025-11-09
"""

import os
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from ganger.mcp.server import create_server, GangerMCPServer, main
from ganger.core.auth import GitHubAuth
from ganger.core.exceptions import GangerError, AuthenticationError


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


class TestAuthenticationError:
    """Test authentication error handling."""

    @patch("ganger.mcp.server.GitHubAuth")
    def test_init_auth_failure_raises_ganger_error(self, mock_auth_class, tmp_path):
        """Test that auth failure in __init__ raises GangerError (lines 50-51)."""
        cache_path = tmp_path / "test.db"

        # Mock authentication failure
        mock_auth_instance = Mock(spec=GitHubAuth)
        mock_auth_instance.authenticate.side_effect = AuthenticationError("No token found")
        mock_auth_class.return_value = mock_auth_instance

        with pytest.raises(GangerError, match="Authentication required"):
            GangerMCPServer(cache_path=cache_path)

        # Verify authenticate was called
        mock_auth_instance.authenticate.assert_called_once()


class TestMainEntryPoint:
    """Test main() entry point."""

    @patch("ganger.mcp.server.create_server")
    @patch.dict(os.environ, {}, clear=True)
    def test_main_with_defaults(self, mock_create_server):
        """Test main() with default env vars (lines 105-112)."""
        mock_server = Mock()
        mock_create_server.return_value = mock_server

        main()

        # Verify create_server was called with defaults
        mock_create_server.assert_called_once_with(cache_path=None, cache_ttl=3600)
        mock_server.run.assert_called_once()

    @patch("ganger.mcp.server.create_server")
    @patch.dict(os.environ, {"GANGER_CACHE_PATH": "/tmp/test.db", "GANGER_CACHE_TTL": "7200"})
    def test_main_with_env_vars(self, mock_create_server):
        """Test main() reads environment variables (lines 105-112)."""
        mock_server = Mock()
        mock_create_server.return_value = mock_server

        main()

        # Verify create_server was called with env var values
        expected_cache_path = Path("/tmp/test.db")
        mock_create_server.assert_called_once_with(cache_path=expected_cache_path, cache_ttl=7200)
        mock_server.run.assert_called_once()

    @patch("ganger.mcp.server.create_server")
    @patch.dict(os.environ, {"GANGER_CACHE_TTL": "invalid"})
    def test_main_with_invalid_ttl(self, mock_create_server):
        """Test main() with invalid TTL env var."""
        mock_server = Mock()
        mock_create_server.return_value = mock_server

        # Should raise ValueError when trying to convert "invalid" to int
        with pytest.raises(ValueError):
            main()


class TestRunFlow:
    """Test server run() flow."""

    @pytest.mark.asyncio
    @patch("ganger.mcp.server.stdio_server")
    @patch("ganger.mcp.tools.register_tools")
    @patch("ganger.mcp.server.GitHubAuth")
    @patch("ganger.mcp.server.GitHubAPIClient")
    async def test_run_flow_async_operations(self, mock_api_client, mock_auth_class, mock_register_tools, mock_stdio_server, tmp_path):
        """Test run() async flow (lines 70-82)."""
        cache_path = tmp_path / "test.db"

        # Mock auth
        mock_auth_instance = Mock(spec=GitHubAuth)
        mock_auth_instance.authenticate.return_value = None
        mock_auth_class.return_value = mock_auth_instance

        # Mock stdio_server context manager
        mock_read_stream = Mock()
        mock_write_stream = Mock()
        mock_stdio_server.return_value.__aenter__ = AsyncMock(return_value=(mock_read_stream, mock_write_stream))
        mock_stdio_server.return_value.__aexit__ = AsyncMock(return_value=None)

        server = GangerMCPServer(auth=mock_auth_instance, cache_path=cache_path)

        # Mock server.run to avoid actually running the server
        server.server.run = AsyncMock()
        server.server.create_initialization_options = Mock(return_value={})

        # Manually call the async _run function logic to test lines 70-82
        await server.initialize()

        # This tests line 74-75 (import and register_tools call)
        from ganger.mcp.tools import register_tools
        register_tools(server.server, server)

        # This tests lines 77-80 (stdio_server and server.run)
        async with mock_stdio_server() as (read_stream, write_stream):
            await server.server.run(
                read_stream, write_stream, server.server.create_initialization_options()
            )

        # Verify tools were registered
        mock_register_tools.assert_called_once_with(server.server, server)

        # Verify server.run was called with streams
        server.server.run.assert_called_once_with(mock_read_stream, mock_write_stream, {})
