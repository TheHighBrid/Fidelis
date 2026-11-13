# Fidelis master exports

## Reblend aligned source passes

```bash
.venv/bin/python scripts/reblend-regions.py base.png texture.png master.png \
  --masks masks.npz --profile luxury_apparel
```

| Input | Handling |
| --- | --- |
| RGB8 or RGB16 sRGB PNG | Retains the highest sample depth by default |
| Straight-alpha RGBA base | Copies all alpha samples and retains base RGB where alpha is zero |
| 8-bit RGB profile embedded in PNG | Requires `--convert-icc` for conversion through Little CMS to sRGB |
| 16-bit PNG with an embedded profile | Requires external colour-managed conversion to sRGB before import |
| Non-normalized orientation or differing grids | Rejected before composition |

The protected regions retain the base samples in the sRGB working space. An 8-bit
sample expanded to 16 bits maps to its exact normalized value. The 16-bit result
can retain fractional blend precision from the linear-light compositor. Source
and model detail still depend on their input samples. If an ICC conversion is
requested, the protected samples come from the converted base. The unsigned
recipe records both input depths, any profile conversions, alpha handling and
the verified output hash. Each export is decoded and checked against the computed
pixel array before publication.

Studio's browser editor and ComfyUI transport use RGB8 inputs. The editor's
**Download 16-bit PNG** option recomputes the saved masks and blend at higher
precision in stripes, preserving locked pixels at their exact normalized
values. Save changes before downloading. The rendering requires temporary disk
space within the configured Studio budget. Use the CLI for alpha, ICC conversion
or 16-bit inputs. The CLI loads the full pass into memory.
Measure peak memory on the target machine before using large 16-bit jobs in production.

## Export a group of saved Studio jobs

Create a JSON array using each saved job ID and revision as reported by
`GET /api/regions/jobs` on the local Studio service.

```json
[
  {"job_id":"replace-with-saved-job-id","revision":1,"filename":"lookbook-01.png"}
]
```

```bash
.venv/bin/python scripts/export-studio-batch.py batch.json deliverables \
  --workspace .cache/web_outputs/region_jobs --output-budget-mib 2048
```

Use a dedicated output directory on a local Linux or macOS filesystem that
supports hard links. The command streams one saved master at a time. It stops at
the first error and preserves completed items. Rerun the same recipe to verify and
reuse completed PNGs. Existing mismatched files, stale pending revisions and
insufficient output space fail with an explicit error. If interrupted between PNG
and receipt publication, the command can finish publication while the same saved
revision remains available. A process killed during staging can leave a temporary
directory that counts as disk usage until removed. This batch path exports saved
masters and performs zero inference.
