"""
MCP server entrypoints for robo-lukas modules.

This package exposes read-only tools over the Model Context Protocol (MCP),
bridging existing CLI modules (git-local, Jira, Outlook, Microsoft To Do).
"""

from .server import main

__all__ = ["main"]
