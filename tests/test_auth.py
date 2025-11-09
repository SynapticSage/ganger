"""
Tests for GitHub authentication.

Modified: 2025-11-07
"""

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
from ganger.core.auth import GitHubAuth
from ganger.core.exceptions import AuthenticationError


class TestGitHubAuth:
    """Test GitHubAuth class."""

    def test_init(self, tmp_path):
        """Test initialization."""
        token_file = tmp_path / "token.json"
        auth = GitHubAuth(token_file=token_file, auth_method="pat")

        assert auth.token_file == token_file
        assert auth.auth_method == "pat"

    def test_save_and_load_token(self, tmp_path):
        """Test saving and loading tokens."""
        token_file = tmp_path / "token.json"
        auth = GitHubAuth(token_file=token_file)

        # Save token
        test_token = "ghp_test1234567890"
        auth._save_token(test_token, {"test": "metadata"})

        assert token_file.exists()

        # Load token
        auth2 = GitHubAuth(token_file=token_file)
        assert auth2._load_token()
        assert auth2._token == test_token

        # Verify file contents
        with open(token_file) as f:
            data = json.load(f)
            assert data["access_token"] == test_token
            assert data["test"] == "metadata"
            assert "created_at" in data

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_env_token"})
    @patch("ganger.core.auth.Github")
    def test_authenticate_from_env(self, mock_github, tmp_path):
        """Test authentication from environment variable."""
        # Mock successful verification
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_github.return_value.get_user.return_value = mock_user

        auth = GitHubAuth(token_file=tmp_path / "token.json")
        auth.authenticate()

        assert auth._token == "ghp_env_token"
        assert mock_github.called

    @patch("ganger.core.auth.Github")
    def test_verify_token_success(self, mock_github, tmp_path):
        """Test successful token verification."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_github.return_value.get_user.return_value = mock_user

        auth = GitHubAuth(token_file=tmp_path / "token.json")
        auth._token = "ghp_valid_token"

        assert auth._verify_token()
        assert auth._github_client is not None

    @patch("ganger.core.auth.Github")
    def test_verify_token_failure(self, mock_github, tmp_path):
        """Test failed token verification."""
        from github import GithubException

        # Mock failed verification
        mock_github.return_value.get_user.side_effect = GithubException(
            401, {"message": "Bad credentials"}
        )

        auth = GitHubAuth(token_file=tmp_path / "token.json")
        auth._token = "ghp_invalid_token"

        assert not auth._verify_token()

    @patch("ganger.core.auth.Github")
    def test_get_github_client(self, mock_github, tmp_path):
        """Test getting GitHub client."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_github.return_value.get_user.return_value = mock_user

        auth = GitHubAuth(token_file=tmp_path / "token.json")
        auth._token = "ghp_test_token"
        auth._github_client = mock_github.return_value

        client = auth.get_github_client()
        assert client is not None

    def test_get_github_client_not_authenticated(self, tmp_path):
        """Test getting client when not authenticated."""
        auth = GitHubAuth(token_file=tmp_path / "token.json")

        with pytest.raises(AuthenticationError, match="Not authenticated"):
            auth.get_github_client()

    @patch("ganger.core.auth.Github")
    def test_get_user_info(self, mock_github, tmp_path):
        """Test getting user info."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.bio = "Test bio"
        mock_user.public_repos = 10
        mock_user.followers = 5
        mock_user.following = 3
        mock_user.created_at = None

        mock_client = Mock()
        mock_client.get_user.return_value = mock_user
        mock_github.return_value = mock_client

        auth = GitHubAuth(token_file=tmp_path / "token.json")
        auth._token = "ghp_test_token"
        auth._github_client = mock_client

        info = auth.get_user_info()

        assert info["login"] == "testuser"
        assert info["name"] == "Test User"
        assert info["email"] == "test@example.com"
        assert info["public_repos"] == 10

    def test_revoke_credentials(self, tmp_path):
        """Test revoking credentials."""
        token_file = tmp_path / "token.json"
        auth = GitHubAuth(token_file=token_file)

        # Create a token file
        auth._save_token("ghp_test_token")
        assert token_file.exists()

        # Revoke
        auth.revoke_credentials()
        assert not token_file.exists()
        assert auth._token is None
        assert auth._github_client is None

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_invalid"})
    @patch("ganger.core.auth.Github")
    def test_authenticate_invalid_env_token(self, mock_github, tmp_path):
        """Test authentication with invalid environment token."""
        # Mock Github to raise exception on invalid token
        mock_github.side_effect = Exception("Bad credentials")

        token_file = tmp_path / "token.json"
        auth = GitHubAuth(token_file=token_file)

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError, match="GITHUB_TOKEN.*invalid"):
            auth.authenticate()

    @patch("ganger.core.auth.Github")
    def test_authenticate_invalid_token_file(self, mock_github, tmp_path):
        """Test authentication with invalid token in file."""
        token_file = tmp_path / "token.json"

        # Create token file with invalid token
        with open(token_file, "w") as f:
            json.dump({"access_token": "ghp_invalid"}, f)

        # Mock Github to fail on invalid token
        mock_github.side_effect = Exception("Bad credentials")

        auth = GitHubAuth(token_file=token_file, auth_method="pat")

        # Should try to load token, verify it fails, and fall through to PAT prompt
        # Since OAuth is not configured and we're in pat mode, it should call _prompt_for_pat
        with patch.object(auth, "_prompt_for_pat") as mock_prompt:
            auth.authenticate()
            # File should be deleted after verification fails
            assert not token_file.exists()
            # Should have called PAT prompt
            mock_prompt.assert_called_once()

    def test_load_token_malformed_json(self, tmp_path):
        """Test loading token from file with malformed JSON."""
        token_file = tmp_path / "token.json"

        # Create file with invalid JSON
        with open(token_file, "w") as f:
            f.write("{invalid json")

        auth = GitHubAuth(token_file=token_file)

        # Should return False without crashing
        assert not auth._load_token()
        assert auth._token is None

    def test_load_token_missing_access_token_key(self, tmp_path):
        """Test loading token from file missing access_token key."""
        token_file = tmp_path / "token.json"

        # Create file without access_token key
        with open(token_file, "w") as f:
            json.dump({"other_key": "value"}, f)

        auth = GitHubAuth(token_file=token_file)

        # Should return False
        assert not auth._load_token()
        assert auth._token is None

    def test_authenticate_no_method_available(self, tmp_path):
        """Test authentication when no method is available."""
        token_file = tmp_path / "token.json"

        # No env token, no token file, no OAuth client ID, wrong auth_method
        with patch.dict(os.environ, {}, clear=True):
            auth = GitHubAuth(token_file=token_file, auth_method="invalid")

            with pytest.raises(AuthenticationError, match="No authentication method available"):
                auth.authenticate()

    def test_save_token_creates_directory(self, tmp_path):
        """Test that saving token creates parent directory."""
        token_file = tmp_path / "subdir" / "nested" / "token.json"

        auth = GitHubAuth(token_file=token_file)
        auth._save_token("ghp_test")

        # Directory should be created
        assert token_file.parent.exists()
        assert token_file.exists()

    def test_save_token_sets_permissions(self, tmp_path):
        """Test that saved token file has restrictive permissions."""
        token_file = tmp_path / "token.json"

        auth = GitHubAuth(token_file=token_file)
        auth._save_token("ghp_test")

        # Check file permissions (owner read/write only)
        import stat
        file_mode = token_file.stat().st_mode
        # Should be 0o600 (rw-------)
        assert stat.S_IMODE(file_mode) == 0o600

    @patch.dict(os.environ, {}, clear=True)
    @patch("ganger.core.auth.GitHubAuth.OAUTH_CLIENT_ID", "test_client_id")
    def test_authenticate_oauth_path_attempted(self, tmp_path):
        """Test that OAuth path is attempted when client ID is configured."""
        token_file = tmp_path / "token.json"

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")

        # Mock the OAuth device flow to avoid actual HTTP requests
        with patch.object(auth, "_oauth_device_flow") as mock_oauth:
            auth.authenticate()
            # Should have attempted OAuth
            mock_oauth.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    def test_authenticate_pat_fallback(self, tmp_path):
        """Test fallback to PAT prompt when OAuth not available."""
        token_file = tmp_path / "token.json"

        auth = GitHubAuth(token_file=token_file, auth_method="auto")

        # No OAuth client ID, should fall back to PAT
        with patch.object(auth, "_prompt_for_pat") as mock_prompt:
            auth.authenticate()
            mock_prompt.assert_called_once()

    def test_token_file_default_location(self):
        """Test that default token file location is correct."""
        auth = GitHubAuth()

        expected_path = Path.home() / ".config" / "ganger" / "token.json"
        assert auth.token_file == expected_path


class TestOAuthDeviceFlow:
    """Test OAuth device flow authentication."""

    @patch("httpx.post")
    @patch("webbrowser.open")
    @patch("time.sleep")
    @patch("ganger.core.auth.Github")
    def test_oauth_device_flow_success(self, mock_github_class, mock_sleep, mock_browser, mock_post, tmp_path):
        """Test successful OAuth device flow (lines 184-267)."""
        token_file = tmp_path / "token.json"

        # Mock device code request
        device_response = Mock()
        device_response.json.return_value = {
            "device_code": "ABC123",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5
        }

        # Mock token polling (first pending, then success)
        token_pending = Mock()
        token_pending.json.return_value = {"error": "authorization_pending"}

        token_success = Mock()
        token_success.json.return_value = {
            "access_token": "gho_test_token_123",
            "token_type": "bearer",
            "scope": "repo user"
        }

        mock_post.side_effect = [device_response, token_pending, token_success]

        # Mock GitHub client for verification
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_github_instance = Mock()
        mock_github_instance.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github_instance

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")
        auth._oauth_device_flow()

        assert auth._token is not None
        assert auth.get_token() == "gho_test_token_123"
        mock_browser.assert_called_once()

    @patch("httpx.post")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_oauth_device_flow_expired(self, mock_sleep, mock_browser, mock_post, tmp_path):
        """Test OAuth flow with expired token (lines 251-252)."""
        token_file = tmp_path / "token.json"

        # Mock device code request
        device_response = Mock()
        device_response.json.return_value = {
            "device_code": "ABC123",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5
        }

        # Mock token expired response
        token_expired = Mock()
        token_expired.json.return_value = {"error": "expired_token"}

        mock_post.side_effect = [device_response, token_expired]

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")

        with pytest.raises(AuthenticationError, match="expired"):
            auth._oauth_device_flow()

    @patch("httpx.post")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_oauth_device_flow_denied(self, mock_sleep, mock_browser, mock_post, tmp_path):
        """Test OAuth flow with user denial (lines 253-254)."""
        token_file = tmp_path / "token.json"

        # Mock device code request
        device_response = Mock()
        device_response.json.return_value = {
            "device_code": "ABC123",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5
        }

        # Mock access denied response
        token_denied = Mock()
        token_denied.json.return_value = {"error": "access_denied"}

        mock_post.side_effect = [device_response, token_denied]

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")

        with pytest.raises(AuthenticationError, match="denied"):
            auth._oauth_device_flow()

    @patch("httpx.post")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_oauth_device_flow_slow_down(self, mock_sleep, mock_browser, mock_post, tmp_path):
        """Test OAuth flow with slow_down response (lines 247-250)."""
        token_file = tmp_path / "token.json"

        # Mock device code request
        device_response = Mock()
        device_response.json.return_value = {
            "device_code": "ABC123",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5
        }

        # Mock slow_down then success
        token_slow_down = Mock()
        token_slow_down.json.return_value = {"error": "slow_down"}

        token_success = Mock()
        token_success.json.return_value = {
            "access_token": "gho_test_token",
            "token_type": "bearer"
        }

        mock_post.side_effect = [device_response, token_slow_down, token_success]

        # Mock GitHub client
        with patch("ganger.core.auth.Github") as mock_github_class:
            mock_user = Mock()
            mock_user.login = "testuser"
            mock_github_instance = Mock()
            mock_github_instance.get_user.return_value = mock_user
            mock_github_class.return_value = mock_github_instance

            auth = GitHubAuth(token_file=token_file, auth_method="oauth")
            auth._oauth_device_flow()

            # Verify slow_down was handled (interval increased)
            assert auth._token is not None

    @patch("httpx.post")
    def test_oauth_device_flow_request_error(self, mock_post, tmp_path):
        """Test OAuth flow with device code request error (lines 196-197)."""
        token_file = tmp_path / "token.json"

        # Mock device code request failure
        mock_post.side_effect = Exception("Network error")

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")

        with pytest.raises(AuthenticationError, match="Failed to request device code"):
            auth._oauth_device_flow()

    @patch("httpx.post")
    @patch("webbrowser.open")
    @patch("time.sleep")
    @patch("time.time")
    def test_oauth_device_flow_timeout(self, mock_time, mock_sleep, mock_browser, mock_post, tmp_path):
        """Test OAuth flow timeout (line 274)."""
        token_file = tmp_path / "token.json"

        # Mock device code request
        device_response = Mock()
        device_response.json.return_value = {
            "device_code": "ABC123",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 10,  # Short timeout
            "interval": 5
        }

        # Mock token polling (always pending)
        token_pending = Mock()
        token_pending.json.return_value = {"error": "authorization_pending"}

        mock_post.side_effect = [device_response] + [token_pending] * 10

        # Mock time to simulate timeout
        mock_time.side_effect = [0, 0, 15]  # Start, loop check, timeout

        auth = GitHubAuth(token_file=token_file, auth_method="oauth")

        with pytest.raises(AuthenticationError, match="timed out"):
            auth._oauth_device_flow()


class TestPATPrompt:
    """Test Personal Access Token prompt authentication."""

    @patch("getpass.getpass")
    @patch("ganger.core.auth.Github")
    def test_prompt_for_pat_success(self, mock_github_class, mock_getpass, tmp_path):
        """Test PAT prompt with valid token (lines 283-302)."""
        token_file = tmp_path / "token.json"
        mock_getpass.return_value = "ghp_valid_token_123"

        # Mock GitHub client for verification
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_github_instance = Mock()
        mock_github_instance.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github_instance

        auth = GitHubAuth(token_file=token_file)
        auth._prompt_for_pat()

        assert auth._token is not None
        assert auth.get_token() == "ghp_valid_token_123"

    @patch("getpass.getpass")
    def test_prompt_for_pat_empty(self, mock_getpass, tmp_path):
        """Test PAT prompt with empty input (lines 294-295)."""
        token_file = tmp_path / "token.json"
        mock_getpass.return_value = ""

        auth = GitHubAuth(token_file=token_file)

        with pytest.raises(AuthenticationError, match="No token provided"):
            auth._prompt_for_pat()

    @patch("getpass.getpass")
    @patch("ganger.core.auth.Github")
    def test_prompt_for_pat_invalid(self, mock_github_class, mock_getpass, tmp_path):
        """Test PAT prompt with invalid token (lines 303-304)."""
        token_file = tmp_path / "token.json"
        mock_getpass.return_value = "invalid_token"

        # Mock GitHub client to fail verification
        mock_github_class.side_effect = Exception("Bad credentials")

        auth = GitHubAuth(token_file=token_file)

        with pytest.raises(AuthenticationError, match="Invalid token"):
            auth._prompt_for_pat()
