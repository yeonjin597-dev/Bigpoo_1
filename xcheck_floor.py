"""
층 검증: 우리가 주소에서 읽은 층 vs 소상공인시장진흥공단 상가(상권)정보의 '층정보' (코딩 1)

왜: 인허가 데이터에는 층 열이 없어서 주소 글자에서 층을 읽었다(lineage.parse_floor).
    같은 주소를 사람이 다시 읽는 것은 독립 검증이 아니므로, 출처가 다른 자료(국세청·카드사 기반)와 대조한다.
방법: 인허가에서 '지금 영업 중'인 가게 ↔ 상가정보 음식점을 (지번주소, 상호) 완전 일치로 짝짓고,
      두 데이터 모두 층이 있는 가게끼리 층 일치율을 본다.
한계: 영업 중인 가게만 대조됨(상가정보에 폐업 가게 없음), 짝짓기 비율 약 51%(깔끔한 표기일수록 짝지어지기 쉬움).
실행: python xcheck_floor.py   → out/1125_층검증_상가정보대조.xlsx
"""
import re
from pathlib import Path
import pandas as pd
import lineage as L

BASE = Path(__file__).resolve().parent
OUT = BASE / 'out' / '1125_층검증_상가정보대조.xlsx'


def norm_name(s):
    return s.fillna('').str.replace(r'[\s\(\)\[\]·\.\-_,&]', '', regex=True).str.lower()


def sbiz_floor(v):
    if pd.isna(v):
        return pd.NA
    v = str(v).strip()
    if v == '지':
        return 'B?'            # 지하인데 몇 층인지 모름
    if re.fullmatch(r'[Bb]\d+', v):
        return 'B' + str(int(v[1:]))
    if re.fullmatch(r'\d+', v):
        return str(int(v))
    return 'other'


def agree(ours, theirs):
    if theirs == 'B?':
        return ours.startswith('B')
    return ours == theirs


def main():
    raw = pd.read_pickle(BASE / 'out' / 'raw_parsed.pkl')
    s = pd.read_csv(L.SBIZ_IN, dtype=str, usecols=['상호명', '상권업종대분류명', '지번주소', '층정보', '호정보'])
    food = s[s['상권업종대분류명'] == '음식'].copy()
    food['nm'] = norm_name(food['상호명'])
    food['jibun'] = food['지번주소'].str.strip()
    food['fl_s'] = food['층정보'].map(sbiz_floor)

    op = raw[raw['cd'].isna()].copy()
    op['nm'] = norm_name(op['name'])
    m = op.merge(food[['jibun', 'nm', 'fl_s', '호정보']], on=['jibun', 'nm'], how='inner')
    m = m[~m.duplicated(['관리번호'], keep=False)]          # 한 가게가 여러 곳과 짝지어지면 제외

    both = m[m['floor'].notna() & m['fl_s'].notna() & (m['fl_s'] != 'other')].copy()
    both['ok'] = [agree(a, b) for a, b in zip(both['floor'], both['fl_s'])]
    both['구분'] = both['floor'].map(lambda x: '지하' if x.startswith('B') else ('1층' if x == '1' else '2층 이상'))
    both.loc[both['floor_range'].fillna(False), '구분'] = '범위 표기'

    # 범위 표기: 상가정보 층이 우리가 읽은 층 집합 안에 드는지
    rg = both[both['구분'] == '범위 표기'].copy()

    def within(r):
        fl = L.floors_in(str(r['지번주소'])) | L.floors_in(str(r['도로명주소']))
        v = r['fl_s']
        if v == 'B?':
            return any(f < 0 for f in fl)
        return (-int(v[1:]) if v.startswith('B') else int(v)) in fl
    rg['in_range'] = rg.apply(within, axis=1)

    summary = pd.DataFrame([
        ['상가정보 서울 음식점 수', len(food), '2026-09 기준, 영업 중'],
        ['상가정보 층정보 채워진 비율', round(food['층정보'].notna().mean(), 4), ''],
        ['인허가 영업 중 가게 수', len(op), ''],
        ['(지번, 상호) 완전 일치로 짝지어진 가게', len(m), f'{len(m) / len(op):.1%}'],
        ['둘 다 층 있는 가게', len(both), ''],
        ['지상층(1층 + 2층 이상, 범위 아님) 일치율', round(both[both['구분'].isin(['1층', '2층 이상'])]['ok'].mean(), 4),
         f"n={both['구분'].isin(['1층', '2층 이상']).sum()}"],
        ['범위 표기: 상가정보 층이 우리 범위 안', round(rg['in_range'].mean(), 4), f'n={len(rg)}. 우리는 가장 낮은 층을 칸으로 씀'],
    ], columns=['항목', '값', '비고'])

    by = both.groupby('구분')['ok'].agg(건수='size', 일치율='mean').round(4).reindex(['1층', '2층 이상', '범위 표기', '지하'])
    mis = (both[~both['ok']].groupby(['floor', 'fl_s']).size().sort_values(ascending=False)
           .head(15).rename('건수').reset_index().rename(columns={'floor': '우리(주소)', 'fl_s': '상가정보'}))
    nof = m[m['floor'].isna()]
    indep = pd.DataFrame([
        ['우리 주소에 층 없음', len(nof)],
        ['그중 상가정보에 층 있음', int(nof['fl_s'].notna().sum())],
        ['비율', round(nof['fl_s'].notna().mean(), 4)],
        ['그중 상가정보 층 = 1', int((nof['fl_s'] == '1').sum())],
    ], columns=['항목', '값'])
    basement = both[(both['구분'] == '지하') & ~both['ok']][['지번주소', '도로명주소', 'floor', 'fl_s']].head(30)
    limits = pd.DataFrame({'한계': [
        '영업 중인 가게만 대조됨. 폐업한 가게(분석의 핵심)는 상가정보에 없음',
        '짝짓기 비율 약 51%. 상호·주소가 깔끔한 가게일수록 짝지어지기 쉬워 일치율이 실제보다 높게 나올 수 있음',
        '상가정보는 지하를 1층으로 적는 경향(지하 표시 약 1.9%) → 지하 칸은 이 자료로 검증 불가, 민감도 분석으로 처리',
        '상가정보 층의 상당수가 "1"이라 기본값일 가능성 → 우리 주소에 층이 없는 가게를 상가정보로 채우는 데는 쓰지 않음',
    ]})
    with pd.ExcelWriter(OUT, engine='openpyxl') as w:
        summary.to_excel(w, sheet_name='요약', index=False)
        by.to_excel(w, sheet_name='구분별 일치율')
        mis.to_excel(w, sheet_name='불일치 조합', index=False)
        indep.to_excel(w, sheet_name='독립성 점검', index=False)
        basement.to_excel(w, sheet_name='지하 불일치 예시(내부용)', index=False)
        limits.to_excel(w, sheet_name='한계', index=False)
    print(summary.to_string(index=False)); print(by)


if __name__ == '__main__':
    main()
