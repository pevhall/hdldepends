"""The dependency resolver.

A flat index of every known :class:`~hdldepends.model.SourceFile`, plus one
recursive walk that turns a top file into a compile order. There is no tree of
lookups and no per-file-type resolution policy: resolution is just "look the
required name up in the index", and a file is processed (its own requires walked)
exactly once.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .constants import LIB_DEFAULT
from .logging_util import log
from .model import FileType, Name, SourceFile


def _version_key(v: str) -> Tuple[Tuple[int, int, str], ...]:
    """Turn a version string into a tuple that sorts numeric components
    numerically, e.g. "2019.2" < "2019.10" -- a plain string compare gets this
    backwards ("2019.10" < "2019.2" lexicographically, since "1" < "2").

    Splits on runs of non-alphanumeric separators; each part becomes a
    ``(0, int, "")`` tuple when purely numeric or ``(1, 0, str)`` otherwise, so a
    numeric part always sorts before an alpha part at the same position and
    mixed version schemes still compare without raising.
    """
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", v) if p]
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts)


def _closest_x_version(candidates: List[SourceFile], target: str) -> SourceFile:
    """Pick the candidate with the tool-version closest to ``target``: the highest
    version at or below the target, else the lowest above it. Lower versions are
    preferred because upgrading an IP is more reliable than downgrading."""
    target_key = _version_key(target)
    below = [c for c in candidates if _version_key(c.x_tool_version) <= target_key]
    if below:
        return max(below, key=lambda c: _version_key(c.x_tool_version))
    return min(candidates, key=lambda c: _version_key(c.x_tool_version))


def _select_x(candidates: List[SourceFile], tool_version: str, device: str) -> SourceFile:
    """Choose the best Xilinx file for the required tool version + device, in
    priority order: exact (version AND device) > same version (any device) >
    same device (closest version) > closest version. Always returns a candidate;
    it warns rather than dropping the dependency when nothing matches exactly."""
    exact = [c for c in candidates if c.x_tool_version == tool_version and c.x_device == device]
    if exact:
        if len(exact) > 1:
            locs = ", ".join(str(c.loc) for c in exact)
            log.error(f"multiple Xilinx files match version {tool_version} and device {device}: {locs}")
        return exact[0]

    ver_match = [c for c in candidates if c.x_tool_version == tool_version]
    if ver_match:
        chosen = ver_match[0]
        log.warning(f"Xilinx {chosen.loc}: version {tool_version} matches but device {chosen.x_device} != {device}")
        return chosen

    dev_match = [c for c in candidates if c.x_device == device]
    chosen = _closest_x_version(dev_match or candidates, tool_version)
    log.warning(
        f"no Xilinx file matches version {tool_version}; using {chosen.loc} "
        f"(version {chosen.x_tool_version}, device {chosen.x_device})"
    )
    return chosen


def _inherit_lib(xci: SourceFile, parent_lib: str, parent_loc: Path) -> None:
    """Let an X_XCI file adopt the library of the (first) VHDL file that
    instantiates it; warn if a later, differently-libraried parent also wants it."""
    if xci.lib_inherited_from is None:
        log.info(f"XCI {xci.loc} inheriting library '{parent_lib}' from {parent_loc}")
        xci.lib = parent_lib
        xci.lib_inherited_from = parent_loc
    elif xci.lib != parent_lib:
        log.warning(
            f"XCI {xci.loc} already inherited library '{xci.lib}' from {xci.lib_inherited_from}, "
            f"ignoring '{parent_lib}' from {parent_loc}"
        )


class Resolver:
    def __init__(self):
        self.by_loc: Dict[Path, SourceFile] = {}
        self.by_name: Dict[Name, List[SourceFile]] = {}
        self.ignore_libs: Set[str] = set()
        self.ignore_packages: Set[Name] = set()
        self.ignore_entities: Set[Name] = set()
        self.ignore_components: Set[str] = set()
        self.skip_locs: Set[Path] = set()
        self.init_files: List[SourceFile] = []
        #: Verilog `include search directories gathered from the config, kept so a
        #: Verilog top file added after the fact (see config.add_top_file_by_path)
        #: can resolve its `include directives the same way project files do.
        self.verilog_include_dirs: List[Path] = []
        self.tag_2_ext: Dict[str, List[Path]] = {}
        self.x_tool_version: str = ""
        self.x_device: str = ""
        #: top file / top entity set via a config's top_vhdl_file / top_verilog_file
        #: / top_x_bd_file / top_entity keys (see config.py). The CLI prefers
        #: --top-file / --top-entity but falls back to these when neither is given.
        self.top_loc: Optional[Path] = None
        self.top_name: Optional[Name] = None
        #: Names already warned about in `resolve` for having multiple, non-Xilinx-
        #: selectable candidates -- so the warning fires once per Name, not once
        #: per instantiation/use site.
        self._ambiguous_warned: Set[Name] = set()

    # --- building the index ------------------------------------------------
    def add(self, sf: SourceFile) -> None:
        """Index ``sf`` by location and by every name it provides.

        Re-adding an already-indexed ``loc`` (e.g. the same file listed by two
        sub-configs -- the diamond case -- or an ``init_files`` stub later
        superseded by the real parsed file) is REPLACE-WITH-CLEANUP: the
        previous object's ``provides`` entries are removed from ``by_name``
        (dropping any name list left empty) before the new object is indexed,
        so ``by_loc`` and ``by_name`` never disagree about which object is
        current for a given location -- last write always wins, and no stale
        object (one ``by_loc`` no longer points at) can linger in ``by_name``.
        """
        existing = self.by_loc.get(sf.loc)
        if existing is not None:
            log.debug(f"{sf.loc}: replacing previously indexed file (re-added)")
            for name in existing.provides:
                lst = self.by_name.get(name)
                if lst is None:
                    continue
                lst[:] = [s for s in lst if s is not existing]
                if not lst:
                    del self.by_name[name]
        self.by_loc[sf.loc] = sf
        for name in sf.provides:
            self.by_name.setdefault(name, []).append(sf)

    @property
    def files(self) -> List[SourceFile]:
        return list(self.by_loc.values())

    # --- resolution --------------------------------------------------------
    def resolve(self, name: Name) -> Optional[SourceFile]:
        """The file providing ``name``, or None if ignored or not found."""
        if name.lib in self.ignore_libs or name in self.ignore_packages or name in self.ignore_entities:
            return None

        candidates = self.by_name.get(name, [])
        if not candidates and name.lib != LIB_DEFAULT:
            # VHDL component / plain instantiation: fall back to the work library.
            candidates = self.by_name.get(Name(LIB_DEFAULT, name.name), [])
        if not candidates:
            # Xilinx IPs are declared in 'work' but may be instantiated from any
            # library; match such files by bare name.
            candidates = [f for f in self.by_loc.values() if f.is_x and any(p.name == name.name for p in f.provides)]

        if len(candidates) > 1 and self.x_tool_version and self.x_device:
            x_cands = [c for c in candidates if c.is_x]
            if x_cands:
                return _select_x(x_cands, self.x_tool_version, self.x_device)

        if len(candidates) > 1 and name not in self._ambiguous_warned:
            # Xilinx version/device selection didn't apply (not configured, or no
            # Xilinx candidates); the first candidate wins silently otherwise, so
            # warn once per Name to flag the ambiguity without spamming per use.
            self._ambiguous_warned.add(name)
            others = ", ".join(str(c.loc) for c in candidates[1:])
            log.warning(f"{name} matches multiple files; using {candidates[0].loc} (also matched: {others})")
        return candidates[0] if candidates else None

    # --- compile order -----------------------------------------------------
    def compile_order(self, top: SourceFile) -> List[SourceFile]:
        """Depth-first post-order: each file appears after everything it needs.

        Driven as an explicit-stack trampoline over ``_walk`` rather than by
        direct/``yield from`` recursion, so a dependency chain thousands of
        files deep does not raise Python's ``RecursionError`` -- each pending
        call lives on the heap-allocated ``stack`` list below, not on the
        interpreter's C call stack (which is what both plain recursion and
        chained ``yield from`` would still consume, one frame per depth level).
        ``_walk`` is otherwise a direct translation of the natural recursive
        walk: every recursive call site (``walk(inc, ...)`` / ``walk(dep,
        ...)``) becomes a ``yield`` of the (file, level) to descend into, and
        the loop below drives exactly one generator -- the innermost pending
        call -- at a time, resuming its caller only once it is exhausted
        (i.e. once that entire sub-tree has been fully emitted), which
        reproduces the same emission order and the same side-effect timing
        (warnings, XCI library inheritance) as direct recursion would.
        """
        order: List[SourceFile] = []
        visited: Set[Path] = set()
        emitted: Set[Path] = set()  # locations already placed in `order`

        def _walk(sf: SourceFile, level: int):
            visited.add(sf.loc)
            if sf.loc in self.skip_locs:
                return
            for iloc in sf.include_locs:
                inc = self.by_loc.get(iloc)
                if inc is not None and inc.loc not in visited:
                    # Marked visited here (not lazily when the pushed frame is
                    # later driven) so a sibling edge below that also targets
                    # `inc` correctly sees it as already claimed -- matching
                    # recursion's eager `visited.add` on entry to the call.
                    visited.add(inc.loc)
                    yield inc, level + 1
            for name in sf.requires:
                dep = self.resolve(name)
                if dep is None:
                    if name.lib not in self.ignore_libs and name.name not in self.ignore_components:
                        log.warning(f"{sf.loc}: could not resolve dependency {name}")
                    continue
                # An XCI adopts the library of the VHDL file instantiating it, so a
                # netlist later generated from it has a valid (non-default) library.
                if dep.ftype == FileType.X_XCI and sf.lib != LIB_DEFAULT:
                    _inherit_lib(dep, sf.lib, sf.loc)
                if dep.loc not in visited:
                    visited.add(dep.loc)
                    yield dep, level + 1
            for dloc in sf.direct_deps:
                if dloc in emitted:
                    # Already emitted: a coefficient file shared by two IPs, or a
                    # direct dep that is itself a project file already placed in
                    # the order by its own requires-walk.
                    continue
                known_sf = self.by_loc.get(dloc)
                if known_sf is not None:
                    if dloc not in visited:
                        # A direct dep that is ALSO an indexed project file: give
                        # it the same full post-order walk as an include/require
                        # edge (so ITS OWN requires are emitted before it),
                        # instead of blindly appending it dependency-blind (which
                        # could also emit it a second time once reached normally).
                        visited.add(dloc)
                        yield known_sf, level + 1
                    # else: an ancestor currently being walked higher up the
                    # stack, or already claimed by an earlier edge in this same
                    # walk that hasn't finished yet -- skip; it is (or will be)
                    # emitted by that walk.
                    continue
                unknown = SourceFile(dloc, FileType.DIRECT)
                unknown.level = level + 1
                order.append(unknown)
                emitted.add(dloc)
            sf.level = level
            order.append(sf)
            emitted.add(sf.loc)

        stack = [_walk(top, 0)]
        while stack:
            try:
                child_sf, child_level = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            stack.append(_walk(child_sf, child_level))
        return order

    def find_top(self, name: Name) -> SourceFile:
        sf = self.resolve(name)
        if sf is None:
            raise KeyError(f"top entity {name} not found in any source file")
        return sf
