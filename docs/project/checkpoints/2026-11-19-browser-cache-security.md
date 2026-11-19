# Legacy local UI cache and rendering security

Base: PR #64, commit `b03100192544024f56646c91ee560b8857de7e1c`.

## Confirmed defects

- The cached-result routes canonicalized arbitrary IDs to a basename and compared resolved paths using a string prefix. A symlink into a sibling directory with the same prefix could serve that directory's file. Both `/api/view` and `/api/download` reproduced this defect in a temporary HTTP test fixture.
- A download filename containing CRLF injected an additional HTTP response header.
- Comparison labels were interpolated into HTML, and response-supplied navigation URLs were assigned directly to links and windows.

## Changes

- Require bounded opaque IDs, reject symlinks, and require a regular PNG-named file directly inside the resolved cache directory.
- Allow only bounded, safe ASCII download names; use a default PNG filename otherwise. Encode generated query strings and send `nosniff`.
- Construct labels with text nodes, restrict navigation to the exact local result/report routes, require PNG data URLs, and remove raw data URL window navigation.

## Verification

The actual HTTP tests reproduce the path alias, sibling symlink and header injection failures before remediation. After remediation, both routes still serve valid cache IDs, unsafe IDs return 404, valid filenames are retained, and injected headers are absent. The Node interaction suite verifies literal comparison text, local result URLs and PNG data URL restrictions.

This is an isolated review branch, not a claim that every outstanding Codacy finding has been resolved. No deployment, paid processing or device access is needed for these regression tests.
