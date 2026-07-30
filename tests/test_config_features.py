"""Config-feature tests: @tags, inline globs + exclusion, skip-order, ext files."""

import subprocess
from pathlib import Path

import pytest

from hdldepends.config import build_resolver
from hdldepends.config_models import ConfigError
from hdldepends.model import FileType, Name


def _yaml(tmp_path, text, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content)
    (tmp_path / "hdldeps.yaml").write_text(text)


def test_vhdl_ver_tag_becomes_the_type(tmp_path, monkeypatch):
    # A custom @tag (VHDL2008) is carried through and shown as the file's type.
    _yaml(
        tmp_path,
        "vhdl_files@VHDL2008:\n  mylib:\n    - ./a.vhd\n",
        a__vhd="library ieee;\nentity a is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    sf = r.find_top(Name("mylib", "a"))
    assert sf.ver == "VHDL2008"
    assert sf.lib == "mylib"
    assert sf.type_str == "VHDL2008"


def test_files_accepts_globs_and_serial_exclusion(tmp_path, monkeypatch):
    # `vhdl_files` (not just `_files_glob`) accepts globs; a `!` pattern removes
    # earlier matches, processed serially.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - './*.vhd'\n    - '!./skip.vhd'\n",
        a__vhd="library ieee;\nentity a is end entity;\n",
        b__vhd="library ieee;\nentity b is end entity;\n",
        skip__vhd="library ieee;\nentity skip is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    stems = {p.stem for p in r.by_loc}
    assert {"a", "b"} <= stems
    assert "skip" not in stems


def test_skip_order_is_parsed_but_not_in_compile_order(tmp_path, monkeypatch):
    # A skip-order file is parsed (its package is discoverable) but excluded from
    # the compile order -- the Xilinx-primitive use case.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\n"
        "vhdl_package_skip_order:\n  work: ./prim.vhd\n",
        prim__vhd="package prim_pkg is end package;\n",
        top__vhd=(
            "library work;\nuse work.prim_pkg.all;\n"
            "entity top is end entity;\narchitecture a of top is begin end architecture;\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.resolve(Name("work", "prim_pkg")) is not None  # discoverable
    stems = [s.loc.stem for s in r.compile_order(r.find_top(Name("work", "top")))]
    assert "top" in stems
    assert "prim" not in stems  # excluded from the order


def test_init_files_force_add_satisfies_dependency(tmp_path, monkeypatch):
    # `secret_ip` is instantiated by top, but its file is encrypted/binary and is
    # never parsed. init_files force-adds it and declares the name it provides, so
    # the instantiation resolves and it lands in the compile order before its user.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\n"
        "init_files:\n  - ['./secret_ip.edn', 'VHDL', '', 'work', 'secret_ip']\n",
        secret_ip__edn="<<encrypted binary netlist, not parseable>>\n",
        top__vhd=(
            "library ieee;\nentity top is end entity;\n"
            "architecture a of top is begin\n"
            "  i : entity work.secret_ip port map (x => x);\nend architecture;\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.resolve(Name("work", "secret_ip")) is not None  # forced file provides it
    stems = [s.loc.stem for s in r.compile_order(r.find_top(Name("work", "top")))]
    assert "secret_ip" in stems and "top" in stems
    assert stems.index("secret_ip") < stems.index("top")


def test_init_files_bare_string_raises_clean_config_error(tmp_path, monkeypatch):
    # init_files must be a list of [loc, type, ...] entries. A bare string is a
    # plausible mistake (most other source-file keys accept a bare string) but
    # previously iterated character-by-character, so `entry[1]` raised a bare,
    # confusing IndexError instead of naming the actual problem.
    _yaml(tmp_path, "init_files: './secret_ip.edn'\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert not isinstance(ei.value, IndexError)
    assert "init_files" in str(ei.value)


def test_init_files_entry_too_short_raises_clean_config_error(tmp_path, monkeypatch):
    # An entry missing the required `type` element previously raised a bare
    # IndexError from `entry[1]`.
    _yaml(tmp_path, "init_files:\n  - ['./only_loc.edn']\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert not isinstance(ei.value, IndexError)
    assert "init_files" in str(ei.value)


def test_pre_cmds_failure_raises_clean_config_error(tmp_path, monkeypatch):
    # A failing pre_cmds command previously escaped build_resolver as a raw
    # subprocess.CalledProcessError (reaching the CLI as a traceback) --
    # CalledProcessError was neither wrapped here nor in cli.py's caught set.
    _yaml(tmp_path, "pre_cmds: 'false'\nvhdl_files: []\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert not isinstance(ei.value, subprocess.CalledProcessError)
    assert "'false'" in str(ei.value)  # the command is named
    assert "hdldeps.yaml" in str(ei.value)  # ...and so is the config file


def test_pre_cmds_failure_message_includes_captured_output_tail(tmp_path, monkeypatch):
    # check_output captures the command's stdout; when the failing command
    # printed something, that output is usually the actual reason it failed,
    # so a tail of it must appear in the error message.
    _yaml(tmp_path, "pre_cmds: 'echo boom; exit 3'\nvhdl_files: []\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert "exit status 3" in str(ei.value)
    assert "boom" in str(ei.value)


def test_ext_files_tracked_but_not_compiled(tmp_path, monkeypatch):
    # External files (.xdc/.tcl) are recorded for `-o ext-list` but never enter
    # the index or the compile order.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\next_files:\n  - ./c.xdc\n  - ./build.tcl\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        c__xdc="# constraints\n",
        build__tcl="# tcl\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    ext_all = [p for paths in r.tag_2_ext.values() for p in paths]
    assert any(p.suffix == ".xdc" for p in ext_all)
    assert any(p.suffix == ".tcl" for p in ext_all)
    assert not any(p.suffix in (".xdc", ".tcl") for p in r.by_loc)


# --- top_entity / top_vhdl_file / top_verilog_file / top_x_bd_file ---------
# Restores a documented (README "Top level file") feature that the flat-Resolver
# rewrite silently dropped: these config keys never reached the loader, so a
# config-only `top_entity`/`top_*_file` produced no compile order at all.

def test_top_entity_bare_name_uses_config_top_lib(tmp_path, monkeypatch):
    # A bare `top_entity` name resolves in the config's default (top) library,
    # not hardcoded 'work' -- str_to_name alone would get this wrong.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_name == Name("work", "top")
    assert r.find_top(r.top_name).loc.stem == "top"


def test_top_entity_lib_dot_name_form_names_library_explicitly(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "vhdl_files:\n  mylib:\n    - ./top.vhd\ntop_entity: mylib.top\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_name == Name("mylib", "top")


def test_top_entity_multi_dot_raises_configerror_not_raw_valueerror(tmp_path, monkeypatch):
    # "a.b.c" makes str_to_name raise ValueError (more than one '.'); the
    # config loader must wrap it as a ConfigError naming the config file, not
    # let the ValueError escape as a raw traceback.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: a.b.c\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert "hdldeps.yaml" in str(ei.value)
    assert "invalid top_entity" in str(ei.value)
    assert "a.b.c" in str(ei.value)


def test_top_vhdl_file_sets_top_loc_and_is_added_to_project(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_vhdl_file: ./top.vhd\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_loc == (tmp_path / "top.vhd").resolve()
    sf = r.by_loc[r.top_loc]
    assert sf.ftype == FileType.VHDL
    assert sf.lib == "work"


def test_top_vhdl_file_lib_dict_form_sets_the_library(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_vhdl_file:\n  mylib: ./top.vhd\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.by_loc[r.top_loc].lib == "mylib"


def test_top_vhdl_file_at_tag_form_sets_the_ver_tag(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_vhdl_file@VHDL2008: ./top.vhd\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.by_loc[r.top_loc].ver == "VHDL2008"


def test_top_verilog_file_sets_top_loc_and_is_added_to_project(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_verilog_file: ./top.v\n",
        top__v="module top;\nendmodule\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_loc == (tmp_path / "top.v").resolve()
    assert r.by_loc[r.top_loc].ftype == FileType.VERILOG


def test_top_x_bd_file_sets_top_loc_and_is_added_to_project(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_x_bd_file: ./top.bd\n",
        top__bd=(
            '{"design": {"design_info": {'
            '"tool_version": "2024.2", "device": "xczu1cg-sbva484-2-e", "name": "top_bd"'
            "}}}\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_loc == (tmp_path / "top.bd").resolve()
    assert r.by_loc[r.top_loc].ftype == FileType.X_BD


def test_multiple_entries_in_one_top_key_raises_configerror(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_vhdl_file:\n  - ./a.vhd\n  - ./b.vhd\n",
        a__vhd="library ieee;\nentity a is end entity;\n",
        b__vhd="library ieee;\nentity b is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        build_resolver("hdldeps.yaml", work_dir=Path("."))


def test_multiple_top_file_keys_in_one_config_raises_configerror(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "top_vhdl_file: ./a.vhd\ntop_verilog_file: ./b.v\n",
        a__vhd="library ieee;\nentity a is end entity;\n",
        b__v="module b;\nendmodule\n",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        build_resolver("hdldeps.yaml", work_dir=Path("."))


def test_top_key_in_sub_config_raises_configerror(tmp_path, monkeypatch):
    # README: "A configuration containing a top file setting cannot be
    # referenced by another configuration through the `sub` option."
    (tmp_path / "root.yaml").write_text("sub: sub.yaml\n")
    (tmp_path / "sub.yaml").write_text("top_entity: top\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("root.yaml", work_dir=Path("."))
    msg = str(ei.value).lower()
    assert "sub" in msg and "cannot be referenced" in msg


def test_top_file_key_in_sub_config_raises_configerror(tmp_path, monkeypatch):
    (tmp_path / "root.yaml").write_text("sub: sub.yaml\n")
    (tmp_path / "sub.yaml").write_text("top_vhdl_file: ./top.vhd\n")
    (tmp_path / "top.vhd").write_text("library ieee;\nentity top is end entity;\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("root.yaml", work_dir=Path("."))
    assert "cannot be referenced" in str(ei.value).lower()


# --- the sub-config top-key prohibition is order-independent ----------------
# The old check ran INSIDE gather() and only fired when `is_root` was False,
# but `is_root` is only meaningful the FIRST time a config is gathered -- a
# second, later `sub` edge onto an already-`done` config short-circuited
# before ever reaching that check, so whether the violation was caught
# depended on which argv order pulled the shared config in as a root first.

def test_top_key_config_referenced_via_sub_raises_regardless_of_argv_order(tmp_path, monkeypatch):
    # a.yaml has a top key; b.yaml sub's it in. Both orders must raise --
    # previously listing a.yaml (the top-key config) first let its root
    # gather() mark it `done` before b.yaml's `sub` edge onto it was ever
    # checked, silently masking the violation for that order only.
    (tmp_path / "a.yaml").write_text("vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\n")
    (tmp_path / "b.yaml").write_text("sub: a.yaml\n")
    (tmp_path / "top.vhd").write_text("library ieee;\nentity top is end entity;\n")
    monkeypatch.chdir(tmp_path)

    for argv in (["a.yaml", "b.yaml"], ["b.yaml", "a.yaml"]):
        with pytest.raises(ConfigError) as ei:
            build_resolver(list(argv), work_dir=Path("."))
        assert "cannot be referenced" in str(ei.value).lower(), argv


def test_top_key_config_used_only_as_root_still_works(tmp_path, monkeypatch):
    # Sanity check for the F5 rewrite: a config with a top key that is NEVER
    # reached via `sub` (used only directly, as a root) must still build.
    (tmp_path / "a.yaml").write_text("vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\n")
    (tmp_path / "top.vhd").write_text("library ieee;\nentity top is end entity;\n")
    monkeypatch.chdir(tmp_path)
    r = build_resolver(["a.yaml"], work_dir=Path("."))
    assert r.top_name == Name("work", "top")


# --- top_*_file + top_entity in the SAME config warns -----------------------

def test_top_entity_and_top_file_same_config_warns_and_top_file_wins(tmp_path, monkeypatch, capsys):
    # A single config setting BOTH a top_*_file key and top_entity was
    # previously silent (top_loc always wins downstream in cli.py, so
    # top_entity was a silent no-op) even though every OTHER conflicting-top
    # case (two configs disagreeing) already warns.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\n    - ./other.vhd\n"
        "top_vhdl_file: ./top.vhd\ntop_entity: other\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        other__vhd="library ieee;\nentity other is end entity;\n",
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_loc == (tmp_path / "top.vhd").resolve()  # top file still wins
    err = capsys.readouterr().err
    assert "WARNING" in err and "top_entity" in err and "overridden" in err


def test_two_root_configs_both_set_top_entity_last_wins_with_warning(tmp_path, monkeypatch, capsys):
    # Each config file passed on the command line is a root and may set the
    # top; when two do, the later one wins (with a warning, not a hard error).
    (tmp_path / "a.yaml").write_text("vhdl_files:\n  work:\n    - ./a.vhd\ntop_entity: a\n")
    (tmp_path / "b.yaml").write_text("vhdl_files:\n  work:\n    - ./b.vhd\ntop_entity: b\n")
    (tmp_path / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (tmp_path / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    monkeypatch.chdir(tmp_path)
    r = build_resolver(["a.yaml", "b.yaml"], work_dir=Path("."))
    assert r.top_name == Name("work", "b")
    err = capsys.readouterr().err
    assert "WARNING" in err


def test_two_root_configs_both_set_top_vhdl_file_last_wins_with_warning(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.yaml").write_text("top_vhdl_file: ./a.vhd\n")
    (tmp_path / "b.yaml").write_text("top_vhdl_file: ./b.vhd\n")
    (tmp_path / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (tmp_path / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    monkeypatch.chdir(tmp_path)
    r = build_resolver(["a.yaml", "b.yaml"], work_dir=Path("."))
    assert r.top_loc == (tmp_path / "b.vhd").resolve()
    err = capsys.readouterr().err
    assert "WARNING" in err


def test_top_vhdl_file_not_otherwise_listed_lands_in_project_and_order(tmp_path, monkeypatch):
    # The top file need not also appear under vhdl_files -- it must still be
    # parsed, indexed, and reachable as the head of the compile order.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./leaf.vhd\ntop_vhdl_file: ./top.vhd\n",
        leaf__vhd="library ieee;\nentity leaf is end entity;\n",
        top__vhd=(
            "library ieee;\nentity top is end entity;\n"
            "architecture a of top is begin\n"
            "  i_leaf : entity work.leaf port map (a_i => a_i);\nend architecture;\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    assert r.top_loc in r.by_loc
    top = r.by_loc[r.top_loc]
    stems = [s.loc.stem for s in r.compile_order(top)]
    assert stems == ["leaf", "top"]


def test_init_files_listed_by_two_sub_configs_dedupes(tmp_path, monkeypatch):
    # Fold-in fix: the same init_files entry listed by two sub-configs (a
    # shared "diamond" dependency) previously left resolver.init_files with
    # two SourceFile objects for the same loc, so cli.py force-added it twice.
    (tmp_path / "root.yaml").write_text("sub:\n  - a.yaml\n  - b.yaml\n")
    entry = "init_files:\n  - ['./secret_ip.edn', 'VHDL', '', 'work', 'secret_ip']\n"
    (tmp_path / "a.yaml").write_text(entry)
    (tmp_path / "b.yaml").write_text(entry)
    (tmp_path / "secret_ip.edn").write_text("<<encrypted binary netlist, not parseable>>\n")
    monkeypatch.chdir(tmp_path)
    r = build_resolver("root.yaml", work_dir=Path("."))
    locs = [sf.loc for sf in r.init_files]
    assert len(locs) == 1


# --- resolver.add() replace-with-cleanup ------------------------------------
# The old first-wins dedup (skip re-add when (lib, ftype, ver, provides) was
# identical) kept an unparsed init_files stub over a later-parsed real file
# with the same loc, since a VHDL entity's provides matches the init stub's
# synthesized name -- so the compile order silently lost the file's real
# dependencies. add() is now unconditional replace-with-cleanup (last write
# wins), which fixes this without reintroducing the by_name staleness G3 (see
# test_resolver.py) originally guarded against.

def test_init_files_and_vhdl_files_same_file_parsed_deps_survive(tmp_path, monkeypatch):
    # Differential repro: top.vhd listed in BOTH init_files (as an unparsed,
    # requires=[] stub) and vhdl_files (parsed for real, with its own
    # requires). Previously the stub -- added first, then "re-added"
    # identically-by-tuple when the parsed file came in -- won the by_loc
    # slot, so leaf (top's only dependency) silently dropped out of the
    # compile order.
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./leaf.vhd\n    - ./top.vhd\n"
        "init_files:\n  - ['./top.vhd', 'VHDL']\n"
        "top_entity: top\n",
        leaf__vhd="library ieee;\nentity leaf is end entity;\n",
        top__vhd=(
            "library ieee;\nentity top is end entity;\n"
            "architecture a of top is begin\n"
            "  i_leaf : entity work.leaf port map (x => x);\n"
            "end architecture;\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    r = build_resolver("hdldeps.yaml", work_dir=Path("."))
    top_sf = r.by_loc[(tmp_path / "top.vhd").resolve()]
    assert top_sf.requires  # the PARSED file's requires, not the stub's empty list
    stems = [sf.loc.stem for sf in r.compile_order(top_sf)]
    assert stems == ["leaf", "top"]  # leaf present and ordered before its dependent


def test_init_files_two_sub_configs_different_lib_matches_by_loc(tmp_path, monkeypatch):
    # Two sub-configs list the SAME init path but with different libs: exactly
    # one resolver.init_files entry must survive, and it must be the SAME
    # object (same lib) that by_loc now resolves to -- not a stale one left
    # over from the sub-config that lost the race.
    (tmp_path / "root.yaml").write_text("sub:\n  - a.yaml\n  - b.yaml\n")
    (tmp_path / "a.yaml").write_text("init_files:\n  - ['./ip.edn', 'VHDL', '', 'lib_a', 'ip']\n")
    (tmp_path / "b.yaml").write_text("init_files:\n  - ['./ip.edn', 'VHDL', '', 'lib_b', 'ip']\n")
    (tmp_path / "ip.edn").write_text("<<encrypted binary netlist, not parseable>>\n")
    monkeypatch.chdir(tmp_path)
    r = build_resolver("root.yaml", work_dir=Path("."))
    assert len(r.init_files) == 1
    ip_loc = (tmp_path / "ip.edn").resolve()
    assert r.init_files[0] is r.by_loc[ip_loc]
    assert r.init_files[0].lib == r.by_loc[ip_loc].lib == "lib_b"
