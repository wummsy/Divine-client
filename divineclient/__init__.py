"""Divine Client v4 - a Minecraft launcher by the Divine Dev Team."""

__version__ = "4.0.0"
__app_name__ = "Divine Client"
__team__ = "Divine Dev Team"

# The number the site compares against to decide whether to push an update, matching
# ``clientversion`` in the server's .env. Separate from __version__ (which is the exe's
# file version) on purpose: this is the release channel. It changes when the site should
# start handing out a new build, not when the same code is rebuilt.
CLIENT_VERSION = "4.0"
