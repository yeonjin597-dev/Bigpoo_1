"""
양도 판정 채점 (코딩 1) — python score_transfer.py <비코딩1.xlsx> [<비코딩2.xlsx>]
출력: out/1127_양도판정_채점.xlsx

기준(참값) = 사람 판정, 비교 대상 = 컴퓨터 30일 규칙(코드_판정). 날짜 간격은 판정자에게 숨김(블라인드).
- 묶음 A(0~30일): 컴퓨터 = 양도 → '사람도 양도' 비율 = 30일 규칙의 양도 판정이 맞을 확률(양성 예측도)
- 묶음 B(31~90일)·C(91~365일): 컴퓨터 = 폐업 → '사람은 양도' 비율 = 30일 규칙이 놓친 양도
- 판단불가는 일치율 계산에서 빼고 건수를 따로 보고
- 전체 일치율은 묶음별 모집단 크기(A 19,806 / B 3,610 / C 5,227)로 가중
- 규칙 준수: 판정자가 적은 A·B·C로 판정 규칙을 다시 적용한 결과와 최종 판정이 같은지
- OECD 문자 그대로: B 아니오 + A 예 → 양도(주인만 바뀜)로 본 판정
- 교차 25줄(두 사람 모두 판정)이 있으면 Cohen κ
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

BASE = Path(__file__).resolve().parent
KEY = BASE / 'sheets' / '1124_양도판정385_정답_코딩1만.xlsx'
PLAN = BASE / 'sheets' / '1124b_양도판정_분배표_코딩1만.xlsx'
POP = {'A': 19806, 'B': 3610, 'C': 5227}
COLS = {'A. 업태(하는 장사) 이어짐': 'A', 'B. 상호·간판 이어짐': 'B', 'C. 로드뷰': 'C', '최종 판정': '판정', '메모': '메모'}


def rule(a, b, c):
    if b == '예':
        return '양도'
    if b == '아니오' and a == '아니오':
        return '폐업후새가게'
    if b == '아니오' and a == '예':
        return {'이어짐': '양도', '끊김': '폐업후새가게'}.get(c, '판단불가')
    return '판단불가'


def oecd(a, b):
    if b == '예' or (b == '아니오' and a == '예'):
        return '양도'          # 위치 같음 + 바뀐 요소 1개 이하 → 연속
    if b == '아니오' and a == '아니오':
        return '폐업후새가게'
    return '판단불가'


def load(path, who):
    v = pd.read_excel(path, sheet_name='판정').rename(columns=COLS)
    v['판정자'] = who
    v['판정'] = v['판정'].fillna('판단불가')   # 빈칸(미기입)은 판단불가로 처리
    for c in ['A', 'B', 'C']:
        v[c] = v[c].astype(object).where(v[c].notna(), '미기입')
    return v[['구분', '번호', 'A', 'B', 'C', '판정', '메모', '판정자']]


def ci(k, n):
    if n == 0:
        return (np.nan, np.nan)
    return proportion_confint(k, n, method='wilson')


def score(df, verdict_col, label):
    rows = []
    for g in ['A', 'B', 'C']:
        s = df[df['묶음'] == g]
        valid = s[s[verdict_col] != '판단불가']
        k = int((valid[verdict_col] == valid['코드_판정']).sum()); n = len(valid)
        tr = int((valid[verdict_col] == '양도').sum())
        lo, hi = ci(k, n)
        rows.append({'판정 기준': label, '묶음': g, '컴퓨터 판정': '양도' if g == 'A' else '폐업후새가게',
                     '판정한 줄': len(s), '판단불가': int((s[verdict_col] == '판단불가').sum()), '판정 가능': n,
                     '일치': k, '일치율': k / n if n else np.nan, '95% CI 하한': lo, '95% CI 상한': hi,
                     '사람 판정 양도 비율': tr / n if n else np.nan})
    r = pd.DataFrame(rows)
    w = np.array([POP[g] for g in r['묶음']]); w = w / w.sum()
    r.loc[len(r)] = {'판정 기준': label, '묶음': '전체(모집단 가중)', '일치율': float(np.nansum(w * r['일치율'].values))}
    return r


def kappa(a, b):
    labs = sorted(set(a) | set(b))
    po = np.mean(np.array(a) == np.array(b))
    pe = sum((np.mean(np.array(a) == l)) * (np.mean(np.array(b) == l)) for l in labs)
    return (po - pe) / (1 - pe) if pe < 1 else np.nan, po


def main(paths):
    key = pd.read_excel(KEY)
    sheets = [load(p, f'비코딩{i + 1}') for i, p in enumerate(paths)]
    allj = pd.concat(sheets).merge(key, on='번호', how='left')
    allj['규칙 재적용'] = [rule(a, b, c) for a, b, c in zip(allj['A'], allj['B'], allj['C'])]
    allj['OECD 문자 그대로'] = [oecd(a, b) for a, b in zip(allj['A'], allj['B'])]
    own = allj[allj['구분'] != '교차'].copy()
    out = {}
    out['채점 (판정자 최종 판정)'] = score(own, '판정', '판정자 최종 판정')
    out['채점 (OECD 문자 그대로)'] = score(own, 'OECD 문자 그대로', 'OECD 문자 그대로 (B 아니오+A 예 = 양도)')
    comp = own.groupby('판정자').apply(lambda s: pd.Series({
        '본인 몫 줄 수': len(s), '최종 판정 = 규칙 재적용': int((s['판정'] == s['규칙 재적용']).sum()),
        '규칙 준수율': (s['판정'] == s['규칙 재적용']).mean(),
        '로드뷰 확인(이어짐/끊김)': int(s['C'].isin(['이어짐', '끊김']).sum()), '사진없음': int((s['C'] == '사진없음').sum())}))
    out['판정자별 규칙 준수'] = comp.reset_index()
    out['규칙과 다른 판정 (확인용)'] = own[own['판정'] != own['규칙 재적용']][['판정자', '번호', '묶음', 'A', 'B', 'C', '판정', '규칙 재적용', '메모']]
    # 묶음별 오분류 방향 (시뮬레이션 입력)
    mis = []
    for g in ['A', 'B', 'C']:
        r = out['채점 (판정자 최종 판정)'].query('묶음 == @g').iloc[0]
        mis.append({'묶음': g, '컴퓨터 판정': r['컴퓨터 판정'], '오분류율 (1 - 일치율)': 1 - r['일치율'], '판정 가능 n': r['판정 가능']})
    out['오판정률 (시뮬레이션용)'] = pd.DataFrame(mis)
    if len(paths) == 2:
        x = allj[allj['구분'] == '교차'][['번호', '판정', '판정자']]
        y = allj[allj['구분'] != '교차'][['번호', '판정', '판정자']]
        m = x.merge(y, on='번호', suffixes=('_교차', '_원래'))
        k, po = kappa(m['판정_교차'].tolist(), m['판정_원래'].tolist())
        out['교차 판정 일치도'] = pd.DataFrame({'항목': ['교차 줄 수', '단순 일치율', "Cohen's κ"], '값': [len(m), po, k]})
        out['교차 판정 상세'] = m
    else:
        out['교차 판정 일치도'] = pd.DataFrame({'항목': ['상태'], '값': ['비코딩 2 파일이 오면 계산']})
    with pd.ExcelWriter(BASE / 'out' / '1127_양도판정_채점.xlsx', engine='openpyxl') as w:
        for k_, v in out.items():
            v.round(4).to_excel(w, sheet_name=k_[:31], index=False)
    for k_ in ['채점 (판정자 최종 판정)', '채점 (OECD 문자 그대로)', '판정자별 규칙 준수', '교차 판정 일치도']:
        print('==', k_); print(out[k_].round(3).to_string(index=False))
    print('규칙과 다른 판정', len(out['규칙과 다른 판정 (확인용)']))


if __name__ == '__main__':
    main(sys.argv[1:])
