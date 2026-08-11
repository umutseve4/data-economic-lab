# Sample data — SYNTHETIC

**These files are not real statistics.** They do not come from TCMB, TÜİK, or the
World Bank. They exist for one reason only: so that `pytest` and GitHub Actions
can run the complete pipeline with **no network access and no API key**.

| File | Series it stands in for | Unit | Rows | Period |
| --- | --- | --- | --- | --- |
| `cpi.csv` | Consumer price index (monthly) | index (2003=100 style) | 72 | 2019-01 … 2024-12 |
| `usdtry.csv` | USD/TRY, monthly average | TRY per USD | 72 | 2019-01 … 2024-12 |
| `policy_rate.csv` | Policy / funding rate (monthly) | percent per annum | 72 | 2019-01 … 2024-12 |

## How they were produced

Deterministically, from a closed-form function of the month index `i`
(`i = 0` for 2019-01). There is no randomness anywhere, so the files are
byte-reproducible:

```
cpi[i]    : level_0 = 400, level_i = level_{i-1} * (1 + r_i)
            r_i = 0.012 + 0.010 * (i / 71) + 0.003 * sin(2*pi*(i mod 12)/12)
usdtry[i] = 5.50 * exp(0.0225 * i + 0.00012 * i^2)
policy[i] = piecewise linear plateaus (see the table below)
```

`policy_rate` segments (`i` = month index):

| `i` range | formula |
| --- | --- |
| 0–11 | `22.0 - 0.9 * i` |
| 12–23 | `11.0 + 0.25 * (i - 12)` |
| 24–35 | `14.0 + 0.05 * (i - 24)` |
| 36–47 | `14.5 - 0.20 * (i - 36)` |
| 48–59 | `12.0 + 2.6 * (i - 48)` |
| 60–71 | `43.0 + 0.55 * (i - 60)` |

The shapes are *loosely* inspired by the real Turkish macro record (rising
inflation, a depreciating lira, a rate-cut episode followed by a sharp
tightening) so that the charts and the correlation table are not degenerate.
**No number here should be quoted as a fact about the Turkish economy.**

## Format

CSV, UTF-8, two comment lines starting with `#`, then a `period,value` header.
`period` is `YYYY-MM`. Missing values would be written as an empty field; the
current files contain none.
