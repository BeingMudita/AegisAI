"""Framework adapters — the only framework-specific code in AegisAI.

Each adapter translates one agent framework's wire format to and from the
framework-neutral :mod:`app.platform.protocol`. Pick one by name with
:func:`get_adapter`.
"""

from __future__ import annotations

from app.platform.adapters.base import (
    available_adapters,
    get_adapter,
    register_adapter,
)

__all__ = ["available_adapters", "get_adapter", "register_adapter"]
