"""
지역 차이 심화 (탐색적, 코딩 1) — python explore_region.py → out/1128_지역차이_심화.xlsx
교수님 피드백 "지역 차이를 변수로(건대·홍대 vs 월계동)"를 범주 4개(RQ8) 말고 연속적인 동네 특성으로 다시 본다.
질문: 이전 폐업 1회의 위험 크기가 동네 특성(회전율·밀도·지가·유동인구)에 따라 달라지는가?
방법: 동네 특성을 3분위(하·중·상)로 나눠 분위별 기울기(X × 분위) + 분위 더미 + M2, 기울기 동일 Wald 검정(df=2).
      + 연속형 상호작용(X × 표준화 특성) 계수. 회전율·밀도는 개업 시점 값, 지가·생활인구는 2026년 값(탐색적).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from analysis_main import cox          # noqa: E402
from sens_short import main_sample     # noqa: E402

OUT = BASE / 'out'
MODS = [('hex_closure_rate_3y', '동네 회전율 (100m, 개업 전 3년 폐업률)', '개업 시점'),
        ('hex_density', '동네 음식점 밀도 (100m)', '개업 시점'),
        ('log_공시지가', '공시지가 (log)', '2026년 값, 탐색적'),
        ('생활인구', '생활인구', '2026년 값, 탐색적')]


def main():
    t, d, M2 = main_sample()
    extra = t[['license_id', '공시지가', 'log_공시지가', '생활인구']]
    d = d.drop(columns=[c for c in ['공시지가', 'log_공시지가', '생활인구'] if c in d]).merge(extra, on='license_id', how='left')
    rows, base_rows = [], []
    for var, lab, when in MODS:
        dd = d.dropna(subset=[var]).copy()
        dd['q'] = pd.qcut(dd[var].rank(method='first'), 3, labels=['하', '중', '상'])
        xv, ctrl = [], []
        for g in ['하', '중', '상']:
            dd[f'X_{g}'] = dd['prior_closures'] * (dd['q'] == g)
            xv.append(f'X_{g}')
            if g != '하':
                dd[f'Q_{g}'] = (dd['q'] == g).astype(float)
                ctrl.append(f'Q_{g}')
        o, r, used = cox(dd, xv, ctrl + M2)
        b, V = r.params[:3], r.cov_params()[:3, :3]
        C = np.array([[1, -1, 0], [1, 0, -1]], float)
        w = float((C @ b) @ np.linalg.solve(C @ V @ C.T, C @ b))
        p_w = 1 - stats.chi2.cdf(w, 2)
        # 연속형 상호작용
        dd['z'] = (dd[var] - dd[var].mean()) / dd[var].std()
        dd['X_z'] = dd['prior_closures'] * dd['z']
        o2, _, _ = cox(dd, ['prior_closures', 'X_z'], ['z'] + M2)
        iz = o2.iloc[1]
        for i, g in enumerate(['하', '중', '상']):
            s = dd[dd['q'] == g]
            rows.append({'동네 특성': lab, '값 시점': when, '분위': g,
                         '범위': f"{s[var].min():.3g} ~ {s[var].max():.3g}",
                         '1회당 HR': o.iloc[i]['HR'], 'CI_low': o.iloc[i]['CI_low'], 'CI_high': o.iloc[i]['CI_high'],
                         '가게 수': len(s), '3년 안 폐업률': s['dead_3y'].mean(), '이전 폐업 1회 이상 비율': (s['prior_closures'] >= 1).mean(),
                         '기울기 동일 p (Wald, df=2)': p_w,
                         '연속 상호작용 HR (특성 1SD당)': iz['HR'], '연속 상호작용 p': iz['p'], 'n': int(o.iloc[0]['n'])})
        print(lab, [round(o.iloc[i]['HR'], 3) for i in range(3)], 'Wald p', round(p_w, 3), 'int', round(iz['HR'], 3), round(iz['p'], 3), flush=True)
    res = pd.DataFrame(rows)
    note = pd.DataFrame({'항목': ['질문', '방법', '읽는 법', '주의'], '내용': [
        '이전 폐업 1회의 위험 크기가 동네 특성에 따라 달라지는가 (교수님 피드백: 지역 차이를 변수로)',
        '동네 특성 3분위별 기울기(X × 분위) + 분위 더미 + M2 통제. 기울기 동일 Wald 검정(df=2). 연속형 상호작용(X × 표준화 특성)도 함께.',
        '1회당 HR이 분위마다 비슷하고 Wald p가 크면 → 효과 크기는 동네와 무관. 3년 안 폐업률·이전 폐업 비율은 동네마다 다른 기본 수준.',
        '공시지가·생활인구는 2026년 값이라 탐색적. 탐색 4개 검정이라 p < 0.05 하나는 우연일 수 있음 (Bonferroni 기준 0.0125).']})
    with pd.ExcelWriter(OUT / '1128_지역차이_심화.xlsx') as w:
        note.to_excel(w, sheet_name='읽는 법', index=False)
        res.round(4).to_excel(w, sheet_name='분위별 결과', index=False)


if __name__ == '__main__':
    main()
