"""Writing the resolved compile order / file lists to disk and stdout."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from .model import FileType, SourceFile


def _filter(files: List[SourceFile], ftype: Optional[FileType], lib: Optional[str]):
    for sf in files:
        if ftype is not None and sf.ftype != ftype:
            continue
        if lib is not None and sf.lib != lib:
            continue
        yield sf


def format_compile_order(order: List[SourceFile]) -> str:
    """Render ``order`` as the human-readable, tree-indented compile-order
    listing (the exact text :func:`print_compile_order` writes to stdout, minus
    the trailing newline). Shared by the CLI and
    :meth:`hdldepends.api.AnalysisResult.format_compile_order`."""
    lines = ["compile order:"]
    for sf in order:
        lines.append(f"  {sf.type_str + ':':14} {'|---' * sf.level}{sf.lib}: {sf.loc}")
    return "\n".join(lines)


def print_compile_order(order: List[SourceFile]) -> None:
    print(format_compile_order(order))


def write_compile_order(
    order, loc: Path, ftype: Optional[FileType] = None, lib: Optional[str] = None, paths_only: bool = False
) -> None:
    with open(loc, "w", encoding="utf-8") as f:
        for sf in _filter(order, ftype, lib):
            if paths_only or lib is not None:
                f.write(f"{sf.loc}\n")
            else:
                f.write(f"{sf.type_str} {sf.lib} {sf.loc}\n")


def write_file_list(files, loc: Path, ftype: Optional[FileType] = None, lib: Optional[str] = None) -> None:
    with open(loc, "w", encoding="utf-8") as f:
        for sf in _filter(files, ftype, lib):
            f.write(f"{sf.loc}\n" if lib is not None else f"{sf.lib}\t{sf.loc}\n")


def write_ext_list(tag_2_ext: Dict[str, List[Path]], loc: Path, tag: Optional[str] = None) -> None:
    with open(loc, "w", encoding="utf-8") as f:
        if tag is not None:
            for path in tag_2_ext.get(tag, []):
                f.write(f"{path}\n")
        else:
            for t, paths in tag_2_ext.items():
                for path in paths:
                    # `t` is None for untagged ext files -- print an empty
                    # column, not the literal string "None".
                    f.write(f"{t or ''}\t{path}\n")


def compile_order_to_dicts(order: List[SourceFile], tag_2_ext: Dict[str, List[Path]]) -> List[Dict]:
    """Build the flat, JSON-safe list of dicts used by both the
    ``compile-order-json`` CLI output and :func:`hdldepends.api.analyse`:
    EXTERNAL entries (from ``tag_2_ext``) first, then one entry per file in
    ``order``, with ``is_top`` set on the last one."""
    files = []
    for tag, paths in tag_2_ext.items():
        for path in paths:
            ext_entry = {"type": "EXTERNAL", "file_ext": path.suffix.upper().lstrip(".") or "UNKNOWN", "path": str(path)}
            if tag:
                ext_entry["ver_tag"] = tag
            files.append(ext_entry)
    for i, sf in enumerate(order):
        # `type` is the base language (VHDL/VERILOG/...); the custom @tag (e.g.
        # VHDL2008) is reported separately as `ver_tag` so the two are independent.
        entry: Dict = {"type": sf.ftype.name, "library": sf.lib}
        if sf.ver:
            entry["ver_tag"] = sf.ver
        entry["path"] = str(sf.loc)
        if i == len(order) - 1:
            entry["is_top"] = True
        files.append(entry)
    return files


def write_compile_order_json(order: List[SourceFile], tag_2_ext: Dict[str, List[Path]], loc: Path) -> None:
    with open(loc, "w") as f:
        json.dump({"files": compile_order_to_dicts(order, tag_2_ext)}, f, indent=2)
        f.write("\n")
