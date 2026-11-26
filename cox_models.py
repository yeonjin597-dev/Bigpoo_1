"""
코딩 2 · 본분석 v0: run_cox 함수 + M0~M4 (공시지가·상권영역은 아직 없음 → 들어오면 CONTROLS에 추가)

질문: "같은 칸의 이전 폐업 횟수(X)가 1 높은 가게는 폐업 위험이 몇 배인가?" 통제를 하나씩 늘려 가며 본다.
  M0: X만
  M1: + 가게 특성 (업태, log 면적, 개업 연도, 칸 등장 후 경과 연수)
  M2: + 동네 (100m 육각형 3년 폐업률, 밀도·밀도²)          ※ 공시지가는 코딩 3이 주면 추가
  M3: + 같은 건물 층화 (strata=jibun → 같은 건물 안 가게끼리만 비교)
  M4: + 진입 방식 (같은 업태 승계, log 공실 기간, 첫 입점 여부)
표준오차: 칸(site) 군집 강건 표준오차 (같은 칸 가게들은 서로 독립이 아니므로)
비교 가능성: 모든 모형을 같은 표본(M4 변수까지 결측 없는 가게)에서 추정한다.
원인 분해: (log HR0 − log HRk) / log HR0  (연속형 X 기준)
실행: python cox_models.py  → out/1125_Cox_M0toM4_v0.xlsx
"""
from pathlib import Path
import time
import numpy as np
import pandas as pd
from lifelines import CoxPHFitter

BASE = Path(__file__).resolve().parent
TABLE = BASE / 'out' / 'analysis_table_v1.parquet'
OUT = BASE / 'out' / '1125_Cox_M0toM4_v0.xlsx'


def prepare(t):
    """모형에 넣을 수 있게 변수 가공 (범주 → 더미, 로그, 결측 표시)."""
    d = t.copy()
    top = d['category'].value_counts()
    keep_cat = top[top >= 1000].index
    d['cat'] = d['category'].where(d['category'].isin(keep_cat), '기타(소수업태)')
    d['log_area'] = np.log1p(d['area_m2'].clip(lower=0))
    d['site_age_y'] = d['site_age_days'] / 365.25
    d['hex_density_100'] = d['hex_density'] / 100
    d['hex_density_100_sq'] = d['hex_density_100'] ** 2
    d['first_tenant'] = d['seq'].eq(1).astype(int)
    d['same_cat'] = d['same_cat_successor'].astype('float').fillna(0)
    d['log_vacancy'] = np.log1p(d['vacancy_days'].clip(lower=0)).fillna(0)
    dummies = pd.get_dummies(d[['cat']].astype(str), prefix='cat', drop_first=True, dtype=float)
    years = pd.get_dummies(d['open_year'].astype(str), prefix='yr', drop_first=True, dtype=float)
    pc = pd.get_dummies(d['prior_closures_cat'], prefix='pc', dtype=float).drop(columns='pc_0')
    d = pd.concat([d, dummies, years, pc], axis=1)
    return d, list(dummies.columns), list(years.columns), list(pc.columns)


def run_cox(d, exposure, controls=(), event='event_ours', strata=None, cluster='site'):
    """위험비·95% 신뢰구간·p값·표본 수·사건 수를 돌려준다. 코딩 3도 인자만 바꿔 재사용."""
    cols = ['duration_days', event, cluster] + list(exposure) + list(controls) + ([strata] if strata else [])
    x = d[cols].copy()
    x = x[x['duration_days'] > 0]
    cph = CoxPHFitter(penalizer=0.0)
    cph.fit(x, 'duration_days', event, cluster_col=cluster, strata=strata, robust=True)
    s = cph.summary.loc[list(exposure), ['exp(coef)', 'exp(coef) lower 95%', 'exp(coef) upper 95%', 'p']]
    s.columns = ['HR', 'CI_low', 'CI_high', 'p']
    s['n'] = len(x)
    s['events'] = int(x[event].sum())
    return s, cph


def main():
    t = pd.read_parquet(TABLE)
    d, cat_cols, yr_cols, pc_cols = prepare(t)
    M1 = cat_cols + yr_cols + ['log_area', 'site_age_y']
    M2 = M1 + ['hex_closure_rate_3y', 'hex_density_100', 'hex_density_100_sq']
    M4 = M2 + ['same_cat', 'log_vacancy', 'first_tenant']
    need = ['duration_days', 'event_ours', 'site', 'jibun', 'prior_closures'] + M4 + pc_cols
    d = d.dropna(subset=need)
    n_build = d.groupby('jibun')['site'].transform('size')
    share_m3 = (n_build > 1).mean()                      # M3에서 비교에 기여하는(같은 건물에 2개 이상) 가게 비율
    specs = [('M0', [], None), ('M1', M1, None), ('M2', M2, None), ('M3', M2, 'jibun'), ('M4', M4, 'jibun')]
    cont, cat = [], []
    for name, ctrl, strata in specs:
        t0 = time.time()
        s, _ = run_cox(d, ['prior_closures'], ctrl, strata=strata)
        cont.append(s.assign(model=name))
        s2, _ = run_cox(d, pc_cols, ctrl, strata=strata)
        cat.append(s2.assign(model=name))
        print(name, s.round(4).to_dict('records'), f'{time.time() - t0:.0f}s')
    cont = pd.concat(cont).reset_index(names='변수')
    cat = pd.concat(cat).reset_index(names='변수')
    lhr0 = np.log(cont.loc[cont['model'] == 'M0', 'HR'].iloc[0])
    cont['설명비율_vs_M0'] = (lhr0 - np.log(cont['HR'])) / lhr0
    note = pd.DataFrame({'항목': [
        '표본', 'M3 기여 가게 비율', '표준오차', '공시지가·상권영역', '해석 주의'], '내용': [
        f'2013~2022 개업 코호트 중 M4 변수까지 결측 없는 {len(d):,}곳 (모든 모형 동일 표본)',
        f'{share_m3:.1%} (같은 건물에 가게가 2곳 이상이어야 M3 비교에 기여)',
        '칸(site) 군집 강건 표준오차',
        '아직 없음 → 들어오면 M2에 추가하고 다시 실행 (v1)',
        '"원인"이 아니라 "통제 후 남는 연관". 설명비율은 통제 전후 차이 방식'],
    })
    with pd.ExcelWriter(OUT, engine='openpyxl') as w:
        note.to_excel(w, sheet_name='읽는 법', index=False)
        cont.round(4).to_excel(w, sheet_name='연속형 X (1회당)', index=False)
        cat.round(4).to_excel(w, sheet_name='범주형 X (횟수별)', index=False)
    print(cont.round(4).to_string(index=False))


if __name__ == '__main__':
    main()
