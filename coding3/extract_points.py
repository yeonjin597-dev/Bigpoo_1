"""서울시 일반음식점 인허가 CSV -> 좌표 있는 가게만 점 데이터(GeoParquet)로 저장."""
import subprocess
import sys
from pathlib import Path

for pkg in ("pandas", "geopandas", "pyarrow", "shapely"):
    try:
        __import__(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])

import geopandas as gpd
import pandas as pd

BASE = Path(__file__).resolve().parent
SRC_DIR = BASE / "01_원본"
OUT = BASE / "02_계보" / "1125_인허가좌표점_코딩3.parquet"
READ_KW = dict(encoding="cp949", encoding_errors="replace")

# 입력 CSV 찾기 (01_원본/ 우선, 없으면 스크립트 폴더)
csvs = sorted(SRC_DIR.glob("*인허가*.csv")) if SRC_DIR.exists() else []
if not csvs:
    csvs = sorted(BASE.glob("*인허가*.csv"))
if not csvs:
    sys.exit("인허가 CSV를 찾지 못했습니다.")
src = csvs[0]
print(f"입력: {src}")

# 열 이름 먼저 확인
cols = list(pd.read_csv(src, nrows=0, **READ_KW).columns)

# 요청 열 -> 파일 내 실제 열 이름 (후보 중 먼저 있는 것)
wanted = {
    "관리번호": ["관리번호"],
    "인허가일자": ["인허가일자"],
    "폐업일자": ["폐업일자"],
    "영업상태명": ["영업상태명"],
    "지번주소": ["소재지전체주소", "지번주소"],
    "도로명주소": ["도로명전체주소", "도로명주소"],
    "사업장명": ["사업장명"],
    "업태구분명": ["업태구분명"],
    "소재지면적": ["소재지면적"],
    "X": ["좌표정보(X)", "좌표정보x(epsg5174)", "좌표정보(x)"],
    "Y": ["좌표정보(Y)", "좌표정보y(epsg5174)", "좌표정보(y)"],
}
colmap = {}
for key, cands in wanted.items():
    hit = next((c for c in cands if c in cols), None)
    if hit is None:
        sys.exit(f"열을 찾지 못함: {key} (후보 {cands})")
    colmap[key] = hit
xcol, ycol = colmap["X"], colmap["Y"]

df = pd.read_csv(src, usecols=list(colmap.values()), dtype=str, low_memory=False, **READ_KW)
total = len(df)

df[xcol] = pd.to_numeric(df[xcol], errors="coerce")
df[ycol] = pd.to_numeric(df[ycol], errors="coerce")
df["소재지면적"] = pd.to_numeric(df[colmap["소재지면적"]], errors="coerce")
df = df.dropna(subset=[xcol, ycol])
kept = len(df)

gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[xcol], df[ycol]), crs="EPSG:5174")
OUT.parent.mkdir(parents=True, exist_ok=True)
gdf.to_parquet(OUT)

lic = pd.to_datetime(gdf[colmap["인허가일자"]].str.strip(), errors="coerce")
since2010 = int((lic >= "2010-01-01").sum())

print(f"전체 행 수: {total:,}")
print(f"좌표 없어서 뺀 행 수: {total - kept:,}")
print(f"저장한 행 수: {kept:,}")
print(f"2010년 이후 인허가 행 수(저장분 기준): {since2010:,}")
print(f"저장: {OUT}")
