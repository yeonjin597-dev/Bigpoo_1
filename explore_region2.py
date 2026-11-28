"""
지역 차이 심화 2 (탐색적, 코딩 1) — python explore_region2.py → out/1128_지역차이_심화.xlsx (시트 추가)
교수님 피드백 "지역 차이를 변수로(건대·홍대 vs 월계동)"에 대한 추가 분석 세 가지.
 A. 25개 구별 기울기: 구마다 이전 폐업 1회당 HR을 따로 추정 + 기울기 동일 Wald 검정(df=24)
 B. 실제 동네 사례: 홍대(마포구 서교·동교·합정·연남동), 건대(광진구 화양·자양동), 월계동(노원구)
 C. 동네 성장/쇠퇴: 개업 시점 250m 격자 안 영업 중 음식점 수를 3년 전과 비교 → 쇠퇴/정체/성장 3분위
    (선행연구의 성장상권·쇠퇴상권 구분을 우리 데이터로 재현. 원본 전체 연도로 세므로 2010년 이전 개업 가게도 포함, 미래 정보 없음)
모든 모형 = 주분석 M2 통제, 칸 군집 표준오차, 단일 점포 칸 56,224곳.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from analysis_main import cox          # noqa: E402
from sens_short import main_sample     # noqa: E402

OUT = BASE / 'out'
CASES = {'홍대 (마포구 서교·동교·합정·연남동)': ('마포구', ['서교동', '동교동', '합정동', '연남동']),
         '건대 (광진구 화양·자양동)': ('광진구', ['화양동', '자양동']),
         '월계동 (노원구)': ('노원구', ['월계동'])}


def wald_equal(r, k):
    b, V = r.params[:k], r.cov_params()[:k, :k]
    C = np.hstack([np.ones((k - 1, 1)), -np.eye(k - 1)])
    w = float((C @ b) @ np.linalg.solve(C @ V @ C.T, C @ b))
    return w, 1 - stats.chi2.cdf(w, k - 1)


def slopes_by(dd, col, levels, M2, ref):
    xv, ctrl = [], []
    for i, g in enumerate(levels):
        dd[f'X_{i}'] = dd['prior_closures'] * (dd[col] == g)
        xv.append(f'X_{i}')
        if g != ref:
            dd[f'G_{i}'] = (dd[col] == g).astype(float)
            ctrl.append(f'G_{i}')
    o, r, _ = cox(dd, xv, ctrl + M2)
    w, p = wald_equal(r, len(xv))
    o['그룹'] = levels
    return o, w, p


def growth_table(d):
    """개업 시점 250m 격자 안 영업 중 음식점 수: 개업일 vs 3년 전 (원본 전체 연도)."""
    raw = pd.read_pickle(OUT / 'raw_parsed.pkl')
    raw = raw[raw['x'].notna() & raw['od'].notna()]
    g = lambda x, y: (np.floor(x / 250)).astype(int).astype(str) + '_' + (np.floor(y / 250)).astype(int).astype(str)
    raw = raw.assign(grid=g(raw['x'], raw['y']))
    big = pd.Timestamp('2100-01-01')
    ods = raw.groupby('grid')['od'].apply(lambda s: np.sort(s.values.astype('datetime64[D]')))
    cds = raw.assign(cd=raw['cd'].fillna(big)).groupby('grid')['cd'].apply(lambda s: np.sort(s.values.astype('datetime64[D]')))
    dd = d[d['x'].notna()].copy()
    dd['grid'] = g(dd['x'], dd['y'])
    now, past = [], []
    for grid, od in zip(dd['grid'], pd.to_datetime(dd['open_date']).values.astype('datetime64[D]')):
        o, c = ods.get(grid), cds.get(grid)
        if o is None:
            now.append(np.nan); past.append(np.nan); continue
        t0 = od - np.timedelta64(1, 'D')                 # 자기 자신 제외: 개업 전날 기준
        t3 = od - np.timedelta64(1095, 'D')
        now.append(np.searchsorted(o, t0, 'right') - np.searchsorted(c, t0, 'right'))
        past.append(np.searchsorted(o, t3, 'right') - np.searchsorted(c, t3, 'right'))
    dd['n_now'], dd['n_3y'] = now, past
    dd['growth'] = np.log((dd['n_now'] + 1) / (dd['n_3y'] + 1))
    return dd


def main():
    t, d, M2 = main_sample()
    for c in ['gu', 'dong', 'x', 'y', 'open_date']:
        if c not in d:
            d = d.merge(t[['license_id', c]], on='license_id', how='left')
    d['dong_short'] = d['dong'].astype(str).str.split().str[-1]
    sheets = {}

    # A. 구별
    gus = sorted(d['gu'].dropna().unique())
    dd = d.dropna(subset=['gu']).copy()
    o, w, p = slopes_by(dd, 'gu', gus, M2, ref=gus[0])
    o['가게 수'] = [int((dd['gu'] == g).sum()) for g in gus]
    o['이전 폐업 1회 이상'] = [int(((dd['gu'] == g) & (dd['prior_closures'] >= 1)).sum()) for g in gus]
    o['3년 안 폐업률'] = [dd.loc[dd['gu'] == g, 'dead_3y'].mean() for g in gus]
    # 경험적 베이즈 축소: log HR을 전체 평균 쪽으로 (구간 추정치의 잡음 제거)
    lb = np.log(o['HR']); se = (np.log(o['CI_high']) - np.log(o['CI_low'])) / (2 * 1.96)
    mu = np.average(lb, weights=1 / se ** 2)
    tau2 = max(0.0, (np.sum(((lb - mu) / se) ** 2) - (len(lb) - 1)) / (np.sum(1 / se ** 2) - np.sum(1 / se ** 4) / np.sum(1 / se ** 2)))
    o['축소 HR (경험적 베이즈)'] = np.exp(mu + tau2 / (tau2 + se ** 2) * (lb - mu))
    o['기울기 동일 p (Wald, df=24)'] = p
    o['구간 이질성 tau (log HR SD)'] = np.sqrt(tau2)
    sheets['A 구별 기울기'] = o[['그룹', 'HR', 'CI_low', 'CI_high', '축소 HR (경험적 베이즈)', '가게 수', '이전 폐업 1회 이상', '3년 안 폐업률', '기울기 동일 p (Wald, df=24)', '구간 이질성 tau (log HR SD)']].rename(columns={'그룹': '구'})
    print('A gu Wald p', round(p, 4), 'tau', round(np.sqrt(tau2), 4), flush=True)

    # B. 사례 동네
    d['case'] = '그 외 서울'
    for lab, (gu, dongs) in CASES.items():
        d.loc[(d['gu'] == gu) & d['dong_short'].isin(dongs), 'case'] = lab
    levels = ['그 외 서울'] + list(CASES)
    dd = d.copy()
    o, w, p = slopes_by(dd, 'case', levels, M2, ref='그 외 서울')
    o['가게 수'] = [int((dd['case'] == g).sum()) for g in levels]
    o['이전 폐업 1회 이상'] = [int(((dd['case'] == g) & (dd['prior_closures'] >= 1)).sum()) for g in levels]
    o['3년 안 폐업률'] = [dd.loc[dd['case'] == g, 'dead_3y'].mean() for g in levels]
    o['이전 폐업 0회 3년 폐업률'] = [dd.loc[(dd['case'] == g) & (dd['prior_closures'] == 0), 'dead_3y'].mean() for g in levels]
    o['이전 폐업 1회+ 3년 폐업률'] = [dd.loc[(dd['case'] == g) & (dd['prior_closures'] >= 1), 'dead_3y'].mean() for g in levels]
    o['기울기 동일 p (Wald, df=3)'] = p
    sheets['B 사례 동네'] = o[['그룹', 'HR', 'CI_low', 'CI_high', '가게 수', '이전 폐업 1회 이상', '3년 안 폐업률', '이전 폐업 0회 3년 폐업률', '이전 폐업 1회+ 3년 폐업률', '기울기 동일 p (Wald, df=3)']].rename(columns={'그룹': '동네'})
    print('B cases', o[['그룹', 'HR', 'CI_low', 'CI_high']].round(3).values.tolist(), 'p', round(p, 3), flush=True)

    # C. 성장/쇠퇴
    dg = growth_table(d).dropna(subset=['growth'])
    dg['trend'] = pd.qcut(dg['growth'].rank(method='first'), 3, labels=['쇠퇴', '정체', '성장']).astype(str)
    levels = ['쇠퇴', '정체', '성장']
    o, w, p = slopes_by(dg, 'trend', levels, M2, ref='쇠퇴')
    dg['z'] = (dg['growth'] - dg['growth'].mean()) / dg['growth'].std()
    dg['X_z'] = dg['prior_closures'] * dg['z']
    oc, _, _ = cox(dg, ['prior_closures', 'X_z'], ['z'] + M2)
    o['격자 음식점 수 변화 (3년, 중앙값 %)'] = [100 * (np.exp(dg.loc[dg['trend'] == g, 'growth'].median()) - 1) for g in levels]
    o['가게 수'] = [int((dg['trend'] == g).sum()) for g in levels]
    o['3년 안 폐업률'] = [dg.loc[dg['trend'] == g, 'dead_3y'].mean() for g in levels]
    o['이전 폐업 1회 이상 비율'] = [(dg.loc[dg['trend'] == g, 'prior_closures'] >= 1).mean() for g in levels]
    o['기울기 동일 p (Wald, df=2)'] = p
    o['연속 상호작용 HR (성장 1SD당)'] = oc.iloc[1]['HR']
    o['연속 상호작용 p'] = oc.iloc[1]['p']
    sheets['C 성장·쇠퇴 동네'] = o[['그룹', 'HR', 'CI_low', 'CI_high', '격자 음식점 수 변화 (3년, 중앙값 %)', '가게 수', '3년 안 폐업률', '이전 폐업 1회 이상 비율', '기울기 동일 p (Wald, df=2)', '연속 상호작용 HR (성장 1SD당)', '연속 상호작용 p']].rename(columns={'그룹': '동네 추세'})
    print('C trend', o[['그룹', 'HR', 'CI_low', 'CI_high', '격자 음식점 수 변화 (3년, 중앙값 %)', '3년 안 폐업률']].round(3).values.tolist(), 'p', round(p, 3), 'int', round(oc.iloc[1]['HR'], 3), round(oc.iloc[1]['p'], 3), flush=True)

    path = OUT / '1128_지역차이_심화.xlsx'
    old = pd.read_excel(path, sheet_name=None) if path.exists() else {}
    with pd.ExcelWriter(path) as wtr:
        for k, v in old.items():
            if k not in sheets:
                v.to_excel(wtr, sheet_name=k, index=False)
        for k, v in sheets.items():
            v.round(4).to_excel(wtr, sheet_name=k, index=False)


if __name__ == '__main__':
    main()
