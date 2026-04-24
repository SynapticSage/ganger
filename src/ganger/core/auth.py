"""
GitHub authentication with dual support for OAuth and Personal Access Tokens.

Modified: 2025-11-07
"""

import json
import logging
import os
import time
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

import httpx
from github import Github, GithubException

from ganger.core.exceptions import AuthenticationError


logger = logging.getLogger(__name__)


class GitHubAuth:
    """
    GitHub authentication manager supporting both OAuth device flow and PAT.

    OAuth device flow is recommended for better UX (no manual token creation),
    but PAT is simpler for testing and power users.
    """

    # GitHub OAuth app credentials (these would be registered with GitHub)
    # For now, using environment variables or requiring users to provide their own
    OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")

    # Scopes required for Ganger
    SCOPES = [
        "user",  # Read user profile
        "repo",  # Full repo access (needed for private starred repos)
    ]

    def __init__(
        self,
        token_file: Optional[Path] = None,
        auth_method: str = "auto",  # "auto", "oauth", "pat"
        silent: bool = False,  # Suppress console output (for TUI mode)
        oauth_callback: Optional[Callable[[str, str, int], None]] = None,
        token: Optional[str] = None,
    ):
        """
        Initialize GitHub authentication.

        Args:
            token_file: Path to store/load token (default: ~/.config/ganger/token.json)
            auth_method: Authentication method - "auto" tries env var first, then oauth
            silent: If True, suppress console output (use logging instead)
            oauth_callback: Optional callback(user_code, verification_url, expires_in)
                           called when OAuth device flow starts, for TUI integration
        """
        if token_file is None:
            config_dir = Path.home() / ".config" / "ganger"
            config_dir.mkdir(parents=True, exist_ok=True)
            token_file = config_dir / "token.json"

        self.token_file = token_file
        self.auth_method = auth_method
        self.silent = silent
        self.oauth_callback = oauth_callback
        self._token: Optional[str] = token
        self._github_client: Optional[Github] = None

    def _log(self, message: str) -> None:
        """Log message, also print if not in silent mode."""
        logger.info(message)
        if not self.silent:
            print(message)

    def authenticate(self) -> None:
        """
        Perform authentication based on configured method.

        Priority:
        1. GITHUB_TOKEN environment variable (PAT)
        2. Existing token file
        3. OAuth device flow (if client ID configured)
        4. Prompt user for PAT (only in non-silent mode)

        Raises:
            AuthenticationError: If authentication fails
        """
        # Try explicitly configured token first
        if self._token:
            if self._verify_token():
                self._log("✓ Authenticated via configured token")
                return
            raise AuthenticationError("Configured GitHub token is invalid")

        # Try environment variable first (PAT)
        env_token = os.getenv("GITHUB_TOKEN")
        if env_token:
            self._token = env_token
            if self._verify_token():
                self._log("✓ Authenticated via GITHUB_TOKEN environment variable")
                return
            else:
                raise AuthenticationError(
                    "GITHUB_TOKEN environment variable is set but invalid"
                )

        # Try loading existing token file
        if self.token_file.exists():
            if self._load_token():
                if self._verify_token():
                    self._log(f"✓ Authenticated via token file: {self.token_file}")
                    return
                else:
                    logger.warning("Stored token is invalid, re-authenticating...")
                    if not self.silent:
                        print("⚠ Stored token is invalid, re-authenticating...")
                    self.token_file.unlink()  # Remove invalid token

        # Try OAuth device flow if client ID is configured
        if self.OAUTH_CLIENT_ID and self.auth_method in ["auto", "oauth"]:
            self._log("Starting OAuth device flow authentication...")
            self._oauth_device_flow()
            return

        # Fallback: prompt for PAT (only works in non-silent mode)
        if self.auth_method in ["auto", "pat"] and not self.silent:
            self._prompt_for_pat()
            return

        # In silent mode, if we get here, we have no valid auth
        raise AuthenticationError(
            "No authentication method available. Set GITHUB_TOKEN environment variable "
            "or run 'ganger auth' to authenticate."
        )

    def _verify_token(self) -> bool:
        """
        Verify that the current token is valid.

        Returns:
            True if token is valid, False otherwise
        """
        if not self._token:
            return False

        try:
            # Try to get authenticated user
            g = Github(self._token)
            user = g.get_user()
            _ = user.login  # Force API call
            self._github_client = g
            return True
        except GithubException:
            return False
        except Exception:
            return False

    def _load_token(self) -> bool:
        """
        Load token from file.

        Returns:
            True if token loaded successfully, False otherwise
        """
        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)
                self._token = data.get("access_token")
                return self._token is not None
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return False

    def _save_token(self, token: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Save token to file.

        Args:
            token: GitHub access token
            metadata: Optional metadata (e.g., created_at, expires_at)
        """
        data = {
            "access_token": token,
            "created_at": datetime.now().isoformat(),
        }
        if metadata:
            data.update(metadata)

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_file, "w") as f:
            json.dump(data, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        self.token_file.chmod(0o600)

    def _oauth_device_flow(self) -> None:
        """
        Perform OAuth device flow authentication.

        This is the recommended flow for CLI apps:
        1. Request device code
        2. Show user code and verification URL
        3. Poll for authorization
        4. Save access token

        Raises:
            AuthenticationError: If OAuth flow fails
        """
        # Step 1: Request device code
        try:
            response = httpx.post(
                "https://github.com/login/device/code",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.OAUTH_CLIENT_ID,
                    "scope": " ".join(self.SCOPES),
                },
                timeout=30,
            )
            response.raise_for_status()
            device_data = response.json()
        except Exception as e:
            raise AuthenticationError(f"Failed to request device code: {e}")

        # Step 2: Show user code and URL
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        expires_in = device_data["expires_in"]
        interval = device_data.get("interval", 5)

        # Call the OAuth callback if provided (for TUI integration)
        if self.oauth_callback:
            try:
                self.oauth_callback(user_code, verification_uri, expires_in)
            except Exception as e:
                logger.warning(f"OAuth callback failed: {e}")

        if not self.silent:
            print("\n" + "=" * 60)
            print("GitHub Authentication Required")
            print("=" * 60)
            print(f"\n1. Visit: {verification_uri}")
            print(f"2. Enter code: {user_code}")
            print(f"\nWaiting for authorization (expires in {expires_in}s)...\n")
        else:
            logger.info(f"OAuth device flow: Visit {verification_uri} and enter code {user_code}")

        # Try to open browser automatically
        try:
            webbrowser.open(verification_uri)
            self._log("✓ Opened browser automatically")
        except Exception:
            pass

        # Step 3: Poll for authorization
        device_code = device_data["device_code"]
        start_time = time.time()

        while time.time() - start_time < expires_in:
            time.sleep(interval)

            try:
                token_response = httpx.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self.OAUTH_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    timeout=30,
                )
                token_response.raise_for_status()
                token_data = token_response.json()

                # Check for errors
                if "error" in token_data:
                    error = token_data["error"]
                    if error == "authorization_pending":
                        # Still waiting
                        if not self.silent:
                            print(".", end="", flush=True)
                        continue
                    elif error == "slow_down":
                        # Increase polling interval
                        interval += 5
                        continue
                    elif error == "expired_token":
                        raise AuthenticationError("Device code expired")
                    elif error == "access_denied":
                        raise AuthenticationError("Authorization denied by user")
                    else:
                        raise AuthenticationError(f"OAuth error: {error}")

                # Success!
                if "access_token" in token_data:
                    self._token = token_data["access_token"]
                    self._save_token(self._token, token_data)

                    if self._verify_token():
                        self._log("\n✓ Authentication successful!")
                        user = self._github_client.get_user()
                        self._log(f"✓ Logged in as: {user.login}")
                        return
                    else:
                        raise AuthenticationError("Token verification failed")

            except httpx.HTTPError as e:
                raise AuthenticationError(f"Failed to poll for token: {e}")

        raise AuthenticationError("Authentication timed out")

    def _prompt_for_pat(self) -> None:
        """
        Prompt user to enter a Personal Access Token.

        Note: This only works in non-silent mode (CLI context).

        Raises:
            AuthenticationError: If PAT is invalid
        """
        if self.silent:
            raise AuthenticationError(
                "Cannot prompt for PAT in silent mode. "
                "Set GITHUB_TOKEN environment variable or run 'ganger auth'."
            )

        print("\n" + "=" * 60)
        print("GitHub Personal Access Token Required")
        print("=" * 60)
        print("\n1. Visit: https://github.com/settings/tokens/new")
        print("2. Create a token with 'repo' and 'user' scopes")
        print("3. Enter the token below\n")

        import getpass

        token = getpass.getpass("GitHub Token: ").strip()

        if not token:
            raise AuthenticationError("No token provided")

        self._token = token
        if self._verify_token():
            self._save_token(token)
            self._log("\n✓ Authentication successful!")
            user = self._github_client.get_user()
            self._log(f"✓ Logged in as: {user.login}")
        else:
            raise AuthenticationError("Invalid token")

    def get_github_client(self) -> Github:
        """
        Get authenticated GitHub client (PyGithub).

        Returns:
            Authenticated Github client

        Raises:
            AuthenticationError: If not authenticated
        """
        if not self._github_client:
            if not self._token:
                raise AuthenticationError("Not authenticated. Run authenticate() first.")

            self._github_client = Github(self._token)

        return self._github_client

    def get_token(self) -> str:
        """
        Get the current access token.

        Returns:
            GitHub access token

        Raises:
            AuthenticationError: If not authenticated
        """
        if not self._token:
            raise AuthenticationError("Not authenticated. Run authenticate() first.")
        return self._token

    def revoke_credentials(self) -> None:
        """
        Revoke stored credentials and delete token file.
        """
        if self.token_file.exists():
            self.token_file.unlink()
            self._log(f"✓ Deleted token file: {self.token_file}")

        self._token = None
        self._github_client = None
        self._log("✓ Credentials revoked")

    def get_user_info(self) -> Dict[str, Any]:
        """
        Get authenticated user information.

        Returns:
            Dictionary with user info (login, name, email, etc.)

        Raises:
            AuthenticationError: If not authenticated
        """
        client = self.get_github_client()
        user = client.get_user()

        return {
            "login": user.login,
            "name": user.name,
            "email": user.email,
            "bio": user.bio,
            "public_repos": user.public_repos,
            "followers": user.followers,
            "following": user.following,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
