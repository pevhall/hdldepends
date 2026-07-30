"""Tests for the public Python API (:mod:`hdldepends.api` / ``hdldepends.analyse``).

Fixture/config conventions mirror ``tests/test_golden.py`` (copy a project
under ``tests/fixtures/<name>/`` into a temp dir) and ``tests/test_config_features.py``
(build a minimal YAML config inline for cases no committed fixture covers).
"""

import json
import shutil
from pathlib import Path

import pytest

import hdldepends
from hdldepends import api
from hdldepends.config import build_resolver
from hdldepends.constants import LIB_DEFAULT
from hdldepends.errors import ConfigError
from hdldepends.model import Name, SourceFile
from hdldepends.output import format_compile_order, write_compile_order_json

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _yaml(tmp_path, text, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content)
    (tmp_path / "hdldeps.yaml").write_text(text)


# --- parity with the compile-order-json writer ------------------------------

def test_analyse_matches_compile_order_json_file(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")

    # Independently reproduce the compile-order-json file the CLI would write
    # for the same invocation, and check the API's dict-form output matches it
    # byte-for-byte (after JSON round-tripping).
    resolver = build_resolver("hdldeps.toml", work_dir=Path("."), top_lib=LIB_DEFAULT)
    top = resolver.find_top(Name(LIB_DEFAULT, "del21"))
    order = api.apply_forced_init_files(resolver, resolver.compile_order(top))
    json_path = work / "compile_order.json"
    write_compile_order_json(order, resolver.tag_2_ext, json_path)
    expected = json.loads(json_path.read_text())

    assert result.to_dict() == expected


def test_result_is_json_safe(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    dumped = json.dumps(result.to_dict())
    assert json.loads(dumped) == result.to_dict()


def test_is_top_on_last_entry_only(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    files = result.compile_order
    assert len(files) >= 2  # del21 depends on del211 -- more than just the top
    assert all("is_top" not in f for f in files[:-1])
    assert files[-1]["is_top"] is True
    assert files[-1]["path"].endswith("del21.vhd")


# --- EXTERNAL entries (tag_2_ext) --------------------------------------------

def test_ext_files_produce_leading_external_entries(tmp_path, monkeypatch):
    # No committed fixture uses ext_files; build a minimal one inline (same
    # pattern as test_config_features.py's ext_files test).
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\next_files:\n  - ./c.xdc\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        c__xdc="# constraints\n",
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyse("hdldeps.yaml")
    files = result.compile_order

    assert files[0]["type"] == "EXTERNAL"
    assert files[0]["file_ext"] == "XDC"
    assert files[0]["path"].endswith("c.xdc")
    assert files[-1]["is_top"] is True
    assert files[-1]["path"].endswith("top.vhd")


def test_ext_files_tagged_version_reported_as_ver_tag(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\next_files@constraints:\n  - ./c.xdc\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        c__xdc="# constraints\n",
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyse("hdldeps.yaml")
    ext = result.compile_order[0]
    assert ext["type"] == "EXTERNAL"
    assert ext["ver_tag"] == "constraints"


# --- top-selection precedence ------------------------------------------------

def _two_entity_project(tmp_path):
    # `a` is both the config's top_entity AND (via top_vhdl_file) the config's
    # top file; `b` is a second, unrelated top-level entity so --top-entity /
    # top_file arguments can be pointed somewhere else and distinguished.
    (tmp_path / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (tmp_path / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    (tmp_path / "hdldeps.yaml").write_text(
        "vhdl_files:\n  work:\n    - ./a.vhd\n    - ./b.vhd\ntop_entity: a\n"
    )


def test_top_file_beats_top_entity_and_config_top(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyse("hdldeps.yaml", top_file="b.vhd", top_entity="a")
    assert result.compile_order[-1]["path"].endswith("b.vhd")


def test_top_entity_beats_config_top(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyse("hdldeps.yaml", top_entity="b")
    assert result.compile_order[-1]["path"].endswith("b.vhd")


def test_config_top_entity_used_when_nothing_explicit(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyse("hdldeps.yaml")
    assert result.compile_order[-1]["path"].endswith("a.vhd")


def test_relative_top_file_is_anchored_to_work_dir(tmp_path, monkeypatch):
    # A relative top_file resolves against work_dir (like relative
    # config_files), NOT against the process CWD -- a library caller may not
    # control the CWD at all.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = hdldepends.analyse("hdldeps.toml", work_dir=work, top_file="del21.vhd")
    assert result.compile_order[-1]["path"] == str(work / "del21.vhd")

    # Sanity check of the contrast: without work_dir the same relative
    # top_file is CWD-relative, which from `elsewhere` names a path that is
    # neither in the project nor on disk -- the auto-add then fails to read it.
    with pytest.raises(OSError):
        hdldepends.analyse(str(work / "hdldeps.toml"), top_file="del21.vhd")


def test_absolute_top_file_ignores_work_dir(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = hdldepends.analyse("hdldeps.toml", work_dir=work, top_file=work / "del21.vhd")
    assert result.compile_order[-1]["path"] == str(work / "del21.vhd")


# --- errors -------------------------------------------------------------

def test_nonexistent_config_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises((ConfigError, OSError)):
        hdldepends.analyse("does_not_exist.yaml")


def test_top_entity_not_found_raises_value_error(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    with pytest.raises(ValueError):
        hdldepends.analyse("hdldeps.toml", top_entity="does_not_exist")


def test_top_file_not_in_project_is_added(tmp_path, monkeypatch):
    # A top_file not listed in the config is parsed and added on the fly (its
    # type inferred from the .vhd extension), so a testbench top level need not
    # be added to the config just to run a compile order.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    (work / "not_in_project.vhd").write_text("library ieee;\nentity nip is end entity;\n")
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_file="not_in_project.vhd")
    assert result.compile_order[-1]["path"].endswith("not_in_project.vhd")
    assert result.compile_order[-1]["is_top"] is True


def test_added_top_file_pulls_in_config_dependencies(tmp_path, monkeypatch):
    # An auto-added top file's dependencies still resolve against the project:
    # a testbench that instantiates a config entity produces the full order.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    (work / "tb.vhd").write_text(
        "library ieee;\n"
        "entity tb is end entity;\n"
        "architecture sim of tb is\n"
        "begin\n"
        "  dut : entity work.del21\n"
        "  port map (\n"
        "    clk => clk\n"
        "  );\n"
        "end architecture;\n"
    )
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_file="tb.vhd")
    paths = [f["path"] for f in result.compile_order]
    assert paths[-1].endswith("tb.vhd")
    assert any(p.endswith("del21.vhd") for p in paths[:-1])


def test_added_top_file_unknown_extension_raises(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    (work / "top.qqq").write_text("nonsense\n")
    monkeypatch.chdir(work)

    with pytest.raises(ConfigError, match="extension"):
        hdldepends.analyse("hdldeps.toml", top_file="top.qqq")


def test_no_top_anywhere_raises_value_error(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "verilog_basic", work)
    monkeypatch.chdir(work)

    with pytest.raises(ValueError):
        hdldepends.analyse("hdldeps.toml")


# --- config_files: single path vs sequence -----------------------------------

def test_config_files_accepts_single_path_or_str(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    by_str = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    by_path = hdldepends.analyse(Path("hdldeps.toml"), top_entity="del21")
    assert by_str.to_dict() == by_path.to_dict()


def test_config_files_accepts_a_sequence(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    by_list = hdldepends.analyse(["hdldeps.toml"], top_entity="del21")
    by_str = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    assert by_list.to_dict() == by_str.to_dict()


# --- x_tool_version / x_device kwargs ----------------------------------------

def test_x_tool_version_and_x_device_applied_to_resolver(tmp_path, monkeypatch):
    # x_device_filter registers two same-named Xilinx IPs (axi_a.xci /
    # axi_b.xci) at different tool versions/devices; only passing matching
    # x_tool_version + x_device selects axi_b.xci -- mirrors
    # tests/test_golden.py's x_device_compile CLI case (see that snapshot).
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "x_device_filter", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse(
        "hdldeps.toml",
        top_entity="axi_bram_ctrl_0",
        x_tool_version="2024.2",
        x_device="xczu1cg-sbva484-2-e",
    )
    assert [f["path"] for f in result.compile_order] == [str(work / "axi_b.xci")]


def test_x_tool_version_and_x_device_default_to_unset_on_resolver(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    resolver = build_resolver("hdldeps.toml", work_dir=Path("."), top_lib=LIB_DEFAULT)
    assert resolver.x_tool_version == ""
    assert resolver.x_device == ""


# --- AnalysisResult.format_compile_order / print_compile_order --------------

def test_format_compile_order_returns_indented_string(tmp_path, monkeypatch):
    # del21 (the top) instantiates del211, so the resolved order is
    # [del211 @ level 1, del21 @ level 0]: the dependency is tree-indented with
    # "|---" and the top is not, exactly as the CLI prints it.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    text = result.format_compile_order()

    assert isinstance(text, str)
    lines = text.splitlines()
    assert lines[0] == "compile order:"
    dep_line = next(ln for ln in lines if ln.endswith("del211.vhd"))
    top_line = next(ln for ln in lines if ln.endswith("del21.vhd"))
    assert "|---" in dep_line          # dependency is indented
    assert "|---" not in top_line      # top sits at level 0


def test_format_compile_order_matches_free_function(tmp_path, monkeypatch):
    # The method is faithful to the CLI: it renders the retained SourceFile
    # order through the very same output.format_compile_order helper the CLI
    # uses, so the two are byte-for-byte identical.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    assert result.format_compile_order() == format_compile_order(result.source_files)
    assert all(isinstance(sf, SourceFile) for sf in result.source_files)


def test_print_compile_order_writes_format_to_stdout(tmp_path, monkeypatch, capsys):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    result.print_compile_order()

    out = capsys.readouterr().out
    assert out == result.format_compile_order() + "\n"


def test_source_files_excluded_from_to_dict(tmp_path, monkeypatch):
    # source_files holds live SourceFile objects for rendering only; the
    # JSON-safe representation must not leak them.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyse("hdldeps.toml", top_entity="del21")
    d = result.to_dict()
    assert set(d.keys()) == {"files"}
    # round-trips through JSON without hitting the non-serializable SourceFiles
    json.dumps(d)
