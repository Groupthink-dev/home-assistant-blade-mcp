# Changelog

All notable changes to `home-assistant-blade-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-05-24

### Changed
- DD-338 Phase E.python: depend on `stallari-mcp-helpers>=0.1.0,<1.0.0`; deleted
  local `src/ha_blade_mcp/domain_hint.py` and the `_append_meta` helper in
  `src/ha_blade_mcp/formatters.py`. `Pattern` + `load_patterns_from_yaml` now
  import from the canonical package. `compute_domain_hint(record, patterns,
  projector)` is preserved as a thin wrapper in `server.py` because HA's
  `_field_projector` synthesises logical fields (`entity_namespace` from
  `entity_id`) that the canonical dot-path resolver doesn't natively cover —
  the wrapper pre-projects field values into a flat dict before delegating to
  the canonical helper.
- Wire-shape: `_meta.filtered_by` now alphabetically sorted (previously
  caller-order preserved); JSON separators tightened from `(", ", ": ")` to
  `(",", ":")`; `_meta.redactions: []` and `_meta.next_cursor: null` are now
  always emitted by the canonical builder (the "absent when empty" semantic
  is gone). Assembler regex `\n\n_meta: (\{.*\})$` still matches.
