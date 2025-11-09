"""
Tests for rate limiter.

Modified: 2025-11-07
"""

import pytest
import time
from datetime import datetime, timedelta
from ganger.utils.rate_limiter import RateLimiter


class TestRateLimiter:
    """Test RateLimiter class."""

    def test_initialization(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(buffer=50)

        assert limiter.buffer == 50
        assert limiter.quota_used == 0
        assert limiter.hourly_quota == 5000

    def test_track_request(self):
        """Test tracking requests."""
        limiter = RateLimiter()

        limiter.track_request("list_starred")
        assert limiter.quota_used == 1

        limiter.track_request("search", count=5)
        assert limiter.quota_used == 51  # 1 + (10 * 5)

    def test_get_remaining(self):
        """Test getting remaining quota."""
        limiter = RateLimiter()
        limiter.quota_used = 100

        remaining = limiter.get_remaining()
        assert remaining == 4900

    def test_should_warn(self):
        """Test warning threshold."""
        limiter = RateLimiter(buffer=100)

        # Not yet at warning threshold
        limiter.quota_used = 4800
        assert not limiter.should_warn()

        # At warning threshold
        limiter.quota_used = 4901
        assert limiter.should_warn()

    def test_should_wait(self):
        """Test wait threshold."""
        limiter = RateLimiter()

        # Not at limit
        limiter.quota_used = 4999
        assert not limiter.should_wait()

        # At limit
        limiter.quota_used = 5000
        assert limiter.should_wait()

    def test_update_from_headers(self):
        """Test updating from GitHub API headers."""
        limiter = RateLimiter()

        headers = {
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4500",
            "X-RateLimit-Reset": str(int(time.time()) + 3600),
        }

        limiter.update_from_headers(headers)

        assert limiter.hourly_quota == 5000
        assert limiter.quota_used == 500
        assert limiter.reset_time is not None

    def test_get_wait_time(self):
        """Test calculating wait time."""
        limiter = RateLimiter()

        # No reset time set
        assert limiter.get_wait_time() == 0

        # Reset time in future
        limiter.reset_time = datetime.now() + timedelta(seconds=60)
        wait_time = limiter.get_wait_time()
        assert 55 < wait_time <= 60  # Allow some variance

        # Reset time in past
        limiter.reset_time = datetime.now() - timedelta(seconds=10)
        assert limiter.get_wait_time() == 0

    def test_get_status(self):
        """Test getting status dictionary."""
        limiter = RateLimiter(buffer=100)
        limiter.quota_used = 200

        status = limiter.get_status()

        assert status["quota"] == 5000
        assert status["used"] == 200
        assert status["remaining"] == 4800
        assert status["should_warn"] is False
        assert status["should_wait"] is False

    def test_quota_costs(self):
        """Test that quota costs are defined."""
        limiter = RateLimiter()

        # Check that costs are defined for common operations
        assert "list_starred" in limiter.QUOTA_COSTS
        assert "star_repo" in limiter.QUOTA_COSTS
        assert "search" in limiter.QUOTA_COSTS

        assert limiter.QUOTA_COSTS["list_starred"] == 1
        assert limiter.QUOTA_COSTS["search"] == 10
