# Context.dev research ingestion (opt-in)

This tool is a **read-only, standalone research capture**. It does not participate in
Fidelis rendering, model downloads, inference, enhancement, quality scoring or release gates.

## Configure

Use a **server/CLI process only**, not the Studio browser bundle:

```sh
export CONTEXT_DEV_API_KEY="<set privately from Context.dev dashboard>"
python scripts/contextdev-research.py --kind model https://huggingface.co/example/model
```

The CLI also accepts `CONTEXT_API_KEY` as a legacy alias. The key must never be
committed, printed, put in a shared script, or shipped to the editor.

Optional flags: `--kind dataset --images` to collect image URLs without downloading,
`--highlights` for short hardware/license/performance evidence,
`--zdr` if your account supports zero data retention, and `--fresh` to bypass
the 24-hour cache. `--zdr` cannot be combined with `--highlights`.
Use `--out <path>` for a different JSONL file; the default
`.cache/contextdev-research.jsonl` is ignored by Git. Each record keeps the
requested/final URL, retrieval time, format statuses, partial flag and extracted claims.

The tool uses a native `POST https://api.context.dev/v1/web/scrape` request,
20-second per-attempt timeout, 25-second caller budget and at most one retry.
No scheduled scraping or automatic discovery is enabled. Restrict use to manually
approved public URLs. Only request Images for approved dataset pages.
Structured JSON is credit-bearing, and Highlights and Images may add costs.
Browser actions and authenticated pages are deliberately unsupported.

**Evidence policy:** all extracted licenses and benchmarks are unverified
publisher claims. `license_review=pending`,
`rights_cleared_for_benchmark=false` and
`publisher_results_locally_verified=false` are fixed conservative labels.
An extracted result cannot add an asset to a rights-cleared 60-case benchmark
or claim a measured model-quality result. Manual source/license verification
and the existing corpus gates remain required.

## Offline checks

```sh
python -m unittest tests/test_contextdev_research.py -v
```

No live API requests are issued by these tests. A live run consumes account
credits and should only be done with a known source and an approved budget.
