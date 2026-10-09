"""
KOPIS 공연예술 연구 데이터 랩
- KOPIS Open API 19개 데이터 서비스 통합 Streamlit 앱 (단일 파일)
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    import koreanize_matplotlib  # noqa: F401
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(
    layout="wide",
    page_title="KOPIS 공연예술 연구 데이터 랩",
    page_icon="🎭",
)

SERVICE_KEY = "1610e189717b4c9a9a2bb74c10d47130"
BASE_URL = "http://www.kopis.or.kr/openApi/restful"
REQUEST_TIMEOUT = 30

GENRE_OPTIONS = {
    "전체": "",
    "연극(AAAA)": "AAAA",
    "무용(BBBC)": "BBBC",
    "클래식(CCCA)": "CCCA",
    "국악(CCCC)": "CCCC",
    "대중음악(CCCD)": "CCCD",
    "복합(EEEA)": "EEEA",
    "뮤지컬(GGGA)": "GGGA",
}

AREA_OPTIONS = {
    "전체": "",
    "서울(11)": "11",
    "부산(26)": "26",
    "대구(27)": "27",
    "인천(28)": "28",
    "광주(29)": "29",
    "대전(30)": "30",
    "울산(31)": "31",
    "세종(36)": "36",
    "경기(41)": "41",
    "강원(51)": "51",
    "충북(43)": "43",
    "충남(44)": "44",
    "전북(45)": "45",
    "전남(46)": "46",
    "경북(47)": "47",
    "경남(48)": "48",
    "제주(50)": "50",
    "대학로(UNI)": "UNI",
}

SEAT_SCALE_OPTIONS = {
    "전체": "",
    "미상(0)": "0",
    "1~300석 미만": "100",
    "300~500석 미만": "300",
    "500~1000석 미만": "500",
    "1000~5000석 미만": "1000",
    "5000~10000석 미만": "5000",
    "10000석 이상": "10000",
}

FACILITY_CHAR_OPTIONS = {
    "전체": "",
    "문예회관": "1",
    "공연장": "2",
    "기타(공공)": "3",
    "기타(민간)": "4",
    "학교": "5",
    "극장": "6",
}

BOX_PERIOD_OPTIONS = {"일별": "day", "주별": "week", "월별": "month"}

# XML item 태그 → 한글 컬럼 매핑 (값 중복 금지: rename 후 열 이름 충돌 방지)
FIELD_LABELS = {
    "mt20id": "공연ID",
    "prfnm": "공연명",
    "prfpdfrom": "시작일",
    "prfpdto": "종료일",
    "fcltynm": "시설명",
    "poster": "포스터",
    "genrenm": "공연장르",
    "prfstate": "공연상태",
    "area": "지역",
    "openrun": "오픈런",
    "mt10id": "시설ID",
    "mt13cnt": "공연장수",
    "fcltychartr": "시설특성",
    "sidonm": "시도",
    "gugunnm": "구군",
    "opende": "개관연도",
    "seatscale": "객석수",
    "telno": "전화번호",
    "relateurl": "홈페이지",
    "adres": "주소",
    "restaurant": "레스토랑",
    "cafe": "카페",
    "store": "편의점",
    "nolibang": "놀이방",
    "suyu": "수유실",
    "parkbarrier": "장애인주차장",
    "restbarrier": "장애인화장실",
    "runwbarrier": "경사로",
    "elevbarrier": "엘리베이터",
    "parkinglot": "주차장",
    "mt30id": "제작사ID",
    "entrpsnm": "제작사명",
    "cate": "장르코드명",
    "catenm": "장르명",
    "rnum": "순위",
    "prfpd": "공연기간",
    "prfplcnm": "공연장",
    "seatcnt": "좌석수",
    "prfdtcnt": "상연횟수",
    "prfdt": "일자",
    "prfprocnt": "개막편수",
    "amount": "매출액",
    "nmrs": "관객수",
    "nmrsshr": "관객점유율",
    "amountshr": "매출점유율",
    "prfcnt": "공연건수",
    "fcltycnt": "공연시설수",
    "prfplccnt": "시설내공연장수",
    "totnmrs": "총티켓판매수",
    "nmrcancl": "취소수",
    "ntssnmrs": "판매수",
    "cancelnmrs": "예매취소수",
    "prfcltynm": "공연시설명",
    "prfnmfct": "통계시설명",
    "prfnmplc": "공연장명",
    "sty": "줄거리",
    "prfcast": "출연진",
    "prfcrew": "제작진",
    "prfruntime": "런타임",
    "prfage": "관람연령",
    "pcseguidance": "관람료",
    "entrpsnmH": "주최",
    "entrpsnmP": "제작",
    "dtguidance": "공연시간안내",
    "disabledseatscale": "장애인관객석",
    "ntssnmrssm": "예매수합계",
    "cancelnmrssm": "취소수합계",
    "totnmrssm": "총티켓판매수합계",
    "ntssamountsm": "총티켓판매액합계",
    "price": "가격대",
    "timename": "시간대",
    "pertotnmrssm": "장르별티켓비중",
}


# ---------------------------------------------------------------------------
# API / 파싱 유틸
# ---------------------------------------------------------------------------
def to_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def clamp_period(stdate: date, eddate: date, max_days: int = 31) -> tuple[date, date]:
    """KOPIS 통계 API 최대 조회 기간(통상 31일)에 맞게 종료일을 보정."""
    if eddate < stdate:
        eddate = stdate
    if (eddate - stdate).days > max_days - 1:
        eddate = stdate + timedelta(days=max_days - 1)
    return stdate, eddate


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def item_to_dict(item: ET.Element) -> dict[str, str]:
    """단일 XML item/db/boxof/prfst 노드를 dict로 변환 (누락 태그 안전 처리)."""
    data: dict[str, str] = {}
    for child in list(item):
        tag = child.tag
        # 중첩 목록(mt13s 등)은 스킵하고 1depth 텍스트만 수집
        if list(child):
            continue
        # 동일 태그가 여러 번 오면 첫 값만 유지 (키 유일성)
        if tag in data:
            continue
        data[tag] = item.findtext(tag, default="") or ""
    return data


def unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    """중복 열 이름을 제거해 st.dataframe / describe 오류를 방지."""
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    if df.shape[1] == 0:
        return df.copy()
    # 이름이 비어 있거나 공백만인 열도 정리
    cols = [str(c).strip() if c is not None else "" for c in df.columns]
    out = df.copy()
    fixed: list[str] = []
    for i, c in enumerate(cols):
        fixed.append(c if c else f"col_{i}")
    out.columns = fixed
    # 완전 중복 열 제거 (첫 번째만 유지)
    out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")]
    return out


def make_unique_labels(columns: list[str], label_map: dict[str, str] | None = None) -> list[str]:
    """원본 키 → 한글 라벨 변환 시 중복되면 접미사를 붙여 유일화."""
    label_map = label_map or {}
    seen: dict[str, int] = {}
    result: list[str] = []
    for col in columns:
        base = label_map.get(col, col)
        base = str(base).strip() if base is not None else str(col)
        if not base:
            base = str(col) if col else "col"
        count = seen.get(base, 0)
        if count == 0:
            result.append(base)
        else:
            result.append(f"{base}_{count + 1}")
        seen[base] = count + 1
    return result


def rows_to_df(rows: list[dict[str, str]], rename: bool = True) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    # 행마다 키가 달라도 합집합으로 맞추되, 키는 원본(영문) 유지
    df = pd.DataFrame(rows)
    df = unique_columns(df)
    if rename:
        df.columns = make_unique_labels(list(df.columns), FIELD_LABELS)
        df = unique_columns(df)
    return df


def safe_dataframe(df: pd.DataFrame, **kwargs: Any) -> None:
    """중복 열을 제거한 뒤 st.dataframe 출력."""
    st.dataframe(unique_columns(df), **kwargs)


def parse_xml_items(xml_text: str, item_tags: tuple[str, ...]) -> list[dict[str, str]]:
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: list[ET.Element] = []
    for tag in item_tags:
        found = root.findall(f".//{tag}")
        if found:
            items = found
            break
    return [item_to_dict(el) for el in items]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_kopis(endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """
    KOPIS REST XML 호출 + 캐시.
    endpoint 예: 'pblprfr', 'pblprfr/PF132236', 'boxoffice'
    """
    params = dict(params or {})
    params["service"] = SERVICE_KEY
    # 빈 문자열 파라미터는 제거
    params = {k: v for k, v in params.items() if v is not None and v != ""}

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except requests.RequestException:
        return []

    text = resp.text or ""
    # API 오류 응답(errmsg)은 빈 결과로 처리
    if "<errmsg>" in text:
        return []

    # 엔드포인트별 XML 아이템 태그
    if endpoint.startswith("boxoffice"):
        tags = ("boxof",)
    elif endpoint.startswith("boxStats"):
        tags = ("boxStatsof", "boxof")
    elif endpoint.startswith("prfsts"):
        tags = ("prfSt", "prfst", "prfSts")
    else:
        tags = ("db",)

    return parse_xml_items(text, tags)


def boxoffice_period(ststype: str, base: date) -> tuple[str, str]:
    """일/주/월별 조회에 맞는 stdate~eddate 산출 (최대 31일)."""
    if ststype == "week":
        start = base - timedelta(days=6)
    elif ststype == "month":
        start = base.replace(day=1)
    else:
        start = base
    start, end = clamp_period(start, base, max_days=31)
    return to_yyyymmdd(start), to_yyyymmdd(end)


def show_api_error() -> None:
    st.error("데이터를 불러오지 못했습니다. 날짜 범위를 확인해주세요.")


def metric_fmt_int(n: int | float) -> str:
    return f"{int(n):,}"


def metric_fmt_won(n: int | float) -> str:
    return f"{int(n):,}원"


def download_buttons(df: pd.DataFrame, stem: str) -> None:
    df = unique_columns(df)
    if df.empty:
        st.info("다운로드할 데이터가 없습니다.")
        return
    c1, c2 = st.columns(2)
    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    c1.download_button(
        "📥 CSV 다운로드",
        data=csv_bytes,
        file_name=f"{stem}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
    c2.download_button(
        "📥 Excel 다운로드",
        data=buf.getvalue(),
        file_name=f"{stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("KOPIS Research Lab")
    st.caption("공연예술통합전산망 Open API · 논문 연구용")

    today = date.today()
    default_end = today - timedelta(days=1)
    default_start = default_end - timedelta(days=6)

    st.subheader("공통 검색 조건")
    date_range = st.date_input(
        "조회 기간",
        value=(default_start, default_end),
        max_value=today,
        help="통계·예매 API는 보통 최대 31일까지 조회 가능합니다.",
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range if isinstance(date_range, date) else default_start

    start_date, end_date = clamp_period(start_date, end_date, max_days=31)
    stdate = to_yyyymmdd(start_date)
    eddate = to_yyyymmdd(end_date)

    genre_label = st.selectbox("장르 선택", list(GENRE_OPTIONS.keys()))
    area_label = st.selectbox("지역 선택", list(AREA_OPTIONS.keys()))
    shcate = GENRE_OPTIONS[genre_label]
    signgucode = AREA_OPTIONS[area_label]
    # boxoffice용 지역/장르 코드
    catecode = shcate
    area_code = signgucode

    st.divider()
    st.markdown(
        f"**조회 기간:** `{stdate}` ~ `{eddate}`  \n"
        f"**장르:** {genre_label}  \n"
        f"**지역:** {area_label}"
    )
    st.caption("API 결과는 1시간 캐시됩니다 (@st.cache_data ttl=3600).")


st.title("🎭 KOPIS 공연예술 연구 데이터 랩")
st.markdown(
    "KOPIS Open API **19개** 데이터 서비스를 통합 활용하는 논문·연구용 대시보드입니다."
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "📊 시장 거시 통계",
        "🏆 예매 랭킹 & 박스오피스",
        "🎭 공연 Archive & 검색",
        "🏛️ 인프라 & 제작사 DB",
        "🔬 연구 데이터 랩",
    ]
)


# ===========================================================================
# Tab 1: 시장 거시 통계
# ===========================================================================
with tab1:
    st.subheader("시장 거시 통계")
    st.caption("활용 API: `/prfstsTotal`, `/prfstsCate`, `/prfstsArea`, `/prfstsPrice`")

    with st.spinner("거시 통계 데이터를 불러오는 중..."):
        total_rows = fetch_kopis(
            "prfstsTotal",
            {"ststype": "day", "stdate": stdate, "eddate": eddate},
        )
        cate_rows = fetch_kopis(
            "prfstsCate",
            {"stdate": stdate, "eddate": eddate},
        )
        area_rows = fetch_kopis(
            "prfstsArea",
            {"stdate": stdate, "eddate": eddate},
        )
        price_rows = fetch_kopis(
            "prfstsPrice",
            {"stdate": stdate, "eddate": eddate},
        )

    if not total_rows and not cate_rows and not area_rows:
        show_api_error()
    else:
        # 요약 메트릭
        sum_tickets = sum(safe_int(r.get("nmrs")) for r in total_rows)
        sum_amount = sum(safe_int(r.get("amount")) for r in total_rows)
        sum_open = sum(safe_int(r.get("prfprocnt")) for r in total_rows)
        sum_shows = sum(safe_int(r.get("prfdtcnt")) for r in total_rows)

        # total이 비면 장르 합으로 대체
        if not total_rows and cate_rows:
            sum_tickets = sum(safe_int(r.get("nmrs")) for r in cate_rows)
            sum_amount = sum(safe_int(r.get("amount")) for r in cate_rows)
            sum_open = sum(safe_int(r.get("prfprocnt")) for r in cate_rows)
            sum_shows = sum(safe_int(r.get("prfdtcnt")) for r in cate_rows)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 티켓 판매수", metric_fmt_int(sum_tickets))
        m2.metric("총 매출액", metric_fmt_won(sum_amount))
        m3.metric("개막 편수", metric_fmt_int(sum_open))
        m4.metric("상연 횟수", metric_fmt_int(sum_shows))

        c_left, c_right = st.columns(2)

        # 일별 매출 추이
        with c_left:
            st.markdown("#### 일별 매출 추이")
            if total_rows:
                df_total = unique_columns(pd.DataFrame(total_rows))
                df_total["일자"] = df_total["prfdt"] if "prfdt" in df_total.columns else ""
                df_total["매출액"] = df_total["amount"].map(safe_int) if "amount" in df_total.columns else 0
                df_total["티켓판매수"] = df_total["nmrs"].map(safe_int) if "nmrs" in df_total.columns else 0
                df_total = unique_columns(df_total)
                fig_line = go.Figure()
                fig_line.add_trace(
                    go.Scatter(
                        x=df_total["일자"],
                        y=df_total["매출액"],
                        mode="lines+markers",
                        name="매출액",
                        line=dict(color="#1f4e79", width=2),
                    )
                )
                fig_line.add_trace(
                    go.Bar(
                        x=df_total["일자"],
                        y=df_total["티켓판매수"],
                        name="티켓판매수",
                        yaxis="y2",
                        opacity=0.35,
                        marker_color="#5b9bd5",
                    )
                )
                fig_line.update_layout(
                    height=380,
                    margin=dict(l=20, r=20, t=30, b=20),
                    yaxis=dict(title="매출액(원)"),
                    yaxis2=dict(title="티켓판매수", overlaying="y", side="right"),
                    legend=dict(orientation="h", y=1.12),
                )
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("일별 매출 데이터가 없습니다.")

        # 장르별 관객 점유율
        with c_right:
            st.markdown("#### 장르별 관객 점유율(%)")
            if cate_rows:
                df_cate = unique_columns(pd.DataFrame(cate_rows))
                df_cate["장르"] = df_cate["cate"] if "cate" in df_cate.columns else ""
                df_cate["관객수"] = df_cate["nmrs"].map(safe_int) if "nmrs" in df_cate.columns else 0
                df_cate["관객점유율"] = (
                    df_cate["nmrsshr"].map(safe_float) if "nmrsshr" in df_cate.columns else 0.0
                )
                df_cate = unique_columns(df_cate)
                # 점유율이 없으면 관객수 비중으로 계산
                if df_cate["관객점유율"].sum() <= 0 and df_cate["관객수"].sum() > 0:
                    df_cate["관객점유율"] = (
                        df_cate["관객수"] / df_cate["관객수"].sum() * 100
                    )
                fig_pie = px.pie(
                    df_cate,
                    names="장르",
                    values="관객점유율",
                    hole=0.35,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                fig_pie.update_layout(
                    height=380,
                    margin=dict(l=20, r=20, t=30, b=20),
                    showlegend=True,
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("장르별 통계 데이터가 없습니다.")

        # 지역별 총 좌석 수 대비 판매량
        st.markdown("#### 지역별 총 좌석 수 대비 판매량 비교")
        if area_rows:
            df_area = unique_columns(pd.DataFrame(area_rows))
            df_area["지역"] = df_area["area"] if "area" in df_area.columns else ""
            df_area["총좌석수"] = df_area["seatcnt"].map(safe_int) if "seatcnt" in df_area.columns else 0
            df_area["총티켓판매수"] = df_area.apply(
                lambda r: safe_int(r.get("totnmrs") or r.get("nmrs")), axis=1
            )
            df_area = unique_columns(df_area)
            fig_area = go.Figure()
            fig_area.add_trace(
                go.Bar(name="총 좌석 수", x=df_area["지역"], y=df_area["총좌석수"], marker_color="#8faadc")
            )
            fig_area.add_trace(
                go.Bar(
                    name="총 티켓 판매수",
                    x=df_area["지역"],
                    y=df_area["총티켓판매수"],
                    marker_color="#c55a11",
                )
            )
            fig_area.update_layout(
                barmode="group",
                height=420,
                margin=dict(l=20, r=20, t=30, b=20),
                xaxis_title="지역",
                yaxis_title="수량",
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig_area, use_container_width=True)
            safe_dataframe(rows_to_df(area_rows), use_container_width=True, hide_index=True)
        else:
            st.info("지역별 통계 데이터가 없습니다.")

        with st.expander("가격대별 통계 (/prfstsPrice)"):
            if price_rows:
                safe_dataframe(rows_to_df(price_rows), use_container_width=True, hide_index=True)
            else:
                st.info("가격대별 통계가 없습니다.")


# ===========================================================================
# Tab 2: 예매 랭킹 & 박스오피스
# ===========================================================================
with tab2:
    st.subheader("예매 랭킹 & 박스오피스")
    st.caption("활용 API: `/boxoffice`")

    f1, f2, f3 = st.columns(3)
    with f1:
        period_label = st.selectbox("조회 구분", list(BOX_PERIOD_OPTIONS.keys()))
        ststype = BOX_PERIOD_OPTIONS[period_label]
    with f2:
        seat_label = st.selectbox("좌석 수 규모", list(SEAT_SCALE_OPTIONS.keys()))
        srchseatscale = SEAT_SCALE_OPTIONS[seat_label]
    with f3:
        box_date = st.date_input("기준일 (date)", value=end_date, key="box_date")

    box_st, box_ed = boxoffice_period(ststype, box_date)
    box_params = {
        "stdate": box_st,
        "eddate": box_ed,
        "catecode": catecode,
        "area": area_code,
        "srchseatscale": srchseatscale,
    }

    with st.spinner("박스오피스 데이터를 불러오는 중..."):
        box_rows = fetch_kopis("boxoffice", box_params)

    if not box_rows:
        show_api_error()
    else:
        df_box = unique_columns(pd.DataFrame(box_rows))
        display_cols = {
            "rnum": "순위",
            "prfnm": "공연명",
            "cate": "장르",
            "prfplcnm": "공연장",
            "seatcnt": "좌석 수",
            "prfpd": "공연기간",
            "prfdtcnt": "상연횟수",
            "area": "지역",
        }
        keep = [c for c in display_cols if c in df_box.columns]
        view = df_box[keep].copy()
        view.columns = make_unique_labels(list(view.columns), display_cols)
        view = unique_columns(view)
        if "순위" in view.columns:
            view["순위"] = view["순위"].map(safe_int)
            view = view.sort_values("순위")
        safe_dataframe(view, use_container_width=True, hide_index=True)

        if "장르" in view.columns:
            genre_cnt = view["장르"].value_counts().reset_index()
            genre_cnt.columns = ["장르", "작품수"]
            fig_box = px.bar(
                genre_cnt,
                x="장르",
                y="작품수",
                title="박스오피스 장르 분포",
                color="장르",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_box.update_layout(showlegend=False, height=360, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_box, use_container_width=True)


# ===========================================================================
# Tab 3: 공연 Archive & 검색
# ===========================================================================
with tab3:
    st.subheader("공연 Archive & 검색")
    st.caption("활용 API: `/pblprfr`, `/pblprfr/{mt20id}`, `/prfawad`, `/prffest`, `/prfper`")

    s1, s2, s3 = st.columns([2, 1, 1])
    with s1:
        keyword = st.text_input("작품명 검색", placeholder="공연명 일부를 입력하세요")
    with s2:
        only_award = st.checkbox("수상작만 보기")
    with s3:
        only_fest = st.checkbox("축제만 보기")

    list_params: dict[str, Any] = {
        "stdate": stdate,
        "eddate": eddate,
        "cpage": "1",
        "rows": "50",
        "shprfnm": keyword.strip() if keyword else "",
        "shcate": shcate,
        "signgucode": signgucode,
    }

    with st.spinner("공연 목록을 불러오는 중..."):
        if only_award and only_fest:
            award_rows = fetch_kopis("prfawad", list_params)
            fest_rows = fetch_kopis("prffest", list_params)
            # 교집합(공연ID 기준)
            fest_ids = {r.get("mt20id") for r in fest_rows}
            perf_rows = [r for r in award_rows if r.get("mt20id") in fest_ids]
        elif only_award:
            perf_rows = fetch_kopis("prfawad", list_params)
        elif only_fest:
            perf_rows = fetch_kopis("prffest", list_params)
        else:
            perf_rows = fetch_kopis("pblprfr", list_params)
            # 보조: 기간 공연 목록
            per_rows = fetch_kopis("prfper", list_params)
            if not perf_rows and per_rows:
                perf_rows = per_rows

    if not perf_rows:
        show_api_error()
    else:
        df_perf = unique_columns(pd.DataFrame(perf_rows))
        label_map = {
            "mt20id": "공연ID",
            "prfnm": "공연명",
            "genrenm": "장르",
            "fcltynm": "공연장",
            "prfpdfrom": "시작일",
            "prfpdto": "종료일",
            "area": "지역",
            "prfstate": "상태",
        }
        show_cols = [c for c in label_map if c in df_perf.columns]
        list_view = df_perf[show_cols].copy()
        list_view.columns = make_unique_labels(list(list_view.columns), label_map)
        list_view = unique_columns(list_view)
        safe_dataframe(list_view, use_container_width=True, hide_index=True)

        options = []
        for r in perf_rows:
            pid = r.get("mt20id", "")
            pname = r.get("prfnm", "")
            if pid:
                options.append(f"{pname} [{pid}]")

        selected = st.selectbox("상세 조회할 공연 선택", options if options else ["(없음)"])
        if options and selected:
            mt20id = selected.rsplit("[", 1)[-1].rstrip("]")
            detail_rows = fetch_kopis(f"pblprfr/{mt20id}", {})
            if not detail_rows:
                st.warning("상세 정보를 불러오지 못했습니다.")
            else:
                d = detail_rows[0]
                left, right = st.columns([1, 2])
                with left:
                    poster = d.get("poster") or ""
                    if poster:
                        st.image(poster, use_container_width=True, caption="포스터")
                    else:
                        st.info("포스터 이미지가 없습니다.")
                with right:
                    st.markdown(f"### {d.get('prfnm') or selected}")
                    st.markdown(
                        f"**장르:** {d.get('genrenm', '')}  ·  "
                        f"**기간:** {d.get('prfpdfrom', '')} ~ {d.get('prfpdto', '')}  ·  "
                        f"**장소:** {d.get('fcltynm', '')}"
                    )
                    st.markdown(f"**출연진:** {d.get('prfcast', '') or '-'}")
                    st.markdown(f"**관람료:** {d.get('pcseguidance', '') or '-'}")
                    st.markdown(f"**관람연령:** {d.get('prfage', '') or '-'}  ·  **런타임:** {d.get('prfruntime', '') or '-'}")
                    st.markdown("**줄거리**")
                    st.write(d.get("sty", "") or "줄거리 정보가 없습니다.")


# ===========================================================================
# Tab 4: 인프라 & 제작사 DB
# ===========================================================================
with tab4:
    st.subheader("인프라 & 제작사 DB")
    st.caption("활용 API: `/prfplc`, `/prfplc/{mt10id}`, `/mnfct`")

    mode = st.radio("조회 대상", ["공연장(시설)", "기획/제작사"], horizontal=True)

    if mode == "공연장(시설)":
        i1, i2 = st.columns(2)
        with i1:
            facility_q = st.text_input("공연장(시설명) 검색", placeholder="예: 예술의전당")
        with i2:
            char_label = st.selectbox("시설 특성", list(FACILITY_CHAR_OPTIONS.keys()))
            fcltychartr = FACILITY_CHAR_OPTIONS[char_label]

        fac_params = {
            "cpage": "1",
            "rows": "50",
            "shprfnmfct": facility_q.strip() if facility_q else "",
            "fcltychartr": fcltychartr,
            "signgucode": signgucode,
        }

        with st.spinner("공연시설 목록을 불러오는 중..."):
            fac_rows = fetch_kopis("prfplc", fac_params)

        if not fac_rows:
            show_api_error()
        else:
            df_fac = rows_to_df(fac_rows)
            safe_dataframe(df_fac, use_container_width=True, hide_index=True)

            fac_opts = [
                f"{r.get('fcltynm', '')} [{r.get('mt10id', '')}]"
                for r in fac_rows
                if r.get("mt10id")
            ]
            picked = st.selectbox("시설 상세(편의시설/장애인 시설)", fac_opts if fac_opts else ["(없음)"])
            if fac_opts and picked:
                mt10id = picked.rsplit("[", 1)[-1].rstrip("]")
                detail = fetch_kopis(f"prfplc/{mt10id}", {})
                if not detail:
                    st.warning("시설 상세를 불러오지 못했습니다.")
                else:
                    d = detail[0]
                    st.markdown(f"### {d.get('fcltynm', '')}")
                    st.markdown(
                        f"**주소:** {d.get('adres', '')}  ·  **객석수:** {d.get('seatscale', '')}  ·  "
                        f"**개관:** {d.get('opende', '')}"
                    )
                    amenity = unique_columns(
                        pd.DataFrame(
                            [
                                {"구분": "편의시설", "항목": "레스토랑", "현황": d.get("restaurant", "")},
                                {"구분": "편의시설", "항목": "카페", "현황": d.get("cafe", "")},
                                {"구분": "편의시설", "항목": "편의점", "현황": d.get("store", "")},
                                {"구분": "편의시설", "항목": "놀이방", "현황": d.get("nolibang", "")},
                                {"구분": "편의시설", "항목": "수유실", "현황": d.get("suyu", "")},
                                {"구분": "편의시설", "항목": "주차장", "현황": d.get("parkinglot", "")},
                                {"구분": "장애인 시설", "항목": "주차장", "현황": d.get("parkbarrier", "")},
                                {"구분": "장애인 시설", "항목": "화장실", "현황": d.get("restbarrier", "")},
                                {"구분": "장애인 시설", "항목": "경사로", "현황": d.get("runwbarrier", "")},
                                {"구분": "장애인 시설", "항목": "엘리베이터", "현황": d.get("elevbarrier", "")},
                                {
                                    "구분": "장애인 시설",
                                    "항목": "관객석",
                                    "현황": d.get("disabledseatscale", ""),
                                },
                            ]
                        )
                    )
                    st.markdown("#### 편의시설 / 장애인 시설 현황")
                    safe_dataframe(amenity, use_container_width=True, hide_index=True)
    else:
        mnf_q = st.text_input("제작사명 검색", placeholder="예: 극단")
        mnf_params = {
            "cpage": "1",
            "rows": "50",
            "entrpsnm": mnf_q.strip() if mnf_q else "",
            "shcate": shcate,
            "signgucode": signgucode,
        }
        with st.spinner("제작사 목록을 불러오는 중..."):
            mnf_rows = fetch_kopis("mnfct", mnf_params)
        if not mnf_rows:
            show_api_error()
        else:
            safe_dataframe(rows_to_df(mnf_rows), use_container_width=True, hide_index=True)


# ===========================================================================
# Tab 5: 연구 데이터 랩
# ===========================================================================
with tab5:
    st.subheader("연구 데이터 랩")
    st.caption(
        "현재 조건 기반 기초통계량 및 19개 서비스 데이터셋 다운로드 "
        "(`/boxStats`, `/boxStatsCate`, `/boxStatsTime`, `/boxStatsPrice`, "
        "`/prfstsPrfBy`, `/prfstsPrfByFct` 포함)"
    )

    dataset_name = st.selectbox(
        "분석·다운로드 데이터셋",
        [
            "기간별 통계 (prfstsTotal)",
            "장르별 통계 (prfstsCate)",
            "지역별 통계 (prfstsArea)",
            "가격대별 통계 (prfstsPrice)",
            "예매통계 기간별 (boxStats)",
            "예매통계 장르별 (boxStatsCate)",
            "예매통계 시간대별 (boxStatsTime)",
            "예매통계 가격대별 (boxStatsPrice)",
            "공연별 통계 (prfstsPrfBy)",
            "공연시설별 통계 (prfstsPrfByFct)",
            "공연 목록 (pblprfr)",
            "박스오피스 (boxoffice)",
        ],
    )

    with st.spinner("연구용 데이터셋을 불러오는 중..."):
        if dataset_name.startswith("기간별"):
            raw = fetch_kopis("prfstsTotal", {"ststype": "day", "stdate": stdate, "eddate": eddate})
            stem = "prfstsTotal"
        elif dataset_name.startswith("장르별"):
            raw = fetch_kopis("prfstsCate", {"stdate": stdate, "eddate": eddate})
            stem = "prfstsCate"
        elif dataset_name.startswith("지역별"):
            raw = fetch_kopis("prfstsArea", {"stdate": stdate, "eddate": eddate})
            stem = "prfstsArea"
        elif dataset_name.startswith("가격대별"):
            raw = fetch_kopis("prfstsPrice", {"stdate": stdate, "eddate": eddate})
            stem = "prfstsPrice"
        elif "boxStatsCate" in dataset_name:
            raw = fetch_kopis("boxStatsCate", {"stdate": stdate, "eddate": eddate, "ststype": "day"})
            stem = "boxStatsCate"
        elif "boxStatsTime" in dataset_name:
            raw = fetch_kopis("boxStatsTime", {"stdate": stdate, "eddate": eddate, "ststype": "day"})
            stem = "boxStatsTime"
        elif "boxStatsPrice" in dataset_name:
            raw = fetch_kopis("boxStatsPrice", {"stdate": stdate, "eddate": eddate, "ststype": "day"})
            stem = "boxStatsPrice"
        elif dataset_name.startswith("예매통계 기간별"):
            raw = fetch_kopis("boxStats", {"stdate": stdate, "eddate": eddate, "ststype": "day"})
            stem = "boxStats"
        elif dataset_name.startswith("공연별"):
            raw = fetch_kopis(
                "prfstsPrfBy",
                {"cpage": "1", "rows": "100", "stdate": stdate, "eddate": eddate, "shcate": shcate},
            )
            stem = "prfstsPrfBy"
        elif dataset_name.startswith("공연시설별"):
            raw = fetch_kopis(
                "prfstsPrfByFct",
                {
                    "cpage": "1",
                    "rows": "100",
                    "stdate": stdate,
                    "eddate": eddate,
                    "sharea": signgucode,
                },
            )
            stem = "prfstsPrfByFct"
        elif dataset_name.startswith("공연 목록"):
            raw = fetch_kopis(
                "pblprfr",
                {
                    "stdate": stdate,
                    "eddate": eddate,
                    "cpage": "1",
                    "rows": "100",
                    "shcate": shcate,
                    "signgucode": signgucode,
                },
            )
            stem = "pblprfr"
        else:
            raw = fetch_kopis(
                "boxoffice",
                {
                    "stdate": eddate,
                    "eddate": eddate,
                    "catecode": catecode,
                    "area": area_code,
                },
            )
            stem = "boxoffice"

    if not raw:
        show_api_error()
    else:
        df = rows_to_df(raw, rename=True)
        st.markdown("#### 미리보기")
        safe_dataframe(df, use_container_width=True, hide_index=True)

        # 수치형 변환 후 describe
        num_df = unique_columns(df.copy())
        for col in list(num_df.columns):
            converted = pd.to_numeric(
                num_df[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
            if converted.notna().sum() >= max(1, int(len(num_df) * 0.3)):
                num_df[col] = converted
        num_df = unique_columns(num_df)

        st.markdown("#### 기초통계량 (`.describe()`)")
        desc = unique_columns(num_df.describe(include="all").transpose())
        safe_dataframe(desc, use_container_width=True)

        st.markdown("#### 데이터 다운로드")
        download_buttons(unique_columns(df), f"kopis_{stem}_{stdate}_{eddate}")

        # 전체 서비스 커버리지 안내
        with st.expander("통합 활용 중인 KOPIS Open API 19개 서비스"):
            st.markdown(
                """
| # | 엔드포인트 | 용도 | 탭 |
|---|---|---|---|
| 1 | `/pblprfr` | 공연 목록 | Tab 3, 5 |
| 2 | `/pblprfr/{mt20id}` | 공연 상세 | Tab 3 |
| 3 | `/prfplc` | 공연시설 목록 | Tab 4 |
| 4 | `/prfplc/{mt10id}` | 공연시설 상세 | Tab 4 |
| 5 | `/mnfct` | 기획/제작사 | Tab 4 |
| 6 | `/prfawad` | 수상작 | Tab 3 |
| 7 | `/prffest` | 축제 | Tab 3 |
| 8 | `/prfper` | 공연기간 목록 | Tab 3 |
| 9 | `/boxoffice` | 예매상황판 | Tab 2, 5 |
| 10 | `/boxStats` | 예매통계 기간별 | Tab 5 |
| 11 | `/boxStatsCate` | 예매통계 장르별 | Tab 5 |
| 12 | `/boxStatsTime` | 예매통계 시간대 | Tab 5 |
| 13 | `/boxStatsPrice` | 예매통계 가격대 | Tab 5 |
| 14 | `/prfstsTotal` | 기간별 통계 | Tab 1, 5 |
| 15 | `/prfstsArea` | 지역별 통계 | Tab 1, 5 |
| 16 | `/prfstsCate` | 장르별 통계 | Tab 1, 5 |
| 17 | `/prfstsPrfBy` | 공연별 통계 | Tab 5 |
| 18 | `/prfstsPrfByFct` | 시설별 통계 | Tab 5 |
| 19 | `/prfstsPrice` | 가격대별 통계 | Tab 1, 5 |
                """
            )


# ===========================================================================
# Tab 6: Research-oriented J-POP data collection
# ===========================================================================
from jpop_research import render_jpop_research

with tab6:
    render_jpop_research(SERVICE_KEY)
