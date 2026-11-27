"""
위약(placebo) 검증 (코딩 3) — python placebo.py [--n 100] [--workers 4] → out/1128_위약검증_코딩3.xlsx + out/fig_위약_*.png

주분석과 같은 조건: analysis_main.cox() (statsmodels PHReg, Breslow, 칸 군집 강건 SE), cox_models.prepare(),
  표본 = single_unit_site & M3 변수까지 결측 없음 & 생존기간 > 0 (analysis_main.main()의 d와 동일), 통제 = M2.
  동네 고정효과(strata)는 쓰지 않는다 (같은 칸 앞뒤 가게 비교가 섞이는 기계적 편향, analysis_main D5 참고).
  [A] 격자 셔플: 격자ID 안에서 prior_closures를 무작위로 섞어 N_SHUFFLE번 재추정 → 실제 HR의 순위 p
  [B] 다른 층 위약: 노출 = other_floor_closures, 그리고 prior_closures와 함께
  [C] 동네 평균 통제: 같은 격자 다른 가게들의 prior_closures 평균(자기 제외) grid_mean_pc 추가
  [D] 다른 업종: 일반음식점 KAN과 휴게음식점 칸 테이블에 같은 단순 모형
셔플은 회당 약 3분 → --workers개 하위 프로세스(BLAS 스레드 1개씩)가 out/shuffle_log_w{k}.csv에 매회 append,
  끝나면(또는 중단·재실행 때) out/shuffle_log.csv로 합친다. 이미 끝난 회차는 건너뛴다.
  각 회차는 seed=[SEED, 회차]로 섞으므로 중간에 끊겨도 결과가 같다. 로그에는 입력 파일·seed가 함께 적혀
  설정이 바뀌면(예: 양도 규칙을 바꾼 TABLE) 이전 행은 쓰지 않는다.
상호·주소(칸ID·지번)는 저장하지 않는다 (요약 수치만).
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

# ───────────── 설정 (양도 규칙이 바뀌면 파일만 바꿔서 다시 실행) ─────────────
TABLE = 'out/analysis_table_v2.parquet'
KAN = 'out/1126_칸테이블_가게단위_일반음식점.parquet'
HUGE = 'data/휴게음식점_원본.csv'
N_SHUFFLE = 100
WORKERS = 1          # 셔플 병렬 워커 수 (워커당 메모리 약 0.8GB, BLAS 스레드 1개)
SEED = 42            # 회차 i는 np.random.default_rng([SEED, i])
OUT_XLSX = 'out/1128_위약검증_코딩3.xlsx'
SHUFFLE_LOG = 'out/shuffle_log.csv'
FIG_PREFIX = 'out/fig_위약_'
GRID = '격자ID'

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from analysis_main import cox          # noqa: E402
from cox_models import prepare         # noqa: E402

EXPO = 'prior_closures'


def p_(path):
    p = Path(path)
    return p if p.is_absolute() else BASE / p


def judge(row, rule):
    return '버팀' if rule(row) else '뒤집힘'


# ───────────── 주분석 표본 ─────────────
def load_main(table):
    t = pd.read_parquet(table)
    if GRID not in t.columns:
        sys.exit(f'{table}에 {GRID} 열이 없음')
    full, cat_cols, yr_cols, _ = prepare(t)
    M2 = cat_cols + yr_cols + ['log_area', 'site_age_y', 'hex_closure_rate_3y', 'hex_density_100', 'hex_density_100_sq']
    M3 = M2 + ['other_floor_closures']
    d = full[full['single_unit_site']].dropna(subset=M3 + [EXPO, 'duration_days']).copy()
    d = d[d['duration_days'] > 0].reset_index(drop=True)
    blank = d[GRID].astype('string').str.strip().eq('').fillna(False).to_numpy(dtype=bool)
    n_nan = int(d[GRID].isna().sum())
    d.loc[blank, GRID] = np.nan                        # 빈 문자열('')·공백도 결측으로 → 셔플 안 함, C에서도 빠짐
    print(f'주표본 {len(d):,}  폐업 {int(d["event_ours"].sum()):,}  격자ID 결측 NaN {n_nan:,} + 빈 문자열 {int(blank.sum()):,}',
          flush=True)
    return d, M2


# ───────────── [A] 격자 셔플 ─────────────
def shuffle_within(values, groups, rng):
    """groups가 같은 행끼리만 values를 섞는다. groups 결측 행은 그대로."""
    out = values.copy()
    ok = np.flatnonzero(pd.notna(groups))
    g = pd.factorize(groups[ok])[0]
    src = ok[np.lexsort((rng.random(len(ok)), g))]     # 그룹 안 무작위 순서
    dst = ok[np.lexsort((np.arange(len(ok)), g))]      # 그룹 안 원래 순서
    out[dst] = values[src]
    return out


def worker_log(w):
    p = p_(SHUFFLE_LOG)
    return p.with_name(f'{p.stem}_w{w}{p.suffix}')


def merge_logs():
    """워커별 로그(shuffle_log_w*.csv)를 shuffle_log.csv에 합치고 워커 로그는 지운다 (중단 후 재실행 때도 먼저 합침)."""
    main_p = p_(SHUFFLE_LOG)
    parts = sorted(main_p.parent.glob(f'{main_p.stem}_w*{main_p.suffix}'))
    if not parts:
        return
    frames = [pd.read_csv(f) for f in ([main_p] if main_p.exists() else []) + parts]
    log = pd.concat(frames, ignore_index=True).drop_duplicates(['i', 'table', 'seed'], keep='last')
    log.sort_values(['table', 'seed', 'i']).to_csv(main_p, index=False, encoding='utf-8-sig')
    for f in parts:
        f.unlink()
    print(f'  워커 로그 {len(parts)}개 → {SHUFFLE_LOG}에 합침 (총 {len(log)}행)', flush=True)


def read_log(table_name, seed):
    main_p = p_(SHUFFLE_LOG)
    if not main_p.exists():
        return pd.DataFrame(columns=['i', 'HR', 'CI_low', 'CI_high', 'p', 'n', 'events', 'sec', 'table', 'seed'])
    log = pd.read_csv(main_p)
    same = (log['table'].astype(str) == table_name) & (log['seed'].astype(str) == str(seed))
    if (~same).any():
        print(f'  shuffle_log: 설정이 다른 행 {int((~same).sum())}개는 무시 (table/seed 다름)')
    return log[same].drop_duplicates('i', keep='last')


def shuffle_items(d, M2, items, seed, log_path, table_name, tag=''):
    """items의 각 회차를 seed=[seed, i]로 섞어 cox(M2) → 한 줄씩 log_path에 append."""
    base_vals = d[EXPO].to_numpy()
    grp = d[GRID].to_numpy(dtype=object)
    for k, i in enumerate(items):
        t0 = time.time()
        rng = np.random.default_rng([seed, i])
        ds = d.assign(**{EXPO: shuffle_within(base_vals, grp, rng)})
        o, _, _ = cox(ds, [EXPO], M2)
        r = o.iloc[0]
        row = pd.DataFrame([{'i': i, 'HR': r['HR'], 'CI_low': r['CI_low'], 'CI_high': r['CI_high'], 'p': r['p'],
                             'n': int(r['n']), 'events': int(r['events']), 'sec': round(time.time() - t0, 1),
                             'table': table_name, 'seed': seed}])
        row.to_csv(log_path, mode='a', header=not log_path.exists(), index=False, encoding='utf-8-sig')
        print(f'  {tag}셔플 i={i} ({k + 1}/{len(items)})  HR {r["HR"]:.4f}  {time.time() - t0:.0f}s', flush=True)


def run_shuffle(n, seed, table_name, workers, a):
    """남은 회차를 workers개 하위 프로세스에 나눠 돌린다. 각 워커는 BLAS 스레드 1개, 자기 로그 파일에 기록."""
    merge_logs()
    done_i = set(read_log(table_name, seed)['i'].astype(int))
    todo = [i for i in range(n) if i not in done_i]
    workers = max(1, min(workers, len(todo))) if todo else 0
    print(f'[A] 셔플 {n}회 중 완료 {n - len(todo)}회, 남은 {len(todo)}회 → 워커 {workers}개', flush=True)
    if todo:
        env = os.environ.copy()
        env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONIOENCODING='utf-8')
        procs = []
        for w in range(workers):
            items = todo[w::workers]
            cmd = [sys.executable, str(Path(__file__).resolve()), '--table', a.table,
                   '--worker-id', str(w), '--items', ','.join(map(str, items))]
            procs.append(subprocess.Popen(cmd, env=env, cwd=str(BASE)))
        try:
            codes = [p.wait() for p in procs]
        except KeyboardInterrupt:
            for p in procs:
                p.terminate()
            merge_logs()
            sys.exit('중단 — 끝난 회차는 저장됨. 같은 명령으로 다시 실행하면 이어서 함')
        merge_logs()
        if any(codes):
            sys.exit(f'워커 오류 (종료 코드 {codes}) — 끝난 회차는 저장됨. 다시 실행하면 이어서 함')
    log = read_log(table_name, seed)
    return log[log['i'].astype(int) < n].sort_values('i').reset_index(drop=True)


# ───────────── [D] 다른 업종 ─────────────
def kan_model(kan, label):
    k = kan[(kan['코호트여부'].astype(bool)) & (kan['칸_동시영업최대'] == 1)].copy()
    k['duration_days'] = pd.to_numeric(k['생존기간'], errors='coerce')
    k['폐업여부'] = k['폐업여부'].astype(int)
    k['이전폐업수'] = k['이전폐업수'].astype(float)
    yr = pd.to_datetime(k['개업일']).dt.year.astype(str)
    top = k['업태'].value_counts()
    cat = k['업태'].where(k['업태'].isin(top[top >= 1000].index), '기타')
    yd = pd.get_dummies(yr, prefix='yr', drop_first=True, dtype=float)
    cd = pd.get_dummies(cat, prefix='cat', drop_first=True, dtype=float)
    k = pd.concat([k, yd, cd], axis=1)
    o, _, _ = cox(k, ['이전폐업수'], list(yd.columns) + list(cd.columns), event='폐업여부', cluster='칸ID')
    print(f'[D] {label}: HR {o["HR"].iloc[0]:.4f}  n {int(o["n"].iloc[0]):,}', flush=True)
    return o.assign(업종=label)


def check_columns(kan_h, kan_g, raw_h):
    from kan_table import COLS
    need_raw = ['인허가일자', '폐업일자', '사업장명', '업태구분명', '소재지면적', '좌표정보(X)', '좌표정보(Y)',
                '지번주소', '도로명주소', '관리번호']
    miss_raw = [c for c in need_raw if c not in raw_h.columns]
    ref = list(kan_g.columns) if kan_g is not None else list(COLS.values())
    a, b = set(kan_h.columns), set(ref)
    if miss_raw or a != b:
        print('열 이름이 일반음식점과 다름 → 중단')
        if miss_raw:
            print('  휴게음식점 원본에 없는 열:', miss_raw)
        print('  휴게음식점에만 있음:', sorted(a - b))
        print('  일반음식점에만 있음:', sorted(b - a))
        sys.exit(1)


def part_d(kan_path, huge_path):
    rows, notes = [], []
    kan_g = None
    if kan_path.exists():
        kan_g = pd.read_parquet(kan_path)
    else:
        notes.append(f'일반음식점 KAN 없음: {kan_path.relative_to(BASE) if kan_path.is_relative_to(BASE) else kan_path}')
    if huge_path.exists():
        from kan_table import make_kan_table
        t0 = time.time()
        raw_h = pd.read_csv(huge_path, encoding='cp949', dtype=str, encoding_errors='replace', low_memory=False)
        kan_h = make_kan_table(raw_h)
        print(f'[D] 휴게음식점 칸 테이블 {len(kan_h):,}행 ({time.time() - t0:.0f}s)', flush=True)
        check_columns(kan_h, kan_g, raw_h)
    else:
        kan_h = None
        notes.append(f'휴게음식점 원본 없음: {huge_path}')
    if kan_g is not None:
        rows.append(kan_model(kan_g, '일반음식점 (기준)'))
    if kan_h is not None:
        rows.append(kan_model(kan_h, '휴게음식점'))
    for n_ in notes:
        print('[D] 건너뜀 —', n_, flush=True)
    return (pd.concat(rows) if rows else pd.DataFrame()), notes


# ───────────── 그림 ─────────────
def setup_font():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR']:
        if any(f == z.name for z in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams['axes.unicode_minus'] = False
    return plt


def fig_shuffle(plt, hrs, real, path):
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.hist(hrs, bins=min(30, max(5, len(hrs) // 5)), color='#B4B2A9', edgecolor='white')
    ax.axvline(real, color='#D85A30', lw=2, label=f'실제 HR {real:.3f}')
    ax.axvline(1, color='#888780', ls='--', lw=1)
    ax.set_xlabel('이전 폐업 1회당 위험비 (M2)')
    ax.set_ylabel('셔플 횟수')
    ax.set_title(f'격자 안에서 이전 폐업 수를 섞었을 때 (N={len(hrs)})')
    ax.legend()
    plt.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ───────────── 실행 ─────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=N_SHUFFLE, help='셔플 횟수')
    ap.add_argument('--table', default=TABLE)
    ap.add_argument('--kan', default=KAN)
    ap.add_argument('--huge', default=HUGE)
    ap.add_argument('--workers', type=int, default=WORKERS, help='셔플 병렬 워커 수 (워커당 약 0.8GB)')
    ap.add_argument('--worker-id', type=int, default=None, help=argparse.SUPPRESS)   # 내부용
    ap.add_argument('--items', default='', help=argparse.SUPPRESS)                   # 내부용
    a = ap.parse_args()
    table, kan_path, huge_path = p_(a.table), p_(a.kan), p_(a.huge)
    t_all = time.time()
    if a.worker_id is not None:                                    # 워커 모드: 받은 회차만 돌리고 끝
        d, M2 = load_main(table)
        items = [int(s) for s in a.items.split(',') if s]
        shuffle_items(d, M2, items, SEED, worker_log(a.worker_id), Path(a.table).name, tag=f'[w{a.worker_id}] ')
        return
    d, M2 = load_main(table)
    res, report = {}, []

    # 실제 HR (= 주분석 M2)
    main_o, _, _ = cox(d, [EXPO], M2)
    real = main_o.iloc[0]
    print(f'실제 HR (주분석 M2) {real["HR"]:.4f} [{real["CI_low"]:.4f}, {real["CI_high"]:.4f}]', flush=True)
    report.append({'검증': '주분석 (M2)', '변수': EXPO, **real[['HR', 'CI_low', 'CI_high', 'p', 'n', 'events']].to_dict(),
                   '판정': '기준', '판정 기준': '-'})

    # [A]
    log = run_shuffle(a.n, SEED, Path(a.table).name, a.workers, a)
    hrs = log['HR'].to_numpy()
    p_rank = (1 + int((hrs >= real['HR']).sum())) / (len(hrs) + 1)
    res['A 셔플 요약'] = pd.DataFrame({'항목': ['실제 HR', '셔플 횟수', '셔플 HR 평균', '셔플 HR 2.5%', '셔플 HR 97.5%',
                                            '셔플 HR ≥ 실제 HR 개수', '순위 p = (1+개수)/(N+1)', '셔플 안 한 행 (격자ID 결측)'],
                                     '값': [real['HR'], len(hrs), hrs.mean(), np.quantile(hrs, .025), np.quantile(hrs, .975),
                                           int((hrs >= real['HR']).sum()), p_rank, int(d[GRID].isna().sum())]})
    res['A 셔플 전체'] = log.drop(columns=['table'])
    report.append({'검증': f'A 격자 셔플 (N={len(hrs)})', '변수': EXPO, 'HR': real['HR'],
                   'CI_low': np.quantile(hrs, .025), 'CI_high': np.quantile(hrs, .975), 'p': p_rank,
                   'n': real['n'], 'events': real['events'],
                   '판정': '버팀' if p_rank < 0.05 else '뒤집힘',
                   '판정 기준': '순위 p < 0.05 (CI 칸 = 셔플 HR 2.5~97.5%, p = 순위 p)'})

    # [B]
    b1, _, _ = cox(d, ['other_floor_closures'], M2)
    b2, _, _ = cox(d, [EXPO, 'other_floor_closures'], M2)
    res['B 다른 층 위약'] = pd.concat([b1.assign(모형='다른 층만'), b2.assign(모형='둘 다')])
    r = b1.iloc[0]
    report.append({'검증': 'B 다른 층 위약 (다른 층만)', '변수': 'other_floor_closures',
                   **r[['HR', 'CI_low', 'CI_high', 'p', 'n', 'events']].to_dict(),
                   '판정': '버팀' if r['HR'] < real['CI_low'] else '뒤집힘',
                   '판정 기준': '다른 층 HR < 주분석 HR의 CI 하한 (칸 효과가 건물 효과보다 큼)'})
    r = b2.iloc[0]
    report.append({'검증': 'B 다른 층 위약 (둘 다, 칸 계수)', '변수': EXPO,
                   **r[['HR', 'CI_low', 'CI_high', 'p', 'n', 'events']].to_dict(),
                   '판정': '버팀' if r['CI_low'] > 1 else '뒤집힘', '판정 기준': 'prior_closures CI 하한 > 1'})
    print('[B]', res['B 다른 층 위약'][['변수', 'HR', 'CI_low', 'CI_high', '모형']].round(4).values.tolist(), flush=True)

    # [C] 같은 격자 다른 가게들의 prior_closures 평균 (자기 제외)
    g = d.groupby(GRID)[EXPO]
    s, c = g.transform('sum'), g.transform('count')
    d['grid_mean_pc'] = np.where(c > 1, (s - d[EXPO]) / (c - 1), np.nan)
    c1, _, _ = cox(d, [EXPO, 'grid_mean_pc'], M2)
    c0, _, _ = cox(d.dropna(subset=['grid_mean_pc']), [EXPO], M2)   # 같은 표본, 평균 없이 (비교용)
    res['C 동네 평균 통제'] = pd.concat([c1.assign(모형='+ grid_mean_pc'), c0.assign(모형='같은 표본, grid_mean_pc 없이')])
    r = c1.iloc[0]
    report.append({'검증': 'C 동네 평균 통제 (+grid_mean_pc)', '변수': EXPO,
                   **r[['HR', 'CI_low', 'CI_high', 'p', 'n', 'events']].to_dict(),
                   '판정': '버팀' if r['CI_low'] > 1 else '뒤집힘', '판정 기준': 'prior_closures CI 하한 > 1'})
    print('[C]', res['C 동네 평균 통제'][['변수', 'HR', 'CI_low', 'CI_high', '모형']].round(4).values.tolist(), flush=True)

    # [D]
    dres, dnotes = part_d(kan_path, huge_path)
    res['D 다른 업종'] = dres if len(dres) else pd.DataFrame({'메모': dnotes})
    for _, r in dres.iterrows():
        base = r['업종'].startswith('일반')
        report.append({'검증': f'D 다른 업종: {r["업종"]}', '변수': '이전폐업수',
                       **r[['HR', 'CI_low', 'CI_high', 'p', 'n', 'events']].to_dict(),
                       '판정': '기준' if base else ('버팀' if r['CI_low'] > 1 else '뒤집힘'),
                       '판정 기준': '-' if base else '휴게음식점에서도 CI 하한 > 1 (다른 업종에서 재현)'})
    if dnotes:
        report.append({'검증': 'D 다른 업종 (일부 건너뜀)', '변수': '-', '판정': '미실행', '판정 기준': ' / '.join(dnotes)})

    # 그림
    plt = setup_font()
    fig_shuffle(plt, hrs, real['HR'], p_(FIG_PREFIX + '격자셔플.png'))

    # 저장 (요약 수치만: 상호·주소·칸ID 없음)
    rep = pd.DataFrame(report).rename(columns={'events': '사건 수'})
    note = pd.DataFrame({'항목': ['입력', '표본', '모형', '통제 (M2)', 'A', 'B', 'C', 'D', '재현'], '내용': [
        f'TABLE={a.table} | KAN={a.kan} | HUGE={a.huge}',
        f'single_unit_site & M3 변수 결측 없음 & 생존기간>0: {len(d):,}곳, 폐업 {int(d["event_ours"].sum()):,}건 (주분석과 동일)',
        'analysis_main.cox (PHReg, Breslow, 칸 군집 강건 SE), 동네 고정효과(strata) 없음',
        '업태 더미 + 개업연도 더미 + log 면적 + 칸 경과 연수 + 100m 육각형 3년 폐업률 + 밀도 + 밀도²',
        f'{GRID} 안에서 prior_closures 셔플 (결측 격자는 그대로), seed=[{SEED}, 회차], N={len(hrs)}',
        '노출을 다른 층 폐업 수로 바꿈 / 둘 다 넣음',
        '같은 격자 다른 가게들의 prior_closures 평균(자기 제외). 격자에 가게 1곳이면 결측 → 표본에서 빠짐',
        '코호트여부 & 칸_동시영업최대==1, 노출 이전폐업수, 통제 = 개업연도 + 업태(1000건 미만 기타), 군집 칸ID',
        f'python placebo.py --n {a.n}  (셔플은 {SHUFFLE_LOG}에서 이어서 함)']})
    out = p_(OUT_XLSX)
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        rep.round(4).to_excel(w, sheet_name='보고 표', index=False)
        note.to_excel(w, sheet_name='읽는 법', index=False)
        for k, v in res.items():
            v.round(4).to_excel(w, sheet_name=k[:31], index=False)
    pd.set_option('display.width', 200)
    print(rep[['검증', 'HR', 'CI_low', 'CI_high', 'p', 'n', '사건 수', '판정']].round(4).to_string(index=False))
    print(f'저장: {out.relative_to(BASE)}  ({time.time() - t_all:.0f}s)')


if __name__ == '__main__':
    main()
