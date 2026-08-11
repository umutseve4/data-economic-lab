# data-economic-lab — Milestone 1

A small, reproducible pipeline: ingest → validate → store → analyze → report.

## 1. Problem statement

This project ingests three Turkish monthly macroeconomic series (consumer prices,
the USD/TRY exchange rate and the central bank policy rate), validates them against
explicit structural rules, stores them in a local SQLite database with a stable
schema, and produces a small set of descriptive outputs: year-over-year change, a
rolling three-month mean, and a correlation table computed on the overlapping period
only. It is a data-engineering exercise, not a forecasting or causal-inference
exercise.

## 2. Data source, series codes, date range

Primary source: TCMB EVDS API (`https://evds2.tcmb.gov.tr/service/evds`). The API key
is read from the `EVDS_API_KEY` environment variable and appears nowhere in the source,
tests, logs or this README.

| name | series code | unit | aggregation |
|---|---|---|---|
| `cpi` | `TP.FG.J0` | index (2003=100) | last |
| `usdtry` | `TP.DK.USD.A.YTL` | TRY per USD | avg |
| `policy_rate` | `TP.APIFON4` | percent per annum | avg |

Default date range: `2019-01-01` .. `2024-12-01` (72 monthly observations per series).

**Status of these series codes: `not implemented` (unverified).** They were written
from documentation and were *not* confirmed against the live EVDS catalogue, because
the build environment had no network access. Verify each code before trusting a live
run. Each one can be overridden without touching the code:
`ECOLAB_SERIES_CPI`, `ECOLAB_SERIES_USDTRY`, `ECOLAB_SERIES_POLICY_RATE`.

`data/sample/` is **synthetic**, deterministic data produced by a closed-form formula
(documented in `data/sample/README.md`). It exists only so that tests and CI run with
no network and no credentials. It is not real TCMB data and must not be presented as
such.

## 3. Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env      # then edit .env — never commit it
export EVDS_API_KEY=...   # only needed for --source evds
```

Configuration is entirely environment-driven. All variables are optional; defaults shown.

| variable | default | meaning |
|---|---|---|
| `ECOLAB_DATA_DIR` | `data` | root for `raw/`, `sample/`, the database |
| `ECOLAB_SOURCE` | `sample` | `sample` (offline CSV) or `evds` (live API) |
| `ECOLAB_DB_PATH` | `data/economic.db` | SQLite file |
| `ECOLAB_REPORT_DIR` | `reports` | report and figures output |
| `ECOLAB_START` | `2019-01-01` | first period (ISO date) |
| `ECOLAB_END` | `2024-12-01` | last period (ISO date) |
| `ECOLAB_LOG_LEVEL` | `INFO` | stdlib logging level |
| `ECOLAB_HTTP_TIMEOUT` | `30` | seconds |
| `ECOLAB_MAX_RETRIES` | `3` | retry attempts on transient failures |
| `ECOLAB_BACKOFF_BASE` | `1.0` | seconds; delay = base · 2^(attempt−1) |
| `ECOLAB_EVDS_BASE_URL` | `https://evds2.tcmb.gov.tr/service/evds` | API base |

## 4. Usage

One CLI, four commands:

```bash
python -m ecolab validate     # structural checks only, no writes
python -m ecolab ingest       # fetch/load -> validate -> SQLite (idempotent)
python -m ecolab analyze      # YoY, rolling 3-month mean, correlation
python -m ecolab report       # reports/report.md + reports/figures/*.png
```

### `validate` — `verified end-to-end`

```
$ ECOLAB_SOURCE=sample python -m ecolab validate
OK cpi          code=TP.FG.J0             rows=  72 missing=0 range=2019-01..2024-12
OK usdtry       code=TP.DK.USD.A.YTL      rows=  72 missing=0 range=2019-01..2024-12
OK policy_rate  code=TP.APIFON4           rows=  72 missing=0 range=2019-01..2024-12
Validation passed for all series.
```

### `ingest` — `verified end-to-end` (with `--source sample`)

```
$ ECOLAB_SOURCE=sample python -m ecolab ingest
cpi          code=TP.FG.J0             rows=  72 missing=0 range=2019-01..2024-12
usdtry       code=TP.DK.USD.A.YTL      rows=  72 missing=0 range=2019-01..2024-12
policy_rate  code=TP.APIFON4           rows=  72 missing=0 range=2019-01..2024-12
Database: data/economic.db
Rows written this run: 216
Total rows in database: 216
```

Running it a second time prints the same `Total rows in database: 216`. Idempotency is
enforced by the primary key `(series_code, period)` and an upsert, and is covered by a
dedicated test.

### `analyze` — `verified end-to-end`

```
$ ECOLAB_SOURCE=sample python -m ecolab analyze
== Coverage (levels) ==
cpi          range=2019-01..2024-12 n=72 missing=0
usdtry       range=2019-01..2024-12 n=72 missing=0
policy_rate  range=2019-01..2024-12 n=72 missing=0

== Year-over-year change (%), last 6 rows ==
               cpi  usdtry  policy_rate
period
2024-07-01  27.599  55.706       67.754
2024-08-01  27.812  56.155       55.132
2024-09-01  28.024  56.605       44.512
2024-10-01  28.236  57.057       35.452
2024-11-01  28.449  57.510       27.632
2024-12-01  28.662  57.964       20.813

== Rolling 3-month mean (levels), last 6 rows ==
                 cpi  usdtry  policy_rate
period
2024-07-01  1196.267  39.441        45.75
2024-08-01  1221.720  40.978        46.30
2024-09-01  1246.220  42.585        46.85
2024-10-01  1270.153  44.266        47.40
2024-11-01  1294.270  46.024        47.95
2024-12-01  1319.513  47.863        48.50

== Correlation (levels, overlapping period only) ==
overlap range = 2019-01..2024-12, n_obs = 72
                cpi  usdtry  policy_rate
cpi          1.0000  0.9926       0.8541
usdtry       0.9926  1.0000       0.8962
policy_rate  0.8541  0.8962       1.0000

Correlation is not causation.
```

### `report` — `verified end-to-end`

```
$ ECOLAB_SOURCE=sample python -m ecolab report
Wrote reports/report.md
Figures in reports/figures
```

Exit codes: `0` success, `1` generic error, `2` configuration error, `3` validation
failure, `4` ingestion failure.

## 5. Architecture

```
  ingest.py    ->   validate.py   ->    store.py    ->   analyze.py   ->   report.py
  EVDS API          schema check        SQLite            YoY %             report.md
  or sample CSV     duplicate dates     upsert on         rolling 3m        PNG figures
  retry+backoff     monotonic index     (series_code,     correlation       titles, units,
  cache to          gap > 1 period       period)          on overlap        source line
  data/raw/         parse errors        idempotent        n_obs reported

                        all orchestrated by cli.py  (the only module allowed to print)
```

SQLite schema:

```sql
CREATE TABLE observations (
    series_code TEXT NOT NULL,
    period      DATE NOT NULL,
    value       REAL,
    unit        TEXT NOT NULL,
    source      TEXT NOT NULL,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (series_code, period)
);
```

## 6. Testing

```bash
pytest --cov=ecolab --cov-report=term-missing --cov-branch
```

62 tests. Every module in `src/ecolab` has at least one test:

| test file | tests | covers |
|---|---|---|
| `test_ingest.py` | 15 | ingest.py |
| `test_config.py` | 13 | config.py, errors.py |
| `test_validate.py` | 10 | validate.py (each failure mode individually) |
| `test_analyze.py` | 7 | analyze.py (YoY on a hand-written fixture) |
| `test_cli.py` | 7 | cli.py, `__main__.py` (end-to-end, sample only) |
| `test_store.py` | 6 | store.py (idempotency) |
| `test_report.py` | 4 | report.py |

**Measured coverage: `not implemented`.** `pytest-cov` could not be installed in the
build environment, so no coverage percentage was measured. No number is claimed here.
Run the command above to obtain one.

**How the suite was executed: `unit tested`, not under real pytest.** `pytest` itself
could not be installed in the build environment. The 62 tests were executed with a
minimal in-house runner implementing the subset of the pytest API the suite uses
(fixtures, `tmp_path`, `monkeypatch`, `capsys`, `raises`, `approx`); the result was
`62 passed, 0 failed`. That is not equivalent to a real pytest run. Treat the suite as
verified only after `pytest` has been run on a normal machine.

**CI status: `not implemented`.** The GitHub Actions workflow in
`.github/workflows/ci.yml` has never been executed. `ruff`, `mypy` and `pytest` could
not be installed in the build environment, so lint, format and type errors may surface
on the first run. A green badge is not claimed here.

## 7. Results

Figures written by `report`:

- `reports/figures/cpi_level.png`
- `reports/figures/usdtry_level.png`
- `reports/figures/policy_rate_level.png`
- `reports/figures/yoy_comparison.png`

Every chart carries a title, axis labels with units, and a source line. `reports/` is
gitignored, so neither `report.md` nor the PNG files are committed; run
`ECOLAB_SOURCE=sample python -m ecolab report` to regenerate them.

On the sample period 2019-01..2024-12 (n = 72) the level correlations are
cpi–usdtry 0.9926, cpi–policy_rate 0.8541, usdtry–policy_rate 0.8962. Correlations this
high between levels are largely an artefact of three trending series sharing a common
time trend, so on their own they say very little. The year-over-year panel is the more
informative view: it shows the three series moving in the same broad direction with a
lag rather than in lockstep. Because `data/sample/` is synthetic, none of these numbers
carry economic meaning — they demonstrate that the pipeline computes, aligns and
reports correctly, and nothing beyond that.

## 8. Known limitations

- Correlation is not causation. No identification strategy is used anywhere.
- Revisions to official statistics are not handled; a later download silently
  overwrites an earlier value for the same `(series_code, period)`.
- The inflation series is not seasonally adjusted.
- The sample period (72 months) is short for any statistical inference.
- Year-over-year change is applied uniformly, including to `policy_rate`. For a rate
  series a percentage-point difference would be the more meaningful transform.
- Correlations are computed on levels, not on stationary transforms.
- Only complete cases enter the correlation. Missing values are reported explicitly and
  are never filled.
- Monthly aggregation (`last` vs `avg`) is declared per series but is applied to data
  that already arrives monthly; it is not exercised on higher-frequency input.

## 9. What this project does NOT do

No dashboard, no web API, no machine-learning model, no forecasting, no seasonal
adjustment, no causal inference, no multi-source reconciliation, no scheduler or
orchestrator, no cloud deployment, no alerting.

## 10. License

MIT — see [`LICENSE`](LICENSE).
