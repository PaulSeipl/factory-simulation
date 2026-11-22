# Changelog

`mes_bridge` only; thesis changes go to `math/protocol.md`. Newest first.

## Unreleased

- Skeleton: own uv project with an editable path dependency on `simulation` (no workspace, so the thesis lock
  stays untouched); test that `src/simulation` never imports `mes_bridge`.
