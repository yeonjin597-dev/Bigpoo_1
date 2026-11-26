"""로드뷰 40쌍 측정 시트 생성 (코딩 1). 입력: out/1127_로드뷰_짝목록_비코딩2.xlsx → sheets/1127_로드뷰_측정시트_코딩1.xlsx"""
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parents[1]
src = pd.read_excel(BASE / 'out' / '1127_로드뷰_짝목록_비코딩2.xlsx')
OUT = BASE / 'sheets' / '1127_로드뷰_측정시트_코딩1.xlsx'; OUT.parent.mkdir(exist_ok=True)

ITEMS = [  # (열 이름, 선택지 or None(숫자), 정의, 근거)
 ('Q0 로드뷰 확인', ['확인', '사진없음', '위치불명'], '해당 지번 건물이 로드뷰에서 확인되는가. 사진없음·위치불명이면 나머지는 비워 둔다.', '측정 가능 여부 기록 (Kelly et al. 2013: 대상 도로의 28%가 촬영되지 않아 제외)'),
 ('Q1 촬영 연도', None, '로드뷰 화면 왼쪽 위/아래에 표시되는 촬영 연월 중 연도(예: 2023).', '시점 차이 통제용 (Rundle et al. 2011: 사진 시점과 실제 시점의 차이가 타당도에 영향)'),
 ('Q2 접면 도로 차로 수', ['0(보행자전용·골목)', '1', '2', '3 이상'], '가게 입구가 면한 도로의 차로 수(양방향 합계). 중앙선 없는 이면도로는 1.', '크고 변하지 않는 항목 = 일치도 높음 (Rundle et al. 2011; 도로 특성 PABAK 0.91, Kelly et al. 2013)'),
 ('Q3 모퉁이 칸', ['예', '아니오'], '건물이 교차로 모퉁이에 있어 두 도로에 면하는가.', '크고 안정적인 항목 (Rundle et al. 2011)'),
 ('Q4 보도 있음', ['예', '아니오'], '입구 앞에 차도와 분리된 보도(연석·볼라드·색 구분)가 있는가.', '보도 유무 PABAK 0.90 (Kelly et al. 2013)'),
 ('Q5 입구 가시성', ['잘 보임', '일부 가림', '안 보임'], '도로에서 정면으로 볼 때 가게(층) 입구·간판 자리가 보이는 정도. 나무·기둥·다른 간판 가림 포함.', '입지 가시성 (점포 생존 요인으로 자주 쓰이는 입지 특성)'),
 ('Q6 위층·지하 접근', ['해당없음(1층)', '입구가 길에서 보임', '입구가 안 보임'], '1층이 아니면, 그 층으로 가는 계단·엘리베이터 입구가 길에서 보이는가.', '층 접근성 (본 프로젝트 칸 = 지번+층 정의와 연결)'),
 ('Q7 양옆 빈 점포 수', ['0', '1', '2', '3', '4'], '같은 건물·옆 건물 1층 기준 양옆 2칸씩(총 4칸) 중 임대 현수막·셔터·내부 비어 있음이 보이는 칸 수.', '⚠ 시간에 따라 변하는 항목 = 일치도 낮을 수 있음 (Rundle et al. 2011). 해석 주의'),
 ('Q8 대중교통 보임', ['예', '아니오'], '가게 위치에서 화면을 돌려 버스정류장 또는 지하철 출입구가 보이는가.', '대중교통 항목 PABAK 0.90 (Kelly et al. 2013)'),
 ('Q9 경사', ['평지', '경사'], '입구 앞 도로가 눈에 띄게 경사져 있는가.', '크고 안정적인 항목'),
 ('Q10 이미지 품질', ['양호', '가림(차량·공사)', '흐림·어두움'], '측정에 쓴 화면의 품질.', '사진 품질·가림 기록 권고 (Rundle et al. 2011)'),
]
F = '맑은 고딕'
hdr_fill = PatternFill('solid', fgColor='3C3489'); in_fill = PatternFill('solid', fgColor='FFF7CC'); fix_fill = PatternFill('solid', fgColor='EEEEEE')
thin = Side(style='thin', color='CCCCCC'); box = Border(left=thin, right=thin, top=thin, bottom=thin)

wb = Workbook()
g = wb.active; g.title = '안내'
guide = [
 ('로드뷰 40쌍 측정 시트', ''),
 ('목적', '이전 폐업이 많았던 칸(고위험)과 오래 버틴 칸(장수)이 눈에 보이는 입지 조건에서 다른지 탐색적으로 비교한다 (RQ7). 짝은 같은 250m 격자 안에서 성향점수로 맞췄다.'),
 ('블라인드', 'A/B 중 어느 쪽이 고위험 칸인지 표시하지 않았다. 측정이 모두 끝날 때까지 정답표(1127_장수칸짝_정답표_코딩1만.xlsx)를 열지 않는다.'),
 ('방법', '네이버 지도 또는 카카오맵 로드뷰를 직접 보고 기록만 한다. 화면 저장·자동 다운로드는 하지 않는다.'),
 ('입력할 칸', '「측정」 시트의 노란 칸만 입력한다. 회색 칸(짝 번호·칸·주소·층)은 수정하지 않는다. 대부분 목록에서 고른다.'),
 ('순서', '짝 단위로 A → B를 연달아 측정한다. 칸 하나에 약 3분, 80칸 전체 약 4시간 (2회로 나누어 진행 권장).'),
 ('판단이 애매할 때', '보수적인 쪽(가림·아니오 등)을 고르고 메모에 이유를 적는다.'),
 ('분석 계획', '짝 단위 비교: 예/아니오 항목은 McNemar 검정, 순서형 항목(차로 수·가시성·빈 점포 수)은 Wilcoxon 부호순위 검정. 40쌍이라 검정력이 낮으므로 탐색적 결과로만 보고한다.'),
 ('신뢰도 (선택)', '10쌍을 다른 사람(비코딩 1)이 한 번 더 측정하면 항목별 일치도(κ)를 보고할 수 있다.'),
 ('', ''),
 ('예시 (가상)', '짝 0 / A / Q0 확인 / Q1 2023 / Q2 1 / Q3 아니오 / Q4 아니오 / Q5 일부 가림 / Q6 해당없음(1층) / Q7 1 / Q8 아니오 / Q9 평지 / Q10 양호 / 메모: 입구 앞 주차 차량'),
]
for i, (a, b) in enumerate(guide, 1):
    g.cell(i, 1, a).font = Font(name=F, bold=True, size=14 if i == 1 else 10)
    c = g.cell(i, 2, b); c.font = Font(name=F, size=10); c.alignment = Alignment(wrap_text=True, vertical='top')
g.column_dimensions['A'].width = 16; g.column_dimensions['B'].width = 110

d = wb.create_sheet('항목 정의')
for j, h in enumerate(['항목', '선택지', '정의', '근거'], 1):
    c = d.cell(1, j, h); c.font = Font(name=F, bold=True, color='FFFFFF'); c.fill = hdr_fill
for i, (n, opts, de, ba) in enumerate(ITEMS, 2):
    for j, v in enumerate([n, ' / '.join(opts) if opts else '숫자(연도)', de, ba], 1):
        c = d.cell(i, j, v); c.font = Font(name=F, size=10); c.alignment = Alignment(wrap_text=True, vertical='top'); c.border = box
r = len(ITEMS) + 3
for k, t in enumerate(['참고문헌',
    'Rundle, A. G., Bader, M. D. M., Richards, C. A., Neckerman, K. M., & Teitler, J. O. (2011). Using Google Street View to audit neighborhood environments. American Journal of Preventive Medicine, 40(1), 94–100.',
    'Kelly, C. M., Wilson, J. S., Baker, E. A., Miller, D. K., & Schootman, M. (2013). Using Google Street View to audit the built environment: Inter-rater reliability results. Annals of Behavioral Medicine, 45(Suppl 1), S108–S112.']):
    c = d.cell(r + k, 1, t); c.font = Font(name=F, size=10, bold=(k == 0))
for col, w in zip('ABCD', [20, 34, 60, 60]): d.column_dimensions[col].width = w

m = wb.create_sheet('측정'); wb.move_sheet('측정', offset=-2)
heads = list(src.columns) + [n for n, *_ in ITEMS] + ['메모']
for j, h in enumerate(heads, 1):
    c = m.cell(1, j, h); c.font = Font(name=F, bold=True, color='FFFFFF', size=10); c.fill = hdr_fill
    c.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center'); c.border = box
n = len(src)
for i, row in enumerate(src.itertuples(index=False), 2):
    for j, v in enumerate(row, 1):
        c = m.cell(i, j, v); c.fill = fix_fill; c.font = Font(name=F, size=10); c.border = box
    for j in range(len(src.columns) + 1, len(heads) + 1):
        c = m.cell(i, j); c.fill = in_fill; c.font = Font(name=F, size=10); c.border = box
for k, (nm, opts, *_) in enumerate(ITEMS):
    col = get_column_letter(len(src.columns) + 1 + k)
    if opts:
        dv = DataValidation(type='list', formula1='"' + ','.join(opts) + '"', allow_blank=True)
    else:
        dv = DataValidation(type='whole', operator='between', formula1='2007', formula2='2026', allow_blank=True)
    dv.error = '목록(또는 2007~2026 연도)에서 입력'; m.add_data_validation(dv); dv.add(f'{col}2:{col}{n + 1}')
m.freeze_panes = 'E2'; m.row_dimensions[1].height = 42
for j, w in enumerate([7, 5, 34, 6] + [13] * len(ITEMS) + [30], 1):
    m.column_dimensions[get_column_letter(j)].width = w
# 진행 현황 (수식)
qc = get_column_letter(len(src.columns) + 1); last = get_column_letter(len(heads) - 1)
pr = n + 3
m.cell(pr, 3, 'Q0 입력한 칸 수').font = Font(name=F, bold=True)
m.cell(pr, 5, f'=COUNTA({qc}2:{qc}{n + 1})')
m.cell(pr + 1, 3, '측정 가능(확인) 칸 수').font = Font(name=F, bold=True)
m.cell(pr + 1, 5, f'=COUNTIF({qc}2:{qc}{n + 1},"확인")')
m.cell(pr + 2, 3, '진행률').font = Font(name=F, bold=True)
m.cell(pr + 2, 5, f'=E{pr}/{n}').number_format = '0.0%'
wb.save(OUT); print(OUT, n)
