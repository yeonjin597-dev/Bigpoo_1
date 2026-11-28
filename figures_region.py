"""
지역 차이 심화 그림 (코딩 1) — python figures_region.py
입력: out/1128_지역차이_심화.xlsx  →  out/fig_지역차이_구별.png, out/fig_지역차이_요약.png
"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

BASE = Path(__file__).resolve().parent
OUT = BASE / 'out'
X = OUT / '1128_지역차이_심화.xlsx'
C_MAIN, C_SUB, C_GRAY = '#3C3489', '#7F77DD', '#888780'
for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP']:
    if any(f == z.name for z in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = f
        break
plt.rcParams['axes.unicode_minus'] = False


def fig_gu():
    a = pd.read_excel(X, sheet_name='A 구별 기울기').sort_values('HR').reset_index(drop=True)
    p = a['기울기 동일 p (Wald, df=24)'].iloc[0]
    y = np.arange(len(a))
    fig, ax = plt.subplots(figsize=(7.8, 8.2))
    ax.errorbar(a['HR'], y, xerr=[a['HR'] - a['CI_low'], a['CI_high'] - a['HR']], fmt='o', color=C_SUB, ecolor='#CFCBF3',
                capsize=2, ms=5, label='구별 추정치 (95% CI)')
    ax.scatter(a['축소 HR (경험적 베이즈)'], y, marker='D', s=26, color=C_MAIN, zorder=3, label='잡음 보정 후 (경험적 베이즈)')
    ax.axvline(1, color=C_GRAY, ls='--', lw=1)
    ax.axvline(1.165, color=C_MAIN, ls=':', lw=1)
    ax.text(1.168, len(a) - 0.3, '서울 전체 1.17', color=C_MAIN, fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{g} ({n:,})" for g, n in zip(a['구'], a['가게 수'])], fontsize=8.5)
    ax.set_xlabel('이전 폐업 1회당 위험비 (M2 통제)')
    ax.set_title(f'구별 차이는 대부분 표본 잡음: 기울기 같음 검정 p = {p:.2f}', fontsize=11)
    ax.legend(fontsize=8, loc='lower right', frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / 'fig_지역차이_구별.png', dpi=160)
    plt.close(fig)


def fig_summary():
    q = pd.read_excel(X, sheet_name='분위별 결과')
    b = pd.read_excel(X, sheet_name='B 사례 동네')
    c = pd.read_excel(X, sheet_name='C 성장·쇠퇴 동네')
    r8 = pd.read_excel(OUT / '1127_본분석_v1.xlsx', sheet_name='RQ8 지역유형')
    rows = []
    rows += [('지역 유형', f'{g}', h, l, u) for g, h, l, u in zip(r8['지역'], r8['HR'], r8['CI_low'], r8['CI_high'])]
    rows += [('사례 동네', g.split(' (')[0], h, l, u) for g, h, l, u in zip(b['동네'], b['HR'], b['CI_low'], b['CI_high'])]
    rows += [('동네 추세 (3년)', g, h, l, u) for g, h, l, u in zip(c['동네 추세'], c['HR'], c['CI_low'], c['CI_high'])]
    for lab, short in [('동네 회전율 (100m, 개업 전 3년 폐업률)', '동네 회전율'), ('동네 음식점 밀도 (100m)', '음식점 밀도')]:
        s = q[q['동네 특성'] == lab]
        rows += [(short, f'{short} {g}', h, l, u) for g, h, l, u in zip(s['분위'], s['1회당 HR'], s['CI_low'], s['CI_high'])]
    pv = {'지역 유형': r8.iloc[0, -1], '사례 동네': b.iloc[0, -1], '동네 추세 (3년)': c['기울기 동일 p (Wald, df=2)'].iloc[0],
          '동네 회전율': q.loc[q['동네 특성'].str.startswith('동네 회전율'), '기울기 동일 p (Wald, df=2)'].iloc[0],
          '음식점 밀도': q.loc[q['동네 특성'].str.startswith('동네 음식점'), '기울기 동일 p (Wald, df=2)'].iloc[0]}
    df = pd.DataFrame(rows, columns=['그룹', '이름', 'HR', 'lo', 'hi'])
    y = np.arange(len(df))[::-1]
    fig, ax = plt.subplots(figsize=(7.8, 0.36 * len(df) + 1.6))
    cols = {k: v for k, v in zip(pv, [C_MAIN, C_SUB, '#1D9E75', '#BA7517', '#888780'])}
    for i, r in df.iterrows():
        ax.errorbar(r['HR'], y[i], xerr=[[r['HR'] - r['lo']], [min(r['hi'], 1.9) - r['HR']]], fmt='o', color=cols[r['그룹']], capsize=2, ms=5)
    ax.axvline(1, color=C_GRAY, ls='--', lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(df['이름'], fontsize=8.5)
    ax.set_xlim(0.8, 1.9)
    for g in pv:
        yy = y[df.index[df['그룹'] == g]].mean()
        ax.text(1.62, yy, f'{g}\n같음 검정 p = {pv[g]:.2f}', fontsize=7.5, color=cols[g], va='center')
    ax.set_xlabel('이전 폐업 1회당 위험비 (95% CI, M2 통제)')
    ax.set_title('어떻게 나눠 봐도 한 번 망한 자리의 위험 크기는 비슷함', fontsize=11)
    ax.spines[['top', 'right']].set_visible(False)
    fig.text(0.01, 0.01, '월계동은 가게 170곳(이전 폐업 24곳)이라 구간이 넓음. 1.9 이상은 잘라서 표시', fontsize=7.5, color=C_GRAY)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT / 'fig_지역차이_요약.png', dpi=160)
    plt.close(fig)




def fig_activity():
    x = pd.read_excel(OUT / '1128_동네활성도.xlsx', sheet_name=None)
    b = x['B 위험 크기 (분위별)']
    b = b[b['나눈 기준'] == '동네 활성도 5분위'].reset_index(drop=True)
    c = x['C 빈 자리 다시 채워지는 속도']
    labs = ['1\n조용', '2', '3', '4', '5\n번화']
    xx = np.arange(5)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.9))
    ax = axes[0]
    ax.bar(xx - 0.2, b['3년 안 폐업률'] * 100, 0.4, color=C_MAIN, label='3년 안 폐업률')
    ax.bar(xx + 0.2, b['이전 폐업 1회 이상 비율'] * 100, 0.4, color='#CFCBF3', label='망한 자리 비율')
    for i, v in enumerate(b['3년 안 폐업률'] * 100):
        ax.text(i - 0.2, v + 0.6, f'{v:.0f}', ha='center', fontsize=8)
    ax.set_xticks(xx); ax.set_xticklabels(labs, fontsize=8.5); ax.set_ylabel('%'); ax.set_ylim(0, 42)
    ax.set_title('① 번화할수록 기본 폐업률은 낮음', fontsize=10.5)
    ax.legend(fontsize=7.5, frameon=False, loc='upper right')
    ax = axes[1]
    ax.errorbar(xx, b['1회당 HR'], yerr=[b['1회당 HR'] - b['CI_low'], b['CI_high'] - b['1회당 HR']], fmt='o', color=C_MAIN, capsize=3)
    ax.axhline(1, color=C_GRAY, ls='--', lw=1)
    ax.set_xticks(xx); ax.set_xticklabels(labs, fontsize=8.5); ax.set_ylim(0.95, 1.35)
    ax.set_ylabel('이전 폐업 1회당 위험비')
    ax.set_title(f"② 망한 자리의 위험 배수는 같음 (p = {b['기울기 같음 p (Wald)'].iloc[0]:.2f})", fontsize=10.5)
    ax = axes[2]
    ax.bar(xx, c['1년 안에 다음 가게 입점 비율'] * 100, 0.55, color=C_SUB)
    for i, v in enumerate(c['1년 안에 다음 가게 입점 비율'] * 100):
        ax.text(i, v + 0.8, f'{v:.0f}', ha='center', fontsize=8)
    ax.set_xticks(xx); ax.set_xticklabels(labs, fontsize=8.5); ax.set_ylim(0, 45); ax.set_ylabel('%')
    ax.set_title('③ 폐업 뒤 1년 안에 다음 가게 입점', fontsize=10.5)
    for a in axes:
        a.spines[['top', 'right']].set_visible(False)
    fig.suptitle('동네 활성도(생활인구·공시지가·음식점 밀도) 5분위: 동네는 기본 위험을 바꾸지만 저주의 배수는 바꾸지 않음', fontsize=11)
    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT / 'fig_지역차이_동네활성도.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    fig_gu()
    fig_summary()
    fig_activity()
    print('saved')
