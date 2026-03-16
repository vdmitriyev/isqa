"""Provides module specific exceptions."""


class IsQAException(Exception):
    """Generic exception for IsQA."""


class IsQAWrongCLIParams(Exception):
    """exception for wrong params passed to CLI"""


class IsQAGitlabConnection(Exception):
    """Generic exception for IsQA - connection to Gitlab."""


class IsQAGitlabNoRepository(Exception):
    """Generic exception for IsQA - no repository found."""
