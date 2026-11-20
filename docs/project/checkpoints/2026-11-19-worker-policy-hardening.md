# F05-A / MEL-76: worker preflight policy hardening

Base: #64 at `b03100192544024f56646c91ee560b8857de7e1c`.

Custom policies may narrow but never expand the built-in HTTP loopback host
allowlist, zero-paid-spend requirement, timeout bounds, or 500-node graph limit.
Built-in credential field names cannot be removed by a custom policy.
Malformed ports, authorities, credentials, query/fragment markers and control
characters fail closed; rejected addresses are omitted from emitted receipts.
No probe occurs on rejected requests. Valid local and SSH tunnel endpoints keep
the existing protocol and receipt schema.

Verification: all 11 worker-preflight unittest cases, compileall, and diff check
passed on the isolated checkout. Tests include local mock HTTP protocol checks,
custom-policy bounds, secret-list override and malformed endpoint subcases.
No real GPU worker, inference, device qualification or paid execution performed.

Next: review into #64, then run the approved worker's actual graph/schema
preflight before any live texture qualification.
