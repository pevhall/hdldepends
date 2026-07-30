"""Configuration loading and Resolver construction.

Loads a config file (TOML / JSON / YAML), validates it, discovers the source
files it lists (handling globs, file-of-files, per-library dicts, ``@tags`` and
recursive ``sub`` configs), parses each one, and builds a single flat
:class:`~hdldepends.resolver.Resolver`. There is no tree of lookups: every
sub-config's files land in the same index.
"""

import json
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .config_models import validate_config
from .constants import HDL_DEPENDS_VERSION_NUM, LIB_DEFAULT
from .discovery import process_glob_patterns
from .errors import ConfigError
from .logging_util import log
from .model import FileType, Name, SourceFile, str_to_name, string_to_filetype
from .parsers.verilog import parse_verilog_file
from .parsers.vhdl import parse_vhdl_file
from .resolver import Resolver
from .util import key_split_opt_ver, make_list, make_set, path_abs_from_dir, resolve_abs_path
from .vendors.xilinx.bd import parse_x_bd_file
from .vendors.xilinx.xci import parse_x_xci_file

# Optional-dependency imports: kept below the unconditional imports (rather than
# interleaved) so they don't split the sorted import block and trip E402.
tomllib = None
try:
    import tomllib  # type: ignore
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        pass

yaml = None
try:
    import yaml  # type: ignore
except ModuleNotFoundError:
    pass

KNOWN_SUFFIXES = (".toml", ".json", ".yaml", ".yml")

#: The three keys that each name exactly one top-level file (mutually exclusive,
#: at most one entry total, within a single config -- see the top-file handling
#: in ``gather`` below).
TOP_FILE_KEYS = ("top_vhdl_file", "top_verilog_file", "top_x_bd_file")
#: All config keys that set the project's top level (file or entity). A
#: sub-config (pulled in via ``sub``) may not use any of these -- see the "Top
#: level file" section of the README.
TOP_KEYS = TOP_FILE_KEYS + ("top_entity",)


def load_config(loc: Path) -> Dict:
    try:
        with open(loc, "rb") as f:
            if loc.suffix == ".json":
                try:
                    return json.load(f)
                except json.decoder.JSONDecodeError as e:
                    raise ConfigError(f"{loc} is not valid JSON: {e}") from e
            if loc.suffix == ".toml":
                if tomllib is None:
                    raise RuntimeError(
                        "tomli is required to load .toml configs on Python < 3.11 -- "
                        "install with `pip install tomli`"
                    )
                try:
                    return tomllib.load(f)
                except tomllib.TOMLDecodeError as e:
                    raise ConfigError(f"{loc} is not valid TOML: {e}") from e
            if loc.suffix in (".yaml", ".yml"):
                if yaml is None:
                    raise RuntimeError(
                        "PyYAML is required to load .yaml configs -- install with `pip install PyYAML`"
                    )
                try:
                    return yaml.safe_load(f)
                except yaml.YAMLError as e:
                    raise ConfigError(f"{loc} is not valid YAML: {e}") from e
    except Exception as e:
        log.error(f"failed to load config {loc}")
        raise e
    raise RuntimeError(f"Unexpected config file format: {loc.suffix}")


def _find_config(loc: Path, work_dir: Optional[Path]) -> Path:
    """Resolve a config path, searching parent directories if it is a bare name."""
    if loc.suffix == "":
        # YAML is the primary/recommended format (TOML and JSON still load).
        loc = loc.with_suffix(".yaml")
    if loc.suffix not in KNOWN_SUFFIXES:
        raise ConfigError(f"{loc} expected suffix {' / '.join(KNOWN_SUFFIXES)} but got {loc.suffix}")
    if loc.is_file():
        return loc
    if loc.is_absolute() or work_dir is None:
        raise FileNotFoundError(f"could not find config file {loc}")
    base = resolve_abs_path(work_dir)
    while not (base / loc).is_file():
        if base.parent == base:
            raise FileNotFoundError(f"could not find config file {loc}")
        base = base.parent
    return base / loc


def _for_each_file_spec(config: dict, key: str, callback: Callable, with_ver: bool, top_lib: str) -> None:
    """Call ``callback(lib, value[, ver])`` for every entry of config key ``key``.

    A value may be a per-library dict, a list, or a scalar; the key may carry an
    ``@tag`` version suffix when ``with_ver`` is set.
    """
    for config_key in config:
        base, ver = key_split_opt_ver(config_key) if with_ver else (config_key, None)
        if base != key:
            continue
        value = config[config_key]
        items = value.items() if isinstance(value, dict) else [(top_lib, value)]
        for lib, vals in items:
            for v in make_list(vals):
                callback(lib, v, ver) if with_ver else callback(lib, v)


def _files_for(tag: str, config: dict, work_dir: Path, top_lib: str) -> List[Tuple[str, Path, str]]:
    """Resolve ``<tag>_files`` / ``<tag>_files_glob`` / ``<tag>_files_file`` to (lib, loc, ver).

    Every entry is treated as a glob pattern (a plain path is a glob that matches
    only itself), so ``<tag>_files`` and ``<tag>_files_glob`` behave identically;
    a ``!``-prefixed pattern removes earlier matches. Patterns are applied
    serially per (library, @tag) group.
    """
    out: List[Tuple[str, Path, str]] = []

    # _files and _files_glob: glob patterns relative to the config dir.
    patterns: Dict[Tuple[str, str], List[str]] = {}

    def add_pattern(lib, pat, ver):
        patterns.setdefault((lib, ver), []).append(pat)

    _for_each_file_spec(config, tag + "_files", add_pattern, True, top_lib)
    _for_each_file_spec(config, tag + "_files_glob", add_pattern, True, top_lib)
    for (lib, ver), pats in patterns.items():
        for loc in process_glob_patterns(pats, work_dir):
            out.append((lib, path_abs_from_dir(work_dir, loc), ver))

    # _files_file: each entry is a file listing patterns (relative to that file).
    def add_listed(lib, f_str, ver):
        list_loc = path_abs_from_dir(work_dir, Path(f_str))
        pats = [line.strip() for line in list_loc.read_text().splitlines() if line.strip()]
        for loc in process_glob_patterns(pats, list_loc.parent):
            out.append((lib, path_abs_from_dir(list_loc.parent, loc), ver))

    _for_each_file_spec(config, tag + "_files_file", add_listed, True, top_lib)
    return out


def _no_lib(file_list: List[Tuple[str, Path, str]]) -> List[Tuple[Path, str]]:
    for lib, loc, _ver in file_list:
        if lib != LIB_DEFAULT:
            log.error(f"only VHDL files support libraries; got library {lib} on {loc}")
    return [(loc, ver) for _lib, loc, ver in file_list]


def _set_of_names(config: dict, key: str, top_lib: str) -> Set[Name]:
    names: Set[Name] = set()
    _for_each_file_spec(config, key, lambda lib, name: names.add(Name(lib, name)), False, top_lib)
    return names


def _top_entity_name(raw: str, top_lib: str) -> Name:
    """Resolve a ``top_entity`` value to a Name: a bare ``name`` uses the
    config's top library; ``lib.name`` names the library explicitly."""
    return str_to_name(raw) if "." in raw else Name(top_lib, raw)


def _init_files(config: dict, work_dir: Path, cfg_loc: Path) -> List[SourceFile]:
    """Forced-add files: entries are [loc, type, ver_tag?, lib?, name?].

    The file is NOT parsed (it may be encrypted / binary), but it is registered
    as *providing* a name -- ``name`` if given, otherwise the file stem -- so an
    instantiation of that name resolves to it instead of failing. They are also
    force-included in the compile order even if nothing instantiates them.
    """
    out: List[SourceFile] = []
    raw = config.get("init_files", [])
    if not isinstance(raw, list):
        # e.g. a bare string: iterating it yields individual characters, so
        # `entry[1]` below would raise a bare, confusing IndexError instead of
        # naming the actual problem.
        raise ConfigError(f"{cfg_loc}: init_files must be a list of [loc, type, ...] entries, got {raw!r}")
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            raise ConfigError(
                f"{cfg_loc}: init_files entry must be a [loc, type, ver_tag?, lib?, name?] list, got {entry!r}"
            )
        loc = path_abs_from_dir(work_dir, Path(entry[0]))
        ftype = string_to_filetype(entry[1])
        ver = entry[2] if len(entry) > 2 and entry[2] else None
        lib = entry[3] if len(entry) > 3 and entry[3] else LIB_DEFAULT
        name = entry[4] if len(entry) > 4 and entry[4] else loc.stem
        sf = SourceFile(loc, ftype, lib=lib, ver=ver)
        sf.provides.append(Name(lib, name))
        out.append(sf)
    return out


def build_resolver(toml_locs, work_dir: Optional[Path] = None, top_lib: Optional[str] = None) -> Resolver:
    """Build a flat Resolver from one or more config files and their sub-configs."""
    top_lib = top_lib or LIB_DEFAULT
    resolver = Resolver()
    resolver.ignore_libs |= {"ieee", "std"}

    vhdl: List[Tuple[str, Path, str]] = []
    verilog: List[Tuple[Path, str]] = []
    other: List[Tuple[Path, str]] = []
    x_bd: List[Tuple[Path, str]] = []
    x_xci: List[Tuple[Path, str]] = []
    inc_dirs: List[Path] = []
    inc_files: List[Tuple[Path, str]] = []
    done: Set[Path] = set()
    #: init_files stubs seen so far, keyed by loc. A plain dict gives last-wins
    #: replacement (matching resolver.add's semantics) while keeping
    #: the position of the FIRST occurrence: re-assigning an existing key
    #: updates its value in place rather than moving it, so a later sub-config
    #: re-listing the same init file (diamond case, possibly with a different
    #: lib/name) replaces its entry rather than duplicating or reordering it.
    init_by_loc: Dict[Path, SourceFile] = {}
    #: Every config loc that declares at least one TOP_KEYS key, and every
    #: loc reached via a `sub` edge from some other config (mapped to that
    #: parent). Checked for overlap after ALL gathers below -- order-
    #: independently, per the README's "Top level file" contract: a config
    #: with a top key may not ALSO be sub'd in by another config.
    top_key_configs: Dict[Path, Set[str]] = {}
    sub_referenced_by: Dict[Path, Path] = {}

    def gather(loc: Path, wd: Optional[Path], ancestors: frozenset, parent: Optional[Path]) -> None:
        loc = _find_config(loc, wd)
        if loc in ancestors:
            raise ConfigError(f"circular sub config detected: {loc}")
        if parent is not None:
            # Recorded unconditionally, even when `loc` is already in `done`
            # (reached previously via another parent -- the DAG/diamond case)
            # -- so the top-key-vs-sub-referenced check below doesn't depend
            # on whether this edge or another one (or a direct root gather())
            # for the same config ran first.
            sub_referenced_by.setdefault(loc, parent)
        if loc in done:
            return  # already pulled in via another parent (a DAG/diamond)
        done.add(loc)
        ancestors = ancestors | {loc}
        cfg = load_config(loc)
        validate_config(cfg, loc)
        cwd = loc.parent

        if "min_ver" in cfg and HDL_DEPENDS_VERSION_NUM < cfg["min_ver"]:
            raise ConfigError(f"hdldepends {HDL_DEPENDS_VERSION_NUM} < {cfg['min_ver']} required by {loc}")

        top_keys_present = {key_split_opt_ver(k)[0] for k in cfg} & set(TOP_KEYS)
        if top_keys_present:
            top_key_configs[loc] = top_keys_present

        for cmd in make_list(cfg.get("pre_cmds", [])):
            try:
                subprocess.check_output(cmd, shell=True, cwd=cwd)
            except subprocess.CalledProcessError as e:
                # check_output captures stdout only (stderr passes through to
                # the terminal as usual), so include a tail of that captured
                # output in the message when there is any -- it is often the
                # actual reason the command failed.
                msg = f"{loc}: pre_cmds command {cmd!r} failed with exit status {e.returncode}"
                out = e.output.decode(errors="replace").strip() if e.output else ""
                if out:
                    msg += f"; output (tail): {out[-500:]}"
                raise ConfigError(msg) from e

        resolver.ignore_libs |= make_set(cfg.get("ignore_libs", set()))
        resolver.ignore_packages |= _set_of_names(cfg, "ignore_packages", top_lib)
        resolver.ignore_entities |= _set_of_names(cfg, "ignore_entities", top_lib)
        if "ignore_components" in cfg:
            resolver.ignore_components |= make_set(cfg["ignore_components"])
        for sf in _init_files(cfg, cwd, loc):
            resolver.add(sf)  # so an instantiation of its name resolves to it
            # The same init file may be (redundantly) listed by two sub-configs
            # (the diamond case), possibly with a different lib/name each time;
            # last-wins, matching resolver.add's by_loc semantics, while a
            # plain dict keeps the position of the FIRST occurrence.
            init_by_loc[sf.loc] = sf
        for x_key in ("x_tool_version", "x_device"):
            if x_key in cfg and not getattr(resolver, x_key):
                setattr(resolver, x_key, str(make_list(cfg[x_key])[0]))

        # vhdl_package_skip_order: VHDL files (often Xilinx primitive packages like
        # unisim) that must be PARSED so their packages/entities are discoverable,
        # but kept OUT of the compile order. It is a direct key (lib-dict / list /
        # scalar) whose paths may use {ENV_VAR} (e.g. {XILINX_VIVADO}/...).
        skip: List[Tuple[str, Path, str]] = []
        _for_each_file_spec(
            cfg, "vhdl_package_skip_order",
            lambda lib, loc_str, ver: skip.append((lib, path_abs_from_dir(cwd, Path(loc_str)), ver)),
            True, top_lib,
        )
        for _lib, sloc, _ver in skip:
            resolver.skip_locs.add(sloc)

        vhdl.extend(_files_for("vhdl", cfg, cwd, top_lib) + skip)
        verilog.extend(_no_lib(_files_for("verilog", cfg, cwd, top_lib)))
        other.extend(_no_lib(_files_for("other", cfg, cwd, top_lib)))
        x_bd.extend(_no_lib(_files_for("x_bd", cfg, cwd, top_lib)))
        x_xci.extend(_no_lib(_files_for("x_xci", cfg, cwd, top_lib)))
        inc_dirs.extend(path_abs_from_dir(cwd, Path(d)) for d in make_list(cfg.get("verilog_include_dir", [])))
        inc_files.extend(_no_lib(_files_for("verilog_include", cfg, cwd, top_lib)))
        for eloc, ever in _no_lib(_files_for("ext", cfg, cwd, top_lib)):
            resolver.tag_2_ext.setdefault(ever, []).append(eloc)

        # top_vhdl_file / top_verilog_file / top_x_bd_file: each names exactly one
        # file, which is added to the project (like any other file key -- a
        # per-library dict or @tag is accepted) and marked as the top. At most one
        # entry total across the three keys is allowed per config.
        top_files: List[Tuple[str, Path, str, FileType]] = []

        def add_top_file(ftype):
            def callback(lib, loc_str, ver):
                top_files.append((lib, path_abs_from_dir(cwd, Path(loc_str)), ver, ftype))
            return callback

        _for_each_file_spec(cfg, "top_vhdl_file", add_top_file(FileType.VHDL), True, top_lib)
        _for_each_file_spec(cfg, "top_verilog_file", add_top_file(FileType.VERILOG), True, top_lib)
        _for_each_file_spec(cfg, "top_x_bd_file", add_top_file(FileType.X_BD), True, top_lib)
        if len(top_files) > 1:
            locs = ", ".join(f"{t_lib}:{t_loc}" for t_lib, t_loc, _t_ver, _t_ftype in top_files)
            raise ConfigError(
                f"{loc}: only one of top_vhdl_file / top_verilog_file / top_x_bd_file "
                f"(and only one entry within it) is supported per config; got {locs}"
            )
        if top_files:
            t_lib, t_loc, t_ver, t_ftype = top_files[0]
            if resolver.top_loc is not None and resolver.top_loc != t_loc:
                log.warning(f"{loc}: top file {t_loc} overrides previously set top file {resolver.top_loc}")
            resolver.top_loc = t_loc
            if t_ftype == FileType.VHDL:
                vhdl.append((t_lib, t_loc, t_ver))
            elif t_ftype == FileType.VERILOG:
                if t_lib != LIB_DEFAULT:
                    log.error(f"verilog does not support libraries; got library {t_lib} on {t_loc}")
                verilog.append((t_loc, t_ver))
            else:  # FileType.X_BD
                if t_lib != LIB_DEFAULT:
                    log.error(f"x_bd does not support libraries; got library {t_lib} on {t_loc}")
                x_bd.append((t_loc, t_ver))

        if "top_entity" in cfg:
            raw_name = cfg["top_entity"]
            if not isinstance(raw_name, str):
                raise ConfigError(f"{loc}: top_entity must be a string, got {raw_name!r}")
            try:
                name = _top_entity_name(raw_name, top_lib)
            except ValueError as e:
                raise ConfigError(f"{loc}: invalid top_entity {raw_name!r}: {e}") from e
            if resolver.top_name is not None and resolver.top_name != name:
                log.warning(f"{loc}: top_entity {name} overrides previously set top_entity {resolver.top_name}")
            resolver.top_name = name
            if top_files:
                # Both a top_*_file key and top_entity set in the SAME config:
                # cli.py always prefers resolver.top_loc over resolver.top_name,
                # so top_entity here is silently inert downstream -- warn
                # instead of leaving it a silent no-op.
                log.warning(
                    f"{loc}: top_entity {name} is overridden by top file {resolver.top_loc} "
                    f"(top file takes precedence)"
                )

        for sub in make_list(cfg.get("sub", [])):
            gather(Path(sub), cwd, ancestors, loc)

    for toml_loc in make_list(toml_locs):
        gather(Path(toml_loc), work_dir, frozenset(), None)

    resolver.init_files = list(init_by_loc.values())

    conflicts = sorted(set(top_key_configs) & set(sub_referenced_by), key=str)
    if conflicts:
        parts = [
            f"{c} (found {', '.join(sorted(top_key_configs[c]))}; referenced by {sub_referenced_by[c]})"
            for c in conflicts
        ]
        raise ConfigError(
            "a configuration containing a top file setting cannot be referenced by another "
            "configuration through the 'sub' option: " + "; ".join(parts)
        )

    # includes first (so Verilog parsing can resolve them), then everything else.
    for loc, ver in inc_files:
        resolver.add(SourceFile(loc, FileType.VERILOG_INCLUDE, ver=ver))
    inc_locs = [loc for loc, _ver in inc_files]
    resolver.verilog_include_dirs = list(inc_dirs)
    for lib, loc, ver in vhdl:
        resolver.add(parse_vhdl_file(loc, lib=lib, ver=ver))
    for loc, ver in verilog:
        resolver.add(parse_verilog_file(loc, ver, inc_dirs, inc_locs))
    for loc, ver in x_bd:
        resolver.add(parse_x_bd_file(loc, ver))
    for loc, ver in x_xci:
        resolver.add(parse_x_xci_file(loc, ver))
    for loc, ver in other:
        sf = SourceFile(loc, FileType.OTHER, ver=ver)
        sf.provides.append(Name(LIB_DEFAULT, Path(loc).stem))
        resolver.add(sf)
    return resolver


#: File extension -> FileType, used to pick a parser when a top file is named by
#: path but isn't already part of the project (see add_top_file_by_path).
TOP_FILE_EXT_TYPES: Dict[str, FileType] = {
    ".vhd": FileType.VHDL,
    ".vhdl": FileType.VHDL,
    ".v": FileType.VERILOG,
    ".sv": FileType.VERILOG,
    ".bd": FileType.X_BD,
    ".xci": FileType.X_XCI,
}


def add_top_file_by_path(
    resolver: Resolver, loc: Path, lib: str = LIB_DEFAULT, ver: Optional[str] = None
) -> SourceFile:
    """Parse ``loc`` and add it to an already-built ``resolver``, returning the
    :class:`~hdldepends.model.SourceFile`.

    This restores the old ``--top-file-type`` auto-add: a top file (typically a
    testbench) can be named on the command line / API without also listing it in
    the config. The parser is chosen from ``loc``'s extension; an unrecognised
    extension raises :class:`~hdldepends.errors.ConfigError`.
    """
    ftype = TOP_FILE_EXT_TYPES.get(loc.suffix.lower())
    if ftype is None:
        known = " / ".join(sorted(TOP_FILE_EXT_TYPES))
        raise ConfigError(
            f"cannot infer a file type for top file {loc} from its extension "
            f"{loc.suffix!r}; expected one of {known}"
        )
    if ftype == FileType.VHDL:
        sf = parse_vhdl_file(loc, lib=lib, ver=ver)
    elif ftype == FileType.VERILOG:
        inc_locs = [f.loc for f in resolver.by_loc.values() if f.ftype == FileType.VERILOG_INCLUDE]
        sf = parse_verilog_file(loc, ver, resolver.verilog_include_dirs, inc_locs)
    elif ftype == FileType.X_BD:
        sf = parse_x_bd_file(loc, ver)
    else:  # FileType.X_XCI
        sf = parse_x_xci_file(loc, ver)
    resolver.add(sf)
    return sf
