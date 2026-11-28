"""
본분석 결과 그림 6개 (코딩 2)

입력: out/1127_본분석_v1.xlsx (analysis_main.py 결과, 시트 이름으로 읽음)
출력: out/fig_*.png 6개 (dpi 160)
  fig_위험비_M0toM4.png      RQ1·2 연속형 (1회당)
  fig_위험비_민감도.png       민감도 (M2, 1회당 HR)
  fig_범주형_HR.png          RQ1 범주형 (0번 대비)
  fig_예측생존곡선_M2.png     예측 생존곡선 (M2)
  fig_효과크기_5년.png        효과 크기 (예측 생존)
  fig_지역유형_HR.png         RQ8 지역유형

모형은 다시 돌리지 않는다. 엑셀 표만 읽어서 그린다.
실행: python figures.py
"""
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager

BASE = Path(__file__).resolve().parent
OUT = BASE / 'out'
SRC = OUT / '1127_본분석_v1.xlsx'
DPI = 160
XLABEL = '이전 폐업 1회당 위험비 (95% CI)'

for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR']:
    if any(f == z.name for z in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = f
        break
plt.rcParams['axes.unicode_minus'] = False


def save(fig, name):
    fig.savefig(OUT / name, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    print('저장:', name)


def forest(d, labels, title, name, highlight_first=False):
    """숲 그림: 1행 = 점(HR) + 가로선(95% CI). 점선(HR = 1)은 '차이 없음'."""
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(d) + 1.5))
    for i, (hr, lo, hi) in enumerate(zip(d['HR'], d['CI_low'], d['CI_high'])):
        color = 'tab:red' if highlight_first and i == 0 else 'tab:blue'      # 주분석 행만 다른 색
        ax.errorbar(hr, i, xerr=[[hr - lo], [hi - hr]], fmt='o', capsize=3, color=color)
        ax.text(hi + 0.01, i, f'{hr:.2f} ({lo:.2f}–{hi:.2f})', va='center', fontsize=8)
    ax.axvline(1, ls='--', color='gray')
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(min(0.95, d['CI_low'].min() - 0.03), d['CI_high'].max() + 0.15)   # 오른쪽에 숫자 쓸 자리
    ax.set_xlabel(XLABEL)
    ax.set_title(title)
    save(fig, name)


def main():
    x = pd.read_excel(SRC, sheet_name=None)


    m = x['RQ1·2 연속형 (1회당)']
    forest(m, m['모형'], '통제 변수를 늘려도 위험비는 1보다 큼 (M0~M4)', 'fig_위험비_M0toM4.png')


    s = x['민감도 (M2, 1회당 HR)']
    forest(s, s['분석'], f'분석 기준을 바꿔도 위험비는 1보다 큼 (범위 {s["HR"].min():.2f}–{s["HR"].max():.2f})',
           'fig_위험비_민감도.png', highlight_first=True)

    c = x['RQ1 범주형 (0번 대비)']
    models = c['모형'].unique()
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(models) + 1.5))
    for k, color, shift in [('1번', 'tab:blue', -0.15), ('2번 이상', 'tab:red', 0.15)]:
        g = c[c['변수'] == k]                     # 시트에서 모형 순서가 같음 (M0 → M4)
        y = [i + shift for i in range(len(g))]
        ax.errorbar(g['HR'], y, xerr=[g['HR'] - g['CI_low'], g['CI_high'] - g['HR']],
                    fmt='o', capsize=3, color=color, label=f'이전 폐업 {k}')
    ax.axvline(1, ls='--', color='gray')
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models)
    ax.invert_yaxis()
    ax.set_xlabel('이전 폐업 0번 대비 위험비 (95% CI)')
    ax.set_title('이전 폐업 횟수별 위험비 (0번 대비, 95% CI)')
    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1))
    save(fig, 'fig_범주형_HR.png')

    sv = x['예측 생존곡선 (M2)']
    fig, ax = plt.subplots(figsize=(8, 5))
    for k, g in sv.groupby('이전 폐업'):
        ax.step(g['개업 후 연수'], g['예측 생존 확률'], where='post', label=f'이전 폐업 {k}번')
    ax.set_xlabel('개업 후 연수')
    ax.set_ylabel('예측 생존 확률')
    ax.set_ylim(0, 1.01)
    ax.set_xlim(0, sv['개업 후 연수'].max())
    ax.grid(alpha=0.3)
    ax.legend()
    ax.set_title('이전 폐업이 많은 칸일수록 예측 생존 확률이 낮음 (M2, 다른 변수는 평균)')
    save(fig, 'fig_예측생존곡선_M2.png')

    e = x['효과 크기 (예측 생존)']
    e.columns = [str(col) for col in e.columns]
    years = ['1', '3', '5']
    fig, ax = plt.subplots(figsize=(8, 5))
    for j, (_, r) in enumerate(e.iterrows()):
        bars = ax.bar([i + (j - 1) * 0.25 for i in range(3)], [r[yr] for yr in years], 0.25,
                      label=f'이전 폐업 {int(r["이전 폐업"])}번')
        ax.bar_label(bars, fmt='%.3f', fontsize=8, padding=2)
    ax.set_xticks(range(3))
    ax.set_xticklabels([f'{yr}년' for yr in years])
    ax.set_ylabel('예측 생존 확률')
    ax.set_ylim(0, 1.05)
    ax.legend()
    s0, s2 = e.loc[e['이전 폐업'] == 0, '5'].iloc[0], e.loc[e['이전 폐업'] == 2, '5'].iloc[0]
    ax.set_title(f'5년 예측 생존 확률: 이전 폐업 0번 {s0:.1%} → 2번 {s2:.1%} (M2)')
    save(fig, 'fig_효과크기_5년.png')

    a = x['RQ8 지역유형']
    p = a['기울기 동일 검정 p (Wald, df=3)'].iloc[0]
    forest(a, [f'{k} (n={n:,})' for k, n in zip(a['지역'], a['가게 수'])],
           f'지역유형별 위험비 차이는 뚜렷하지 않음 (기울기 동일 검정 p = {p:.2f})', 'fig_지역유형_HR.png')

    print('점검: M0~M4', len(m), '행 | 모두 HR > 1:', bool((m['HR'] > 1).all()))
    print('점검: 5년 예측 생존 (0/1/2번):', ' / '.join(f'{v:.3f}' for v in e['5']))
    print(f'점검: RQ8 Wald p = {p:.2f}')


if __name__ == '__main__':
    main()
