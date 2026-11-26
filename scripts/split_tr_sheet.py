"""양도 판정 시트를 비코딩 1·2용으로 나눈다 (표본·번호는 1124와 동일 -> 정답 파일 그대로 사용)
- 묶음(A/B/C) x 경우(상호이어짐/둘다다름/같은업태다른상호/기타포함)별로 번갈아 배정 -> 두 파일 난이도 비슷
- 각자 본인 몫 중 20줄 = '시험'(수요일 오전), 상대 몫 중 25줄 = '교차'(목요일 오후, 둘이 따로 판정)
- 분배표(누가 어떤 번호를 받았는지)는 코딩 1만 보관
"""
import re
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Alignment, Font, PatternFill

SEED = 42
SRC = 'out/1124b_양도판정385_판정시트.xlsx'
KEY = 'out/1124_양도판정385_정답_코딩1만.xlsx'

d = pd.read_excel(SRC, sheet_name='판정')
key = pd.read_excel(KEY)[['번호', '묶음']]
d = d.merge(key, on='번호', how='left')

norm = lambda s: re.sub(r'[\s\(\)\.\-·]', '', str(s)).lower()
a, b = d['앞 가게 상호'].map(norm), d['다음 가게 상호'].map(norm)
same_name = [x == y or (len(x) >= 2 and len(y) >= 2 and (x in y or y in x)) for x, y in zip(a, b)]
etc = (d['앞 가게 업태'] == '기타') | (d['다음 가게 업태'] == '기타')
same_type = (d['앞 가게 업태'] == d['다음 가게 업태']) & ~etc
d['경우'] = np.select([same_name, etc, same_type], ['1상호', '4기타', '3같은업태'], '2둘다다름')

rng = np.random.default_rng(SEED)
d['_r'] = rng.random(len(d))
d = d.sort_values(['묶음', '경우', '_r']).reset_index(drop=True)
d['담당'] = np.where(np.arange(len(d)) % 2 == 0, '비코딩1', '비코딩2')


def pick(df, n):
    # 묶음·경우 비율을 유지하며 n줄 뽑기
    df = df.sample(frac=1, random_state=SEED)
    df = df.sort_values(['묶음', '경우'], kind='stable')
    idx = np.linspace(0, len(df) - 1, n).round().astype(int)
    return df.iloc[idx]


trial, cross = {}, {}
for who in ['비코딩1', '비코딩2']:
    mine = d[d['담당'] == who]
    trial[who] = set(pick(mine, 20)['번호'])
    rest = mine[~mine['번호'].isin(trial[who])]
    cross[who] = set(pick(rest, 25)['번호'])  # 이 사람 몫 중 상대도 판정할 25줄

base_cols = ['번호', '칸 주소 (지번)', '도로명주소', '층(코드)',
             '앞 가게 상호', '앞 가게 업태', '앞 가게 면적(㎡)', '앞 가게 영업 연도',
             '다음 가게 상호', '다음 가게 업태', '다음 가게 면적(㎡)', '다음 가게 개업 연도']
FILL = {
    'A. 업태(하는 장사) 이어짐': '예 / 아니오 / 모름',
    'B. 상호·간판 이어짐': '예 / 아니오 / 모름',
    'C. 로드뷰': '이어짐 / 끊김 / 사진없음 / 안봄',
    '최종 판정': '양도 / 폐업후새가게 / 판단불가',
    '메모': '',
}

GUIDE = [
    ['목적', '동일한 점포 자리(칸)에서 앞 가게 폐업 후 다음 가게가 개업한 경우, 해당 쌍이 "양도"(주인만 바뀐 동일 점포)인지 "폐업후새가게"(폐업 후 신규 점포 입점)인지 판정한다. 1행 = 1쌍(앞 가게 → 다음 가게).'],
    ['작업 순서', '"구분" 열의 순서를 따른다. ① 시험 20행(수요일 오전, 소요 시간 기록) → ② 본인 할당분 → ③ 교차 25행(목요일 오후). 교차 행은 상대방도 동일하게 판정하는 행이므로 상호 상의 없이 독립적으로 판정한다.'],
    ['판정 기준의 근거', 'OECD·Eurostat 기업 연속성 기준(김민창 2024 재인용): 위치·업종·경영권 중 2개 이상이 변경되면 기존 기업은 소멸한 것으로 본다. 본 시트의 쌍은 모두 위치가 동일하므로 업종(A)과 경영권(B)만 판단한다.'],
    ['경영권 판단 방법', '인허가 자료에는 대표자 정보가 없으므로 상호·간판의 연속 여부로 경영권 연속을 대신 판단한다. 띄어쓰기·지점명 차이는 동일 상호(B = 예)로 본다.'],
    ['날짜를 제외한 이유', '컴퓨터는 날짜(30일 규칙)만으로 판정하였다. 판정자가 날짜를 보면 동일한 판단으로 유도되어 독립적 비교가 불가능하므로 날짜와 컴퓨터 판정은 제외하였다.'],
    ['A열', '앞 가게와 다음 가게가 동일 업종이면 "예". 한쪽이 "기타"이면 상호 또는 로드뷰로 메뉴를 확인하며, 확인되지 않으면 "모름".'],
    ['B열', '상호가 동일하거나 거의 동일하면 "예", 전혀 다르면 "아니오". 동일 프랜차이즈 브랜드는 "예".'],
    ['C열', 'A·B로 판정이 결정되지 않는 경우에만 카카오맵 로드뷰 과거 사진을 확인한다. 간판·외관·내부가 유지되면 "이어짐", 변경되었으면 "끊김", 해당 연도 사진이 없으면 "사진없음", 확인하지 않았으면 "안봄". 사진은 육안으로만 확인하며 저장하지 않는다.'],
    ['최종 판정', '① B 예 → 양도\n② B 아니오 + A 아니오 → 폐업후새가게\n③ B 아니오 + A 예 → C 확인: 이어짐이면 양도, 끊김이면 폐업후새가게, 사진없음이면 판단불가\n④ A 또는 B가 모름이어서 위 순서를 적용할 수 없는 경우 → 판단불가'],
    ['예시 1', '"자차김밥 봉천점"(분식) → "자차김밥"(분식): A 예, B 예 → 양도'],
    ['예시 2', '"마바국밥"(한식) → "사아파스타"(경양식): A 아니오, B 아니오 → 폐업후새가게'],
    ['예시 3', '"가나냉면"(한식) → "다라포차"(한식): A 예, B 아니오 → 로드뷰 확인. 간판·내부 변경 = 끊김 → 폐업후새가게'],
    ['시간 제한', '1행당 3분을 초과하면 판단불가로 기록하고 다음 행으로 넘어간다. 각 열은 목록에서 선택한다.'],
    ['제출', '파일명 끝에 본인 이름을 붙여 코딩 1에게 제출한다. 상세 내용은 안내 문서를 참고한다.'],
]

order = {'시험': 0, '본인': 1, '교차': 2}
plan_rows = []
for who, other in [('비코딩1', '비코딩2'), ('비코딩2', '비코딩1')]:
    mine = d[d['담당'] == who].copy()
    mine['구분'] = np.where(mine['번호'].isin(trial[who]), '시험', '본인')
    xs = d[d['번호'].isin(cross[other])].copy()
    xs['구분'] = '교차'
    sheet = pd.concat([mine, xs])
    sheet['_o'] = sheet['구분'].map(order)
    sheet = sheet.sort_values(['_o', '_r']).reset_index(drop=True)
    for _, r in sheet.iterrows():
        plan_rows.append({'담당': who, '번호': r['번호'], '구분': r['구분'], '묶음': r['묶음'], '경우': r['경우']})
    out = sheet[['구분'] + base_cols].copy()
    for c in FILL:
        out[c] = ''
    path = f'out/1124b_양도판정_{who}.xlsx'
    with pd.ExcelWriter(path, engine='openpyxl') as w:
        pd.DataFrame(GUIDE, columns=['항목', '내용']).to_excel(w, sheet_name='판정 기준', index=False)
        out.to_excel(w, sheet_name='판정', index=False)
    wb = load_workbook(path)
    g = wb['판정 기준']
    g.column_dimensions['A'].width = 16
    g.column_dimensions['B'].width = 110
    for row in g.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical='top')
    ws = wb['판정']
    n = len(out) + 1
    hdr = {c.value: c.column_letter for c in ws[1]}
    yellow = PatternFill('solid', fgColor='FFF2CC')
    for name, opts in FILL.items():
        col = hdr[name]
        ws[f'{col}1'].fill = yellow
        ws[f'{col}1'].font = Font(bold=True)
        ws.column_dimensions[col].width = 16 if name != '메모' else 30
        if opts:
            dv = DataValidation(type='list', formula1='"' + ','.join(o.strip() for o in opts.split('/')) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f'{col}2:{col}{n}')
    tint = {'시험': 'DDEBF7', '교차': 'E2EFDA'}
    gcol = hdr['구분']
    for i in range(2, n + 1):
        v = ws[f'{gcol}{i}'].value
        if v in tint:
            ws[f'{gcol}{i}'].fill = PatternFill('solid', fgColor=tint[v])
    for col, wd in zip('ABCDEFGHIJKLM', [7, 6, 34, 40, 8, 18, 12, 10, 12, 18, 12, 10, 10]):
        ws.column_dimensions[col].width = wd
    ws.freeze_panes = 'C2'
    wb.save(path)

plan = pd.DataFrame(plan_rows)
plan.to_excel('out/1124b_양도판정_분배표_코딩1만.xlsx', index=False)

# 점검
print(plan.groupby(['담당', '구분']).size().unstack())
print(pd.crosstab([plan['담당']], [plan['묶음']]))
print(pd.crosstab(plan[plan['구분'] != '교차']['담당'], plan[plan['구분'] != '교차']['경우']))
own = plan[plan['구분'] != '교차']
print('번호 중복 없이 385 전부 배정:', own['번호'].nunique() == 385 and len(own) == 385)
x1 = set(plan[(plan['담당'] == '비코딩1') & (plan['구분'] == '교차')]['번호'])
x2 = set(plan[(plan['담당'] == '비코딩2') & (plan['구분'] == '교차')]['번호'])
print('교차 줄이 상대 본인 몫에 있음:', x1 <= set(own[own['담당'] == '비코딩2']['번호']), x2 <= set(own[own['담당'] == '비코딩1']['번호']))
