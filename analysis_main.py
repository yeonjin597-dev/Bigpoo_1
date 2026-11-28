"""
본분석 (코딩 2 몫, 코딩 1이 수행) — python analysis_main.py → out/1127_본분석_v1.xlsx (그림은 figures.py, 코딩 2)

표본: 단일 점포 칸(D1, single_unit_site) + M4 변수까지 결측 없는 가게 (모든 모형 같은 표본)
모형: Cox 비례위험 (statsmodels PHReg, Breslow), 칸(site) 군집 강건 표준오차
  M0: X(이전 폐업 횟수)
  M1: + 가게 (업태, 개업 연도, log 면적, 칸 등장 후 경과 연수)
  M2: + 동네 (100m 육각형 직전 3년 폐업률, 밀도, 밀도²)         ← 개업 전 정보만 (D2)
  M3: + 건물 (같은 건물 다른 층의 개업 전 3년 진짜 폐업 수)
  M4: + 진입 (같은 업태 승계, log 공실 일수, 첫 입점 여부)
설계 변경(D5): 원래 M3는 '같은 건물 층화'였으나, 같은 칸을 차례로 거친 가게끼리 비교하게 되어
  "다음 가게가 있다 = 앞 가게가 폐업했다"는 구조 때문에 기계적으로 음(-)의 효과가 나온다(시험 결과 HR 0.38).
  → 건물 영향은 다른 층 이력(개업 전 정보)으로 통제한다.
"""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.stats.multitest import multipletests
import lineage as L
from cox_models import prepare

warnings.filterwarnings('ignore')
BASE = Path(__file__).resolve().parent
OUT = BASE / 'out'


# ───────────── 모형 함수 ─────────────
def cox(d, xvars, ctrl=(), event='event_ours', strata=None, cluster='site'):
    """위험비·95% CI·p·n·사건 수 (칸 군집 강건 SE). 코딩 3도 이 함수로 검증 가능."""
    cols = list(xvars) + list(ctrl)
    x = d.dropna(subset=cols + ['duration_days', event])
    x = x[x['duration_days'] > 0]
    keep = [c for c in ctrl if x[c].astype(float).std() > 0]       # 부분 표본에서 값이 하나뿐인 통제변수 제외
    cols = list(xvars) + keep
    m = PHReg(x['duration_days'].values, x[cols].astype(float).values, status=x[event].astype(int).values,
              strata=(pd.factorize(x[strata])[0] if strata else None), ties='breslow')
    r = m.fit(groups=pd.factorize(x[cluster])[0])
    k = len(xvars)
    ci = np.exp(r.conf_int()[:k])
    out = pd.DataFrame({'변수': list(xvars), 'HR': np.exp(r.params[:k]), 'CI_low': ci[:, 0], 'CI_high': ci[:, 1],
                        'p': r.pvalues[:k], 'n': len(x), 'events': int(x[event].sum())})
    return out, r, x


def breslow_cumhaz(x, beta, cols, event='event_ours'):
    """Breslow 기저 누적위험 H0(t)와 각 가게의 선형예측 η."""
    eta = x[cols].astype(float).values @ beta
    o = np.argsort(x['duration_days'].values)
    t = x['duration_days'].values[o]; e = x[event].values[o].astype(int); w = np.exp(eta[o])
    risk = np.cumsum(w[::-1])[::-1]                      # 시점 t에 위험집합에 있는 exp(η) 합
    ut, idx = np.unique(t, return_index=True)
    dsum = np.add.reduceat(e, idx)
    h = dsum / risk[idx]
    return ut, np.cumsum(h), eta


def H_at(ut, H, tq):
    i = np.searchsorted(ut, tq, side='right') - 1
    return np.where(i >= 0, H[np.clip(i, 0, None)], 0.0)


def area_closure_vars(t_keys, raw_all, lin, keyfun, prefix):
    """동네 단위를 바꿔(250m·500m 정사각 격자, 법정동) 개업 전 3년 폐업률·밀도를 다시 계산.
    lineage.neighborhood_table/add_neighborhood와 같은 규칙, 육각형 대신 keyfun으로 동네를 정한다."""
    a = raw_all[['관리번호', 'od', 'cd', 'x', 'y', 'dong']].copy()
    a['k'] = keyfun(a)
    a = a[a['k'].notna() & a['od'].notna()]
    ev = lin.set_index('관리번호')['event_ours']
    a['real_close'] = a['cd'].notna()
    known = a['관리번호'].isin(ev.index)
    a.loc[known, 'real_close'] = a.loc[known, '관리번호'].map(ev).values
    rows = []
    for yr in range(2007, 2027):
        jan1 = pd.Timestamp(f'{yr}-01-01')
        alive = (a['od'] <= jan1) & (a['cd'].isna() | (a['cd'] > jan1))
        closes = a['real_close'] & (a['cd'].dt.year == yr)
        g = pd.DataFrame({'k': a['k'], 'alive': alive, 'closes': closes}).groupby('k')[['alive', 'closes']].sum()
        g['year'] = yr
        rows.append(g.reset_index())
    nb = pd.concat(rows).set_index(['k', 'year'])
    k = keyfun(t_keys); yr = t_keys['od'].dt.year
    clos = sum(nb['closes'].reindex(list(zip(k, yr - j))).fillna(0).values for j in (1, 2, 3))
    aliv = sum(nb['alive'].reindex(list(zip(k, yr - j))).fillna(0).values for j in (1, 2, 3))
    dens = nb['alive'].reindex(list(zip(k, yr))).fillna(0).values / 100
    out = pd.DataFrame({f'{prefix}_rate': np.where(aliv > 0, clos / np.maximum(aliv, 1), np.nan),
                        f'{prefix}_dens': dens, f'{prefix}_dens_sq': dens ** 2}, index=t_keys.index)
    return out


def grid_key(size):
    return lambda a: np.where(a['x'].notna(), (np.floor(a['x'] / size)).astype('Int64').astype(str) + '_' +
                              (np.floor(a['y'] / size)).astype('Int64').astype(str), None)


def neighborhood_sensitivity(d, M1, lin):
    from fill_coords import apply_common_coords
    raw = pd.read_pickle(OUT / 'raw_parsed.pkl')
    raw = raw[raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')]
    raw = apply_common_coords(raw, L.COORD_IN) if L.COORD_IN.exists() else raw
    tk = d[['license_id', 'x', 'y', 'dong']].copy()
    tk['od'] = pd.to_datetime(d['open_date'])
    rows = []
    for lab, kf, pre in [('D4: 동네 = 250m 정사각 격자', grid_key(250), 'g250'),
                         ('D4: 동네 = 500m 정사각 격자', grid_key(500), 'g500'),
                         ('D4: 동네 = 법정동', lambda a: a['dong'], 'dong')]:
        v = area_closure_vars(tk, raw, lin, kf, pre)
        dd = pd.concat([d, v], axis=1)
        o, _, _ = cox(dd, ['prior_closures'], M1 + list(v.columns))
        rows.append(o.assign(분석=lab))
    return rows


def main():
    res = {}
    t = pd.read_parquet(OUT / 'analysis_table_v2.parquet')
    full, cat_cols, yr_cols, _ = prepare(t)
    full['pc1'] = (full['prior_closures'] == 1).astype(float)
    full['pc2p'] = (full['prior_closures'] >= 2).astype(float)
    M1 = cat_cols + yr_cols + ['log_area', 'site_age_y']
    M2 = M1 + ['hex_closure_rate_3y', 'hex_density_100', 'hex_density_100_sq']
    M3 = M2 + ['other_floor_closures']
    M4 = M3 + ['same_cat', 'log_vacancy']      # 직전 가게가 있는 가게만 (첫 입점 여부는 X=0과 기계적으로 묶여 제외)
    d = full[full['single_unit_site']].dropna(subset=M3 + ['prior_closures', 'duration_days']).copy()
    d = d[d['duration_days'] > 0]
    print('주표본', len(d), '폐업', int(d['event_ours'].sum()))

    # 표본 요약
    s = d['prior_closures'].clip(upper=2)
    res['표본 요약'] = pd.DataFrame({
        '이전 폐업': ['0번', '1번', '2번 이상', '전체'],
        '가게 수': list(s.value_counts().sort_index().values) + [len(d)],
        '진짜 폐업': list(d.groupby(s)['event_ours'].sum().values) + [int(d['event_ours'].sum())],
        '3년 안 폐업률(%)': list((d.groupby(s)['dead_3y'].mean() * 100).round(1).values) + [round(d['dead_3y'].mean() * 100, 1)],
    })

    # RQ1·2: M0~M4
    dp = d[d['first_tenant'] == 0]               # 직전 가게가 있는 가게 (M4용)
    specs = [('M0', [], d), ('M1', M1, d), ('M2', M2, d), ('M3', M3, d),
             ('M3 (직전 가게 있는 가게만, M4 비교용)', M3, dp), ('M4 (직전 가게 있는 가게만)', M4, dp)]
    cont, catr = [], []
    for nm, ctrl, dd in specs:
        o, _, _ = cox(dd, ['prior_closures'], ctrl); cont.append(o.assign(모형=nm))
        o2, _, _ = cox(dd, ['pc1', 'pc2p'], ctrl); catr.append(o2.assign(모형=nm))
        print(nm, o.round(4)[['HR', 'CI_low', 'CI_high']].values.tolist(), flush=True)
    cont = pd.concat(cont); catr = pd.concat(catr)
    l0 = np.log(cont['HR'].iloc[0])
    cont['M0 대비 설명 비율'] = ((l0 - np.log(cont['HR'])) / l0).round(3)
    res['RQ1·2 연속형 (1회당)'] = cont
    res['RQ1 범주형 (0번 대비)'] = catr.replace({'pc1': '1번', 'pc2p': '2번 이상'})

    # RQ3: 실패 정의 3개 (X와 폐업 여부를 같은 정의로 다시 계산)
    lin = pd.read_pickle(OUT / 'lineage.pkl')
    coh = lin[lin['관리번호'].isin(d['license_id'])].copy()
    coh['row'] = np.arange(len(coh))
    rq3 = []
    for k, lab in [('ours', '우리 (60일 안 같은 상호 재입점 = 양도, D9)'), ('days30', '구 규칙 (30일 안 아무 가게 재입점 = 양도)'),
                   ('jari', 'jari (같은 상호 60일 안, 상호 완전 일치)'), ('parsa', 'Parsa (모든 교체 = 폐업)')]:
        coh[f'X_{k}'] = L.count_prior(coh, lin[lin[f'event_{k}']], 'site')
        dd = d.merge(coh[['관리번호', f'X_{k}', f'event_{k}']].rename(columns={'관리번호': 'license_id', f'event_{k}': f'ev_{k}'}), on='license_id')
        dd[f'ev_{k}'] = dd[f'ev_{k}'].astype(int)
        o, _, _ = cox(dd, [f'X_{k}'], M2, event=f'ev_{k}')
        rq3.append(o.assign(정의=lab))
    res['RQ3 정의 비교 (M2)'] = pd.concat(rq3)

    # RQ4: 우리 칸 이력 vs 같은 건물 다른 층 이력 (= M3)
    o, _, _ = cox(d, ['prior_closures', 'other_floor_closures'], M2)
    res['RQ4 우리 칸 vs 다른 층'] = o

    # RQ5: 직전 가게 (직전 가게가 있는 가게만)
    d5 = d[d['first_tenant'] == 0].copy()
    d5['prev_short_f'] = d5['prev_short'].astype(float)
    o, _, _ = cox(d5, ['prior_closures', 'prev_short_f', 'log_vacancy'], M2)
    res['RQ5 직전 가게'] = o.replace({'prev_short_f': '직전 가게 1년 안 폐업', 'log_vacancy': 'log 공실 일수'})

    # RQ8: 지역유형별 기울기 (기준 = 골목상권)
    d8 = d.dropna(subset=['area_rq8']).copy()
    areas = ['골목상권', '발달상권', '상권밖', '전통시장']
    for a in areas:
        d8[f'X_{a}'] = d8['prior_closures'] * (d8['area_rq8'] == a)
        if a != '골목상권':
            d8[f'A_{a}'] = (d8['area_rq8'] == a).astype(float)
    xv = [f'X_{a}' for a in areas]
    o, r8, _ = cox(d8, xv, [f'A_{a}' for a in areas[1:]] + M2)
    k = len(xv)
    b, V = r8.params[:k], r8.cov_params()[:k, :k]
    C = np.array([[1, -1, 0, 0], [1, 0, -1, 0], [1, 0, 0, -1]], float)
    w = float((C @ b) @ np.linalg.solve(C @ V @ C.T, C @ b))
    p_w = 1 - stats.chi2.cdf(w, 3)
    o['지역'] = areas
    o['가게 수'] = [int((d8['area_rq8'] == a).sum()) for a in areas]
    o['이전 폐업 1회 이상'] = [int(((d8['area_rq8'] == a) & (d8['prior_closures'] >= 1)).sum()) for a in areas]
    o['기울기 동일 검정 p (Wald, df=3)'] = round(p_w, 4)
    res['RQ8 지역유형'] = o
    print('RQ8 Wald p', round(p_w, 4))

    # 비례위험 점검: X 효과가 시기별로 같은가 (개업 1년 이내 vs 이후, 에피소드 분할)
    a = d.copy(); a['t0'] = 0; a['t1'] = np.minimum(a['duration_days'], 365); a['ev'] = np.where(a['duration_days'] <= 365, a['event_ours'], 0)
    bb = d[d['duration_days'] > 365].copy(); bb['t0'] = 365; bb['t1'] = bb['duration_days']; bb['ev'] = bb['event_ours']
    ph = []
    for lab, dd in [('개업 1년 이내', a), ('1년 이후 (1년 생존 가게)', bb)]:
        dd = dd.assign(duration_days=dd['t1'] - dd['t0'], event_ours=dd['ev'])
        o, _, _ = cox(dd, ['prior_closures'], M2); ph.append(o.assign(시기=lab))
    res['비례위험 점검 (시기별 HR)'] = pd.concat(ph)

    # ───── 저주 칸: M2 통제(X 제외) 기대 폐업 vs 실제 ─────
    o, rr, xx = cox(d, M2[:1], M2[1:])                  # 통제변수만 (첫 변수를 xvars 자리로)
    ut, H, eta = breslow_cumhaz(xx, rr.params, M2)
    xx = xx.assign(E=H_at(ut, H, xx['duration_days'].values) * np.exp(eta))
    site = xx.groupby('site').agg(O=('event_ours', 'sum'), E=('E', 'sum'), n=('license_id', 'size'))
    site['p'] = stats.poisson.sf(site['O'] - 1, site['E'])
    site['q'] = multipletests(site['p'], method='fdr_bh')[1]
    site['저주칸'] = site['q'] < 0.05
    st = pd.read_parquet(OUT / '1126_칸테이블_v2.parquet').set_index('site')
    site = site.join(st[['jibun', 'floor', 'gu', '격자ID', 'obs_years', 'n_stores', 'n_closures_ours', 'area_type']])
    res['저주 칸 요약'] = pd.DataFrame({'항목': ['검정한 칸', 'FDR 0.05 통과 (저주 칸, 확증)', '보정 전 p<0.05 & 폐업 2번 이상 (탐색적 고위험, RQ7용)',
                                            '실제 폐업 합', '기대 폐업 합 (M2 통제, X 제외)'],
                                     '값': [len(site), int(site['저주칸'].sum()), int(((site['p'] < 0.05) & (site['O'] >= 2)).sum()),
                                           int(site['O'].sum()), round(site['E'].sum(), 1)]})
    print('저주 칸', int(site['저주칸'].sum()), '/', len(site))

    # jari 위험 칸(이전 폐업 2회 이상, jari 정의) 중 저주 칸 비율
    coh['site'] = coh['site'].astype(str)
    jr = coh[coh['X_jari'] >= 2]['site'].unique()
    jr_in = site.index.isin(jr)
    res['jari 오분류'] = pd.DataFrame({'항목': ['jari 기준 위험 칸(이전 폐업 2회 이상)', '그중 FDR 통과 저주 칸', '비율'],
                                    '값': [int(jr_in.sum()), int(site.loc[jr_in, '저주칸'].sum()),
                                          round(site.loc[jr_in, '저주칸'].mean(), 3) if jr_in.sum() else np.nan]})

    # 장수 칸 짝 (같은 250m 격자, 같은 층 구분, 3층 이상 제외, 관찰 5년 이상, 폐업 0번)
    site['floor_cls'] = np.where(site['floor'].astype(str).str.startswith('B'), '지하',
                                 np.where(site['floor'].astype(str) == '1', '1층', np.where(site['floor'].astype(str) == '2', '2층', '3층+')))
    site['탐색적고위험'] = (site['p'] < 0.05) & (site['O'] >= 2)      # RQ7 로드뷰용(탐색적): 보정 전 p<0.05, 폐업 2번 이상
    cur = site[site['탐색적고위험'] & (site['floor_cls'] != '3층+')]
    lng = site[(site['O'] == 0) & (site['obs_years'] >= 5) & (site['floor_cls'] != '3층+') & ~site['탐색적고위험']]
    sc = xx.groupby('site')[['hex_closure_rate_3y', 'log_area']].mean()
    pool = pd.concat([cur.assign(y=1), lng.assign(y=0)]).join(sc)
    pool = pool.dropna(subset=['hex_closure_rate_3y', 'log_area'])
    pairs = []
    if pool['y'].sum() > 0:
        import statsmodels.api as sm
        Xp = pd.get_dummies(pool[['floor_cls']], dtype=float).iloc[:, 1:]
        Xp[['hex', 'area', 'obs']] = pool[['hex_closure_rate_3y', 'log_area', 'obs_years']].values
        lg = sm.Logit(pool['y'], sm.add_constant(Xp)).fit(disp=0)
        pool['lps'] = np.log(lg.predict(sm.add_constant(Xp)) / (1 - lg.predict(sm.add_constant(Xp))))
        cal = 0.2 * pool['lps'].std()
        used = set()
        rng = np.random.default_rng(42)
        for sid in rng.permutation(pool[pool['y'] == 1].index):
            c = pool.loc[sid]
            for level, key in [('같은 250m 격자', '격자ID'), ('같은 구', 'gu')]:
                cand = pool[(pool['y'] == 0) & (pool[key] == c[key]) & (pool['floor_cls'] == c['floor_cls']) & ~pool.index.isin(used)]
                cand = cand[(cand['lps'] - c['lps']).abs() <= cal]
                if len(cand):
                    m = (cand['lps'] - c['lps']).abs().idxmin(); used.add(m)
                    pairs.append({'짝 번호': len(pairs) + 1, '고위험칸': sid, '장수칸': m, '매칭 단위': level,
                                  '층': c['floor_cls'], '로짓 성향점수 차': round(abs(pool.loc[m, 'lps'] - c['lps']), 3)})
                    break
    pairs = pd.DataFrame(pairs)
    print('장수 칸 짝', len(pairs))
    res['장수 칸 짝 요약'] = pd.DataFrame({'항목': ['탐색적 고위험 칸(3층 미만)', '장수 칸 후보', '짝 수', '그중 같은 250m 격자', '캘리퍼(로짓 SD×0.2)', '로드뷰 측정용 (같은 250m 격자 쌍 중 무작위 40쌍, seed 42)'],
                                     '값': [len(cur), len(lng), len(pairs), int((pairs.get('매칭 단위', pd.Series(dtype=str)) == '같은 250m 격자').sum()),
                                           round(cal, 3) if pool['y'].sum() else np.nan,
                                           min(40, int((pairs.get('매칭 단위', pd.Series(dtype=str)) == '같은 250m 격자').sum()))]})

    # ───── 민감도 ─────
    sens = []
    def add(label, dd, ctrl=M2, xv=('prior_closures',), event='event_ours'):
        o, _, _ = cox(dd, list(xv), ctrl, event=event); o = o.iloc[[0]].assign(분석=label); sens.append(o)
    allc = full.dropna(subset=M2 + ['prior_closures'])
    add('주분석: 단일 점포 칸 (D1)', d)
    add('D1 대안: 전체 칸', allc)
    add('D1 대안: 동시 영업 10곳 이상 칸 제외', allc[allc['max_concurrent'] < 10])
    add('D1 대안: 동시 영업 3곳 이상 칸 제외', allc[allc['max_concurrent'] < 3])
    dg = d.copy(); dg['log_pop'] = np.log1p(dg['생활인구'])
    add('D2: + 2026 log 공시지가·log 생활인구', dg, M2 + ['log_공시지가', 'log_pop'])
    add('D2: + 2026 값, 2020~2022 개업만', dg[dg['open_year'] >= 2020], [c for c in M2 if not c.startswith('yr_')] + ['log_공시지가', 'log_pop'])
    # 동네 고정효과(층화)는 칸이 적은 동네에서 같은 칸의 앞뒤 가게 비교가 섞여 M3와 같은 기계적 편향 → 동네 단위별 폐업률 통제로 대신
    sens += neighborhood_sensitivity(d, M1, lin)
    # 양도 기간·이전 폐업 창 바꾸기 (make_kan_table로 X·폐업 재계산, 통제변수는 주분석 값)
    from kan_table import make_kan_table
    raw = pd.read_pickle(OUT / 'raw_parsed.pkl')
    raw = raw[raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')]
    for lab, kw in [('양도: 구 규칙 (30일 안 아무 가게)', dict(transfer_rule='days', transfer_days=30)),
                    ('양도: 같은 상호 30일 안', dict(transfer_days=30)), ('양도: 같은 상호 90일 안', dict(transfer_days=90)),
                    ('양도: 상호 완전 일치만 (60일)', dict(name_match='strict')), ('이전 폐업 창 1년', dict(window_days=365)),
                    ('이전 폐업 창 5년', dict(window_days=1825))]:
        k_ = make_kan_table(raw, already_standardized=True, **kw)
        k_ = k_[['관리번호', '이전폐업수', '폐업여부', '생존기간']].rename(columns={'관리번호': 'license_id'})
        dd = d.drop(columns=['event_ours']).merge(k_, on='license_id')
        dd = dd.assign(prior_closures=dd['이전폐업수'], event_ours=dd['폐업여부'], duration_days=dd['생존기간'])
        add(lab, dd)
    res['민감도 (M2, 1회당 HR)'] = pd.concat(sens)

    # ───── 효과 크기 (예측 생존) ─────
    # 그림은 figures.py (코딩 2)가 이 시트와 아래 예측곡선 시트를 읽어서 그림
    o, r2, x2 = cox(d, ['prior_closures'], M2)
    cols = ['prior_closures'] + M2
    ut, H, _ = breslow_cumhaz(x2, r2.params, cols)
    xbar = x2[cols].astype(float).mean().values
    pred, curve = [], []
    grid_days = np.arange(0, 10 * 365.25 + 1, 30.4375)  # 0~10년, 한 달 간격
    for v in [0, 1, 2]:
        xv = xbar.copy(); xv[0] = v
        risk = np.exp(xv @ r2.params)
        for yrs in [1, 3, 5]:
            pred.append({'이전 폐업': v, '연수': yrs, '예측 생존 확률': round(float(np.exp(-H_at(ut, H, yrs * 365.25) * risk)), 3)})
        for g in grid_days:
            curve.append({'이전 폐업': v, '개업 후 연수': round(g / 365.25, 3), '예측 생존 확률': round(float(np.exp(-H_at(ut, H, g) * risk)), 4)})
    res['효과 크기 (예측 생존)'] = pd.DataFrame(pred).pivot(index='이전 폐업', columns='연수', values='예측 생존 확률').add_prefix('').reset_index()
    res['예측 생존곡선 (M2)'] = pd.DataFrame(curve)

    # ───── 저장 ─────
    note = pd.DataFrame({'항목': ['표본', '모형', '표준오차', 'M3 설계 변경 (D5)', '해석 주의', '재현'], '내용': [
        f'2013~2022 개업 · 단일 점포 칸(D1) · M4 변수 결측 없음: {len(d):,}곳, 진짜 폐업 {int(d["event_ours"].sum()):,}건',
        'Cox 비례위험 (statsmodels PHReg, Breslow). M0 X → M1 가게 → M2 동네(개업 전 정보) → M3 건물(다른 층 이력) → M4 진입',
        '칸(site) 군집 강건 표준오차',
        '같은 건물 층화는 같은 칸의 앞뒤 가게를 비교하게 되어 기계적으로 HR<1(시험 0.38) → 다른 층 이력 통제로 변경. M4는 첫 입점 여부(X=0과 기계적 연동) 대신 직전 가게가 있는 가게만으로 추정',
        '"원인"이 아니라 "통제 후 남는 연관". 설명 비율은 통제 전후 차이 방식',
        'python analysis_main.py (약 10분)']})
    with pd.ExcelWriter(OUT / '1127_본분석_v1.xlsx', engine='openpyxl') as w:
        note.to_excel(w, sheet_name='읽는 법', index=False)
        for k, v in res.items():
            v.round(4).to_excel(w, sheet_name=k[:31], index=False)
    site.reset_index().to_parquet(OUT / '1127_칸별_O_E_저주칸.parquet', index=False)
    if len(pairs):
        # 로드뷰 측정용: 같은 250m 격자 쌍 중 무작위 40쌍 (seed 42), A/B 순서도 무작위 (seed 7) → 측정자 블라인드
        sel = (pairs[pairs['매칭 단위'] == '같은 250m 격자'].sample(min(40, (pairs['매칭 단위'] == '같은 250m 격자').sum()), random_state=42)
               .sort_values('짝 번호').reset_index(drop=True))
        sel['로드뷰 짝 번호'] = np.arange(1, len(sel) + 1)
        with pd.ExcelWriter(OUT / '1127_장수칸짝_정답표_코딩1만.xlsx', engine='openpyxl') as w:
            pairs.to_excel(w, sheet_name='전체 571쌍', index=False)
            sel.to_excel(w, sheet_name='로드뷰 40쌍', index=False)
        blind = []
        rng = np.random.default_rng(7)
        for _, p in sel.iterrows():
            a, b = (p['고위험칸'], p['장수칸']) if rng.random() < .5 else (p['장수칸'], p['고위험칸'])
            for tag, sid in [('A', a), ('B', b)]:
                jb, fl = sid.split('|')
                blind.append({'짝 번호': p['로드뷰 짝 번호'], '칸': tag, '지번주소': jb, '층': fl})
        pd.DataFrame(blind).to_excel(OUT / '1127_로드뷰_짝목록_비코딩2.xlsx', index=False)
    print('done')


if __name__ == '__main__':
    main()
