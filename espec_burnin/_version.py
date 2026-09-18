"""Single source of truth for the version.

CI rewrites this file from the git tag at build time (see
.github/workflows/release.yml), so a build can never disagree with its tag.
"""

__version__ = "0.9.0"
