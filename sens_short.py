"""
민감도: 초단기 영업(생존 N일 미만 폐업) 가게를 계보에서 빼고 이전 폐업 수를 다시 센다 (코딩 1)
python sens_short.py  →  out/1127_민감도_초단기제외.xlsx
                         out/analysis_table_v2_short30.parquet   (코딩 3 위약 재실행용, 30일 기준)
                         out/1127_칸테이블_가게단위_short30.parquet

배경 (코딩 3 발견, main.py 시연 중): 같은 상호가 매년 4~9일씩만 인허가를 냈다 닫는 칸이 있음 (행사·임시 영업 추정).
  이런 폐업이 '진짜 폐업'으로 세어지고, 다음 가게의 prior_closures에도 들어감.
설계
  S1 계보에서 제외: 원본에서 폐업일이 있고 (폐업일 - 개업일) < N일인 인허가를 지운 뒤 make_kan_table로 계보·X·폐업 재계산.
     → 초단기 가게는 X에도, 분석 대상에도 들어가지 않음. N = 14 / 30 / 60 / 90일 (기준 하나에 기대지 않도록 범위 확인, 원칙 P2)
  S2 분석 대상에서만 제외: X는 그대로 두고 생존 30일 미만 가게만 표본에서 뺌 (차이가 X 때문인지 표본 때문인지 분리)
  통제변수(M2)는 주분석 값을 그대로 씀 (100m 동네 폐업률에는 초단기 가게가 남아 있음 → 한계로 적음)
"""
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from analysis_main import cox                 # noqa: E402
from cox_models import prepare                # noqa: E402
from kan_table import make_kan_table          # noqa: E402

OUT = BASE / 'out'
THRESHOLDS = [14, 30, 60, 90]
SHARE_N = 30


def main_sample():
    t = pd.read_parquet(OUT / 'analysis_table_v2.parquet')
    full, cat_cols, yr_cols, _ = prepare(t)
    M1 = cat_cols + yr_cols + ['log_area', 'site_age_y']
    M2 = M1 + ['hex_closure_rate_3y', 'hex_density_100', 'hex_density_100_sq']
    M3 = M2 + ['other_floor_closures']
    d = full[full['single_unit_site']].dropna(subset=M3 + ['prior_closures', 'duration_days']).copy()
    return t, d[d['duration_days'] > 0], M2


def main():
    t, d, M2 = main_sample()
    raw = pd.read_pickle(OUT / 'raw_parsed.pkl')
    raw = raw[raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')]
    life = (raw['cd'] - raw['od']).dt.days
    rows, desc = [], []

    def add(label, dd, note=''):
        o, _, _ = cox(dd, ['prior_closures'], M2)
        r = o.iloc[0].to_dict()
        r.update(분석=label, 비고=note)
        rows.append(r)
        print(label, round(r['HR'], 4), round(r['CI_low'], 4), round(r['CI_high'], 4), int(r['n']), int(r['events']), flush=True)

    add('주분석 (초단기 포함)', d)
    for n in THRESHOLDS:
        t0 = time.time()
        short = raw['cd'].notna() & (life < n)
        k = make_kan_table(raw[~short], already_standardized=True)
        kk = k[['관리번호', '이전폐업수', '폐업여부', '생존기간']].rename(columns={'관리번호': 'license_id'})
        dd = d.drop(columns=['event_ours']).merge(kk, on='license_id', how='inner')
        changed = (dd['prior_closures'] != dd['이전폐업수'])
        dd = dd.assign(prior_closures=dd['이전폐업수'], event_ours=dd['폐업여부'], duration_days=dd['생존기간'])
        dd = dd[dd['duration_days'] > 0]
        add(f'S1 계보에서 제외: 생존 {n}일 미만', dd,
            f'원본에서 지운 인허가 {int(short.sum()):,}건 / 주표본에서 빠진 가게 {len(d) - len(dd):,} / X가 바뀐 가게 {int(changed.sum()):,}')
        desc.append({'기준(일)': n, '원본에서 지운 인허가': int(short.sum()),
                     '주표본에서 빠진 가게': len(d) - len(dd), 'X가 바뀐 가게': int(changed.sum()),
                     'X 평균 (전→후)': f"{d['prior_closures'].mean():.4f} → {dd['prior_closures'].mean():.4f}",
                     '소요(초)': round(time.time() - t0)})
        if n == SHARE_N:      # 코딩 3 위약 재실행용 파일
            tt = t.drop(columns=['prior_closures', 'event_ours', 'duration_days']).merge(
                kk.rename(columns={'이전폐업수': 'prior_closures', '폐업여부': 'event_ours', '생존기간': 'duration_days'}),
                on='license_id', how='inner')
            tt['prior_closures_cat'] = tt['prior_closures'].clip(upper=4).astype(int).astype(str).replace({'4': '4+'})
            tt.to_parquet(OUT / 'analysis_table_v2_short30.parquet', index=False)
            k.to_parquet(OUT / '1127_칸테이블_가게단위_short30.parquet', index=False)
    add('S2 분석 대상에서만 제외: 생존 30일 미만 (X는 그대로)', d[d['duration_days'] >= 30])

    res = pd.DataFrame(rows)[['분석', 'HR', 'CI_low', 'CI_high', 'p', 'n', 'events', '비고']]
    note = pd.DataFrame({'항목': ['배경', 'S1', 'S2', '통제', '공유 파일', '해석'], '내용': [
        '코딩 3 발견: 같은 상호가 매년 수일씩만 인허가를 냈다 닫는 칸(행사·임시 영업 추정). 주표본에서 생존 30일 미만 455곳, 그중 진짜 폐업 364건.',
        '원본에서 (폐업일 - 개업일) < N일인 인허가를 지우고 계보·이전 폐업 수·폐업 여부를 다시 계산. N = 14/30/60/90일로 범위 확인.',
        '이전 폐업 수는 그대로, 생존 30일 미만 가게만 표본에서 제외.',
        'M2 (업태·개업연도·면적·칸 경과 연수·100m 동네 폐업률·밀도). 동네 폐업률은 주분석 값(초단기 포함) 그대로.',
        'analysis_table_v2_short30.parquet / 1127_칸테이블_가게단위_short30.parquet (30일 기준, 코딩 3 위약 재실행용)',
        '주분석 HR과 S1·S2가 비슷하면 초단기 영업이 결과를 만든 것이 아님.']})
    with pd.ExcelWriter(OUT / '1127_민감도_초단기제외.xlsx') as w:
        note.to_excel(w, sheet_name='읽는 법', index=False)
        res.round(4).to_excel(w, sheet_name='결과 (M2, 1회당 HR)', index=False)
        pd.DataFrame(desc).to_excel(w, sheet_name='제외 규모', index=False)
    print(pd.DataFrame(desc).to_string())


if __name__ == '__main__':
    main()
