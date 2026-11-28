"""
지역 차이 심화 3: '사람 많이 다니는 동네' vs '조용한 동네' (탐색적, 코딩 1)
python explore_region3.py → out/1128_동네활성도.xlsx

교수님 예시(건대·홍대 vs 월계동)를 '번화한 동네 vs 조용한 주거 동네'로 읽고, 동네 활성도를 우리가 직접 정의한다.
 1) 동네 활성도 지수 = 세 지표의 주성분(PCA 1축):
      생활인구(유동·거주 인구, 격자 기준, 2026) · 공시지가(땅값 = 상권 수요, 2026) · 100m 음식점 밀도(개업 시점)
    → 5분위(1 조용 ~ 5 번화). 지수 상위 동(洞) 목록으로 '번화가'를 제대로 잡는지 확인.
 2) 주점가 비율 = 개업 시점 250m 안 영업 중 음식점 중 주점류(호프/통닭·정종/대포집/소주방·감성주점·라이브카페) 비율
    → 밤 상권 vs 식사 상권 (원본 전체 연도로 계산, 미래 정보 없음)
 질문 A: 활성도에 따라 기본 폐업률·망한 자리 빈도가 다른가 (기술)
 질문 B: 망한 자리 1회의 위험 크기가 활성도·주점가 비율에 따라 다른가 (X × 분위, Wald)
 질문 C(기제): 번화한 동네에서는 빈 자리가 더 빨리 다시 채워지는가 → 망한 자리가 더 자주 '쌓이는' 이유
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
from explore_region2 import slopes_by  # noqa: E402

OUT = BASE / 'out'
PUBS = ['호프/통닭', '정종/대포집/소주방', '감성주점', '라이브카페']


def pub_share(d):
    raw = pd.read_pickle(OUT / 'raw_parsed.pkl')
    raw = raw[raw['x'].notna() & raw['od'].notna()]
    g = lambda x, y: (np.floor(x / 250)).astype(int).astype(str) + '_' + (np.floor(y / 250)).astype(int).astype(str)
    raw = raw.assign(grid=g(raw['x'], raw['y']), pub=raw['category'].isin(PUBS))
    big = np.datetime64('2100-01-01')
    tabs = {}
    for grid, s in raw.groupby('grid'):
        cd = s['cd'].values.astype('datetime64[D]')
        cd = np.where(np.isnat(cd), big, cd)
        tabs[grid] = (np.sort(s['od'].values.astype('datetime64[D]')), np.sort(cd),
                      np.sort(s.loc[s['pub'], 'od'].values.astype('datetime64[D]')),
                      np.sort(cd[s['pub'].values]))
    out = []
    for grid, od in zip(g(d['x'], d['y']), pd.to_datetime(d['open_date']).values.astype('datetime64[D]')):
        tb = tabs.get(grid)
        if tb is None:
            out.append(np.nan); continue
        t0 = od - np.timedelta64(1, 'D')
        n = np.searchsorted(tb[0], t0, 'right') - np.searchsorted(tb[1], t0, 'right')
        p = np.searchsorted(tb[2], t0, 'right') - np.searchsorted(tb[3], t0, 'right')
        out.append(p / n if n >= 5 else np.nan)          # 음식점 5곳 미만 격자는 비율이 불안정 → 결측
    return np.array(out)


def main():
    t, d, M2 = main_sample()
    need = ['gu', 'dong', 'x', 'y', 'open_date', '생활인구', 'log_공시지가', 'hex_density', 'area_type', 'category']
    d = d.merge(t[['license_id'] + [c for c in need if c not in d]], on='license_id', how='left')
    d['dong_short'] = d['gu'].astype(str) + ' ' + d['dong'].astype(str).str.split().str[-1]
    sheets = {}

    # 1) 활성도 지수
    comp = pd.DataFrame({'log 생활인구': np.log(d['생활인구']), 'log 공시지가': d['log_공시지가'], 'log(1+음식점 밀도)': np.log1p(d['hex_density'])})
    ok = comp.notna().all(axis=1)
    z = (comp[ok] - comp[ok].mean()) / comp[ok].std()
    vals, vecs = np.linalg.eigh(np.cov(z.T.values))
    v = vecs[:, -1] * np.sign(vecs[:, -1].sum())
    d.loc[ok, 'activity'] = z.values @ v
    d['act5'] = pd.qcut(d['activity'].rank(method='first'), 5, labels=['1 조용', '2', '3', '4', '5 번화']).astype(object)
    load = pd.DataFrame({'지표': comp.columns, '주성분 적재값': v, '지표 간 상관 (평균)': z.corr().mean().values,
                         '1축 설명 비율': vals[-1] / vals.sum()})
    sheets['지수 구성'] = load
    top = (d[d['act5'] == '5 번화'].groupby('dong_short').size().sort_values(ascending=False).head(20)
           .rename('번화 5분위 가게 수').reset_index().rename(columns={'dong_short': '동'}))
    low = (d[d['act5'] == '1 조용'].groupby('dong_short').size().sort_values(ascending=False).head(20)
           .rename('조용 1분위 가게 수').reset_index().rename(columns={'dong_short': '동'}))
    sheets['지수 확인 (상·하위 동)'] = pd.concat([top, low], axis=1)
    for nm in ['마포구 서교동', '광진구 화양동', '노원구 월계동']:
        s = d.loc[d['dong_short'] == nm, 'act5']
        print(nm, s.value_counts(normalize=True).round(2).to_dict(), flush=True)

    # 2) 주점가 비율
    d['pub_share'] = pub_share(d)
    d['pub3'] = pd.qcut(d['pub_share'].rank(method='first'), 3, labels=['식사 상권', '중간', '주점가']).astype(object)

    rows = []
    for col, levels, lab in [('act5', ['1 조용', '2', '3', '4', '5 번화'], '동네 활성도 5분위'),
                             ('pub3', ['식사 상권', '중간', '주점가'], '주점가 비율 3분위')]:
        dd = d.dropna(subset=[col]).copy()
        o, w, p = slopes_by(dd, col, levels, M2, ref=levels[0])
        zz = dd['activity'] if col == 'act5' else dd['pub_share']
        dd['zc'] = (zz - zz.mean()) / zz.std()
        dd['X_zc'] = dd['prior_closures'] * dd['zc']
        oc, _, _ = cox(dd, ['prior_closures', 'X_zc'], ['zc'] + M2)
        for i, g in enumerate(levels):
            s = dd[dd[col] == g]
            closed = s[s['event_ours'] == 1]
            rows.append({'나눈 기준': lab, '그룹': g, '1회당 HR': o.iloc[i]['HR'], 'CI_low': o.iloc[i]['CI_low'], 'CI_high': o.iloc[i]['CI_high'],
                         '가게 수': len(s), '3년 안 폐업률': s['dead_3y'].mean(),
                         '이전 폐업 1회 이상 비율': (s['prior_closures'] >= 1).mean(),
                         '발달상권·관광특구 비율': s['area_type'].isin(['발달상권', '관광특구']).mean(),
                         '주점류 가게 비율': s['category'].isin(PUBS).mean(),
                         '기울기 같음 p (Wald)': p, '연속 상호작용 HR (1SD당)': oc.iloc[1]['HR'], '연속 상호작용 p': oc.iloc[1]['p']})
        print(lab, [round(o.iloc[i]['HR'], 3) for i in range(len(levels))], 'Wald p', round(p, 3), 'int', round(oc.iloc[1]['HR'], 3), round(oc.iloc[1]['p'], 3), flush=True)
    sheets['B 위험 크기 (분위별)'] = pd.DataFrame(rows)

    # 3) 기제: 폐업 뒤 다음 가게가 들어오기까지 (계보 기준, 코호트 가게 중 진짜 폐업)
    lin = pd.read_pickle(OUT / 'lineage.pkl')[['관리번호', 'gap_next_days', 'nxt_od', 'cd']]
    m = d[d['event_ours'] == 1].merge(lin, left_on='license_id', right_on='관리번호', how='left')
    cen = pd.Timestamp('2026-11-05')
    m['obs_after'] = (cen - pd.to_datetime(m['cd'])).dt.days
    m = m[m['obs_after'] >= 365]                          # 폐업 뒤 1년 이상 관찰된 경우만
    rows = []
    for g in ['1 조용', '2', '3', '4', '5 번화']:
        s = m[m['act5'] == g]
        refill = s['gap_next_days'].between(0, 365)
        rows.append({'동네 활성도': g, '진짜 폐업 수 (1년 이상 관찰)': len(s),
                     '1년 안에 다음 가게 입점 비율': refill.mean(),
                     '다음 가게까지 일수 (중앙값, 1년 안 입점한 경우)': s.loc[refill, 'gap_next_days'].median(),
                     '다음 가게 없음 (관찰 끝까지 공실·업종 전환)': s['nxt_od'].isna().mean()})
    sheets['C 빈 자리 다시 채워지는 속도'] = pd.DataFrame(rows)
    print(pd.DataFrame(rows).round(3).to_string(), flush=True)

    note = pd.DataFrame({'항목': ['질문', '활성도 지수', '주점가 비율', '모형', '주의'], '내용': [
        '사람 많이 다니는 번화한 동네와 조용한 동네에서 (A) 기본 폐업 수준, (B) 망한 자리 1회의 위험 크기, (C) 빈 자리가 다시 채워지는 속도가 다른가',
        '생활인구·공시지가(2026년 값)와 개업 시점 100m 음식점 밀도를 표준화해 주성분 1축으로 합친 값. 5분위. 「지수 확인」 시트의 상·하위 동으로 타당성 확인',
        '개업 시점 250m 격자 안 영업 중 음식점 중 주점류 비율 (원본 전체 연도로 계산). 음식점 5곳 미만 격자는 제외',
        '주분석 M2 통제, 칸 군집 표준오차, 단일 점포 칸. 분위별 기울기 + 분위 더미, 기울기 같음 Wald 검정 + 연속형 상호작용',
        '생활인구·공시지가는 2026년 값이라 지수는 탐색적. 인과가 아닌 연관.']})
    with pd.ExcelWriter(OUT / '1128_동네활성도.xlsx') as w:
        note.to_excel(w, sheet_name='읽는 법', index=False)
        for k, v in sheets.items():
            v.round(4).to_excel(w, sheet_name=k[:31], index=False)


if __name__ == '__main__':
    main()
