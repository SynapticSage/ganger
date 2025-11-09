"""
CLI entry point for Ganger.

Modified: 2025-11-07
"""

import sys
import click
from pathlib import Path
from ganger import __version__
from ganger.core.auth import GitHubAuth
from ganger.core.exceptions import AuthenticationError


@click.group()
@click.version_option(version=__version__)
def cli():
    """Ganger - GitHub Ranger for managing starred repositories."""
    pass


@cli.command()
@click.option(
    "--method",
    type=click.Choice(["auto", "oauth", "pat"], case_sensitive=False),
    default="auto",
    help="Authentication method to use",
)
@click.option(
    "--token-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to token file (default: ~/.config/ganger/token.json)",
)
def auth(method: str, token_file: Path):
    """Set up GitHub authentication (OAuth or PAT)."""
    try:
        github_auth = GitHubAuth(token_file=token_file, auth_method=method)
        github_auth.authenticate()

        # Show user info
        info = github_auth.get_user_info()
        click.echo("\n" + "=" * 60)
        click.echo("Authentication Details")
        click.echo("=" * 60)
        click.echo(f"Username: {info['login']}")
        if info["name"]:
            click.echo(f"Name: {info['name']}")
        if info["email"]:
            click.echo(f"Email: {info['email']}")
        click.echo(f"Public Repos: {info['public_repos']}")
        click.echo(f"Followers: {info['followers']}")
        click.echo("=" * 60)

    except AuthenticationError as e:
        click.echo(f"✗ Authentication failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Unexpected error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--revoke", is_flag=True, help="Revoke stored credentials")
def logout(revoke: bool):
    """Logout and remove stored credentials."""
    try:
        github_auth = GitHubAuth()
        github_auth.revoke_credentials()
        click.echo("✓ Successfully logged out")
    except Exception as e:
        click.echo(f"✗ Error during logout: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--cache-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to cache database",
)
@click.option(
    "--cache-ttl",
    type=int,
    default=3600,
    help="Cache TTL in seconds (default: 3600)",
)
def mcp(cache_path: Path, cache_ttl: int):
    """Start the MCP server."""
    try:
        from ganger.mcp import main as mcp_main
        import os

        # Set environment variables if provided
        if cache_path:
            os.environ["GANGER_CACHE_PATH"] = str(cache_path)
        os.environ["GANGER_CACHE_TTL"] = str(cache_ttl)

        # Run MCP server
        mcp_main()
    except Exception as e:
        click.echo(f"✗ MCP server error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Configuration directory (default: ~/.config/ganger)",
)
def tui(config_dir: Path):
    """Launch the TUI interface."""
    try:
        import asyncio
        from ganger.tui.app import run_app

        # Run the TUI
        asyncio.run(run_app(config_dir=config_dir))
    except KeyboardInterrupt:
        click.echo("\nGoodbye!")
    except Exception as e:
        click.echo(f"✗ TUI error: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
def status():
    """Show current configuration and cache status."""
    click.echo(f"Ganger v{__version__}")
    click.echo("\nAuthentication:")

    try:
        github_auth = GitHubAuth()
        github_auth.authenticate()
        info = github_auth.get_user_info()

        # Show token file location
        token_file = github_auth.token_file
        if token_file.exists():
            click.echo(f"✓ Authenticated via token file: {token_file}")

        click.echo(f"  ✓ Logged in as: {info['login']}")

        if info.get("name"):
            click.echo(f"  Name: {info['name']}")
        click.echo(f"  Public Repos: {info['public_repos']}")
        click.echo(f"  Followers: {info['followers']}")

    except AuthenticationError:
        click.echo("  ✗ Not authenticated (run 'ganger auth')")
    except Exception as e:
        click.echo(f"  ✗ Error: {e}")

    click.echo("\nCache:")
    click.echo("  Location: ~/.cache/ganger/ganger.db")
    click.echo("  Status: Ready")

    click.echo("\nConfiguration:")
    click.echo("  Config Dir: ~/.config/ganger/")
    click.echo("  Status: Using defaults")


if __name__ == "__main__":
    cli()
