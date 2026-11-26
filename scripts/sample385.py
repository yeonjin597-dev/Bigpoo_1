"""
2단계용 385건 층화 추출 (코딩 1 → 비코딩 1·2)
- 층 판정용: 2010년 이후 인허가 가게 1건 = 1줄
- 양도 판정용: 같은 칸의 '앞 가게 폐업 → 다음 가게 개업' 1쌍 = 1줄
블라인드 시트(사람용)에는 코드의 판정을 넣지 않고, 정답 파일은 코딩 1만 보관한다.
"""
import re
import pandas as pd

OUT_DIR = 'out'
SEED = 42
N = {'A': 130, 'B': 130, 'C': 125}

raw = pd.read_pickle(f'{OUT_DIR}/raw_parsed.pkl')
lin = pd.read_pickle(f'{OUT_DIR}/lineage.pkl')


def draw(df, col):
    parts = []
    for k, n in N.items():
        pool = df[df[col] == k]
        parts.append(pool.sample(min(n, len(pool)), random_state=SEED).assign(묶음=k))
    out = pd.concat(parts).sample(frac=1, random_state=SEED).reset_index(drop=True)
    out.insert(0, '번호', range(1, len(out) + 1))
    return out


# ───────── 층 판정용 ─────────
f = raw[(raw['od'] >= '2010-01-01') & raw['jibun'].notna()].copy()
hard = f['floor_range'] | f['floor'].fillna('').str.startswith('B')
f['stratum'] = 'A'
f.loc[hard, 'stratum'] = 'B'
f.loc[f['floor'].isna(), 'stratum'] = 'C'
fs = draw(f, 'stratum')
floor_blind = fs[['번호', '지번주소', '도로명주소', '사업장명', 'od']].rename(columns={'od': '개업일'})
floor_blind['개업일'] = floor_blind['개업일'].dt.strftime('%Y-%m-%d')
floor_blind['판정 층 (예: 1, 2, B1 / 판단불가)'] = ''
floor_blind['근거 (①주소원문 ②도로명 ③로드뷰)'] = ''
floor_blind['메모'] = ''
floor_key = fs[['번호', '묶음', '관리번호', 'floor', 'floor_range', 'floor_src']].rename(
    columns={'floor': '코드_층', 'floor_range': '코드_범위표기', 'floor_src': '코드_출처'})

# ───────── 양도 판정용 ─────────
d = lin.sort_values(['site', 'od']).copy()
g = d.groupby('site')
nxt = d[['site', 'od', 'cd', 'name', 'category', 'area_m2', '사업장명']].groupby('site').shift(-1)
pairs = d.assign(n_od=nxt['od'], n_cd=nxt['cd'], n_name=nxt['사업장명'], n_cat=nxt['category'], n_area=nxt['area_m2'])
pairs = pairs[pairs['cd'].notna() & pairs['n_od'].notna()].copy()
pairs['gap'] = (pairs['n_od'] - pairs['cd']).dt.days
pairs = pairs[pairs['gap'] >= 0]
pairs['stratum'] = pd.cut(pairs['gap'], [-1, 30, 90, 365], labels=['A', 'B', 'C']).astype(object)
pairs = pairs[pairs['stratum'].notna()]
ts = draw(pairs, 'stratum')
yr = lambda s: s.dt.year.astype('Int64').astype(str)
tr_blind = pd.DataFrame({
    '번호': ts['번호'],
    '칸 주소 (지번)': ts['지번주소'], '도로명주소': ts['도로명주소'], '층(코드)': ts['floor'],
    '앞 가게 상호': ts['사업장명'], '앞 가게 업태': ts['category'], '앞 가게 면적(㎡)': ts['area_m2'],
    '앞 가게 영업 연도': yr(ts['od']) + '~' + yr(ts['cd']),
    '다음 가게 상호': ts['n_name'], '다음 가게 업태': ts['n_cat'], '다음 가게 면적(㎡)': ts['n_area'],
    '다음 가게 개업 연도': yr(ts['n_od']),
    '판정 (양도 / 폐업후새가게 / 판단불가)': '', '근거 (①상호 ②업태 ③면적 ④로드뷰)': '', '메모': ''})
tr_key = pd.DataFrame({'번호': ts['번호'], '묶음': ts['묶음'], '앞_관리번호': ts['관리번호'],
                       '간격_일': ts['gap'], '코드_판정': ts['gap'].le(30).map({True: '양도', False: '폐업후새가게'})})

GUIDE_FLOOR = [
    ['목적', '컴퓨터가 주소에서 뽑은 층이 맞는지 사람이 확인합니다. 코드의 답은 이 시트에 없습니다(블라인드).'],
    ['순서', '① 지번주소의 층 문구 → ② 도로명주소의 층 → ③ 카카오맵 로드뷰에서 간판·출입구가 있는 층'],
    ['적는 값', '1, 2, 3 … / 지하는 B1, B2 / 여러 층에 걸치면 가장 낮은 층을 적고 메모에 "1~2층" / 모르겠으면 판단불가'],
    ['주의', '"B101호", "지하15호"처럼 호수에 붙은 숫자는 층이 아닙니다 (B101호 → 보통 지하 1층)'],
    ['시간', '한 건에 5분 넘게 쓰지 말고 판단불가로 넘어가기'],
]
GUIDE_TR = [
    ['목적', '같은 칸에서 앞 가게가 문을 닫고 다음 가게가 열렸을 때, "같은 가게가 주인만 바뀐 것(양도)"인지 "망하고 새 가게가 들어온 것"인지 판단합니다.'],
    ['블라인드', '정확한 날짜(간격 일수)는 일부러 뺐습니다. 우리 규칙(30일)을 검증하려는 것이라, 날짜가 아닌 다른 증거로 판단해 주세요.'],
    ['증거 순서', '① 상호가 같거나 거의 같음 ② 업태가 같음 ③ 면적이 같음(±10% 정도) ④ 로드뷰에서 간판·외관·인테리어가 이어짐'],
    ['판정 기준(제안)', '①이 같으면 양도 / ①이 다르고 ②③④ 중 2개 이상 이어지면 양도 / 그 외는 폐업후새가게 / 정보가 부족하면 판단불가'],
    ['주의', '프랜차이즈 같은 상호(예: 같은 브랜드 다른 점주)도 "주인만 바뀐 것"이면 양도로 봅니다'],
    ['시간', '한 건에 5분 넘게 쓰지 말고 판단불가로 넘어가기'],
]


def save(blind, key, guide, name):
    with pd.ExcelWriter(f'{OUT_DIR}/{name}_판정시트.xlsx', engine='openpyxl') as w:
        pd.DataFrame(guide, columns=['항목', '내용']).to_excel(w, sheet_name='판정 기준', index=False)
        blind.to_excel(w, sheet_name='판정', index=False)
    key.to_excel(f'{OUT_DIR}/{name}_정답_코딩1만.xlsx', index=False)


save(floor_blind, floor_key, GUIDE_FLOOR, '1124_층판정385')
save(tr_blind, tr_key, GUIDE_TR, '1124_양도판정385')
print('층:', fs['묶음'].value_counts().to_dict(), '| 양도:', ts['묶음'].value_counts().to_dict())
print('모집단 크기 층:', f['stratum'].value_counts().to_dict(), '| 양도:', pairs['stratum'].value_counts().to_dict())
