#!/usr/bin/env python3
"""Use hdldepends as a Python library instead of the CLI.

Run it from anywhere:

    python examples/python_api/analyse_example.py

It resolves the small VHDL project in this directory with
``hdldepends.analyse`` and shows what the API gives you:

1. a human-readable compile order -- the same tree-indented text the CLI
   prints -- via ``AnalysisResult.print_compile_order()``;
2. the machine-readable, JSON-safe compile order (``compile_order`` / a list of
   plain dicts, and ``to_dict()``);
3. pointing the analysis at a testbench that is NOT in the config: the API adds
   it on the fly (``top_file``), so simulation-only files need not be listed.
"""

import json
from pathlib import Path

import hdldepends

# This example is self-contained: resolve paths relative to THIS file so it runs
# the same regardless of the current working directory. `work_dir` is what
# relative config paths (and a relative `top_file`) are anchored to.
HERE = Path(__file__).resolve().parent
CONFIG = "hdldeps.yaml"           # relative to work_dir (HERE) below
TESTBENCH = "sim/counter_tb.vhd"  # deliberately NOT listed in hdldeps.yaml


def banner(text: str) -> None:
    print("\n" + "=" * 64)
    print(text)
    print("=" * 64)


def main() -> None:
    # 1. Resolve using the config's own top (top_entity: counter).
    result = hdldepends.analyse(CONFIG, work_dir=HERE)

    banner("1. Compile order for the config's top (entity `counter`)")
    # print_compile_order() writes the same tree-indented listing as the CLI.
    result.print_compile_order()

    # 2. The same result, machine-readable. `compile_order` is a list of plain
    #    dicts (JSON-safe); `to_dict()` wraps it as {"files": [...]}.
    banner("2. Machine-readable compile order (JSON)")
    print(json.dumps(result.to_dict(), indent=2))

    # ...or just pull out the ordered file paths:
    print("\nOrdered paths:")
    for entry in result.compile_order:
        print(f"  {entry['path']}")

    # 3. Point the analysis at a simulation testbench that is NOT in the config.
    #    `top_file` adds it to the project on the fly (its file type inferred
    #    from the extension) and uses it as the top -- so the compile order now
    #    ends at the testbench and pulls its dependencies (counter, counter_pkg)
    #    in ahead of it.
    banner("3. Testbench top via `top_file` (auto-added, not in the config)")
    tb_result = hdldepends.analyse(CONFIG, work_dir=HERE, top_file=TESTBENCH)

    # format_compile_order() returns the listing as a string, so you can log it,
    # write it to a file, diff it, etc. Here we simply print it.
    listing = tb_result.format_compile_order()
    print(listing)


if __name__ == "__main__":
    main()
