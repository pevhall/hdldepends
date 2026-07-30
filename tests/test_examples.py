"""End-to-end tests that run the projects under examples/ and check the result.

These double as executable documentation: each test builds a real example
project (with its YAML config) and asserts the resolved compile order, libraries,
file types and external-file handling.
"""

from pathlib import Path

import hdldepends
from hdldepends.config import build_resolver
from hdldepends.model import Name

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _resolve(monkeypatch, example: str, top_entity: str):
    """Build an example's resolver and its compile order for ``top_entity``."""
    monkeypatch.chdir(EXAMPLES / example)
    resolver = build_resolver("hdldeps.yaml", work_dir=Path("."))
    order = resolver.compile_order(resolver.find_top(Name("work", top_entity)))
    return resolver, order


def _by_stem(order):
    return {sf.loc.stem: sf for sf in order}


# --- examples/multi_lang_yaml ----------------------------------------------

def test_multi_lang_yaml(monkeypatch):
    resolver, order = _resolve(monkeypatch, "multi_lang_yaml", "top")
    stems = [sf.loc.stem for sf in order]

    # cross-language + cross-library resolution, dependencies before dependents
    assert set(stems) == {"math_pkg", "adder", "fifo", "sync_fifo", "datapath", "top"}
    assert stems[-1] == "top"
    assert stems.index("math_pkg") < stems.index("adder") < stems.index("datapath")
    assert stems.index("fifo") < stems.index("sync_fifo") < stems.index("datapath")

    by = _by_stem(order)
    # common_lib VHDL is tagged with its library; the SystemVerilog/Verilog is work
    assert by["math_pkg"].lib == "common_lib" and by["adder"].lib == "common_lib"
    assert by["datapath"].lib == "work" and by["top"].lib == "work"
    assert by["fifo"].type_str == "VERILOG" and by["sync_fifo"].type_str == "VERILOG"


# --- examples/vhdl2008_ext_exclude -----------------------------------------

def test_vhdl2008_ext_exclude(monkeypatch):
    resolver, order = _resolve(monkeypatch, "vhdl2008_ext_exclude", "top")
    stems = [sf.loc.stem for sf in order]

    # the excluded legacy file is absent; everything else is present
    assert set(stems) == {"pkg_types", "alu", "clk_div", "core", "top"}
    assert "legacy" not in stems
    assert all("legacy" not in str(loc) for loc in resolver.by_loc)

    # correct topological order
    assert stems[-1] == "top"
    assert stems.index("pkg_types") < stems.index("alu") < stems.index("core")
    assert stems.index("clk_div") < stems.index("core")

    # VHDL-2008 files report the @tag as their type; the SV module stays VERILOG
    by = _by_stem(order)
    for name in ("pkg_types", "alu", "core", "top"):
        assert by[name].type_str == "VHDL2008", name
    assert by["clk_div"].type_str == "VERILOG"

    # external files are recorded by tag and never enter the index / order
    assert [p.name for p in resolver.tag_2_ext["xdc"]] == ["pins.xdc"]
    assert [p.name for p in resolver.tag_2_ext["tcl"]] == ["build.tcl"]
    assert not any(p.suffix in (".xdc", ".tcl") for p in resolver.by_loc)


# --- examples/python_api (the Python API walkthrough) ----------------------

def test_python_api_example():
    # Drive the example the way analyse_example.py does, so the example's
    # documented behaviour stays verified.
    api_dir = EXAMPLES / "python_api"

    # 1. Config's own top (top_entity: counter): counter_pkg before counter.
    result = hdldepends.analyse("hdldeps.yaml", work_dir=api_dir)
    stems = [Path(e["path"]).stem for e in result.compile_order]
    assert stems == ["counter_pkg", "counter"]
    assert result.compile_order[-1]["is_top"] is True
    # the human-readable listing is available as a string / via stdout
    assert result.format_compile_order().startswith("compile order:")

    # 2. Testbench top via top_file -- auto-added (not in hdldeps.yaml) and its
    #    dependencies pulled in ahead of it.
    tb = hdldepends.analyse("hdldeps.yaml", work_dir=api_dir, top_file="sim/counter_tb.vhd")
    tb_stems = [Path(e["path"]).stem for e in tb.compile_order]
    assert tb_stems == ["counter_pkg", "counter", "counter_tb"]
    assert tb.compile_order[-1]["is_top"] is True
