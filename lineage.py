"""
코딩 1 · 데이터 구축 파이프라인
서울시 일반음식점 인허가 원본 → 칸(지번+층) 계보 → 분석용 테이블

실행: python lineage.py   (data/ 폴더에 원본 CSV 2개를 넣고 실행. 자세한 건 README.md)
결정 사항(결정 기록에 남길 것):
  - 칸 = 지번 + 층, 2010년 이후 인허가로 계보 구성
  - 양도 = 폐업 후 TRANSFER_DAYS(60일) 안에 같은 칸에 **같은 상호(정규화)**가 재입점 (결정 D9: OECD 연속성 기준 + jari 60일 정의,
    비코딩 1 판정과 대조). 구 규칙(30일 안 아무 가게 재입점, 식품위생법 제39조 지위승계 기간)은 TRANSFER_RULE='days'로 재현
  - 분석 코호트 = 2013~2022년 개업 (3년 창이 전부 2010년 이후에 들어가도록)
  - 이전 폐업 = 개업일 직전 WINDOW_DAYS(기본 1095일) 안, 같은 칸, 다른 상호의 '진짜 폐업'
  - 중도절단 기준일 = 원본에 있는 가장 늦은 날짜(인허가일·폐업일 중 최댓값)
  - 좌표 결측 = 같은 지번 → 상가정보 지번 순으로 채움, coord_src 열로 출처 표시 (fill_coords.py)
"""
import re
from pathlib import Path
import numpy as np
import pandas as pd

# ───────────────────────── 설정 ─────────────────────────
BASE = Path(__file__).resolve().parent
DATA_IN = BASE / 'data' / '인허가_원본.csv'   # 서울시 일반음식점 인허가 CSV (cp949)
SBIZ_IN = BASE / 'data' / '소상공인시장진흥공단_상가_상권_정보_서울_202609.csv'
COORD_IN = BASE / 'data' / '1125_좌표보충_코딩3.parquet'   # 팀 공통 좌표 (코딩 3). 있으면 이걸 씀
OUT_DIR = BASE / 'out'                        # 결과 저장 폴더
TRANSFER_DAYS = 60                       # D9: 60일 + 같은 상호 (구 규칙은 30일 + 아무 가게)
TRANSFER_RULE = 'name'                   # 'name' = 같은 상호만 양도 / 'days' = 기간 안 아무 가게 재입점이면 양도 (구 규칙)
NAME_MATCH = 'loose'                     # 'loose' = 지점명·괄호·영한 표기·어순·앞부분 일치 허용 / 'strict' = 정규화 후 완전 일치
JARI_DAYS = 60
WINDOW_DAYS = 1095
LINEAGE_START = '2010-01-01'
COHORT = ('2013-01-01', '2023-01-01')    # [시작, 끝)
HEX_SIZE_M = 100                         # 육각형 크기(m). 변 길이로 가정 → 김동준 외(2018) 원문 확인 후 조정
SEED = 42


# ───────────────────────── 1. 원본 읽기 ─────────────────────────
def standardize(df):
    """인허가 원본 열을 분석용 이름으로 바꾼다. 일반음식점·휴게음식점 등 LOCALDATA 인허가 공통 형식."""
    df = df.copy()
    df['od'] = pd.to_datetime(df['인허가일자'], errors='coerce')
    df['cd'] = pd.to_datetime(df['폐업일자'], errors='coerce')
    df['name'] = df['사업장명'].fillna('').str.replace(r'\s+', '', regex=True)
    df['category'] = df['업태구분명'].fillna('미상')
    df['area_m2'] = pd.to_numeric(df['소재지면적'], errors='coerce')
    df['x'] = pd.to_numeric(df['좌표정보(X)'], errors='coerce')
    df['y'] = pd.to_numeric(df['좌표정보(Y)'], errors='coerce')
    seoul = df['지번주소'].fillna('').str.startswith('서울특별시') | df['도로명주소'].fillna('').str.startswith('서울특별시')
    print(f'서울 밖 주소 제외: {(~seoul).sum()}건 (예: 부천 원미구 등)')
    return df[seoul].copy()


def load_raw(path=DATA_IN):
    df = pd.read_csv(path, encoding='cp949', encoding_errors='replace', dtype=str, low_memory=False)
    return standardize(df)


# ───────────────────────── 2. 주소 파싱 ─────────────────────────
JIBUN_RE = re.compile(r'^(서울특별시\s+\S+구\s+\S+?(?:동|가|로)\d*가?\s+(?:산\s*)?\d+(?:-\d+)?)')
RANGE_RE = re.compile(r'(지하\s*)?(\d{1,2})\s*층?\s*[~\-]\s*(?:지상\s*)?(지하\s*)?(\d{1,2})\s*층')
LIST_RE = re.compile(r'(지하\s*)?(\d{1,2})\s*층?\s*,\s*(?:지상\s*)?(\d{1,2})\s*층')
BASE_RE = re.compile(r'(?:지하\s*(\d{1,2})(?!\d)(?![\d,\-\s]*호)|[Bb]\s*(\d{1,2})\s*층|(?<![가-힣])지\s*(\d{1,2})\s*층)')
BHO_RE = re.compile(r'[Bb]\s*\d{1,4}(?:-\d+)?[A-Za-z]?(?!\s*동)(?![\d])')   # B101호, B1-05 같은 지하 호수
GROUND_RE = re.compile(r'(?<!\d)(?<!\d-)(?<!\d~)(?<!\d,)(\d{1,2})\s*층')


def parse_jibun(addr):
    m = JIBUN_RE.match(addr or '')
    if not m:
        return None, ''
    jb = re.sub(r'\s+', ' ', re.sub(r'-0$', '', m.group(1)))
    return jb, (addr or '')[m.end():]


def floors_in(text):
    """주소의 나머지 문자열에서 층 후보를 모두 찾는다. 지하는 음수."""
    fl = set()
    for m in RANGE_RE.finditer(text):
        a = -int(m.group(2)) if m.group(1) else int(m.group(2))
        b = -int(m.group(4)) if m.group(3) else int(m.group(4))
        fl.update([a, b])
    for m in LIST_RE.finditer(text):
        sign = -1 if m.group(1) else 1
        fl.update([sign * int(m.group(2)), sign * int(m.group(3))])
    for m in BASE_RE.finditer(text):
        fl.add(-int(next(g for g in m.groups() if g)))
    for m in GROUND_RE.finditer(text):
        fl.add(int(m.group(1)))
    if '지하' in text and not any(f < 0 for f in fl):
        fl.add(-1)
    if not fl and BHO_RE.search(text):      # 층 표기 없이 'B101호'만 있으면 지하 1층으로
        fl.add(-1)
    fl.discard(0)
    return fl


def parse_floor(jibun_rest, road_addr):
    """지번주소 나머지 → 없으면 도로명주소(쉼표 뒤, 괄호 앞)에서 층을 찾는다.
    반환: (층 라벨 'B1'/'2' 또는 None, 범위 여부, 출처)"""
    fl = floors_in(jibun_rest)
    src = 'jibun'
    if not fl:
        road = road_addr or ''
        # 도로명주소: 쉼표 뒤(상세주소) + 끝 괄호 안(법정동, 건물명·호수). 도로명 본문의 '지하 96' 같은 번지는 쓰지 않음
        paren = re.search(r'\(([^()]*)\)\s*$', road)
        body = re.sub(r'\s*\([^()]*\)\s*$', '', road)
        rest = (body.split(',', 1)[1] if ',' in body else '') + ' ' + (paren.group(1) if paren else '')
        fl = floors_in(rest)
        src = 'road'
    if not fl:
        return None, False, None
    low = min(fl)
    label = f'B{-low}' if low < 0 else str(low)
    return label, len(fl) > 1, src


def add_address(df):
    jb = df['지번주소'].fillna('').map(parse_jibun)
    df['jibun'] = jb.str[0]
    rest = jb.str[1]
    parsed = [parse_floor(r, a) for r, a in zip(rest, df['도로명주소'].fillna(''))]
    df['floor'] = [p[0] for p in parsed]
    df['floor_range'] = [p[1] for p in parsed]
    df['floor_src'] = [p[2] for p in parsed]
    df['gu'] = df['jibun'].str.split(' ').str[1]
    df['dong'] = df['jibun'].str.rsplit(' ', n=1).str[0]
    return df


# ───────────────────────── 3. 칸 계보 + 실패 정의 ─────────────────────────
def build_lineage(df, transfer_days=TRANSFER_DAYS, jari_days=JARI_DAYS, start=LINEAGE_START,
                  transfer_rule=TRANSFER_RULE, name_match=NAME_MATCH):
    """칸(지번+층)별로 가게를 개업 순서로 줄 세우고, 다음 가게와의 간격으로 실패를 정의한다.
    다른 업종(예: 휴게음식점) 데이터에도 같은 함수를 쓴다."""
    d = df[(df['od'] >= start) & df['jibun'].notna() & df['floor'].notna()].copy()
    d['site'] = d['jibun'] + '|' + d['floor']
    d = d.sort_values(['site', 'od', 'cd']).reset_index(drop=True)
    g = d.groupby('site')
    d['seq'] = g.cumcount() + 1
    d['nxt_od'] = g['od'].shift(-1)
    d['nxt_name'] = g['name'].shift(-1)
    d['prev_od'] = g['od'].shift(1)
    d['prev_cd'] = g['cd'].shift(1)
    d['prev_name'] = g['name'].shift(1)
    d['prev_category'] = g['category'].shift(1)
    gap = (d['nxt_od'] - d['cd']).dt.days
    d['gap_next_days'] = gap
    closed = d['cd'].notna()
    d['event_parsa'] = closed
    d['event_jari'] = closed & ~((d['nxt_name'] == d['name']) & gap.between(0, jari_days))
    raw_name = d['사업장명'] if '사업장명' in d else d['name']
    d['name_key'] = [''.join(name_tokens(x)) or n for x, n in zip(raw_name, d['name'])]
    in_window = closed & gap.between(0, transfer_days)
    if transfer_rule == 'name':        # D9: 기간 안 + 같은 상호만 양도
        nxt_raw = raw_name.groupby(d['site']).shift(-1)
        idx = in_window[in_window].index
        same = pd.Series(False, index=d.index)
        same.loc[idx] = [same_business_name(a, b, name_match) for a, b in zip(raw_name.loc[idx], nxt_raw.loc[idx])]
        d['transfer'] = in_window & same
    else:                              # 구 규칙: 기간 안 아무 가게 재입점
        d['transfer'] = in_window
    d['event_ours'] = closed & ~d['transfer']
    d['event_days30'] = closed & ~gap.between(0, 30)     # 구 규칙 (비교용)
    # 다음 가게가 내 폐업 전에 개업 = 한 층에 가게 여럿(다점포)
    overlap_next = gap < 0
    overlap_prev = (d['od'] - d['prev_cd']).dt.days < 0
    site_multi = (overlap_next | overlap_prev).groupby(d['site']).transform('any')
    d['multi_tenant'] = site_multi
    return d


# ───────────────────────── 상호 연속성 (D9) ─────────────────────────
_SYN = {'cafe': '카페', 'coffee': '커피'}


def name_tokens(s):
    """상호 → 비교용 토큰: (주)·괄호 제거, 소문자, 특수문자 제거, 끝의 '…점'(지점명) 제거, cafe→카페."""
    if not isinstance(s, str):
        return []
    s = re.sub(r'\(주\)|주식회사|㈜', '', s)
    s = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', s)
    t = [re.sub(r'[^0-9a-z가-힣]', '', w.lower()) for w in s.split()]
    t = [_SYN.get(w, w) for w in t if w]
    while len(t) > 1 and t[-1].endswith('점'):
        t = t[:-1]
    return t


def same_business_name(a, b, match=NAME_MATCH):
    """두 상호가 같은 사업체로 이어지는가 (비코딩 1의 B열 판정과 대조: 218쌍 중 216쌍 일치)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    ja, jb = ''.join(ta), ''.join(tb)
    if ja == jb:
        return True
    if match == 'strict':
        return False
    if sorted(ta) == sorted(tb):
        return True
    short, long_ = (ja, jb) if len(ja) <= len(jb) else (jb, ja)
    return len(short) >= 2 and long_.startswith(short)


# ───────────────────────── 4. 3단계 변수 ─────────────────────────
def count_prior(coh, fails, key, window=WINDOW_DAYS, other_floor=False):
    """coh의 각 가게에 대해, 같은 key(칸 또는 지번)에서 개업일 직전 window일 안에
    '진짜 폐업'한 다른 상호의 가게 수를 센다. (미래 정보 없음: 폐업일 < 개업일)"""
    nm = 'name_key' if ('name_key' in coh and 'name_key' in fails) else 'name'   # D9: 정규화 상호로 '다른 상호' 판단
    left = coh[['row', key, 'od', nm, 'floor']].rename(columns={nm: 'name'})
    right = fails[[key, 'cd', nm, 'floor']].rename(columns={'cd': 'cd_p', nm: 'name_p', 'floor': 'floor_p'})
    m = left.merge(right, on=key)
    ok = (m['cd_p'] < m['od']) & (m['cd_p'] >= m['od'] - pd.Timedelta(days=window)) & (m['name_p'] != m['name'])
    ok &= (m['floor_p'] != m['floor']) if other_floor else True
    return m[ok].groupby('row').size().reindex(coh['row']).fillna(0).astype(int).values


def hex_ids(x, y, size=HEX_SIZE_M):
    """평면 좌표(m)를 뾰족한 위쪽(pointy-top) 육각형 격자의 (q, r) 정수 좌표로 바꾼다."""
    q = (np.sqrt(3) / 3 * x - 1 / 3 * y) / size
    r = (2 / 3 * y) / size
    xc, zc = q, r
    yc = -xc - zc
    rx, ry, rz = np.round(xc), np.round(yc), np.round(zc)
    dx, dy, dz = np.abs(rx - xc), np.abs(ry - yc), np.abs(rz - zc)
    fix_x = (dx > dy) & (dx > dz)
    fix_y = ~fix_x & (dy > dz)
    rx = np.where(fix_x, -ry - rz, rx)
    ry = np.where(fix_y, -rx - rz, ry)
    rz = np.where(~fix_x & ~fix_y, -rx - ry, rz)
    qs = pd.Series(rx, index=x.index).round().astype('Int64').astype(str)
    rs = pd.Series(rz, index=x.index).round().astype('Int64').astype(str)
    out = (qs + '_' + rs).astype(object)
    out[x.isna() | y.isna()] = None
    return out


def neighborhood_table(df_all, lin):
    """육각형×연도별: 1월 1일에 영업 중인 가게 수, 그해 '진짜 폐업' 수.
    인허가 전체(2010년 이전 개업 포함, 층 없는 가게 포함)를 쓴다.
    폐업 판정은 계보가 있는 가게는 event_ours, 없는 가게는 단순 폐업."""
    a = df_all[['관리번호', 'od', 'cd', 'x', 'y']].copy()
    a['hex_id'] = hex_ids(a['x'], a['y'])
    a = a[a['hex_id'].notna() & a['od'].notna()]
    ev = lin.set_index('관리번호')['event_ours']
    a['real_close'] = a['cd'].notna()
    known = a['관리번호'].isin(ev.index)
    a.loc[known, 'real_close'] = a.loc[known, '관리번호'].map(ev).values
    rows = []
    for yr in range(2007, 2027):
        jan1 = pd.Timestamp(f'{yr}-01-01')
        alive = (a['od'] <= jan1) & (a['cd'].isna() | (a['cd'] > jan1))
        closes = a['real_close'] & (a['cd'].dt.year == yr)
        t = pd.DataFrame({'hex_id': a['hex_id'], 'alive': alive, 'closes': closes})
        s = t.groupby('hex_id')[['alive', 'closes']].sum()
        s['year'] = yr
        rows.append(s.reset_index())
    return pd.concat(rows, ignore_index=True)


def add_neighborhood(coh, nb):
    """개업 연도 Y 기준: Y-3~Y-1년의 폐업 수 / 같은 기간 1월 1일 영업 가게 수 합 (연 단위 근사),
    밀도 = Y년 1월 1일 영업 중인 일반음식점 수."""
    nb = nb.set_index(['hex_id', 'year'])
    yr = coh['od'].dt.year
    clos = sum(nb['closes'].reindex(list(zip(coh['hex_id'], yr - k))).fillna(0).values for k in (1, 2, 3))
    aliv = sum(nb['alive'].reindex(list(zip(coh['hex_id'], yr - k))).fillna(0).values for k in (1, 2, 3))
    coh['hex_closure_rate_3y'] = np.where(aliv > 0, clos / np.maximum(aliv, 1), np.nan)
    coh['hex_density'] = nb['alive'].reindex(list(zip(coh['hex_id'], yr))).values
    coh['hex_density_sq'] = coh['hex_density'] ** 2
    coh.loc[coh['hex_id'].isna(), ['hex_closure_rate_3y', 'hex_density', 'hex_density_sq']] = np.nan
    return coh


def build_analysis_table(df_all, lin, censor_date, cohort=COHORT, window=WINDOW_DAYS):
    coh = lin[(lin['od'] >= cohort[0]) & (lin['od'] < cohort[1])].copy()
    coh['row'] = np.arange(len(coh))
    fails = lin[lin['event_ours']]
    coh['prior_closures'] = count_prior(coh, fails, 'site', window)
    coh['other_floor_closures'] = count_prior(coh, fails, 'jibun', window, other_floor=True)
    coh['prior_closures_cat'] = coh['prior_closures'].clip(upper=4).astype(str).replace({'4': '4+'})
    # 직전 가게(같은 칸 바로 앞 가게) 정보
    coh['prev_tenure_days'] = (coh['prev_cd'] - coh['prev_od']).dt.days
    no_prev = coh['prev_od'].isna()
    coh['prev_short'] = (coh['prev_tenure_days'] < 365).astype('boolean').mask(no_prev)
    coh['vacancy_days'] = (coh['od'] - coh['prev_cd']).dt.days
    coh['same_cat_successor'] = (coh['prev_category'] == coh['category']).astype('boolean').mask(no_prev)
    first_seen = lin.groupby('site')['od'].min()
    coh['site_age_days'] = (coh['od'] - coh['site'].map(first_seen)).dt.days
    coh['open_year'] = coh['od'].dt.year
    # 결과 변수: 폐업(진짜/양도) 또는 영업 중이면 기준일까지
    end = coh['cd'].fillna(censor_date).clip(upper=censor_date)
    coh['duration_days'] = (end - coh['od']).dt.days
    for k in ('ours', 'parsa', 'jari'):
        coh[f'event_{k}'] = coh[f'event_{k}'].astype(int)
    coh['dead_3y'] = ((coh['event_ours'] == 1) & (coh['duration_days'] <= 1095)).astype(int)
    # 동네
    coh['hex_id'] = hex_ids(coh['x'], coh['y'])
    nb = neighborhood_table(df_all, lin)
    coh = add_neighborhood(coh, nb)
    keep = ['관리번호', 'site', 'jibun', 'floor', 'floor_range', 'floor_src', 'gu', 'dong', 'hex_id',
            'x', 'y'] + (['coord_src'] if 'coord_src' in coh.columns else []) + [
            'od', 'cd', 'name', 'category', 'area_m2', 'open_year', 'seq', 'multi_tenant',
            'prior_closures', 'prior_closures_cat', 'other_floor_closures',
            'prev_tenure_days', 'prev_short', 'vacancy_days', 'same_cat_successor', 'site_age_days',
            'hex_closure_rate_3y', 'hex_density', 'hex_density_sq',
            'duration_days', 'event_ours', 'event_parsa', 'event_jari', 'dead_3y']
    out = coh[keep].rename(columns={'관리번호': 'license_id', 'od': 'open_date', 'cd': 'close_date'})
    return out, nb


if __name__ == '__main__':
    import sys
    from fill_coords import fill_coordinates, apply_common_coords, report
    OUT_DIR.mkdir(exist_ok=True)
    cache = OUT_DIR / 'raw_parsed.pkl'
    if cache.exists() and '--fresh' not in sys.argv:          # 주소 파싱은 오래 걸려서 캐시 재사용
        raw = pd.read_pickle(cache)
    else:
        raw = add_address(load_raw())
        raw.to_pickle(cache)
    seoul = raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')
    raw = raw[seoul].copy()                                      # 캐시가 옛 버전이어도 서울 밖 제외
    raw = apply_common_coords(raw, COORD_IN) if COORD_IN.exists() else fill_coordinates(raw, SBIZ_IN)
    print(report(raw))
    censor = max(raw['od'].max(), raw['cd'].max())
    lin = build_lineage(raw)
    table, nb = build_analysis_table(raw, lin, censor)
    lin.to_pickle(OUT_DIR / 'lineage.pkl')
    table.to_parquet(OUT_DIR / 'analysis_table_v1.parquet', index=False)
    print('rows raw', len(raw), '| lineage', len(lin), '| cohort', len(table), '| censor', censor.date())
