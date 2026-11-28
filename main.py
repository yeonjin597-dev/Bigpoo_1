"""
발표 시연용 · 주소 → 칸(지번+층) 계보와 위험도

실행 (Windows PowerShell에서 한글이 깨지면 먼저: $env:PYTHONIOENCODING='utf-8')
    python main.py "서울특별시 마포구 서교동 123-4 1층"
    python main.py "마포구 서교동 123-4 B1"          # '서울특별시' 생략, 1층/1F/지하1층/B1 모두 가능
    python main.py                                   # 주소를 반복 입력 (빈 줄이면 종료)
    python main.py --anon "..."                      # 상호 → 가게 A, B…, 번지 → *** (발표용)
    python main.py --demo                            # 최근 3년 폐업 0·1·2·3회 이상 칸 자동 시연 (--anon 자동)

규칙
  - 칸ID = lineage.parse_jibun() 지번 + '|' + lineage.parse_floor() 층 (코딩 1 규칙 그대로)
  - 지번주소만 받음 (칸 테이블에는 도로명주소 키가 없음)
  - 결과는 화면에만 출력 (상호·주소가 있어서 파일로 저장하지 않음)
"""
import re
import sys
from pathlib import Path
from unicodedata import east_asian_width

import numpy as np
import pandas as pd

import lineage as L

# ───────────────────────── 설정 (양도 규칙이 바뀌면 파일만 바꾸기) ─────────────────────────
BASE = Path(__file__).resolve().parent
KAN = 'out/1126_칸테이블_가게단위_일반음식점.parquet'
TABLE = 'out/analysis_table_v2.parquet'
RESULT = 'out/1127_본분석_v1.xlsx'
HR = 1.20            # 이전 폐업 1회당 위험비 (본분석 M2)
HR_PLACEBO = 1.16    # 동네 몫을 뺀 1회당 위험비 (위약 검증)
WINDOW_DAYS = L.WINDOW_DAYS   # 최근 3년 = 1,095일
SHORT_DAYS = 30               # 생존 30일 미만 폐업 = 초단기·임시 영업 의심
DEMO_SEED = 42

KAN_COLS = ['칸ID', '지번키', '층', '상호', '업태', '개업일', '폐업일', '폐업여부', '양도여부',
            '생존기간', '이전폐업수', '칸내순번', '칸_동시영업최대']


# ───────────────────────── 데이터 읽기 (필요한 열만) ─────────────────────────
def most_common(tab, key):
    """key별로 가장 많이 나온 격자ID (가게가 같은 칸·지번이면 격자도 같아야 하지만 좌표 보충 차이 대비)."""
    c = tab.dropna(subset=['격자ID']).groupby([key, '격자ID']).size().reset_index(name='n')
    c = c.sort_values([key, 'n', '격자ID'], ascending=[True, False, True]).drop_duplicates(key)
    return c.set_index(key)['격자ID']


def load():
    kan = pd.read_parquet(BASE / KAN, columns=KAN_COLS)
    for c in ('칸ID', '지번키', '층', '상호', '업태'):
        kan[c] = kan[c].astype(object)
    tab = pd.read_parquet(BASE / TABLE, columns=['site', 'jibun', '격자ID'])
    # 데이터 기준일: 칸 테이블 attrs의 censor, 없으면 개업·폐업일 최댓값
    censor = pd.Timestamp(kan.attrs.get('censor') or max(kan['개업일'].max(), kan['폐업일'].max()))

    # 칸별 요약: 진짜 폐업 수(전체), 기준일 직전 3년 진짜 폐업 수 (전체 / 30일 미만 제외)
    kan['초단기'] = kan['폐업일'].notna() & (kan['생존기간'] < SHORT_DAYS)
    recent = kan['폐업여부'].eq(1) & (kan['폐업일'] <= censor) & (kan['폐업일'] > censor - pd.Timedelta(days=WINDOW_DAYS))
    g = kan.groupby('칸ID')
    site = pd.DataFrame({
        '지번키': g['지번키'].first(),
        '진짜폐업': g['폐업여부'].sum(),
        '최근3년': recent.groupby(kan['칸ID']).sum(),
        '최근3년_30일제외': (recent & ~kan['초단기']).groupby(kan['칸ID']).sum(),
        '초단기폐업': (kan['폐업여부'].eq(1) & kan['초단기']).groupby(kan['칸ID']).sum(),
        '초단기있음': (kan['생존기간'] < SHORT_DAYS).groupby(kan['칸ID']).any(),
        '가게수': g.size(),
        '동시영업최대': g['칸_동시영업최대'].max(),
    })
    # 250m 격자: 칸 → 격자ID, 없으면 같은 지번의 격자ID
    by_site, by_jibun = most_common(tab, 'site'), most_common(tab, 'jibun')
    site['격자ID'] = site.index.map(by_site)
    site['격자ID'] = site['격자ID'].fillna(site['지번키'].map(by_jibun))
    grid = site.dropna(subset=['격자ID']).groupby('격자ID').agg(
        격자_칸수=('진짜폐업', 'size'), 격자_진짜폐업=('진짜폐업', 'mean'), 격자_최근3년=('최근3년', 'mean'))

    # 0번 기준 생존율 (효과 크기 시트)
    xl = pd.ExcelFile(BASE / RESULT)
    sheet = next(s for s in xl.sheet_names if s.startswith('효과 크기'))
    eff = pd.read_excel(xl, sheet)
    eff.columns = [eff.columns[0]] + [int(float(c)) for c in eff.columns[1:]]
    row0 = eff[eff.iloc[:, 0].astype(float) == 0].iloc[0]
    s0 = {t: float(row0[t]) for t in (1, 3, 5)}
    dongs = set(kan['지번키'].str.rsplit(' ', n=1).str[0].unique())    # '서울특별시 마포구 서교동'
    return dict(kan=kan, site=site, grid=grid, s0=s0, censor=censor, dongs=dongs)


# ───────────────────────── 주소 해석 ─────────────────────────
def normalize(text):
    s = re.sub(r'\s+', ' ', (text or '').strip())
    s = re.sub(r'^서울(?:특별시|시)?\s*', '', s)
    s = '서울특별시 ' + s
    s = re.sub(r'(\d)\s*번지', r'\1', s)
    # 층 표기 통일: B1 / B1F / b2층 → 지하1층, 1F / 2f → 1층 (B101호 같은 호수는 건드리지 않음)
    s = re.sub(r'(?<![A-Za-z0-9])[Bb]\s*(\d{1,2})(?!\d)\s*(?:[Ff](?![A-Za-z])|층)?', r'지하\1층', s)
    s = re.sub(r'(?<![\dA-Za-z])(\d{1,2})\s*[Ff](?![A-Za-z])', r'\1층', s)
    return s


def looks_like_road(s):
    return bool(re.search(r'\S+(?:로|길)\s*\d', s)) and not re.search(r'\S+(?:동|가)\d*가?\s+(?:산\s*)?\d', s)


def resolve(text):
    """입력 → (지번, 층 라벨 또는 None, 안내문). 지번을 못 찾으면 지번=None."""
    s = normalize(text)
    jibun, rest = L.parse_jibun(s)
    if jibun is None:
        if looks_like_road(s):
            return None, None, '도로명주소는 칸 테이블에 없어요. 지번주소로 입력해 주세요 (예: 마포구 서교동 123-4 1층).'
        return None, None, '주소를 읽지 못했어요. "마포구 서교동 123-4 1층"처럼 구·동·번지·층 순서로 입력해 주세요.'
    floor, _, _ = L.parse_floor(rest, '')
    return jibun, floor, ''


# ───────────────────────── 출력 도우미 ─────────────────────────
def dw(s):
    return sum(2 if east_asian_width(ch) in 'WF' else 1 for ch in str(s))


def pad(s, w, right=False):
    s = str(s)
    if dw(s) > w:                                   # 너무 길면 자르기
        out = ''
        for ch in s:
            if dw(out + ch) > w - 1:
                break
            out += ch
        s = out + '…'
    gap = ' ' * (w - dw(s))
    return gap + s if right else s + gap


def letters(i):
    out = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def mask_jibun(jibun, anon):
    """익명 모드: '서울특별시 마포구 서교동 123-4' → '마포구 ○○동' (구까지만)."""
    if not anon:
        return jibun
    return jibun.split(' ')[1] + ' ○○동'


def floor_text(fl):
    return f'지하 {fl[1:]}층' if fl.startswith('B') else f'{fl}층'


def surv(s0_t, k):
    return s0_t ** (HR ** k)


# ───────────────────────── 한 칸 보여주기 ─────────────────────────
def show_kan(D, kan_id, anon):
    kan, site = D['kan'], D['site']
    rows = kan[kan['칸ID'] == kan_id].sort_values('칸내순번')
    st = site.loc[kan_id]
    jibun, fl = kan_id.split('|')
    print()
    print('━' * 78)
    print(f' 칸: {mask_jibun(jibun, anon)} · {floor_text(fl)}   (가게 {len(rows)}곳, 2010년 이후 인허가)')
    print('━' * 78)

    # 1) 계보 표
    names = {}
    if anon:
        for n in rows['상호']:
            names.setdefault(n, f'가게 {letters(len(names))}')
    W = [4, 25, 20, 10, 9, 10]
    head = ['순번', '개업 ~ 폐업', '상호', '업태', '생존일수', '폐업·양도']
    print(' ' + ' '.join(pad(h, w) for h, w in zip(head, W)) + '  이전폐업')
    print(' ' + '─' * (sum(W) + len(W) + 9))
    fmt = '%Y-%m' if anon else '%Y-%m-%d'           # 익명 모드는 연-월까지만
    for _, r in rows.iterrows():
        od = r['개업일'].strftime(fmt)
        cd = r['폐업일'].strftime(fmt) if pd.notna(r['폐업일']) else '영업중'
        if r['폐업여부'] == 1:
            stat = '진짜 폐업'
        elif r['양도여부'] == 1:
            stat = '양도'
        else:
            stat = '영업 중'
        days = f"{int(r['생존기간']):,}" + ('' if pd.notna(r['폐업일']) else '+')
        name = names.get(r['상호'], r['상호']) if anon else r['상호']
        cells = [r['칸내순번'], f'{od} ~ {cd}', name, r['업태'], days, stat]
        line = ' '.join(pad(c, w, right=(i in (0, 4))) for i, (c, w) in enumerate(zip(cells, W)))
        mark = '  (초단기·임시 영업 의심)' if r['초단기'] else ''
        print(' ' + line + f"  {int(r['이전폐업수']):>4}" + mark)
    print(' (생존일수 + = 영업 중, 데이터 기준일까지 · 양도 = 폐업 후 30일 안에 같은 칸 재입점, 폐업으로 안 셈')
    print('  이전폐업 = 그 가게 개업 직전 3년, 같은 칸, 다른 상호의 진짜 폐업 수)')

    # 2) 요약
    k, k2 = int(st['최근3년']), int(st['최근3년_30일제외'])
    c = D['censor']
    g = D['grid'].loc[st['격자ID']] if pd.notna(st['격자ID']) and st['격자ID'] in D['grid'].index else None
    print()
    print(' [요약]')
    L1 = 44
    print(f"  {pad('이 칸의 진짜 폐업 수 (2010년 이후)', L1)}: {int(st['진짜폐업'])}회")
    print(f"  {pad('지금 새로 들어간다면 최근 3년 진짜 폐업 수', L1)}: {k}회"
          + (f' (30일 미만 제외 {k2}회)' if k2 != k else '')
          + f"  ({(c - pd.Timedelta(days=WINDOW_DAYS - 1)).date()} ~ {c.date()}, 데이터 기준일까지)")
    if g is not None:
        lab = f"같은 250m 격자의 칸 평균 (칸 {int(g['격자_칸수'])}곳)"
        print(f"  {pad(lab, L1)}: 진짜 폐업 {g['격자_진짜폐업']:.2f}회 · 최근 3년 {g['격자_최근3년']:.2f}회")
    else:
        print(f"  {pad('같은 250m 격자의 칸 평균', L1)}: 격자 정보 없음 (좌표 결측)")
    if st['초단기폐업'] > 0:
        print(f"  ⚠ 초단기 폐업 {int(st['초단기폐업'])}회 포함 — 임시·행사 영업일 수 있음")

    # 3) 예측
    s0 = D['s0']
    print()
    print(f' [예측]  S(t) = S0(t) ^ (HR^k),  HR = {HR:.2f},  k = 최근 3년 진짜 폐업 수')
    W2 = 32
    print('  ' + pad('', W2) + '   '.join(f'{t}년 생존' for t in (1, 3, 5)))
    print('  ' + pad('0번 자리', W2) + '   '.join(f'{s0[t] * 100:>7.1f}%' for t in (1, 3, 5)))
    for lab, kk in [(f'이 자리 · 전체 k={k}', k), (f'이 자리 · 30일 미만 제외 k={k2}', k2)]:
        print('  ' + pad(lab, W2) + '   '.join(f'{surv(s0[t], kk) * 100:>7.1f}%' for t in (1, 3, 5)))
    print('  예측은 업종·면적·동네가 평균인 가게 기준 (M2), 이 칸의 실제 조건은 반영 안 됨')
    print(f'  → 이전 폐업 {k}번인 자리에서 3년 생존 예측 약 {surv(s0[3], k) * 100:.1f}% '
          f'(0번인 자리는 {s0[3] * 100:.1f}%)')
    if k2 != k:
        print(f'  → 30일 미만 가게를 빼면 {k2}번 → 약 {surv(s0[3], k2) * 100:.1f}%')
    if k >= 4:
        print('  ※ 4번 이상은 분석 표본에서 드문 구간이라 외삽입니다. 수치는 참고만.')
    if st['동시영업최대'] > 1:
        print(f"  ※ 한 층에 가게가 동시에 최대 {int(st['동시영업최대'])}곳 (푸드코트·다점포 층) → "
              '"한 층 = 한 자리" 정의가 맞지 않는 칸이에요.')


def lookup(D, text, anon):
    jibun, floor, msg = resolve(text)
    if jibun is None:
        print(f'\n ⚠ {msg}')
        return
    floors = D['kan'].loc[D['kan']['지번키'] == jibun, '층'].unique().tolist()
    floors.sort(key=lambda f: -int(f[1:]) if f.startswith('B') else int(f))
    where = mask_jibun(jibun, anon)
    dong = jibun.rsplit(' ', 1)[0]
    if not floors and dong not in D['dongs']:
        if re.search(r'(?:로|길)$', dong):          # '양화로 45'처럼 lineage 규칙상 동 자리에 도로명이 들어간 경우
            print('\n ⚠ 도로명주소는 칸 테이블에 없어요. 지번주소로 입력해 주세요 (예: 마포구 서교동 123-4 1층).')
        else:
            print(f'\n ⚠ 데이터 없음: "{dong}" 동 이름을 데이터에서 찾지 못했어요. 법정동 이름인지 확인해 주세요.')
        return
    if not floors:
        print(f'\n ⚠ 데이터 없음: {where} 에는 2010년 이후 일반음식점 인허가가 없어요.')
        return
    if floor is None:
        print(f"\n 층이 없어서 이 지번의 모든 층을 보여줘요: {', '.join(floor_text(f) for f in floors)}")
        for f in floors:
            show_kan(D, f'{jibun}|{f}', anon)
    elif floor in floors:
        show_kan(D, f'{jibun}|{floor}', anon)
    else:
        print(f"\n ⚠ {where} · {floor_text(floor)} 칸은 데이터에 없어요. "
              f"같은 지번의 다른 층: {', '.join(floor_text(f) for f in floors)}")


def demo_picks(D):
    """기준일 직전 3년 진짜 폐업 0, 1, 2, 3회 이상인 칸을 하나씩
    (단일 점포 칸, 가게 2곳 이상, 격자 있음, 생존 30일 미만 가게 없음)."""
    s = D['site']
    rng = np.random.default_rng(DEMO_SEED)
    ok = (s['동시영업최대'] == 1) & (s['가게수'] >= 2) & s['격자ID'].notna() & ~s['초단기있음']
    picks = []
    for lo, hi in [(0, 0), (1, 1), (2, 2), (3, 10 ** 6)]:
        cand = s.index[ok & s['최근3년'].between(lo, hi)]
        if len(cand) == 0:
            cand = s.index[~s['초단기있음'] & s['최근3년'].between(lo, hi)]
        if len(cand):
            picks.append(sorted(cand)[rng.integers(len(cand))])
    return picks


def footer():
    print()
    print(f' 통제 후 남는 연관이며 원인이 아님. 동네 몫을 빼면 1회당 HR 약 {HR_PLACEBO:.2f} (위약 검증)')


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass
    args = sys.argv[1:]
    demo = '--demo' in args
    anon = '--anon' in args or demo
    addrs = [a for a in args if not a.startswith('--')]

    print(' 데이터 읽는 중…', flush=True)
    D = load()
    print(f" 칸 {len(D['site']):,}곳 · 가게 {len(D['kan']):,}곳 · 데이터 기준일 {D['censor'].date()}"
          + ('  [익명 모드]' if anon else ''))

    if demo:
        for i, kid in enumerate(demo_picks(D), 1):
            print(f"\n\n ▶ 시연 {i}: 최근 3년 진짜 폐업 {int(D['site'].loc[kid, '최근3년'])}회인 칸")
            show_kan(D, kid, anon)
        footer()
        return
    if addrs:
        for a in addrs:
            if not anon:                      # 익명 모드에서는 입력 주소를 다시 찍지 않음
                print(f'\n 입력: {a}')
            lookup(D, a, anon)
        footer()
        return
    while True:
        try:
            a = input('\n지번주소 (빈 줄이면 종료) > ').strip()
        except EOFError:
            break
        if not a:
            break
        lookup(D, a, anon)
        footer()


if __name__ == '__main__':
    main()
