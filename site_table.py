"""
칸 테이블 (칸 1줄) — 코딩 3 검증(위약·셔플)용 (코딩 1)

입력: out/lineage.pkl (2010년 이후 칸 계보), out/analysis_table_v2.parquet (2013~2022 코호트, 가게 1줄),
      data/1126_외부변수_코딩3.parquet (2010년 이후 가게별 격자ID·area_type 등)
출력: out/1126_칸테이블_v2.parquet (+ 열 설명 xlsx)

칸 = 지번 + 층. 한 칸에 2010년 이후 들어온 가게들을 모아 폐업·양도 수를 센다.
가게 단위 '이전 폐업 횟수(prior_closures)'는 개업일 기준 값이라 analysis_table_v1에 있고,
여기서는 칸 단위로 요약(코호트 가게들의 평균·최댓값)해서 붙인다.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import lineage as L
from merge_external import max_concurrent, EXT

BASE = Path(__file__).resolve().parent
OUT = BASE / 'out'


def mode(s):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else pd.NA


def build_site_table():
    lin = pd.read_pickle(OUT / 'lineage.pkl')
    t = pd.read_parquet(OUT / 'analysis_table_v2.parquet')
    ext = pd.read_parquet(EXT)
    censor = max(lin['od'].max(), lin['cd'].max())

    g = lin.groupby('site')
    st = pd.DataFrame({
        'jibun': g['jibun'].first(),
        'floor': g['floor'].first(),
        'floor_range_any': g['floor_range'].agg(lambda s: bool(s.fillna(False).any())),
        'gu': g['gu'].first(),
        'dong': g['dong'].first(),
        'x': g['x'].median(),
        'y': g['y'].median(),
        'coord_src': g['coord_src'].agg(mode),
        'n_stores': g.size(),
        'n_closures_ours': g['event_ours'].sum(),
        'n_transfers': g['transfer'].sum(),
        'n_closures_jari': g['event_jari'].sum(),
        'n_closures_parsa': g['event_parsa'].sum(),
        'first_open': g['od'].min(),
        'last_open': g['od'].max(),
        'open_now': g['cd'].agg(lambda s: bool(s.isna().iloc[-1])),
        'multi_tenant': g['multi_tenant'].first(),
    })
    st['obs_years'] = ((censor - st['first_open']).dt.days / 365.25).round(2)
    st['closures_per_year'] = (st['n_closures_ours'] / st['obs_years'].replace(0, np.nan)).round(4)

    st['hex_id'] = L.hex_ids(st['x'], st['y'])

    st['n_sites_same_building'] = st.groupby('jibun')['jibun'].transform('size')
    oth = st.groupby('jibun')['n_closures_ours'].transform('sum') - st['n_closures_ours']
    st['other_floor_closures_total'] = oth

    st = st.join(max_concurrent(lin))
    e = lin[['관리번호', 'site']].merge(ext, on='관리번호', how='left')
    e.loc[e['공시지가'] <= 0, 'log_공시지가'] = np.nan
    eg = e.groupby('site')
    st['격자ID'] = eg['격자ID'].agg(mode)
    st['area_type'] = eg['area_type'].agg(mode)
    st['상권_코드'] = eg['상권_코드'].agg(mode)
    st['log_공시지가'] = eg['log_공시지가'].median()
    st['생활인구'] = eg['생활인구'].median()

    c = t.groupby('site').agg(cohort_n=('license_id', 'size'),
                              cohort_closures=('event_ours', 'sum'),
                              cohort_prior_mean=('prior_closures', 'mean'),
                              cohort_prior_max=('prior_closures', 'max'),
                              cohort_dead_3y=('dead_3y', 'mean'))
    st = st.join(c, how='left')
    st['cohort_n'] = st['cohort_n'].fillna(0).astype(int)
    st = st.reset_index()
    return st, censor


DESC = [
    ('site', '칸 ID = 지번|층', 'Site ID = lot|floor'),
    ('jibun / floor', '지번, 층 (B1=지하1층)', 'Lot address, floor'),
    ('floor_range_any', '이 칸 가게 중 여러 층 표기(가장 낮은 층 사용)가 있었나', 'Any store listed several floors'),
    ('gu / dong', '구, 법정동 (셔플 단위)', 'District, legal dong (shuffle unit)'),
    ('x / y / coord_src', '칸 좌표(가게 좌표 중앙값, EPSG:5174), 출처(코딩 3 공통 파일 기준 최빈값)', 'Site coordinates, source'),
    ('hex_id', '칸 좌표의 100m 육각형 ID', '100 m hexagon of site coordinates'),
    ('n_stores', '2010년 이후 이 칸에 들어온 가게 수', 'Stores since 2010'),
    ('n_closures_ours', '진짜 폐업 수 (30일 안 재입점 = 양도는 제외)', 'Real closures (transfers excluded)'),
    ('n_transfers', '양도 수', 'Transfers'),
    ('n_closures_jari / parsa', '비교용 정의의 폐업 수', 'Closures under jari / Parsa definitions'),
    ('first_open / last_open', '첫 / 마지막 가게 개업일', 'First / last opening date'),
    ('open_now', '마지막 가게가 지금 영업 중인가', 'Last store still open'),
    ('multi_tenant', '가게가 겹친 적 있는 칸 (한 층 여러 가게 의심)', 'Ever overlapping stores'),
    ('obs_years', '첫 개업 ~ 관찰 종료일(2026-11-05) 연수', 'Years observed'),
    ('closures_per_year', '연간 진짜 폐업 수', 'Real closures per year'),
    ('n_sites_same_building', '같은 지번(건물)의 칸 수', 'Sites in the same building'),
    ('other_floor_closures_total', '같은 건물 다른 칸들의 진짜 폐업 합 (위약 검증용)', 'Real closures in other sites of the building (placebo)'),
    ('cohort_n', '2013~2022 개업 코호트 가게 수 (분석 대상)', 'Cohort stores (2013-2022 openings)'),
    ('cohort_closures', '코호트 가게의 진짜 폐업 수', 'Real closures among cohort stores'),
    ('cohort_prior_mean / max', '코호트 가게들의 이전 폐업 횟수(개업 직전 3년) 평균 / 최댓값', 'Mean / max prior closures of cohort stores'),
    ('cohort_dead_3y', '코호트 가게의 3년 안 폐업 비율', '3-year closure share of cohort stores'),
    ('max_concurrent', '같은 날 동시에 영업한 가게 수의 최댓값 (3 이상 = 한 층 여러 가게: 푸드코트·복합몰 의심)', 'Max stores open on the same day (multi-unit floor if >= 3)'),
    ('격자ID / area_type / 상권_코드', '코딩 3 외부변수의 칸별 최빈값 (250m 격자, 지역유형, 상권)', 'Mode of coding-3 external vars per site'),
    ('log_공시지가 / 생활인구', '칸 가게들의 중앙값 (2026년 값 고정)', 'Median per site (2026 values)'),
]

if __name__ == '__main__':
    st, censor = build_site_table()
    st.to_parquet(OUT / '1126_칸테이블_v2.parquet', index=False)
    pd.DataFrame(DESC, columns=['column', '설명', 'description (EN)']).to_excel(OUT / '1126_칸테이블_열설명.xlsx', index=False)
    print(len(st), 'sites | censor', censor.date())
    print(st[['n_stores', 'n_closures_ours', 'n_transfers', 'cohort_n']].describe().round(2))
    print(st['coord_src'].value_counts(dropna=False).to_dict())
