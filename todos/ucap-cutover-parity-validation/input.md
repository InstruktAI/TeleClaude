# Input: ucap-cutover-parity-validation

Parent:

- `unified-client-adapter-pipeline`

Objective:

- Execute shadow/cutover for unified adapter pipeline.
- Validate cross-client parity and enforce rollback criteria before full bypass retirement.

Context:

- Depends on `ucap-web-adapter-alignment`, `ucap-tui-adapter-alignment`, and `ucap-ingress-provisioning-harmonization`.
