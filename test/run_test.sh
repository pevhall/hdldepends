#!/usr/bin/env bash
#
# Regression test: runs hdldepends on vhdl/hdl_deps_prj.toml with
# --compile-order-json and compares the generated JSON with the expected JSON
# in expected_compile_order.json.
#
#   ./run_test.sh            run the test
#   ./run_test.sh --update   regenerate expected_compile_order.json
#
# Exits non-zero if the generated compile order JSON differs from the expected one.
#
# XILINX_VIVADO is used by vhdl/hdl_deps_prj.toml (xpm / unisim VHDL packages).
# If it is not set, or does not point at a real Vivado install, the test creates
# a minimal stub install in a temporary directory, see test_compile_order_json.py.

cd "$(dirname "$0")" || exit 1

python3 ./test_compile_order_json.py "$@"
