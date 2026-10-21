"""timon — Toolkit of Integrated MicrobiOme analysis with support for loNg reads."""

from importlib.metadata import PackageNotFoundError, version as _installed_version

# The version is the release tag and nothing else: hatch-vcs reads it off the
# tag when the wheel is built, and this reads it back out of the installed
# distribution. So there is no number written down anywhere to fall out of step
# with the tag, and what the page shows is what was actually installed.
try:
    __version__ = _installed_version("timon-gui")
except PackageNotFoundError:
    # A source tree that was never installed — not how timon is run (the
    # `timon` command comes from the install), but importable all the same.
    __version__ = "0+unknown"

# The year __version__ was released, shown in the page footer. Bumped by hand
# with the release, not read from the clock: an old install should keep saying
# the year it is from rather than quietly claiming to be current.
__release_year__ = "2026"
