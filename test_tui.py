#!/usr/bin/env python3
"""Test script for Ganger TUI.

Quick launcher to test the TUI without full installation.

Modified: 2025-11-08
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for development testing
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ganger.tui.app import run_app


async def main():
    """Run the TUI app."""
    config_dir = Path.home() / ".config" / "ganger-dev"
    config_dir.mkdir(parents=True, exist_ok=True)

    await run_app(config_dir=config_dir)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
