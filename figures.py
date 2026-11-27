"""
결과 그림 (코딩 2 작업 5) — python figures.py
입력: out/1127_본분석_v1.xlsx (모형을 다시 돌리지 않고 엑셀만 읽음)
출력: out/fig_위험비_M0toM4.png, fig_위험비_민감도.png, fig_범주형_HR.png,
      fig_예측생존곡선_M2.png, fig_효과크기_5년.png, fig_지역유형_HR.png
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
XLSX = OUT / '1127_본분석_v1.xlsx'
DPI = 160
C_MAIN, C_SUB, C_GRAY = '#3C3489', '#7F77DD', '#888780'   # 주결과 / 나머지 / 기준선
XLAB = '이전 폐업 1회당 위험비 (95% CI)'

for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP']:
    if any(f == z.name for z in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = f
        break
plt.rcParams['axes.unicode_minus'] = False


def sheet(name):
    return pd.read_excel(XLSX, sheet_name=name)


def forest(df, label_col, fn, title, highlight_first=False, note=None):
    """숲 그림: 줄마다 HR 점 + 95% CI 선, 1에 점선."""
    df = df.reset_index(drop=True)
    y = np.arange(len(df))[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(df) + 1.4))
    for i, r in df.iterrows():
        c = C_MAIN if (highlight_first and i == 0) or not highlight_first else C_SUB
        ax.errorbar(r['HR'], y[i], xerr=[[r['HR'] - r['CI_low']], [r['CI_high'] - r['HR']]],
                    fmt='o', color=c, ecolor=c, capsize=3, ms=6)
        ax.text(r['CI_high'] + 0.005, y[i], f"{r['HR']:.2f}", va='center', fontsize=8, color=c)
    ax.axvline(1, color=C_GRAY, ls='--', lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(df[label_col], fontsize=9)
    ax.set_xlabel(XLAB)
    ax.set_title(title, fontsize=11)
    ax.spines[['top', 'right']].set_visible(False)
    if note:
        fig.text(0.01, 0.01, note, fontsize=7.5, color=C_GRAY)
    plt.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(OUT / fn, dpi=DPI)
    plt.close(fig)
    print('saved', fn)


def fig_m0_m4():
    df = sheet('RQ1·2 연속형 (1회당)')
    forest(df, '모형', 'fig_위험비_M0toM4.png', '통제를 늘려도 이전 폐업 1회당 위험비는 1보다 큼',
           note='M0~M3: n=56,224 / M3·M4 부분표본(직전 가게 있음): n=13,757')


def fig_sensitivity():
    df = sheet('민감도 (M2, 1회당 HR)')
    forest(df, '분석', 'fig_위험비_민감도.png', '기준을 바꿔도 위험비는 1보다 큼 (첫 줄 = 주분석)', highlight_first=True)


def fig_categorical():
    df = sheet('RQ1 범주형 (0번 대비)')
    models = list(dict.fromkeys(df['모형']))
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(models) + 1.5))
    y0 = np.arange(len(models))[::-1]
    for k, (lev, c, off) in enumerate([('1번', C_SUB, 0.15), ('2번 이상', C_MAIN, -0.15)]):
        s = df[df['변수'] == lev].set_index('모형').loc[models]
        ax.errorbar(s['HR'], y0 + off, xerr=[s['HR'] - s['CI_low'], s['CI_high'] - s['HR']],
                    fmt='o', color=c, capsize=3, label=f'이전 폐업 {lev} (0번 대비)')
    ax.axvline(1, color=C_GRAY, ls='--', lw=1)
    ax.set_yticks(y0)
    ax.set_yticklabels(models, fontsize=9)
    ax.set_xlabel('위험비 (95% CI), 기준 = 이전 폐업 0번')
    ax.set_title('이전 폐업이 많을수록 위험비가 커짐 (2번 이상 > 1번)', fontsize=11)
    ax.legend(fontsize=8, loc='upper center', bbox_to_anchor=(0.5, -0.13), ncol=2, frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / 'fig_범주형_HR.png', dpi=DPI)
    plt.close(fig)
    print('saved fig_범주형_HR.png')


def fig_curve():
    df = sheet('예측 생존곡선 (M2)')
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    for v, c in zip([0, 1, 2], [C_GRAY, C_SUB, C_MAIN]):
        s = df[df['이전 폐업'] == v]
        ax.step(s['개업 후 연수'], s['예측 생존 확률'], where='post', color=c, lw=2, label=f'이전 폐업 {v}번')
    for yr in [5]:
        ax.axvline(yr, color=C_GRAY, lw=0.6, ls=':')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 1)
    ax.set_xlabel('개업 후 연수')
    ax.set_ylabel('예측 영업 지속 확률')
    ax.set_title('M2 통제 후 예측 생존곡선 (다른 변수는 평균값)', fontsize=11)
    ax.legend(frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / 'fig_예측생존곡선_M2.png', dpi=DPI)
    plt.close(fig)
    print('saved fig_예측생존곡선_M2.png')


def fig_effect():
    df = sheet('효과 크기 (예측 생존)').set_index('이전 폐업')
    df.columns = [int(c) for c in df.columns]
    years = [1, 3, 5]
    w = 0.25
    x = np.arange(len(years))
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    for k, (v, c) in enumerate(zip([0, 1, 2], [C_GRAY, C_SUB, C_MAIN])):
        vals = df.loc[v, years].values
        b = ax.bar(x + (k - 1) * w, vals * 100, w, color=c, label=f'이전 폐업 {v}번')
        for rect, val in zip(b, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, val * 100 + 1, f'{val * 100:.1f}', ha='center', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f'{y}년' for y in years])
    ax.set_ylim(0, 105)
    ax.set_ylabel('예측 영업 지속 확률 (%)')
    gap = (df.loc[0, 5] - df.loc[2, 5]) * 100
    ax.set_title(f'이전 폐업 0번 → 2번이면 5년 생존 확률이 {gap:.1f}%p 낮음 (M2)', fontsize=11)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[['top', 'right']].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / 'fig_효과크기_5년.png', dpi=DPI)
    plt.close(fig)
    print('saved fig_효과크기_5년.png')


def fig_region():
    df = sheet('RQ8 지역유형')
    p = df['기울기 동일 검정 p (Wald, df=3)'].iloc[0]
    df = df.assign(label=[f"{a} (가게 {n:,})" for a, n in zip(df['지역'], df['가게 수'])])
    forest(df, 'label', 'fig_지역유형_HR.png', f'지역 유형별 위험비 (기울기 같음 검정 p = {p:.2f})')


if __name__ == '__main__':
    fig_m0_m4()
    fig_sensitivity()
    fig_categorical()
    fig_curve()
    fig_effect()
    fig_region()
