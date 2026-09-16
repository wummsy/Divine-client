"""Kept as an import point: the tab was called Versions for one phase.

Nothing lives here. The page is :class:`arenclient.ui.pages.instances_page.InstancesPage`,
and ``app.show_page("versions")`` maps onto it, so code written while the tab had the other
name keeps working without pretending there are two pages.
"""
from .instances_page import (InstancesPage, InstanceCard, ConfirmDialog,     # noqa: F401
                             CreateVersionDialog, CreateInstanceDialog,
                             VersionsPage, VersionCard)

__all__ = ["InstancesPage", "InstanceCard", "ConfirmDialog", "CreateVersionDialog",
           "CreateInstanceDialog", "VersionsPage", "VersionCard"]
