"""Backward-compatible service facade.

v1.12 moves implementation into ``app.domain_services`` while preserving all
existing import paths for Telegram handlers, web routes and third-party code.
"""
from .domain_services import *  # noqa: F401,F403
