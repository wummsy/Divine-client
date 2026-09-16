"""Kept as an import point: the loading screen moved to :mod:`arenclient.ui.loading`.

``Splash`` stays as the name the app used before the layout rework, so anything that
still imports it gets the new one.
"""
from .loading import Loading as Splash      # noqa: F401  (re-export on purpose)

__all__ = ["Splash"]
