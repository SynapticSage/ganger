"""
Rate limiter for GitHub API.

Modified: 2025-11-07
"""

import time
from datetime import datetime
from typing import Optional


class RateLimiter:
    """
    Track and manage GitHub API rate limits.

    GitHub rate limits:
    - Authenticated REST: 5,000 requests/hour
    - GraphQL: 5,000 points/hour (query cost varies)
    - Search: 30 requests/minute
    """

    # Quota costs for different operations (conservative estimates)
    QUOTA_COSTS = {
        "list_starred": 1,
        "get_repo": 1,
        "get_readme": 1,
        "star_repo": 1,
        "unstar_repo": 1,
        "search": 10,  # Search is more expensive
        "bulk_graphql": 1,  # GraphQL costs vary by query
    }

    def __init__(self, buffer: int = 100):
        """
        Initialize rate limiter.

        Args:
            buffer: Reserve this many requests before showing warnings
        """
        self.buffer = buffer
        self.quota_used = 0
        self.hourly_quota = 5000  # GitHub default for authenticated users
        self.reset_time: Optional[datetime] = None
        self.last_check: Optional[datetime] = None

    def track_request(self, operation: str = "default", count: int = 1) -> None:
        """
        Track a request against the quota.

        Args:
            operation: Type of operation (for cost calculation)
            count: Number of items (for batch operations)
        """
        cost = self.QUOTA_COSTS.get(operation, 1) * count
        self.quota_used += cost

    def update_from_headers(self, headers: dict) -> None:
        """
        Update rate limit info from GitHub API response headers.

        Args:
            headers: Response headers from GitHub API
        """
        # GitHub provides these headers:
        # X-RateLimit-Limit: 5000
        # X-RateLimit-Remaining: 4999
        # X-RateLimit-Reset: 1372700873 (Unix timestamp)

        if "X-RateLimit-Limit" in headers:
            self.hourly_quota = int(headers["X-RateLimit-Limit"])

        if "X-RateLimit-Remaining" in headers:
            remaining = int(headers["X-RateLimit-Remaining"])
            self.quota_used = self.hourly_quota - remaining

        if "X-RateLimit-Reset" in headers:
            reset_timestamp = int(headers["X-RateLimit-Reset"])
            self.reset_time = datetime.fromtimestamp(reset_timestamp)

        self.last_check = datetime.now()

    def get_remaining(self) -> int:
        """
        Get remaining quota.

        Returns:
            Number of requests remaining
        """
        return max(0, self.hourly_quota - self.quota_used)

    def should_warn(self) -> bool:
        """
        Check if we should warn about low quota.

        Returns:
            True if quota is low
        """
        return self.get_remaining() < self.buffer

    def should_wait(self) -> bool:
        """
        Check if we should wait before making more requests.

        Returns:
            True if quota is exhausted
        """
        return self.get_remaining() == 0

    def get_wait_time(self) -> int:
        """
        Get seconds to wait until rate limit resets.

        Returns:
            Seconds to wait, or 0 if no wait needed
        """
        if not self.reset_time:
            return 0

        now = datetime.now()
        if now < self.reset_time:
            delta = self.reset_time - now
            return int(delta.total_seconds())

        return 0

    def wait_if_needed(self) -> None:
        """
        Wait if rate limit is exhausted.

        This will block until the rate limit resets.
        """
        if self.should_wait():
            wait_time = self.get_wait_time()
            if wait_time > 0:
                print(f"⚠ Rate limit exceeded. Waiting {wait_time}s until reset...")
                time.sleep(wait_time)
                # Reset counters after waiting
                self.quota_used = 0
                self.reset_time = None

    def get_status(self) -> dict:
        """
        Get current rate limit status.

        Returns:
            Dictionary with status information
        """
        return {
            "quota": self.hourly_quota,
            "used": self.quota_used,
            "remaining": self.get_remaining(),
            "reset_time": self.reset_time.isoformat() if self.reset_time else None,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "should_warn": self.should_warn(),
            "should_wait": self.should_wait(),
        }
