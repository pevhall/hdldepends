"""Project-wide constants for hdldepends.

Kept dependency-free so every other module can import from here without risk of
import cycles.
"""

#: Installed package version (single-sourced here; ``pyproject.toml`` reads it
#: back via ``[tool.setuptools.dynamic]``). Not to be confused with
#: ``HDL_DEPENDS_VERSION_NUM`` below, which is the config-schema version.
__version__ = "0.3.0.dev1"

#: Separator used in config keys to attach an optional version/custom tag,
#: e.g. ``vhdl_files@my_tag``.
TOML_KEY_VER_SEP = "@"

#: Current config-schema/tool version. Compared against a config's ``min_ver``.
#: Independent of ``__version__`` (the package/distribution version) above.
HDL_DEPENDS_VERSION_NUM = 1.04

#: Default VHDL library name when none is specified.
LIB_DEFAULT = "work"
