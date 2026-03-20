"""
Read-only Outlook on the web automation.

This package intentionally exposes no APIs for sending mail, composing, or deleting.
"""

from robo_lukas.outlook.safety import assert_readonly_navigation_url

__all__ = ["assert_readonly_navigation_url"]
