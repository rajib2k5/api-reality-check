# api-reality-check fixture eval

Generated 2026-10-30T06:39:14Z by `eval/run_eval.py`. Target: `./fixtures/.venv/bin/python` (Python 3.12.13; numpy 2.5.4, pandas 3.1.0, requests 2.34.2, yfinance 1.7.0).

Gate: **PASS**

| Verdicts scored | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| MISSING | 62 | 0 | 42 | 1.000 | 0.596 |
| MISSING ∪ SUSPECT | 81 | 5 | 23 | 0.942 | 0.779 |

## Recall of MISSING by category

| Category | TP | FN | Recall |
|---|---|---|---|
| invented_function | 14 | 0 | 1.000 |
| invented_kwarg | 7 | 8 | 0.467 |
| invented_kwarg_on_kwargs_func | 0 | 14 | 0.000 |
| invented_method_on_instance | 2 | 14 | 0.125 |
| misspelled | 16 | 2 | 0.889 |
| removed_in_version | 11 | 4 | 0.733 |
| wrong_module_path | 5 | 0 | 1.000 |
| wrong_place | 7 | 0 | 1.000 |

## Conformance with designed verdicts: 100 / 104

| expected -> actual | labels |
|---|---|
| MISSING->MISSING | 62 |
| SUSPECT->NOT_CHECKED | 1 |
| SUSPECT->SUSPECT | 19 |
| UNKNOWN->NOT_CHECKED | 3 |
| UNKNOWN->UNKNOWN | 19 |

## Labels not matching their designed verdict

- `fixtures/cases/pandas_seeded.py:74` kwarg `fil_method`: expected UNKNOWN, got NOT_CHECKED (None)
- `fixtures/cases/pandas_seeded.py:79` attribute `append`: expected SUSPECT, got NOT_CHECKED (None)
- `fixtures/cases/yfinance_seeded.py:97` attribute `moving_average`: expected UNKNOWN, got NOT_CHECKED (None)
- `fixtures/cases/yfinance_seeded.py:102` attribute `to_list`: expected UNKNOWN, got NOT_CHECKED (None)
