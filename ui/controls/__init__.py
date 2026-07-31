"""The four control tabs, one module each. Tab order matches the menu bar."""

from .adjust import AdjustTab
from .globals import GlobalTab
from .local import LocalTab
from .structures import StructuresTab

__all__ = ["AdjustTab", "GlobalTab", "LocalTab", "StructuresTab"]

# Also the order they appear in, which `base._demo` checks over.
TABS = (AdjustTab, GlobalTab, LocalTab, StructuresTab)
