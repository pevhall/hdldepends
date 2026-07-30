# Python API example (`hdldepends.analyse`)

Most examples drive `hdldepends` from the command line. This one uses it as a
**Python library**: [`analyse_example.py`](analyse_example.py) imports
`hdldepends` and calls `hdldepends.analyse(...)`, which returns the compile
order in-process (no output files written) as an `AnalysisResult`.

It shows the three things the API gives you:

1. **A human-readable compile order** — `AnalysisResult.print_compile_order()`
   prints the same tree-indented listing the CLI does, and
   `format_compile_order()` returns it as a string (to log, write, or diff).
2. **A machine-readable compile order** — `result.compile_order` is a list of
   plain, JSON-safe dicts, and `result.to_dict()` wraps it as `{"files": [...]}`.
3. **Auto-added testbench tops** — pointing `analyse` at a `top_file` that is
   *not* in the config adds it on the fly, so simulation-only files need not be
   listed just to get a compile order.

## Layout

```
hdldeps.yaml          config: RTL only (the testbench is intentionally omitted)
analyse_example.py    the Python API walkthrough
rtl/
  counter_pkg.vhd     package  (work)
  counter.vhd         entity, uses work.counter_pkg   (work)
sim/
  counter_tb.vhd      testbench, instantiates work.counter  (NOT in the config)
```

## Run it

From the repository root (with `hdldepends` importable — e.g. after
`pip install -e .`):

```sh
python examples/python_api/analyse_example.py
```

The script anchors every path to its own directory, so the working directory
you launch it from does not matter.

## What it demonstrates

### 1. Compile order for the config's top (`top_entity: counter`)

```python
result = hdldepends.analyse("hdldeps.yaml", work_dir=HERE)
result.print_compile_order()
```

```
compile order:
  VHDL:          |---work: .../rtl/counter_pkg.vhd
  VHDL:          work: .../rtl/counter.vhd
```

`counter` uses `work.counter_pkg`, so the package is emitted first and indented
one level below the top.

### 2. The same result, machine-readable

```python
result.compile_order        # -> list[dict], JSON-safe
result.to_dict()            # -> {"files": [...]}
[e["path"] for e in result.compile_order]   # just the ordered paths
```

```json
{
  "files": [
    { "type": "VHDL", "library": "work", "path": ".../rtl/counter_pkg.vhd" },
    { "type": "VHDL", "library": "work", "path": ".../rtl/counter.vhd", "is_top": true }
  ]
}
```

`is_top` marks the last (top) entry. When a config uses `ext_files`, those
appear first as `{"type": "EXTERNAL", ...}` entries.

### 3. Testbench top via `top_file` (auto-added)

```python
tb = hdldepends.analyse("hdldeps.yaml", work_dir=HERE, top_file="sim/counter_tb.vhd")
print(tb.format_compile_order())
```

`sim/counter_tb.vhd` is not in `hdldeps.yaml`; `analyse` parses and adds it (its
type inferred from the `.vhd` extension), uses it as the top, and resolves its
dependencies against the project:

```
compile order:
  VHDL:          |---|---work: .../rtl/counter_pkg.vhd
  VHDL:          |---work: .../rtl/counter.vhd
  VHDL:          work: .../sim/counter_tb.vhd
```

## API reference

```python
hdldepends.analyse(
    config_files,          # a path, or a sequence of them (TOML / JSON / YAML)
    *,
    top_entity=None,       # top-level entity/module name
    top_file=None,         # top-level file; auto-added if not already in project
    top_lib=None,          # default VHDL library (defaults to "work")
    x_tool_version=None,   # Xilinx tool version (.bd/.xci variant selection)
    x_device=None,         # Xilinx device (.bd/.xci variant selection)
    work_dir=None,         # anchor for relative config paths / top_file
) -> AnalysisResult
```

Top-selection precedence matches the CLI: `top_file` > `top_entity` > the
config's `top_*_file` > the config's `top_entity`.

`AnalysisResult`:

| Member                    | Description                                            |
| ------------------------- | ------------------------------------------------------ |
| `compile_order`           | `list[dict]` — JSON-safe, EXTERNAL entries first       |
| `to_dict()`               | `{"files": compile_order}`                             |
| `format_compile_order()`  | `str` — the tree-indented listing the CLI prints       |
| `print_compile_order()`   | prints `format_compile_order()` to stdout              |
