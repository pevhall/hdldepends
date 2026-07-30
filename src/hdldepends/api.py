"""Public, importable Python API.

Wraps the same building blocks the CLI uses (:func:`~hdldepends.config.build_resolver`
+ :meth:`~hdldepends.resolver.Resolver.compile_order`) behind a single
:func:`analyse` call that returns the compile order as an in-memory,
JSON-safe :class:`AnalysisResult` instead of writing a file.

:func:`select_top` and :func:`apply_forced_init_files` also back ``cli.py``'s
``-o compile-order*`` handling, so the top-selection precedence and the
forced-init-files behaviour are defined exactly once and shared by both
entry points.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .config import add_top_file_by_path, build_resolver
from .constants import LIB_DEFAULT
from .model import Name, SourceFile
from .output import compile_order_to_dicts, format_compile_order, print_compile_order
from .resolver import Resolver
from .util import path_abs_from_dir

#: One config file path, or several (as accepted by ``build_resolver``).
ConfigFiles = Union[str, Path, Sequence[Union[str, Path]]]


def select_top(
    resolver: Resolver,
    top_file: Optional[SourceFile],
    top_entity_name: Optional[Name],
) -> Optional[SourceFile]:
    """Top-selection precedence, shared between the CLI and :func:`analyse`:
    an explicit top file (already looked up by the caller, so it can word its
    own "not in the project" message) > an explicit top entity name > the
    config's top file (``resolver.top_loc``) > the config's top entity
    (``resolver.top_name``). Returns ``None`` if none of these name a top;
    raises ``ValueError`` (reusing :meth:`Resolver.find_top`'s own message,
    and a matching message for an unreachable config top file) if one is
    named but not found.
    """
    if top_file is not None:
        return top_file
    if top_entity_name is not None:
        try:
            return resolver.find_top(top_entity_name)
        except KeyError as e:
            raise ValueError(str(e.args[0]) if e.args else str(e)) from e
    if resolver.top_loc is not None:
        top = resolver.by_loc.get(resolver.top_loc)
        if top is None:
            raise ValueError(f"config top file {resolver.top_loc} is not in the project")
        return top
    if resolver.top_name is not None:
        try:
            return resolver.find_top(resolver.top_name)
        except KeyError as e:
            raise ValueError(str(e.args[0]) if e.args else str(e)) from e
    return None


def apply_forced_init_files(resolver: Resolver, order: List[SourceFile]) -> List[SourceFile]:
    """Prepend any ``resolver.init_files`` not already reached by the
    compile-order walk -- both ``cli.py`` and :func:`analyse` force these
    into the order even if nothing instantiates them."""
    in_order = {sf.loc for sf in order}
    forced = [sf for sf in resolver.init_files if sf.loc not in in_order]
    return forced + order


@dataclass
class AnalysisResult:
    """The result of :func:`analyse`: a flat, JSON-safe compile order."""

    #: Same schema/content as the ``compile-order-json`` CLI output's
    #: ``"files"`` list: EXTERNAL entries (from ``tag_2_ext``) first, then one
    #: entry per compiled file, with ``is_top`` set on the last one.
    compile_order: List[Dict[str, Any]]

    #: The underlying resolved :class:`~hdldepends.model.SourceFile` order
    #: (compiled files only -- no EXTERNAL entries), retained so
    #: :meth:`format_compile_order` / :meth:`print_compile_order` can render the
    #: same tree-indented view the CLI prints. Deliberately excluded from
    #: :meth:`to_dict` (it is not JSON-safe); ``compile_order`` above is the
    #: serializable form.
    source_files: List[SourceFile] = field(default_factory=list, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """The same top-level shape as the ``compile-order-json`` file, e.g.
        for ``json.dump``: ``{"files": self.compile_order}``."""
        return {"files": self.compile_order}

    def format_compile_order(self) -> str:
        """The human-readable, tree-indented compile-order listing (identical to
        what the CLI prints), returned as a string. Compiled files only; the
        leading EXTERNAL entries carried by :attr:`compile_order` are not shown,
        matching the CLI's ``print_compile_order``."""
        return format_compile_order(self.source_files)

    def print_compile_order(self) -> None:
        """Print :meth:`format_compile_order` to stdout -- the same output the
        CLI emits for the resolved compile order."""
        print_compile_order(self.source_files)


def analyse(
    config_files: ConfigFiles,
    *,
    top_entity: Optional[str] = None,
    top_file: Optional[Union[str, Path]] = None,
    top_lib: Optional[str] = None,
    x_tool_version: Optional[str] = None,
    x_device: Optional[str] = None,
    work_dir: Optional[Union[str, Path]] = None,
) -> AnalysisResult:
    """Resolve one or more config files to a dependency compile order.

    Mirrors ``cli.hdldepends()``'s semantics exactly (same top-selection
    precedence, same forced-init-files handling) but returns the result
    in-memory instead of writing an output file.

    :param config_files: a single config file path, or a sequence of them
        (TOML / JSON / YAML, same as the CLI's positional ``config_file``
        arguments).
    :param top_entity: top-level entity/module name (``--top-entity``).
    :param top_file: path to the top-level file (``--top-file``). If it is not
        already part of the project, it is parsed and added (its file type is
        inferred from the extension), so a testbench top level need not be listed
        in the config just to run a basic compile order. A relative path is
        anchored to ``work_dir``, like relative ``config_files``.
    :param top_lib: default VHDL library for ``top_entity`` and for
        unqualified names in the config (``--top-vhdl-lib``); defaults to
        :data:`~hdldepends.constants.LIB_DEFAULT`.
    :param x_tool_version: Xilinx tool version, for ``.bd``/``.xci`` variant
        selection (``--x-tool-version``).
    :param x_device: Xilinx device, for ``.bd``/``.xci`` variant selection
        (``--x-device``).
    :param work_dir: directory relative ``config_files`` and a relative
        ``top_file`` are resolved against; defaults to the current directory.
    :raises hdldepends.errors.ConfigError: the config fails validation, or a
        ``top_file`` not already in the project has an extension no parser
        recognises.
    :raises OSError: a config or referenced source file can't be read.
    :raises ValueError: no top could be determined, or an explicitly named
        top entity does not resolve to a project file.
    """
    top_lib_effective = top_lib or LIB_DEFAULT
    files = [config_files] if isinstance(config_files, (str, Path)) else list(config_files)
    resolved_work_dir = Path(work_dir) if work_dir is not None else Path(".")
    resolver = build_resolver(files, work_dir=resolved_work_dir, top_lib=top_lib_effective)

    if x_tool_version is not None:
        resolver.x_tool_version = x_tool_version
    if x_device is not None:
        resolver.x_device = x_device

    top_file_sf: Optional[SourceFile] = None
    if top_file:
        # A relative top_file is anchored to work_dir, same as the config
        # files themselves (the CLI's --top-file is CWD-relative instead --
        # there the CWD IS the caller's anchor). The extra .resolve() is a
        # no-op for the relative case (path_abs_from_dir already resolves)
        # but normalizes an absolute input to match by_loc's resolved keys.
        loc = path_abs_from_dir(resolved_work_dir, Path(top_file)).resolve()
        top_file_sf = resolver.by_loc.get(loc)
        if top_file_sf is None:
            # Not listed in the config: parse and add it (inferring the file type
            # from its extension), so a testbench top level need not be added to
            # the config just to run a basic simulation compile order.
            top_file_sf = add_top_file_by_path(resolver, loc, lib=top_lib_effective)

    top_entity_name = Name(top_lib_effective, top_entity) if top_entity else None
    top = select_top(resolver, top_file_sf, top_entity_name)
    if top is None:
        raise ValueError(
            "no top could be determined: pass top_file or top_entity, or set a "
            "top_*_file / top_entity key in the config"
        )

    order = apply_forced_init_files(resolver, resolver.compile_order(top))
    return AnalysisResult(
        compile_order=compile_order_to_dicts(order, resolver.tag_2_ext),
        source_files=order,
    )
