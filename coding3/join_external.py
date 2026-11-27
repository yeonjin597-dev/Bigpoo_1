# join_external.py  (코딩 3: 좌표 보충 + 외부 변수 붙이기)
# 실행: python join_external.py
import os, re, glob, traceback
import numpy as np
import pandas as pd
import geopandas as gpd

BASE = os.path.dirname(os.path.abspath(__file__))
def P(*a): return os.path.join(BASE, *a)

# ===== 파일 위치 (폴더 구조가 다르면 여기만 고치기) =====
LICENSE_CSV = P('서울시 일반음식점 인허가 정보.csv')
STORE_GLOB  = P('소상공인시장진흥공단_상가(상권)정보_*', '*서울*.csv')
POP_GLOB    = P('250_LOCAL_RESD_*', '*.csv')
TRDAR_GLOB  = P('서울시 상권분석서비스(영역-상권)', '*.shp')
JIGA_GLOB   = P('공시지가_2026년', '*.csv')
BJD_GLOB    = P('법정동코드 전체자료', '*.*')
OUT         = P('02_계보', '1126_외부변수_코딩3.parquet')
YEAR_FROM   = 2010
LIC_CRS     = 'EPSG:5174'

rules = []   # 처리 중 정한 규칙 기록


def read_csv_any(path, **kw):
    """utf-8 → cp949 순서로 읽기"""
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding='cp949', encoding_errors='replace',
                       low_memory=False, **kw)


def find_col(df, *keys, exclude=()):
    """열 이름에 keys 중 하나가 들어간 첫 열 (exclude가 들어간 열은 제외)"""
    for k in keys:
        for c in df.columns:
            s = str(c)
            if k in s and not any(e in s for e in exclude):
                return c
    return None


def first_file(pattern):
    files = sorted(glob.glob(pattern))
    return files[0] if files else None


# 지번주소 → (구, 동, 산여부, 본번, 부번)
ADDR_RE = r'(\S+구)\s+(\S+)\s+(산\s*)?(\d+)(?:\s*-\s*(\d+))?'

def add_jibun_key(df, addr_col):
    p = df[addr_col].astype(str).str.extract(ADDR_RE)
    p.columns = ['gu', 'dong', 'san', 'bon', 'bu']
    df['gu'] = p['gu']
    df['dong'] = p['dong']
    df['san'] = np.where(p['san'].notna(), '2', '1')        # PNU 규칙: 일반 1, 산 2
    df['bon'] = pd.to_numeric(p['bon'], errors='coerce')
    df['bu'] = pd.to_numeric(p['bu'], errors='coerce').fillna(0)
    ok = df['gu'].notna() & df['bon'].notna()
    df['jkey'] = np.where(
        ok,
        df['gu'].astype(str) + '|' + df['dong'].astype(str) + '|' + df['san'] + '|'
        + df['bon'].fillna(0).astype(int).astype(str).str.zfill(4) + '|'
        + df['bu'].astype(int).astype(str).str.zfill(4),
        None)
    return df


def rate(n, d):
    return f'{n:,} / {d:,} ({n / d:.1%})' if d else f'{n:,} / 0'


# =====================================================================
# 0. 좌표 보충 (삭제하지 않음)
# =====================================================================
print('\n===== 0. 좌표 보충 =====')
lic = read_csv_any(LICENSE_CSV)
C_ID   = find_col(lic, '관리번호')
C_DATE = find_col(lic, '인허가일자')
C_ADDR = find_col(lic, '지번주소', '소재지전체주소')
C_X    = find_col(lic, '좌표정보(X)', '좌표정보X', 'X')
C_Y    = find_col(lic, '좌표정보(Y)', '좌표정보Y', 'Y')
print('사용 열:', C_ID, C_DATE, C_ADDR, C_X, C_Y)

lic['관리번호'] = lic[C_ID].astype(str).str.strip()
lic['open_date'] = pd.to_datetime(lic[C_DATE].astype(str).str.strip(), errors='coerce')
lic['open_year'] = lic['open_date'].dt.year
lic['x'] = pd.to_numeric(lic[C_X], errors='coerce')
lic['y'] = pd.to_numeric(lic[C_Y], errors='coerce')
lic.loc[(lic['x'] <= 0) | (lic['y'] <= 0), ['x', 'y']] = np.nan
lic = add_jibun_key(lic, C_ADDR)
lic['coord_src'] = np.where(lic['x'].notna(), '원본', '결측')

target = lic['open_year'] >= YEAR_FROM
miss0 = (target & lic['x'].isna()).sum()
print(f'{YEAR_FROM}년 이후 가게: {target.sum():,}, 좌표 없음: {miss0:,}')
print('지번 키를 만든 비율(전체):', rate(lic['jkey'].notna().sum(), len(lic)))

# ① 전체 기간에서 같은 지번의 다른 가게 좌표 (가장 최근 개업 가게 것)
donor = (lic[lic['x'].notna() & lic['jkey'].notna()]
         .sort_values('open_date')
         .groupby('jkey')[['x', 'y']].last())
m = lic['x'].isna() & lic['jkey'].isin(donor.index)
lic.loc[m, 'x'] = lic.loc[m, 'jkey'].map(donor['x'])
lic.loc[m, 'y'] = lic.loc[m, 'jkey'].map(donor['y'])
lic.loc[m, 'coord_src'] = '같은지번'
print('① 같은 지번(전체 기간)으로 채움:', f'{(m & target).sum():,} ({YEAR_FROM}년 이후)')
rules.append('좌표 ①: 같은 지번(구+동+산+본번+부번)의 다른 가게 좌표, 전체 기간, 여러 개면 가장 최근 개업 가게')

# ② 소상공인 상가정보의 같은 지번 좌표
try:
    sf = first_file(STORE_GLOB)
    if sf is None:
        print('② 상가정보 파일 없음 → 건너뜀')
    else:
        st = read_csv_any(sf)
        S_ADDR = find_col(st, '지번주소')
        S_LON, S_LAT = find_col(st, '경도'), find_col(st, '위도')
        print('② 상가정보:', os.path.basename(sf), '| 열:', S_ADDR, S_LON, S_LAT)
        st = add_jibun_key(st, S_ADDR)
        st[S_LON] = pd.to_numeric(st[S_LON], errors='coerce')
        st[S_LAT] = pd.to_numeric(st[S_LAT], errors='coerce')
        st = st.dropna(subset=[S_LON, S_LAT, 'jkey'])
        g = gpd.GeoDataFrame(st[['jkey']], crs='EPSG:4326',
                             geometry=gpd.points_from_xy(st[S_LON], st[S_LAT])).to_crs(LIC_CRS)
        g['sx'], g['sy'] = g.geometry.x, g.geometry.y
        d2 = g.groupby('jkey')[['sx', 'sy']].first()
        m2 = lic['x'].isna() & lic['jkey'].isin(d2.index)
        lic.loc[m2, 'x'] = lic.loc[m2, 'jkey'].map(d2['sx'])
        lic.loc[m2, 'y'] = lic.loc[m2, 'jkey'].map(d2['sy'])
        lic.loc[m2, 'coord_src'] = '상가정보'
        print('② 상가정보로 채움:', f'{(m2 & target).sum():,} ({YEAR_FROM}년 이후)')
        rules.append('좌표 ②: 소상공인 상가정보 같은 지번 좌표 (WGS84 → EPSG:5174 변환)')
except Exception:
    print('② 실패:'); traceback.print_exc()

rules.append('좌표 ③: 그래도 없으면 결측으로 둠 (삭제하지 않음)')
T = lic[target].copy()
print('\n[coord_src 분포, 2010년 이후]')
print(T['coord_src'].value_counts().to_string())
print('\n[구별 최종 결측률 상위 10]')
print(T.groupby('gu')['x'].apply(lambda s: s.isna().mean()).sort_values(ascending=False)
      .head(10).map('{:.1%}'.format).to_string())
print('\n[연도별 최종 결측률]')
print(T.groupby('open_year')['x'].apply(lambda s: s.isna().mean()).map('{:.1%}'.format).to_string())

SHARE = P('02_계보', '1125_좌표보충_코딩3.parquet')
lic[['관리번호', 'x', 'y', 'coord_src', 'gu']].to_parquet(SHARE, index=False)
print('\n좌표 공유 파일 저장:', SHARE, f'{len(lic):,}행 (EPSG:5174)')
pts = T[T['x'].notna()]
pts = gpd.GeoDataFrame(pts[['관리번호']], crs=LIC_CRS,
                       geometry=gpd.points_from_xy(pts['x'], pts['y']))
out = T[['관리번호', 'coord_src', 'gu', 'dong', 'san', 'bon', 'bu']].copy()
N = len(out)

# =====================================================================
# 1. 250m 격자 + 생활인구  (격자ID = 국가지점번호, SHP 불필요)
# =====================================================================
print('\n===== 1. 250m 격자 + 생활인구 =====')
try:
    XL = '가나다라마바사아자차카타파하'   # 가로 100km 글자 (가=700km부터)
    YL = '가나다라마바사아자차카타파하'   # 세로 100km 글자 (가=1300km부터)

    def to_gid(x, y):
        xs = int(x // 250 * 250)
        ys = int(y // 250 * 250)
        return (XL[(xs - 700000) // 100000] + YL[(ys - 1300000) // 100000]
                + f'{(xs % 100000) // 10:04d}' + f'{(ys % 100000) // 10:04d}')

    p5179 = pts.to_crs('EPSG:5179')
    gids = [to_gid(g.x, g.y) for g in p5179.geometry]
    out['격자ID'] = out['관리번호'].map(pd.Series(gids, index=p5179['관리번호'].values))
    print('격자ID 계산:', rate(out['격자ID'].notna().sum(), N), '| 예시:', out['격자ID'].dropna().head(3).tolist())

    pop_files = sorted(glob.glob(POP_GLOB))
    print('생활인구 파일 수:', len(pop_files))
    parts = []
    for f in pop_files:
        # 열 순서: 일자, 시간, 행정동코드, 250M격자, 생활인구합계 ... (헤더가 깨진 파일이 있어 위치로 읽음)
        d = read_csv_any(f, usecols=[0, 1, 3, 4], dtype=str)
        d.columns = ['day', 'hour', 'gid', 'pop']
        parts.append(d)
    pop = pd.concat(parts, ignore_index=True)
    pop['pop'] = pd.to_numeric(pop['pop'], errors='coerce')   # '*' 은 결측
    pop['gid'] = pop['gid'].astype(str).str.strip()
    pop['day'] = pop['day'].astype(str).str.strip()
    pop['hour'] = pop['hour'].astype(str).str.strip()
    # 일부 파일은 한글 글자가 깨져 있음 → 숫자 8자리로 정상 격자ID에 복원 (서울은 모두 '다사' 100km 칸)
    good = pop['gid'].str.fullmatch(r'[가-힣]{2}\d{8}')
    if (~good).any():
        suf = pop['gid'].str[-8:]
        smap = pop.loc[good, ['gid']].assign(s=suf[good]).drop_duplicates().groupby('s')['gid']
        smap = smap.first()[smap.nunique() == 1]
        pop.loc[~good, 'gid'] = suf[~good].map(smap)
        print('깨진 격자ID 복원:', rate(pop.loc[~good, 'gid'].notna().sum(), int((~good).sum())),
              '| 파일:', sorted(pop.loc[~good, 'day'].unique()))
        pop = pop.dropna(subset=['gid'])
    print('생활인구 날짜:', sorted(pop['day'].unique()))

    # 한 격자가 행정동 2개에 걸치면 행이 나뉨 → 같은 날·시간끼리 합친 뒤 평균
    ph = pop.groupby(['gid', 'day', 'hour'])['pop'].sum(min_count=1).reset_index()
    popm = ph.groupby('gid')['pop'].mean()

    # 순위 안정성: 앞 절반 날짜 vs 뒤 절반 날짜
    days = sorted(ph['day'].unique())
    half = days[len(days) // 2]
    w1 = ph[ph['day'] < half].groupby('gid')['pop'].mean()
    w2 = ph[ph['day'] >= half].groupby('gid')['pop'].mean()
    both = pd.concat([w1, w2], axis=1, keys=['w1', 'w2']).dropna()
    print('앞 날짜 vs 뒤 날짜 격자 순위 상관(스피어만):',
          round(both['w1'].corr(both['w2'], method='spearman'), 3))

    overlap = out['격자ID'].dropna().isin(popm.index).mean()
    print('가게 격자ID 중 생활인구에 있는 비율:', f'{overlap:.1%}',
          '| 예시:', out['격자ID'].dropna().head(3).tolist(), 'vs', popm.index[:3].tolist())
    out['생활인구'] = out['격자ID'].map(popm)
    print('생활인구 매칭률:', rate(out['생활인구'].notna().sum(), N))
    rules.append(f'생활인구: 250m 격자(국가지점번호), {days[0]}~{days[-1]} {len(days)}일 시간대 평균을 고정값으로 사용')
except Exception:
    print('1단계 실패:'); traceback.print_exc()

# =====================================================================
# 2. 상권 유형 area_type
# =====================================================================
print('\n===== 2. 상권 유형 area_type =====')
try:
    tf = first_file(TRDAR_GLOB)
    if tf is None:
        raise FileNotFoundError('상권영역 폴더에 .shp가 없음 (CSV만 있으면 점 좌표뿐이라 사용 불가)')
    tr = gpd.read_file(tf)
    if tr.crs is None:
        tr = tr.set_crs('EPSG:5181')
    print('상권 파일:', os.path.basename(tf), '| 좌표계:', tr.crs, '| 열:', list(tr.columns))
    if not tr.geom_type.isin(['Polygon', 'MultiPolygon']).all():
        raise ValueError('경계가 다각형이 아님 → 멈춤. 다른 상권 영역 파일 필요')
    T_TYPE = find_col(tr, '상권_구분_코드_명', '구분_코드_명', 'TRDAR_SE_1', 'SE_CD_NM')
    T_CODE = find_col(tr, '상권_코드', 'TRDAR_CD', exclude=('구분', '명', 'SE'))
    T_AREA = find_col(tr, '영역_면적', 'RELM_AR')
    print('사용 열:', T_TYPE, T_CODE, T_AREA)
    if T_AREA is None:
        tr['_area'] = tr.geometry.area; T_AREA = '_area'
    j2 = gpd.sjoin(pts.to_crs(tr.crs), tr[[T_TYPE, T_CODE, T_AREA, 'geometry']],
                   how='inner', predicate='within')
    dup = j2.index.duplicated(keep=False).sum()
    j2 = j2.sort_values(T_AREA).loc[lambda d: ~d.index.duplicated(keep='first')]
    print('두 상권 이상에 겹친 가게(중복 행):', f'{dup:,}')
    k = j2.set_index('관리번호')
    out['상권_코드'] = out['관리번호'].map(k[T_CODE].astype(str))
    out['area_type'] = out['관리번호'].map(k[T_TYPE]).fillna('상권밖')
    out.loc[~out['관리번호'].isin(pts['관리번호']), 'area_type'] = np.nan   # 좌표 결측은 판정 불가
    print('\n[area_type별 가게 수]')
    print(out['area_type'].value_counts(dropna=False).to_string())
    rules.append('area_type: 상권 경계 안이면 상권_구분_코드_명, 밖이면 상권밖, 좌표 결측은 NaN')
    rules.append('겹치는 상권: 영역_면적이 더 작은 상권 하나만 사용')
except Exception:
    print('2단계 실패:'); traceback.print_exc()


# =====================================================================
# 3. 공시지가 (지번 → PNU)
# =====================================================================
print('\n===== 3. 공시지가 =====')
try:
    bf = first_file(BJD_GLOB)
    jf = sorted(glob.glob(JIGA_GLOB))
    if bf is None or not jf:
        raise FileNotFoundError('법정동코드 또는 공시지가 파일 없음 → 건너뜀')
    sep = '\t' if bf.lower().endswith('.txt') else ','
    bjd = read_csv_any(bf, sep=sep, dtype=str)
    B_CODE, B_NAME = find_col(bjd, '법정동코드'), find_col(bjd, '법정동명')
    B_ALIVE = find_col(bjd, '폐지여부')
    if B_ALIVE:
        bjd = bjd[bjd[B_ALIVE].astype(str).str.contains('존재')]
    bjd = bjd[bjd[B_NAME].astype(str).str.startswith('서울특별시')]
    nm = bjd[B_NAME].str.split()
    bjd = bjd[nm.str.len() == 3]
    bmap = dict(zip(nm[nm.str.len() == 3].str[1] + '|' + nm[nm.str.len() == 3].str[2], bjd[B_CODE]))
    code10 = (out['gu'].astype(str) + '|' + out['dong'].astype(str)).map(bmap)
    ok = code10.notna() & out['bon'].notna()
    out['PNU'] = np.where(ok, code10.astype(str) + out['san']
                          + out['bon'].fillna(0).astype(int).astype(str).str.zfill(4)
                          + out['bu'].astype(int).astype(str).str.zfill(4), None)
    print('PNU 생성률:', rate(out['PNU'].notna().sum(), N))

    jparts = []
    for f in jf:
        h = read_csv_any(f, nrows=0)
        J_PNU = find_col(h, '고유번호', 'PNU', '토지코드')
        J_PRICE = find_col(h, '공시지가')
        J_YEAR = find_col(h, '기준연도', '기준년도')
        cols = [c for c in (J_PNU, J_PRICE, J_YEAR) if c]
        d = read_csv_any(f, usecols=cols, dtype={J_PNU: str})
        jparts.append(d.rename(columns={J_PNU: 'PNU', J_PRICE: 'price', J_YEAR: 'year'}))
    jiga = pd.concat(jparts, ignore_index=True)
    jiga['price'] = pd.to_numeric(jiga['price'], errors='coerce')
    if 'year' in jiga:
        print('공시지가 연도:', sorted(jiga['year'].dropna().unique().tolist()))
        jiga = jiga.sort_values('year')
    jm = jiga.dropna(subset=['price']).groupby('PNU')['price'].last()
    out['공시지가'] = out['PNU'].map(jm)
    out['log_공시지가'] = np.log(out['공시지가'].where(out['공시지가'] > 0))
    print('공시지가 매칭률:', rate(out['공시지가'].notna().sum(), N))
    rules.append('공시지가: PNU로 연결, 받은 파일 중 가장 최근 연도 값을 고정값으로, log 변환 열 추가')
except Exception:
    print('3단계 건너뜀/실패:'); traceback.print_exc()


# =====================================================================
# 저장
# =====================================================================
keep = [c for c in ['관리번호', 'coord_src', '격자ID', '생활인구', '상권_코드', 'area_type',
                    '공시지가', 'log_공시지가'] if c in out.columns]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
out[keep].to_parquet(OUT, index=False)
print('\n저장:', OUT, '|', f'{len(out):,}행', '| 열:', keep)

print('\n===== 매칭률 요약 (2010년 이후 기준) =====')
for c in keep[1:]:
    print(f'{c}: {rate(out[c].notna().sum(), N)}')

print('\n===== 정한 규칙 =====')
for i, r in enumerate(rules, 1):
    print(f'{i}. {r}')
