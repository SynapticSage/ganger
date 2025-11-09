"""
Custom exceptions for Ganger.

Modified: 2025-11-07
"""


class GangerError(Exception):
    """Base exception for all Ganger errors."""

    pass


class AuthenticationError(GangerError):
    """Raised when GitHub authentication fails."""

    pass


class RateLimitExceededError(GangerError):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(self, message: str = "GitHub API rate limit exceeded", reset_time: int = 0):
        super().__init__(message)
        self.reset_time = reset_time


class RepoNotFoundError(GangerError):
    """Raised when a repository is not found or inaccessible."""

    pass


class FolderNotFoundError(GangerError):
    """Raised when a virtual folder is not found."""

    pass


class CacheError(GangerError):
    """Raised when cache operations fail."""

    pass


class ConfigurationError(GangerError):
    """Raised when configuration is invalid or missing."""

    pass
