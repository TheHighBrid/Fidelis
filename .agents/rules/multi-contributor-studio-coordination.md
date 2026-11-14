# Multi-Contributor Studio Coordination & Provenance Verification

1. **Additive Branch Unification**:
   - Before merging or cherry-picking isolated `work/mel-*` branches onto `feat/region-aware-studio`, inspect `git log origin/feat/region-aware-studio` to identify modules landed by concurrent contributors (e.g., `SOL 6.1`).
   - Preserve upstream module names, function signatures, and HTTP routes (`fidelis/studio/structure.py`, `fidelis/studio/png.py`, `fidelis/studio/batch.py`, `fidelis/studio/segformer.py`), and keep `REQUIRED_ARCHIVE_PATHS` in `fidelis/studio/packaging.py` synchronized with all tracked Studio modules.
2. **Programmatic Runtime & Weight Provenance**:
   - Every runtime binary and model weight cited in an audition report (`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`, `docs/SEGFORMER_B0_AUDITION.md`) must be verified via `.venv/bin/python scripts/audit-model-provenance.py` (`local=matched`) before recording its SHA-256 digest and byte size.
