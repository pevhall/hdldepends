# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [PEP 440](https://peps.python.org/pep-0440/) for
version identifiers (`.devN` marks a development pre-release).

## [0.3.0.dev1] - 2026-07-18

### Added
- `AnalysisResult.format_compile_order()` returns the human-readable,
  tree-indented compile-order listing as a string, and
  `AnalysisResult.print_compile_order()` prints it -- the same output the CLI
  emits. `AnalysisResult` now retains the underlying `SourceFile` order (a
  non-serialized `source_files` field; `to_dict()` is unchanged). The shared
  rendering logic lives in `output.format_compile_order`.

## [0.3.0.dev0] - 2026-07-18

Opens the 0.3.0 development cycle.

### Fixed
- `analyse(top_file=...)` now parses and adds a top file that is not already
  part of the project (file type inferred from its extension) instead of
  raising "not in the project", so a testbench top level need not be listed in
  the config just to produce a compile order. New
  `config.add_top_file_by_path` / `config.TOP_FILE_EXT_TYPES`; added
  `Resolver.verilog_include_dirs` so an auto-added Verilog top can resolve its
  `` `include `` directives.

## [0.2.0] - 2026-07-11

Major refactor: the monolithic `hdldepends.py` is split into focused modules
(`config`, `model`, `resolver`, `output`, `parsers/`, `vendors/xilinx/`,
`cli`, `api`, ...); `hdldepends.hdldepends` remains as a re-exporting compat
facade so the `hdldepends.hdldepends:hdldepends` console-script entry point
still works.

### Added
- Public Python API: `hdldepends.analyse(config_files, top_entity=..., top_file=..., ...)`
  returns an `AnalysisResult` whose `compile_order` is a JSON-safe list of
  dicts with the same schema as the `compile-order-json` output.
- Unified `-o`/`--output KIND[:SEL=VAL] FILE` flag (repeatable), replacing ten
  separate per-output-kind flags (see Removed).
- `--version` (reports both the package version and the config-schema version).
- Config-driven top selection: `top_entity` / `top_vhdl_file` /
  `top_verilog_file` / `top_x_bd_file` config keys.
- `python -m hdldepends` package entry point.
- Unknown config keys are rejected with a "did you mean" suggestion instead of
  an uncaught `KeyError`.
- `PyYAML` runtime dependency; config validation itself is dependency-free
  plain Python.
- Pytest-based automated test suite (golden CLI snapshots + unit tests), CI
  workflow (ruff + mypy + pytest), and this changelog.

### Changed
- `*_files` and `*_files_glob` unified: every entry in either key is a glob
  pattern (a `!`-prefixed entry excludes, applied serially per lib/@tag);
  previously plain `*_files` entries were literal paths only.
- Sub-configs (`sub`) populate one flat, global index — `ignore_*` settings
  and all discovered files apply project-wide instead of being scoped to the
  declaring config's subtree.
- YAML configs now load end-to-end; a bare config name defaults to `.yaml`
  (was `.toml`).
- An unresolvable instantiation logs a warning and continues instead of
  aborting the run.
- Non-VHDL source files (Verilog, other, `.bd`, `.xci`) report library `work`
  in compile-order/file-list/JSON output (previously the literal text "None").
- The `@tag` on a source file replaces the file type in the text-output type
  column (e.g. `@VHDL2008` prints as `VHDL2008`, not `VHDL@VHDL2008`); the
  JSON output reports the tag separately as `ver_tag`.
- Coefficient/direct-dependency files reached via an XCI (e.g. `.coe`/`.mif`)
  are ordered within the main compile-order walk as `"type": "DIRECT"`
  entries (previously a separate pass emitting `"type": "EXTERNAL"`).
- Numerous parser, resolver, config and vendor-file robustness fixes
  (malformed inputs now produce clean, file-naming errors instead of
  tracebacks; Xilinx tool versions compare numerically; deep dependency
  chains no longer hit `RecursionError`).

### Removed
- Pickle caching entirely, including its flags: `-c`/`--clear-pickle`,
  `--no-pickle`.
- Ten per-output-kind flags, consolidated into `-o`/`--output`:
  `--compile-order`, `--compile-order-path-only` (now `-o compile-order-paths`),
  `--compile-order-type`, `--compile-order-vhdl-lib`, `--compile-order-json`,
  `--file-list`, `--file-list-type`, `--file-list-vhdl-lib`,
  `--ext-file-list`, `--ext-file-list-tag`.
- `--top-file-type`, and with it the ability to use an unregistered file as
  top by naming its type; `--top-file` (kept) still requires the file to
  already be part of the project.
