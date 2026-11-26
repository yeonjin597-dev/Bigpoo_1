"""
좌표 결측 채우기 (코딩 1)

왜: 좌표 없는 가게가 이전 폐업 횟수가 2.3배 높고(0.59 vs 1.36회) 종로·영등포·성북에 몰려 있어,
    삭제하면 결과가 한쪽으로 쏠린다(무작위 결측이 아님).
방법(순서대로):
  1) same_jibun : 인허가 전체 기간에서 같은 지번(같은 건물) 가게들의 좌표 중앙값
  2) sbiz       : 소상공인시장진흥공단 상가(상권)정보의 같은 지번주소 좌표 중앙값 (WGS84 → EPSG:5174 변환)
  3) 남으면 결측
좌표계: 인허가 X·Y = EPSG:5174 (Korean 1985 / Modified Central Belt).
        실증 확인: 공통 지번 96,291개에서 상가정보 경위도를 5174로 바꿨을 때 차이 중앙값 1.8m
        (2097: 255m, 5181: 313m, 5186: 100km).
결과 열: x, y (채운 값), coord_src ∈ {원본, 같은지번, 상가정보, 결측}

팀 공통 좌표: 코딩 3이 같은 방법으로 만든 data/1125_좌표보충_코딩3.parquet(관리번호, x, y, coord_src, gu)가
있으면 apply_common_coords()로 그 좌표를 쓴다(모두가 같은 좌표를 보도록). 내 fill_coordinates()와 비교 결과:
2010년 이후 211,683건 중 출처 판정 다른 것 2건, 좌표 차이 중앙값 0m, 100m 초과 73건
(같은 지번 좌표가 여러 개일 때 코딩 3은 가장 최근 가게, 나는 중앙값을 써서 생긴 차이).
"""
import numpy as np
import pandas as pd

PERMIT_EPSG = 5174
SBIZ_PATH = 'data/소상공인시장진흥공단_상가_상권_정보_서울_202609.csv'


def load_sbiz_coords(path=SBIZ_PATH):
    from pyproj import Transformer
    s = pd.read_csv(path, usecols=['지번주소', '경도', '위도'], dtype=str)
    s['lon'] = pd.to_numeric(s['경도'], errors='coerce')
    s['lat'] = pd.to_numeric(s['위도'], errors='coerce')
    s['jibun'] = s['지번주소'].str.strip().str.replace(r'\s+', ' ', regex=True)
    s = s.dropna(subset=['lon', 'lat', 'jibun'])
    t = Transformer.from_crs(4326, PERMIT_EPSG, always_xy=True)
    s['x'], s['y'] = t.transform(s['lon'].values, s['lat'].values)
    return s.groupby('jibun')[['x', 'y']].median()


def fill_coordinates(df, sbiz_path=SBIZ_PATH):
    """df: add_address()를 거친 인허가 원본(jibun, x, y 열 필요). 제자리에서 x, y를 채우고 coord_src를 단다."""
    df['coord_src'] = np.where(df['x'].notna() & df['y'].notna(), '원본', '결측')
    miss = df['coord_src'] == '결측'

    same = df[~miss & df['jibun'].notna()].groupby('jibun')[['x', 'y']].median()
    hit = miss & df['jibun'].isin(same.index)
    df.loc[hit, 'x'] = df.loc[hit, 'jibun'].map(same['x'])
    df.loc[hit, 'y'] = df.loc[hit, 'jibun'].map(same['y'])
    df.loc[hit, 'coord_src'] = '같은지번'

    miss = df['coord_src'] == '결측'
    sb = load_sbiz_coords(sbiz_path)
    hit = miss & df['jibun'].isin(sb.index)
    df.loc[hit, 'x'] = df.loc[hit, 'jibun'].map(sb['x'])
    df.loc[hit, 'y'] = df.loc[hit, 'jibun'].map(sb['y'])
    df.loc[hit, 'coord_src'] = '상가정보'
    return df


def apply_common_coords(df, path):
    """코딩 3의 공통 좌표 파일을 관리번호로 붙여 x, y, coord_src를 교체한다."""
    c = pd.read_parquet(path)[['관리번호', 'x', 'y', 'coord_src']]
    df = df.drop(columns=['x', 'y', 'coord_src'], errors='ignore').merge(c, on='관리번호', how='left')
    df['coord_src'] = df['coord_src'].fillna('결측')
    return df


def report(df, since='2010-01-01'):
    d = df[df['od'] >= since]
    out = d['coord_src'].value_counts().rename('건수').to_frame()
    out['비율'] = (out['건수'] / len(d)).round(4)
    return out
