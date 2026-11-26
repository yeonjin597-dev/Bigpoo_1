"""양도 판정 시트 v2 (1124 -> 1124b)
- 표본(385쌍)과 행 순서는 그대로: 기존 정답 파일(1124_양도판정385_정답_코딩1만.xlsx)을 그대로 쓴다.
- 바뀐 점: 판정 기준을 OECD/Eurostat 기업 연속성 기준(김민창 2024 재인용)에 맞춰
  '사실 기록 칸'(업태 / 상호·간판 / 로드뷰)을 따로 받고, 최종 판정은 규칙대로 적게 한다.
  면적 일치는 사람이 아니라 코드가 계산한다(시트에 이미 숫자가 있음).
"""
import pandas as pd
from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Alignment, Font, PatternFill

SRC = 'out/1124_양도판정385_판정시트.xlsx'
DST = 'out/1124b_양도판정385_판정시트.xlsx'

old = pd.read_excel(SRC, sheet_name='판정')
keep = ['번호', '칸 주소 (지번)', '도로명주소', '층(코드)',
        '앞 가게 상호', '앞 가게 업태', '앞 가게 면적(㎡)', '앞 가게 영업 연도',
        '다음 가게 상호', '다음 가게 업태', '다음 가게 면적(㎡)', '다음 가게 개업 연도']
new = old[keep].copy()
COLS = {
    'A. 업태(하는 장사) 이어짐': '예 / 아니오 / 모름',
    'B. 상호·간판 이어짐': '예 / 아니오 / 모름',
    'C. 로드뷰': '이어짐 / 끊김 / 사진없음 / 안봄',
    '최종 판정': '양도 / 폐업후새가게 / 판단불가',
    '메모': '',
}
for c in COLS:
    new[c] = ''

GUIDE = [
    ['무엇을 하나요', '같은 칸에서 앞 가게가 문을 닫고 다음 가게가 열렸을 때, "같은 가게가 주인만 바뀐 것(양도)"인지 "망하고 새 가게가 들어온 것"인지 판단합니다. 한 줄 = 한 쌍(앞 가게 → 다음 가게)입니다.'],
    ['기준의 근거', 'OECD·Eurostat 기업 연속성 기준(김민창 2024 재인용): 기업을 정하는 3요소는 ①위치 ②주요 경제활동(업종) ③경영권(주인)이며, 이 중 2개 이상이 바뀌면 이전 기업은 소멸(폐업)하고 새 기업이 생긴 것으로 봅니다. 이 시트의 쌍은 모두 같은 칸이라 ①위치는 항상 같습니다. 그래서 ②업종과 ③주인만 보면 됩니다.'],
    ['주인을 어떻게 보나요', '인허가 자료에는 대표자 이름이 없습니다. 그래서 "상호·간판이 이어지는가"로 주인(경영권)이 이어지는지를 대신 판단합니다. 상호가 같거나 거의 같으면(띄어쓰기·지점명 차이) "예"입니다.'],
    ['블라인드', '날짜 간격(며칠 만에 다음 가게가 열렸는지)은 일부러 뺐습니다. 컴퓨터는 날짜(30일)로 판정했기 때문에, 사람은 날짜가 아닌 다른 증거로 판단해야 비교가 됩니다. 컴퓨터의 답도 이 파일에는 없습니다.'],
    ['순서 1', 'A칸: 앞 가게와 다음 가게의 업태가 같은 장사인지 적습니다. 업태 이름이 같으면 "예". 한쪽이 "기타"이거나 이름만으로 모르겠으면 상호나 로드뷰로 메뉴를 보고 판단하고, 그래도 모르면 "모름".'],
    ['순서 2', 'B칸: 상호·간판이 이어지는지 적습니다. 상호가 같거나 거의 같으면 "예", 전혀 다르면 "아니오". 같은 프랜차이즈 브랜드면 "예"입니다.'],
    ['순서 3', 'C칸: A·B만으로 판정이 안 될 때만 카카오맵 로드뷰 과거 사진을 봅니다. 간판·외관·인테리어가 이어지면 "이어짐", 바뀌었으면 "끊김". 사진이 없으면 "사진없음", 보지 않았으면 "안봄". (사진은 저장하지 말고 눈으로만 보고 기록합니다.)'],
    ['최종 판정 규칙', '① B가 "예" → 양도\n② B가 "아니오"이고 A도 "아니오" → 폐업후새가게 (업종과 주인 2개가 바뀜 = OECD 기준 소멸)\n③ B가 "아니오"이고 A가 "예" → 로드뷰(C)를 봅니다. "이어짐"이면 양도, "끊김"이면 폐업후새가게, "사진없음"이면 판단불가\n④ A나 B가 "모름"이라 위 규칙을 못 쓰면 → 판단불가'],
    ['면적', '면적은 판정에 직접 쓰지 않아도 됩니다. 면적 일치 여부는 코딩 1이 숫자로 따로 계산합니다. 다만 판단에 참고는 해도 됩니다.'],
    ['예시 1', '앞 "자차김밥 봉천점"(분식) → 다음 "자차김밥"(분식): A 예, B 예 → 양도'],
    ['예시 2', '앞 "가나냉면"(한식) → 다음 "다라포차"(한식): A 예, B 아니오 → 로드뷰 확인. 간판·내부가 완전히 바뀌었으면 끊김 → 폐업후새가게'],
    ['예시 3', '앞 "마바국밥"(한식) → 다음 "사아파스타"(경양식): A 아니오, B 아니오 → 폐업후새가게'],
    ['시간', '한 건에 5분 넘게 쓰지 말고 판단불가로 넘어가기. 칸은 목록에서 고르면 됩니다(직접 타이핑하지 않아도 됨).'],
    ['다 하면', '파일 이름 끝에 본인 이름을 붙여 코딩 1에게 보내 주세요. 정답과 맞추는 건 코딩 1이 합니다.'],
]
guide = pd.DataFrame(GUIDE, columns=['항목', '내용'])

with pd.ExcelWriter(DST, engine='openpyxl') as w:
    guide.to_excel(w, sheet_name='판정 기준', index=False)
    new.to_excel(w, sheet_name='판정', index=False)

# 서식 + 드롭다운
wb = load_workbook(DST)
g = wb['판정 기준']
g.column_dimensions['A'].width = 18
g.column_dimensions['B'].width = 110
for row in g.iter_rows(min_row=2):
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical='top')
ws = wb['판정']
n = len(new) + 1
hdr = {c.value: c.column_letter for c in ws[1]}
fill = PatternFill('solid', fgColor='FFF2CC')
for name, opts in COLS.items():
    col = hdr[name]
    ws[f'{col}1'].fill = fill
    ws[f'{col}1'].font = Font(bold=True)
    ws.column_dimensions[col].width = 16 if name != '메모' else 30
    if opts:
        dv = DataValidation(type='list', formula1='"' + ','.join(o.strip() for o in opts.split('/')) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f'{col}2:{col}{n}')
for col, wd in zip('ABCDEFGHIJKL', [6, 34, 40, 8, 18, 12, 10, 12, 18, 12, 10, 10]):
    ws.column_dimensions[col].width = wd
ws.freeze_panes = 'B2'
wb.save(DST)

# 검증: 기존 정답 파일과 번호·상호가 그대로 맞는지
key = pd.read_excel('out/1124_양도판정385_정답_코딩1만.xlsx')
chk = pd.read_excel(DST, sheet_name='판정')
print('rows', len(chk), '| same 번호 order as old sheet:', (chk['번호'].values == old['번호'].values).all(),
      '| same names:', (chk['앞 가게 상호'].fillna('').values == old['앞 가게 상호'].fillna('').values).all())
print('key columns:', key.columns.tolist())
print('번호 in key all present:', set(chk['번호']) <= set(key[key.columns[0]]) if '번호' in key.columns[0] else key.columns[0])
