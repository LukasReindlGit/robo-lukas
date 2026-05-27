"""
Jira module — read-only access to Jira Cloud (or Server/DC) via browser session + REST API.

Strategy: open a Chrome browser window, wait for the user to complete SSO login,
extract the session cookies, then hit the Jira REST API v3 with those cookies.

No API token is required. Works on any Jira instance where the user can log in via browser.
"""
