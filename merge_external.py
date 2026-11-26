"""
외부 변수 합치기 → analysis_table_v2 (코딩 1)

입력
  out/analysis_table_v1.parquet          가게 1줄 (2013~2022 개업 코호트)
  out/lineage.pkl                        칸 계보 (동시 영업 가게 수 계산용)
  data/1126_외부변수_코딩3.parquet        코딩 3: 격자ID(250m), 생활인구, 상권_코드, area_type, 공시지가, log_공시지가
출력
  out/analysis_table_v2.parquet

규칙
  - 행은 지우지 않는다. 매칭 안 된 값은 NaN으로 두고 모형 단계에서 빠지게 한다 (코딩 3 요청).
  - 좌표·coord_src는 코딩 3 공통 좌표 기준 (lineage.py에서 이미 반영). 외부 파일의 coord_src는 일치 확인 후 버린다.
  - 공시지가 0원(9건)은 오류로 보고 NaN, log_공시지가도 NaN.
  - max_concurrent: 그 칸에서 같은 날 동시에 영업한 가게 수의 최댓값.
    한 층에 가게 여럿(푸드코트·복합몰)인 칸을 가려내는 데 쓴다 (칸 = 한 자리라는 정의가 깨지는 곳).
주의 (코딩 3 메모)
  - 생활인구·공시지가는 2026년 값 하나로 고정 → 2013년 가게에도 같은 값. 지역의 상대 수준 통제용, 한계로 보고.
  - 관광특구 362곳(코호트)은 표본이 작고 대형 복합몰이 많음 → RQ8에서 따로 처리.
"""
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / 'out'
EXT = BASE / 'data' / '1126_외부변수_코딩3.parquet'


def max_concurrent(lin, tolerance_days=0, name='max_concurrent'):
    """칸별 '같은 날 동시에 영업한 가게 수'의 최댓값.
    tolerance_days: 앞 가게 폐업일을 이만큼 앞당겨 계산 → 그 이하의 짧은 겹침(인수인계·신고 지연)은 동시 영업으로 안 봄.
    D1에서는 양도 규칙과 같은 30일(식품위생법 제39조 1개월)을 쓴다."""
    censor = max(lin['od'].max(), lin['cd'].max())
    end = lin['cd'].fillna(censor + pd.Timedelta(days=tolerance_days + 1)) - pd.Timedelta(days=tolerance_days)
    end = end.where(end > lin['od'], lin['od'])
    ev = pd.concat([
        pd.DataFrame({'site': lin['site'], 'd': lin['od'], 'k': 1}),
        pd.DataFrame({'site': lin['site'], 'd': end, 'k': -1}),
    ]).sort_values(['site', 'd', 'k'])           # 같은 날이면 폐업(-1)을 먼저 처리
    ev['open'] = ev.groupby('site')['k'].cumsum()
    return ev.groupby('site')['open'].max().rename(name)


def main():
    t = pd.read_parquet(OUT / 'analysis_table_v1.parquet')
    lin = pd.read_pickle(OUT / 'lineage.pkl')
    ext = pd.read_parquet(EXT).rename(columns={'관리번호': 'license_id', 'coord_src': 'coord_src_ext'})
    m = t.merge(ext, on='license_id', how='left')
    bad = (m['coord_src'] != m['coord_src_ext']) & m['coord_src_ext'].notna()
    print('coord_src 불일치:', int(bad.sum()))
    m = m.drop(columns='coord_src_ext')
    zero = m['공시지가'] <= 0
    m.loc[zero, ['공시지가', 'log_공시지가']] = np.nan
    print('공시지가 0원 → NaN:', int(zero.sum()))
    m = m.merge(max_concurrent(lin), on='site', how='left')
    m = m.merge(max_concurrent(lin, 30, 'max_concurrent_30'), on='site', how='left')
    # D1 주표본: 어느 시점에도 가게가 1곳만 영업한 칸(30일 이하 겹침은 인수인계로 허용) = '단일 점포 칸'
    m['single_unit_site'] = m['max_concurrent_30'] <= 1
    # D3 RQ8 지역유형: 관광특구는 주표본에서 66곳(이전 폐업 1회 이상 1곳)이라 기울기 추정 불가 → RQ8에서 제외(기술통계만)
    m['area_rq8'] = m['area_type'].where(m['area_type'].isin(['발달상권', '골목상권', '상권밖', '전통시장']))
    print('주표본(단일 점포 칸):', int(m['single_unit_site'].sum()))
    m.to_parquet(OUT / 'analysis_table_v2.parquet', index=False)
    print(len(m), 'rows | 매칭률 area_type', round(m['area_type'].notna().mean(), 4),
          '생활인구', round(m['생활인구'].notna().mean(), 4), 'log_공시지가', round(m['log_공시지가'].notna().mean(), 4))
    print(m['area_type'].value_counts(dropna=False).to_dict())


if __name__ == '__main__':
    main()
