# Changelog

All notable changes to `home-assistant-blade-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-06-11

### Fixed
- **AUD-04-01 (critical, DD-385 Phase W):** write tools called with an omitted
  `instance` no longer fan out to every configured site. All 13 mutating tools
  (`ha_call_service`, `ha_light`, `ha_climate`, `ha_scene`, `ha_lock`,
  `ha_alarm`, `ha_automation_trigger`, `ha_automation_toggle`,
  `ha_automation_create`, `ha_automation_delete`, `ha_script_run`,
  `ha_webhook`, `ha_notify`) now route through a combined `_write_gate` that
  REFUSES an omitted `instance` when more than one instance is configured,
  with an error naming the configured instances (DD-343 multi-connection
  convention, as established by ubiquiti-unifi-blade-mcp v0.5.0).
  Single-instance configs keep the ergonomic omit; read/survey tools keep
  their aggregate fan-out behaviour.

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
