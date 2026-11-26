"""품질 수치표 + 변수 설명표 (코딩 1 결과물)"""
from pathlib import Path
import pandas as pd
import lineage as L
from fill_coords import fill_coordinates

OUT_DIR = Path(__file__).resolve().parent / 'out'
from fill_coords import apply_common_coords
raw = pd.read_pickle(OUT_DIR / 'raw_parsed.pkl')
raw = raw[raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')]
raw = apply_common_coords(raw, L.COORD_IN) if L.COORD_IN.exists() else fill_coordinates(raw, L.SBIZ_IN)
lin = pd.read_pickle(OUT_DIR / 'lineage.pkl')
t = pd.read_parquet(OUT_DIR / 'analysis_table_v1.parquet')
r10 = raw[raw['od'] >= '2010-01-01']

pct = lambda x: round(100 * float(x), 1)
overlap_all = (lin['gap_next_days'] < 0).sum() / len(lin)
overlap_pair = (lin['gap_next_days'] < 0).sum() / lin['gap_next_days'].notna().sum()
summary = pd.DataFrame([
    ['원본 행 수', len(raw), '다운로드본 기준'],
    ['원본 마지막 날짜 (중도절단 기준일)', str(max(raw['od'].max(), raw['cd'].max()).date()), '인허가일·폐업일 중 최댓값'],
    ['지번 파싱률 (전체, %)', pct(raw['jibun'].notna().mean()), ''],
    ['층 보유율 (전체, %)', pct(raw['floor'].notna().mean()), '옛날 기록일수록 층 표기가 적음'],
    ['층 보유율 (2010년 이후, %)', pct(r10['floor'].notna().mean()), ''],
    ['  층 출처: 지번주소 (%)', pct((r10['floor_src'].astype(object) == 'jibun').mean()), '2010년 이후 전체 대비'],
    ['  층 출처: 도로명주소 (%)', pct((r10['floor_src'].astype(object) == 'road').mean()), ''],
    ['범위·복수 층 표기 비율 (2010년 이후, %)', pct(r10['floor_range'].mean()), '가장 낮은 층을 칸으로 사용'],
    ['칸 계보 가게 수 (2010년 이후, 지번+층 있음)', len(lin), ''],
    ['칸 수', lin['site'].nunique(), ''],
    ['폐업 중 양도(30일 안 재입점) 비율 (%)', pct(lin['transfer'].sum() / lin['cd'].notna().sum()), ''],
    ['겹침: 다음 가게가 앞 가게 폐업 전에 개업 (전체 가게 대비, %)', pct(overlap_all), '파일럿 18.6%와 같은 정의'],
    ['겹침: 위와 같음 (폐업 후 다음 가게가 있는 쌍 대비, %)', pct(overlap_pair), '겹침 기간 중앙값 657일 → 한 층에 가게 여럿'],
    ['한 번이라도 겹친 적 있는 칸의 가게 비율 (코호트, %)', pct(t['multi_tenant'].mean()), 'multi_tenant 열. 민감도 분석에서 제외 대상'],
    ['분석 코호트 (2013~2022 개업)', len(t), ''],
    ['코호트 원본 좌표 결측 (%)', pct((t['coord_src'] != '원본').mean()), '채우기 전'],
    ['  같은 지번 좌표로 채움 (%)', pct((t['coord_src'] == '같은지번').mean()), 'fill_coords.py 1단계'],
    ['  상가정보 지번 좌표로 채움 (%)', pct((t['coord_src'] == '상가정보').mean()), '2단계 (WGS84 → EPSG:5174)'],
    ['코호트 최종 좌표 결측 (%)', pct((t['coord_src'] == '결측').mean()), '동네 변수 결측'],
], columns=['항목', '값', '비고'])

by_gu = r10.groupby('gu')['floor'].apply(lambda s: pct(s.isna().mean())).rename('층 결측(%)').reset_index()
by_gu['가게 수'] = r10.groupby('gu').size().values
coord_gu = r10.groupby('gu')['coord_src'].apply(lambda s: pct((s != '원본').mean())).rename('원본 좌표 결측(%)').reset_index()
coord_gu['채운 뒤 결측(%)'] = r10.groupby('gu')['coord_src'].apply(lambda s: pct((s == '결측').mean())).values
coord_year = r10.groupby(r10['od'].dt.year)['coord_src'].apply(lambda s: pct((s != '원본').mean())).rename('원본 좌표 결측(%)').reset_index().rename(columns={'od': '개업 연도'})
by_year = r10.groupby(r10['od'].dt.year)['floor'].apply(lambda s: pct(s.isna().mean())).rename('층 결측(%)').reset_index().rename(columns={'od': '개업 연도'})

s = t['prior_closures'].clip(upper=2)
rows = []
for k, lab in [('ours', '우리: 30일 안 같은 칸 재입점 = 양도'), ('jari', 'jari: 같은 상호 60일 안 = 계속'), ('parsa', 'Parsa: 모든 교체 = 실패')]:
    d3 = (t[f'event_{k}'] == 1) & (t['duration_days'] <= 1095)
    r = d3.groupby(s).mean()
    rows.append([lab, pct(r[0]), pct(r[1]), pct(r[2]), round(r[2] / r[0], 2)])
defs = pd.DataFrame(rows, columns=['실패 정의', '이전 폐업 0번 (%)', '1번 (%)', '2번 이상 (%)', '2번 이상 / 0번'])
dose = t.groupby(t['prior_closures'].clip(upper=4))['dead_3y'].agg(['size', 'mean']).reset_index()
dose.columns = ['이전 폐업 횟수 (4=4번 이상)', '가게 수', '3년 안 폐업률']
dose['3년 안 폐업률'] = (dose['3년 안 폐업률'] * 100).round(1)
note = pd.DataFrame([['파일럿(11/22) 값', '0/1/2번 이상 = 23.9 / 29.5 / 41.9%, 1.75배 (Parsa 1.54, jari 1.56)'],
                     ['차이 이유', '층 파싱 규칙 보완(호수를 층으로 읽던 오류 수정, 범위 표기는 가장 낮은 층), 원본은 같음']],
                    columns=['항목', '내용'])

DICT = [
    ('license_id', '관리번호', 'License ID (unique per store registration)', '-'),
    ('site', '칸 ID = 지번|층', 'Site ID = lot address | floor', '-'),
    ('jibun', '지번 주소', 'Lot-number address (building)', '-'),
    ('floor', '층 (B1=지하1층)', 'Floor (B1 = basement 1)', '-'),
    ('floor_range', '여러 층 표기였는지', 'Address listed several floors (lowest used)', 'bool'),
    ('floor_src', '층을 찾은 주소 (jibun/road)', 'Address field the floor came from', '-'),
    ('gu', '구', 'District (gu)', '-'),
    ('dong', '법정동 (셔플 검증 동네 단위)', 'Legal dong (unit for within-neighborhood shuffle)', '-'),
    ('hex_id', '100m 육각형 동네 ID', '100 m hexagon neighborhood ID', '-'),
    ('x / y', '좌표 (EPSG:5174, 결측은 채운 값)', 'Coordinates in EPSG:5174 (imputed where missing)', 'm'),
    ('coord_src', '좌표 출처: 원본 / 같은지번 / 상가정보 / 결측 (코딩 3 공통 파일)', 'Coordinate source', '-'),
    ('open_date / close_date', '개업일 / 폐업일', 'Open / close date', 'date'),
    ('name', '상호 (공백 제거)', 'Store name (spaces removed)', '-'),
    ('category', '업태', 'Business category', '-'),
    ('area_m2', '면적', 'Floor area', '㎡'),
    ('open_year', '개업 연도', 'Opening year', 'year'),
    ('seq', '이 칸의 몇 번째 가게인지 (2010년 이후 기준)', 'Order of this store in the site (since 2010)', 'count'),
    ('multi_tenant', '이 칸에서 가게가 겹친 적 있음 (한 층 여러 가게 의심)', 'Site ever had overlapping stores', 'bool'),
    ('prior_closures', '★ 개업 직전 3년 안 같은 칸의 진짜 폐업 수 (다른 상호)', '★ Real closures in the same site in the 3 years before opening (other names)', 'count'),
    ('prior_closures_cat', '위 값을 0/1/2/3/4+로', 'Same, grouped 0/1/2/3/4+', '-'),
    ('other_floor_closures', '같은 건물 다른 층의 진짜 폐업 수 (직전 3년)', 'Real closures on other floors of the same building (3 years)', 'count'),
    ('prev_tenure_days', '바로 앞 가게의 영업 일수', 'Tenure of the previous store', 'days'),
    ('prev_short', '바로 앞 가게가 1년 안에 끝났나', 'Previous store lasted < 1 year', 'bool'),
    ('vacancy_days', '앞 가게 폐업 → 내 개업까지 (음수 = 겹침)', 'Days from previous closure to this opening (negative = overlap)', 'days'),
    ('same_cat_successor', '앞 가게와 업태가 같은가', 'Same category as previous store', 'bool'),
    ('site_age_days', '칸이 처음 나온 뒤 경과 일수 (2010년 이후 기준)', 'Days since the site first appears (since 2010)', 'days'),
    ('hex_closure_rate_3y', '동네의 직전 3년 폐업률 (연 단위 근사)', 'Neighborhood closure rate, previous 3 years (yearly approx.)', 'ratio'),
    ('hex_density / _sq', '개업 연도 1월 1일 동네 영업 음식점 수 / 제곱', 'Restaurants open in the hexagon on Jan 1 of opening year / squared', 'count'),
    ('duration_days', '생존 기간 (영업 중이면 기준일까지)', 'Survival time (censored at data end)', 'days'),
    ('event_ours', '★ 진짜 폐업 (양도면 0, 영업 중이면 0)', '★ Real closure event (transfer = 0, open = 0)', '0/1'),
    ('event_parsa', 'Parsa 정의 폐업 (모든 폐업 = 1)', 'Closure under Parsa definition (any closure)', '0/1'),
    ('event_jari', 'jari 정의 폐업 (같은 상호 60일 안 재개업만 0)', 'Closure under jari definition', '0/1'),
    ('dead_3y', '3년 안 진짜 폐업', 'Real closure within 3 years', '0/1'),
]
vdict = pd.DataFrame(DICT, columns=['column', '설명', 'description (EN)', 'unit'])
vdict['결측 비율(%)'] = [pct(t[c.split(' ')[0]].isna().mean()) if c.split(' ')[0] in t.columns else '' for c in vdict['column']]
vdict.loc[vdict['column'] == 'coord_src', '결측 비율(%)'] = pct((t['coord_src'] == '결측').mean())

with pd.ExcelWriter(OUT_DIR / '1125_품질수치표_코딩1.xlsx', engine='openpyxl') as w:
    summary.to_excel(w, sheet_name='요약', index=False)
    defs.to_excel(w, sheet_name='파일럿 재현_정의별', index=False)
    dose.to_excel(w, sheet_name='파일럿 재현_횟수별', index=False)
    note.to_excel(w, sheet_name='파일럿 재현_비고', index=False)
    by_gu.to_excel(w, sheet_name='구별 층 결측', index=False)
    by_year.to_excel(w, sheet_name='연도별 층 결측', index=False)
    coord_gu.to_excel(w, sheet_name='구별 좌표 결측', index=False)
    coord_year.to_excel(w, sheet_name='연도별 좌표 결측', index=False)
vdict.to_excel(OUT_DIR / '변수설명표_analysis_table_v1.xlsx', index=False)
print(summary.to_string(index=False)); print(defs.to_string(index=False)); print(dose.to_string(index=False))
print(by_gu.sort_values('층 결측(%)').iloc[[0, 1, -2, -1]].to_string(index=False))
