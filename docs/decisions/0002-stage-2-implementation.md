# ADR 0002 — v0.1 implementation refinements

Date: 2026-09-20. Status: accepted technical decisions under owner authorization.

The approved scope is implemented with the following bounded refinements:

- Shared wire contracts live in models/__init__.py; providers and generators remain
  separate modules. Avoid empty re-export modules solely to match the initial diagram.
- Use independent published morphing equations. PsychroLib/pvlib are not required
  dependencies and no reviewed third-party weather-generator code was copied.
- ACCESS-CM2 r1i1p1f1 is the verified default seven-variable monthly intersection.
  Enforce a 3 GB conservative decoded-byte budget; callers can explicitly adjust
  it for larger requests. Preserve original and effective WCRP data licenses.
- Native OEDI noleap calendars are explicit even for leap-labeled source years.
  Preserve their original row years and EPW calendar marker; do not invent Feb 29.
- Historical offsets must align to provider hours. Fractional-hour interpolation
  is deferred; reject it before requesting data instead of silently shifting energy.
  Owner decision 2026-10-12: where the service chooses the offset (the location review
  of chat, the agent and MCP), it uses the point's time zone and rounds a fractional
  standard offset to the nearer whole hour (a tie to the hour nearer mean solar time),
  naming the civil offset in the review. An explicit fractional offset is still refused.
  Owner decision 2026-10-27 (availability follow-ups, Q7): the tie rule stays, although it gives
  Mumbai +5 and Kolkata +6 inside one civil zone (+5:30); it is documented, not changed.
- NSRDB native TMY/TDY/TGY support supplements the planned actual-year adapter.
  Preserve the native timezone and mixed source years.
- REST remote mode requires a bearer token. MCP HTTP binds only to loopback;
  authenticated remote MCP is deferred, with stdio and REST available now.
- SQLite/filesystem jobs support a single process per data root, item checkpointing,
  checksum validation and cooperative cancellation. Distributed coordination is
  outside the approved lightweight scope.
- Raw caches are committed only after successful decoding. Runtime credentials
  and signed CDS result URLs are not persisted. Artifact and plan path inputs are
  constrained, and future scenario/window constraints are rechecked at execution.

These decisions do not add human approval gates. Outstanding operational and
scientific limits are collected in [limitations](../limitations.md); actual
validation is in [acceptance](../validation/v0.1-acceptance.md).
