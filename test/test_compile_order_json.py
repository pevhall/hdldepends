#!/usr/bin/env python3
"""Test for the hdldepends `--compile-order-json` output.

Runs hdldepends on test/vhdl/hdl_deps_prj.toml with `--compile-order-json`, then
compares the generated JSON with the expected (golden) JSON file
`expected_compile_order.json` which lives next to this script.

The paths in the generated JSON are absolute, so before comparing, every path
under the `test` directory is replaced with the placeholder "@TEST_DIR@", which
makes the expected file independent of where the repository is checked out.

Usage:
    ./test_compile_order_json.py              # run the test (used by run_test.sh)
    ./test_compile_order_json.py --update     # regenerate the expected JSON
    ./test_compile_order_json.py -v           # also show the hdldepends output

Exits with 0 on success, 1 if hdldepends fails or if the generated JSON differs
from the expected one. Can also be run with pytest.
"""

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
HDLDEPENDS_PY = REPO_ROOT / "src" / "hdldepends" / "hdldepends.py"
EXPECTED_JSON = TEST_DIR / "expected_compile_order.json"

# Arguments used to generate the compile order.
CONFIG_FILE = "./vhdl/hdl_deps_prj.toml"
X_TOOL_VERSION = "2024.2"
X_DEVICE = "xczu1cg-sbva484-2-e"

PATH_PLACEHOLDER = "@TEST_DIR@"

# Files which must be present in the compile order.
# axis_data_to_chdr.sv has a SystemVerilog `import` statement between the module
# name and the parameter list, it used to be missed by the module declaration
# regular expression (so it was missing from the compile order).
REQUIRED_COMPILE_ORDER_FILES = ["axis_data_to_chdr.sv"]

# Minimal VHDL files used when a real Vivado install is not available.
# vhdl/hdl_deps_prj.toml refers to them through $XILINX_VIVADO, they are parsed
# (but skipped from the compile order), so they only need to declare the
# packages used by the test files.
VIVADO_STUB_FILES = {
    "data/ip/xpm/xpm_VCOMP.vhd": "package VCOMPONENTS is\n\nend VCOMPONENTS;\n",
    "data/vhdl/src/unisims/unisim_VCOMP.vhd": "package VCOMPONENTS is\n\nend VCOMPONENTS;\n",
}


def vivado_stub_dir(base_dir: Path) -> Path:
    """Create a minimal fake Vivado install, return its root."""
    root = base_dir / "vivado_stub"
    for rel_loc, contents in VIVADO_STUB_FILES.items():
        loc = root / rel_loc
        loc.parent.mkdir(parents=True, exist_ok=True)
        loc.write_text(contents)
    return root


def xilinx_vivado_env(base_dir: Path) -> Dict[str, str]:
    """Environment for the hdldepends run, with a usable XILINX_VIVADO."""
    env = dict(os.environ)
    xilinx_vivado = env.get("XILINX_VIVADO")
    required = Path("data/ip/xpm/xpm_VCOMP.vhd")
    if xilinx_vivado is None or not (Path(xilinx_vivado) / required).is_file():
        if xilinx_vivado is not None:
            print(f"note: XILINX_VIVADO={xilinx_vivado} has no {required}, using a stub Vivado install instead")
        env["XILINX_VIVADO"] = str(vivado_stub_dir(base_dir))
        print(f"note: using XILINX_VIVADO={env['XILINX_VIVADO']}")
    return env


def run_hdldepends(compile_order_json: Path, env: Dict[str, str]) -> str:
    """Run hdldepends, writing the compile order JSON to `compile_order_json`. Returns its output."""
    cmd = [
        sys.executable,
        str(HDLDEPENDS_PY),
        CONFIG_FILE,
        f"--x-tool-version={X_TOOL_VERSION}",
        f"--x-device={X_DEVICE}",
        "-c",
        f"--compile-order-json={compile_order_json}",
    ]
    print("running: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(TEST_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0 or not compile_order_json.is_file():
        print(f"hdldepends failed with exit code {result.returncode}:")
        print(result.stdout)
        raise RuntimeError("hdldepends did not produce a compile order JSON file")
    return result.stdout


def normalise_paths(obj: Any) -> Any:
    """Replace absolute paths inside TEST_DIR with PATH_PLACEHOLDER."""

    def normalise_str(value: str) -> str:
        if not Path(value).is_absolute():
            return value
        try:
            resolved = Path(value).resolve()
        except OSError:
            return value
        if resolved == TEST_DIR:
            return PATH_PLACEHOLDER
        if TEST_DIR in resolved.parents:
            return f"{PATH_PLACEHOLDER}/{resolved.relative_to(TEST_DIR).as_posix()}"
        return value

    if isinstance(obj, dict):
        return {key: normalise_paths(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [normalise_paths(value) for value in obj]
    if isinstance(obj, str):
        return normalise_str(obj)
    return obj


def json_lines(obj: Any) -> List[str]:
    return json.dumps(obj, indent=2).splitlines()


def missing_required_files(compile_order: Dict[str, Any]) -> List[str]:
    """Return the REQUIRED_COMPILE_ORDER_FILES missing from the compile order."""
    compile_order_names = [Path(entry.get("path", "")).name for entry in compile_order.get("files", [])]
    return [required for required in REQUIRED_COMPILE_ORDER_FILES if required not in compile_order_names]


def generate_actual_compile_order() -> Tuple[Dict[str, Any], str]:
    """Returns (normalised compile order JSON, hdldepends output)."""
    temp_dir = Path(tempfile.mkdtemp(prefix="hdldepends_test_"))
    try:
        env = xilinx_vivado_env(temp_dir)
        actual_json = temp_dir / "compile_order.json"
        hdldepends_output = run_hdldepends(actual_json, env)
        with open(actual_json) as f:
            return normalise_paths(json.load(f)), hdldepends_output
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def compare_compile_order(actual: Dict[str, Any], expected: Dict[str, Any], hdldepends_output: str = "", verbose: bool = False) -> bool:
    """Compare the generated compile order with the expected one, prints the result."""
    output_shown = [False]

    def show_hdldepends_output():
        if hdldepends_output and (verbose or not output_shown[0]):
            output_shown[0] = True
            print("--- hdldepends output ---")
            print(hdldepends_output)

    if verbose:
        show_hdldepends_output()

    diff = list(
        difflib.unified_diff(
            json_lines(expected), json_lines(actual), fromfile=str(EXPECTED_JSON.name), tofile="generated", lineterm=""
        )
    )
    if diff:
        show_hdldepends_output()
        print("FAIL: generated compile order JSON does not match the expected JSON")
        print("\n".join(diff))
        return False

    missing = missing_required_files(actual)
    if missing:
        show_hdldepends_output()
        print(f"FAIL: {', '.join(missing)} missing from compile order")
        return False

    print(f"PASS: compile order JSON matches {EXPECTED_JSON.name} ({len(actual.get('files', []))} files)")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    arg_parser = argparse.ArgumentParser(description="Compare the hdldepends --compile-order-json output with the expected JSON")
    arg_parser.add_argument("--update", action="store_true", help=f"write the generated JSON to {EXPECTED_JSON.name} instead of comparing")
    arg_parser.add_argument("-v", "--verbose", action="store_true", help="show the hdldepends output")
    args = arg_parser.parse_args(argv)

    if not HDLDEPENDS_PY.is_file():
        print(f"error: cannot find {HDLDEPENDS_PY}")
        return 1

    actual, hdldepends_output = generate_actual_compile_order()

    if args.update:
        EXPECTED_JSON.write_text(json.dumps(actual, indent=2) + "\n")
        print(f"wrote {EXPECTED_JSON}")
        return 0

    if not EXPECTED_JSON.is_file():
        print(f"error: expected JSON file {EXPECTED_JSON} does not exist, create it with --update")
        return 1

    with open(EXPECTED_JSON) as f:
        expected = json.load(f)

    return 0 if compare_compile_order(actual, expected, hdldepends_output, verbose=args.verbose) else 1


def test_compile_order_json():
    """pytest entry point."""
    assert HDLDEPENDS_PY.is_file(), f"cannot find {HDLDEPENDS_PY}"
    assert EXPECTED_JSON.is_file(), f"expected JSON file {EXPECTED_JSON} does not exist"
    with open(EXPECTED_JSON) as f:
        expected = json.load(f)
    actual, hdldepends_output = generate_actual_compile_order()
    assert compare_compile_order(actual, expected, hdldepends_output)


if __name__ == "__main__":
    sys.exit(main())
