# Coding 2 — Tasks

> **Status (Nov 27 night):** Tasks 1–5 were completed by Coding 1. The Check numbers are from v1 (30-day transfer rule); after the rule change (D9) see `docs/결과요약_1127.md`.


Hi! Coding 1 built the data pipeline and ran the main Cox models (`analysis_main.py`).
Your part is **checking the results, describing the data, drawing all figures, and scoring the transfer judgments**.

| # | Task | Output file | Time | Deadline |
| --- | --- | --- | --- | --- |
| 1 | Reproduce the main results | message to Coding 1 | 30 min (mostly waiting) | Fri (Sat at the latest) |
| 2 | Check `n` / `events` in every table | message to Coding 1 | 15 min | Fri (Sat at the latest) |
| 3 | Presentation tables | `out/1127_발표표_coding2.xlsx` | 1 h | Fri (Sat at the latest) |
| 4 | Descriptive notebook | `notebooks/02_descriptive_coding2.ipynb` | 2–3 h | Fri (Sat at the latest) |
| 5 | All result figures | `figures.py` → `out/fig_*.png` | 2–3 h | Fri (Sat at the latest) |
| 6 | Transfer-judgment scoring | `score_transfer.py` → `out/1127_양도판정_채점.xlsx` | 2 h | when Coding 1 sends the files |

**Deadline:** Tasks 1–5 by Friday; if you are busy, Saturday 18:00 at the latest. Task 6 after Coding 1 sends the files.

Each task has a **"Check"** box: numbers your result must match. If it does not match, that is fine —
just send Coding 1 the number you got and we look together.

**Rules for everyone**
- Never commit files in `data/`, `*.parquet`, `*.pkl`, `sheets/` (`.gitignore` already blocks them).
- Store names (상호) and addresses must not appear in figures, notebooks you push, or slides. Show 구 (district) level at most.
- Write "association after controls", never "cause".

---

## Uploading to GitHub
Push your own work to the team repo yourself (the commit history shows who did what).
Upload **only**: `out/1127_발표표_coding2.xlsx`, `notebooks/02_descriptive_coding2.ipynb`, `figures.py`, `out/fig_*.png`, `score_transfer.py`.
- git: `git checkout -b coding2` → `git add <files>` → `git commit -m "coding2: task N"` → `git push origin coding2` → open a Pull Request.
- Web: `Add file → Upload files`. **`.gitignore` does not work for web uploads**, so never drag `data/`, `*.parquet`, `*.pkl`, `sheets/` or the key file.
- Before pushing the notebook, make sure no output shows `name`, `jibun`, `license_id`, `x`, `y` (do not print rows with `.head()` / `.sample()`).

---

## Setup (once)
1. Unzip the folder Coding 1 sends you, open it in VS Code.
2. Terminal:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Mac: source .venv/bin/activate
   pip install -r requirements.txt
   pip install lifelines          # needed for Task 4 (Kaplan–Meier)
   ```
3. Put the 4 data files Coding 1 sends you into `data/` (names in README.md, section 2).
4. Run once: `python lineage.py --fresh`, then `python merge_external.py`, then `python site_table.py`.

**Korean font for figures** (put at the top of `figures.py` and the notebook):
```python
import matplotlib.pyplot as plt
from matplotlib import font_manager
for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic']:
    if any(f == z.name for z in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = f; break
plt.rcParams['axes.unicode_minus'] = False
```

---

## Task 1 — Reproduce the main results
1. Rename Coding 1's file `out/1127_본분석_v1.xlsx` to `out/1127_본분석_v1_coding1.xlsx`.
2. Run `python analysis_main.py` (about 30 minutes).
3. Open both Excel files. For every sheet, check that the numbers are **identical**.
4. Report: "All sheets identical" or the list of sheets/cells that differ.

## Task 2 — Check that every table reports sample size and events
In `out/1127_본분석_v1.xlsx`, every results sheet must have columns `n` and `events`
(except: 읽는 법, 표본 요약, 저주 칸 요약, jari 오분류, 장수 칸 짝 요약, 효과 크기, 예측 생존곡선).
Report any sheet where they are missing or where `n` looks strange (much smaller than 56,224 without a reason in the sheet name).

## Task 3 — Presentation tables
Make `out/1127_발표표_coding2.xlsx` with three small tables, numbers rounded to 2 decimals:

| Table | Source sheet | Columns to keep |
| --- | --- | --- |
| A. Main result | `RQ1·2 연속형 (1회당)` | 모형, HR, CI_low, CI_high, p, n, events |
| B. Definitions | `RQ3 정의 비교 (M2)` | 정의, HR, CI_low, CI_high, n, events |
| C. Robustness | `민감도 (M2, 1회당 HR)` | 분석, HR, CI_low, CI_high, n |

Add one column "HR (95% CI)" formatted like `1.20 (1.13–1.27)`. Write p-values smaller than 0.001 as `<0.001`.

> **Check:** Table A, row M2 = `1.20 (1.13–1.27)`, n = 56,224, events = 25,229.

---

## Task 4 — Descriptive notebook (`notebooks/02_descriptive_coding2.ipynb`)
Goal: show the professor the **raw data → sample → simple pattern** before any model.
Input: `out/analysis_table_v2.parquet` (one row = one store, 2013–2022 openings).

Useful columns:

| Column | Meaning |
| --- | --- |
| `prior_closures` | real closures at the same site (lot + floor) in the 3 years before this store opened |
| `prior_closures_cat` | same, as text: `'0'`, `'1'`, `'2'`, `'3'`, `'4+'` |
| `duration_days`, `event_ours` | survival time and real closure (1) / still open or transferred (0) |
| `dead_3y` | closed (real closure) within 3 years: 1/0 |
| `single_unit_site` | True = only one store on that floor at a time (main sample, decision D1) |
| `gu`, `open_year`, `area_rq8`, `category` | district, opening year, area type (골목/발달/상권밖/전통시장), food type |

Sections:
1. **Sample flow** (a table): all openings → `single_unit_site == True` → no missing values in the M4 controls.
   Use the sheet `표본 요약` for the last number.
2. **3-year closure rate by `prior_closures_cat`**: (a) on the full table, (b) on the main sample (`single_unit_site`).
   Table with count and rate (%), plus a bar chart.
3. **Kaplan–Meier curves** on the main sample, 3 groups: 0 / 1 / 2+ prior closures (`lifelines.KaplanMeierFitter`).
   x-axis = years since opening (0–10), y-axis = share still open. Add a **log-rank test** (`lifelines.statistics.multivariate_logrank_test`) and print the p-value.
4. **By opening year**: 3-year closure rate by `open_year` (2013–2022) and the share of stores with ≥ 1 prior closure.
   Note: stores opened 2022 have a shorter follow-up, so only `dead_3y` is fair for all years.
5. **By area type** (`area_rq8`): count, share with ≥ 1 prior closure, 3-year closure rate.
6. **By district** (`gu`): the same table for the 25 districts, sorted by 3-year closure rate. **No store names, no addresses.**
7. A short "what we see" markdown cell at the end (3–5 bullet points, numbers only, no "cause").

> **Check:**
> - Full table: 111,484 stores; main sample 57,842; complete-case 56,224 (25,229 real closures).
> - 3-year closure rate, full table: 0 → 23.6%, 1 → 29.1%, 2 → 33.2%, 3 → 35.9%, 4+ → 50.8%.
> - 3-year closure rate, main sample (complete-case): 0 → 21.3%, 1 → 25.0%, 2+ → 30.3%.
> - `area_rq8` counts (full table): 발달상권 45,616 / 골목상권 35,280 / 상권밖 20,145 / 전통시장 9,578 / missing 865.

---

## Task 5 — All result figures (`figures.py`)
Write one script that reads `out/1127_본분석_v1.xlsx` and saves the figures below into `out/` (dpi 160).
It must **not** rerun any model, only read the Excel file. Run: `python figures.py`.

| File | Source sheet | What to draw |
| --- | --- | --- |
| `fig_위험비_M0toM4.png` | `RQ1·2 연속형 (1회당)` | forest plot: one row per model (`모형`), point = HR, line = CI_low–CI_high, dashed vertical line at 1 |
| `fig_위험비_민감도.png` | `민감도 (M2, 1회당 HR)` | same forest plot, one row per `분석`; mark the first row (main analysis) in a different color |
| `fig_범주형_HR.png` | `RQ1 범주형 (0번 대비)` | HR of "1번" and "2번 이상" for each model (grouped points with CI) |
| `fig_예측생존곡선_M2.png` | `예측 생존곡선 (M2)` | step lines, x = `개업 후 연수`, y = `예측 생존 확률`, one line per `이전 폐업` (0/1/2) |
| `fig_효과크기_5년.png` | `효과 크기 (예측 생존)` | bar chart of 1-, 3-, 5-year predicted survival for 0/1/2 prior closures (this is the professor's "how much does the result change when the variable changes" figure) |
| `fig_지역유형_HR.png` | `RQ8 지역유형` | forest plot per `지역`, with the Wald p-value (`기울기 동일 검정 p`) written in the title |

Tips:
- A forest-plot helper: `ax.errorbar(hr, y, xerr=[hr - lo, hi - hr], fmt='o', capsize=3)` and `ax.axvline(1, ls='--')`.
- Write the axis label as `이전 폐업 1회당 위험비 (95% CI)`.
- Titles should say the finding in plain words, for example "통제를 늘려도 위험비는 1보다 큼".

> **Check:** M0toM4 has 6 rows (M0, M1, M2, M3, M3 subset, M4) and every point is to the right of 1.
> Predicted 5-year survival: 0 → 0.650, 1 → 0.597, 2 → 0.538.
> 지역유형 title shows p = 0.40.

---

## Task 6 — Transfer-judgment scoring (`score_transfer.py`)
**Start only after Coding 1 sends you the files** (after 비코딩 2 has finished; the key file must not reach the judges).

Background: when a store closes and a new one opens in the same site, the computer calls it a **transfer (양도)** if the gap is ≤ 30 days.
Two non-coding members checked a sample by hand. You measure how often the computer rule agrees with the humans.

Run: `python score_transfer.py <judge1.xlsx> [<judge2.xlsx>]`

Inputs:

| File | Sheet / columns |
| --- | --- |
| judge file(s) `1124b_양도판정_비코딩N_완료.xlsx` | sheet `판정`: `구분` (본인/교차), `번호`, `A. 업태(하는 장사) 이어짐`, `B. 상호·간판 이어짐`, `C. 로드뷰`, `최종 판정`, `메모` |
| key `sheets/1124_양도판정385_정답_코딩1만.xlsx` | `번호`, `묶음` (A/B/C), `간격_일`, `코드_판정` (computer verdict) |

Groups: A = gap 0–30 days (computer says 양도), B = 31–90 days and C = 91–365 days (computer says 폐업후새가게).
Population sizes for weighting: **A 19,806 / B 3,610 / C 5,227**.

The judging rule (re-apply it to check each judge):
```
if B == '예':                         -> '양도'
if B == '아니오' and A == '아니오':     -> '폐업후새가게'
if B == '아니오' and A == '예':        -> '양도' if C == '이어짐', '폐업후새가게' if C == '끊김', else '판단불가'
otherwise                             -> '판단불가'
```

Output `out/1127_양도판정_채점.xlsx`, one sheet each:
1. **Score per group** (use only rows with `구분 != '교차'`, drop `판단불가`): judged rows, 판단불가 count, agree count, agreement rate, **Wilson 95% CI** (`statsmodels.stats.proportion.proportion_confint(k, n, method='wilson')`), share the human called 양도.
   Last row = overall agreement **weighted by the population sizes** above.
2. **Rule compliance per judge**: share of rows where `최종 판정` equals the re-applied rule; count of 로드뷰 이어짐/끊김 and 사진없음.
3. **Rows where the judge differs from the rule** (for checking).
4. **Misclassification rate per group** = 1 − agreement (Coding 1 uses this for a simulation).
5. **Agreement between the two judges** (only if 2 files): the 25 `교차` rows of one judge vs the same `번호` judged by the other → simple agreement and **Cohen's κ** (write the formula yourself: κ = (p_o − p_e) / (1 − p_e)).
6. **Extra:** the same score table, but with the alternative rule "transfer = gap ≤ 60 days AND B == '예'" (Coding 1 is considering this rule).

> **Check (비코딩 1 file only):** A 9/50 = 18.0% (CI 9.8–30.8%), B 51/56 = 91.1%, C 43/45 = 95.6%, weighted ≈ 41.4%, rule compliance 100% (193/193).

---

## Glossary
| Korean | English |
| --- | --- |
| 칸 | site = lot number (지번) + floor |
| 이전 폐업 횟수 (prior_closures) | number of real closures at the same site in the 3 years before opening |
| 진짜 폐업 (event_ours) | closure that is not a transfer |
| 양도 | transfer: the business continues under a new owner, not a real closure |
| 모형 M0~M4 | models with more and more controls (none → store → neighborhood → building → previous store) |
| 위험비 HR | hazard ratio: 1.20 = 20% higher closure risk per one more prior closure |
| 민감도 | robustness check: change one rule and see if the result stays |
| 예측 생존 확률 | predicted probability the store is still open, other variables at their average |

Thank you! Ask Coding 1 anytime.
