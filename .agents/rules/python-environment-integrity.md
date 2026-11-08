---
trigger: always_on
description: Enforce virtual environment Python resolution across all tests, scripts, and subprocesses.
---

# Python Environment Integrity Guardrails

In macOS and custom development environments, the system Python (`/usr/bin/env python3` or bare `python3`) often lacks project-specific virtual environment dependencies (e.g., `PIL`, `numpy`, `torch`, `cv2`).

## Mandatory Rules:
1. **Always Use Active `.venv`**:
   - In shell scripts and tests, resolve the Python binary via:
     ```bash
     python_bin="$repo_root/.venv/bin/python"
     ```
   - Never invoke bare `python3` or `/usr/bin/env python3` when `.venv` exists.
2. **Heredoc & Wrapper Execution with Spaces in Paths**:
   - In shell scripts generating executable wrappers or mock runners via heredocs, do NOT place `$python_bin` directly in the `#!` shebang line if directory paths contain spaces.
   - Use a portable bash wrapper pattern:
     ```bash
     cat > "$wrapper" <<SH
     #!/usr/bin/env bash
     exec "$python_bin" - "\$@" <<'PY'
     # python code here
     PY
     SH
     ```
3. **Subprocess Invocations in Python**:
   - Always spawn subprocesses using `sys.executable`, never hardcoded string `"python3"`.
4. **Graceful Fallbacks for System Python**:
   - In test fixtures or libraries, lazily import heavy scientific dependencies (`numpy`, `torch`, `PIL`) or provide fallback mock structures when running in minimal environments.
