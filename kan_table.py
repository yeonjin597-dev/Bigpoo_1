"""
칸 테이블 (가게 1행) + make_kan_table(df) — 코딩 3 위약(placebo) 검증용 (코딩 1)

일반음식점과 똑같은 규칙으로 휴게음식점 등 다른 업종 인허가 데이터에도 돌릴 수 있게 함수 하나로 묶었다.
규칙은 전부 lineage.py와 같은 함수를 그대로 부른다(규칙이 두 군데서 달라지지 않도록).

사용법
    import pandas as pd
    from kan_table import make_kan_table
    df = pd.read_csv('휴게음식점_원본.csv', encoding='cp949', encoding_errors='replace', dtype=str)
    kan = make_kan_table(df)                                   # 가게 1행
    kan = kan.merge(coords, on='관리번호', how='left')          # 좌표·외부변수는 관리번호로 붙이기

규칙 (일반음식점과 동일)
  - 서울 밖 주소 제외
  - 칸 = 지번 + 층 (주소 글자에서 추출, 여러 층 표기면 가장 낮은 층). 지번이나 층을 못 찾으면 칸에서 빠짐
  - 2010-01-01 이후 개업 가게로 칸 계보를 만든다
  - 양도 = 앞 가게 폐업 후 30일 안에 같은 칸에 다음 가게 개업 (식품위생법 제39조) → 앞 가게는 '폐업 아님'
  - 이전폐업수 = 그 가게 개업일 직전 3년(1,095일) 안에, 같은 칸에서, 다른 상호의 가게가 '진짜 폐업'한 수
                 (폐업일 < 개업일만 셈 → 미래 정보 없음)
  - 생존기간 = 개업일 ~ 폐업일(영업 중이면 관찰 종료일) 일수
주의
  - 2010~2012년 개업 가게는 3년 창이 2010년 이전으로 넘어가 이전폐업수가 덜 세어진다 → 분석은 '코호트여부'=True(2013~2022 개업)만
  - 이전폐업수에 양도는 안 들어간다 (양도는 '폐업 아님')
"""
import numpy as np
import pandas as pd
import lineage as L
from merge_external import max_concurrent

COLS = {
    '관리번호': '관리번호', 'site': '칸ID', 'jibun': '지번키', 'floor': '층', 'floor_range': '층_여러층표기',
    'gu': '구', 'name': '상호', 'category': '업태', 'od': '개업일', 'cd': '폐업일',
    'event_ours': '폐업여부', 'transfer': '양도여부', 'duration_days': '생존기간',
    'prior_closures': '이전폐업수', 'other_floor_closures': '다른층폐업수', 'seq': '칸내순번',
    'n_in_site': '칸_가게수', 'max_concurrent': '칸_동시영업최대', 'cohort': '코호트여부',
    'event_jari': '폐업여부_jari', 'event_parsa': '폐업여부_parsa',
}


def make_kan_table(df, transfer_days=L.TRANSFER_DAYS, window_days=L.WINDOW_DAYS,
                   start=L.LINEAGE_START, cohort=L.COHORT, censor=None, already_standardized=False):
    """인허가 원본(pd.read_csv 그대로) → 가게 1행 칸 테이블. 인자를 바꾸면 민감도 분석에도 쓸 수 있다."""
    raw = df if already_standardized else L.standardize(df)
    if 'jibun' not in raw.columns:
        raw = L.add_address(raw)
    if censor is None:
        censor = max(raw['od'].max(), raw['cd'].max())       # 원본의 가장 늦은 날짜
    lin = L.build_lineage(raw, transfer_days=transfer_days, start=start).copy()
    lin['row'] = np.arange(len(lin))
    fails = lin[lin['event_ours']]
    lin['prior_closures'] = L.count_prior(lin, fails, 'site', window_days)
    lin['other_floor_closures'] = L.count_prior(lin, fails, 'jibun', window_days, other_floor=True)
    end = lin['cd'].fillna(censor).clip(upper=censor)
    lin['duration_days'] = (end - lin['od']).dt.days
    lin['n_in_site'] = lin.groupby('site')['site'].transform('size')
    lin = lin.merge(max_concurrent(lin), on='site', how='left')
    lin['cohort'] = (lin['od'] >= cohort[0]) & (lin['od'] < cohort[1])
    for k in ('ours', 'jari', 'parsa'):
        lin[f'event_{k}'] = lin[f'event_{k}'].astype(int)
    lin['transfer'] = lin['transfer'].astype(int)
    out = lin[list(COLS)].rename(columns=COLS)
    out.attrs['censor'] = str(pd.Timestamp(censor).date())
    return out


if __name__ == '__main__':
    import time
    t0 = time.time()
    raw = pd.read_pickle(L.OUT_DIR / 'raw_parsed.pkl')            # 일반음식점: 캐시 재사용
    seoul = raw['지번주소'].fillna('').str.startswith('서울특별시') | raw['도로명주소'].fillna('').str.startswith('서울특별시')
    kan = make_kan_table(raw[seoul], already_standardized=True)
    kan.to_parquet(L.OUT_DIR / '1126_칸테이블_가게단위_일반음식점.parquet', index=False)
    kan.sample(100, random_state=42).sort_values(['칸ID', '칸내순번']).to_csv(
        L.OUT_DIR / '1126_칸테이블_샘플100.csv', index=False, encoding='utf-8-sig')
    print(len(kan), 'rows | cohort', int(kan['코호트여부'].sum()), '| censor', kan.attrs['censor'], f'| {time.time() - t0:.0f}s')
