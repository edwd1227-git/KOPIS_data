"""KOPIS J-POP research helpers and Streamlit tab.

The API does not label Japan as a performer nationality; candidate matching is only
a discovery aid. A researcher must verify country and solo-concert eligibility.
"""
from __future__ import annotations

import calendar
import io
import re
import time
from datetime import date
from xml.etree import ElementTree as ET

import pandas as pd
import requests
import streamlit as st

BASE_URL = "http://www.kopis.or.kr/openApi/restful"
TARGET_ALIASES = {
    "Ado": ["Ado", "아도"],
    "Fujii Kaze": ["Fujii Kaze", "후지이 카제", "후지이카제", "藤井風"],
    "OFFICIAL HIGE DANDISM": [
        "OFFICIAL HIGE DANDISM", "Official髭男dism",
        "오피셜히게단디즘", "오피셜 히게 단디즘", "히게단",
    ],
}
RESEARCH_FIELDS = [
    "mt20id", "prfnm", "prfpdfrom", "prfpdto", "fcltynm", "area",
    "genrenm", "prfstate", "visit", "prfcast", "entrpsnm", "pcseguidance",
    "prfdtcnt", "seatscale",
]
VERIFICATION_COLUMNS = {
    "artist_verified": "아티스트(검증 후 입력)",
    "japan_verified": "일본 아티스트 여부(확인 필요)",
    "solo_verified": "단독공연 여부(확인 필요)",
    "official_source": "검증 출처 URL",
    "notes": "검증 메모",
}


def month_windows(year: int, months: list[int]) -> list[tuple[str, str]]:
    """Create non-overlapping periods of <=31 calendar days."""
    return [
        (f"{year}{month:02d}01",
         f"{year}{month:02d}{calendar.monthrange(year, month)[1]:02d}")
        for month in sorted(set(months))
        if 1 <= month <= 12
    ]


def normalize_title(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", (value or "").casefold())


def matched_artist(title: str) -> str:
    normalized = normalize_title(title)
    for artist, aliases in TARGET_ALIASES.items():
        if any(normalize_title(alias) in normalized for alias in aliases):
            return artist
    return ""


def extract_items(xml: str, tag: str = "db") -> list[dict[str, str]]:
    """Extract list rows, preserving original KOPIS XML field names."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("KOPIS 응답이 올바른 XML이 아닙니다.") from exc
    error = root.findtext(".//errmsg") or root.findtext(".//message")
    if error and not root.findall(f".//{tag}"):
        raise ValueError(f"KOPIS API 오류: {error}")
    nodes = root.findall(f".//{tag}")
    if root.tag == tag:
        nodes = [root]
    return [
        {child.tag: child.text or "" for child in item if len(child) == 0}
        for item in nodes
    ]


class KOPISClient:
    def __init__(self, service_key: str, timeout: int = 25, session=None):
        if not service_key:
            raise ValueError("KOPIS API 서비스 키가 필요합니다.")
        self.service_key = service_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def get(self, endpoint: str, params: dict, tag: str = "db") -> list[dict[str, str]]:
        parameters = {"service": self.service_key, **params}
        # Do not include key, full URL or the raw response in exceptions.
        try:
            response = self.session.get(
                f"{BASE_URL}/{endpoint.lstrip('/')}",
                params=parameters, timeout=self.timeout
            )
            response.raise_for_status()
            return extract_items(response.text, tag=tag)
        except requests.RequestException as exc:
            raise RuntimeError(f"KOPIS API 연결/HTTP 오류: {type(exc).__name__}") from None

    def collect(
        self,
        year: int,
        months: list[int],
        endpoint: str = "pblprfr",
        keyword: str = "",
        max_pages: int = 40,
        progress=None,
    ) -> tuple[list[dict[str, str]], dict]:
        """Walk all requested months/pages, deduplicating records by KOPIS ID.

        If max_pages is hit, the result is explicitly flagged as incomplete.
        Do not treat these rows as exhaustive national counts.
        """
        windows = month_windows(year, months)
        records: dict[str, dict[str, str]] = {}
        requests_made = 0
        capped = []
        for index, (start, end) in enumerate(windows, 1):
            for page in range(1, max_pages + 1):
                rows = self.get(endpoint, {
                    "cpage": page, "rows": 100,
                    "stdate": start, "eddate": end,
                    "shcate": "CCCD",
                    **({"shprfnm": keyword} if keyword else {}),
                }, tag="db" if endpoint == "pblprfr" else "prfst")
                requests_made += 1
                for row in rows:
                    identity = row.get("mt20id") or (
                        f"{row.get('prfnm','')}|{row.get('prfpdfrom','')}|"
                        f"{row.get('fcltynm','')}"
                    )
                    records[identity] = {**records.get(identity, {}), **row}
                if len(rows) < 100:
                    break
                if page == max_pages:
                    capped.append((start, end))
            if progress:
                progress(index, len(windows))
        return list(records.values()), {
            "year": year,
            "months": months,
            "requests_made": requests_made,
            "page_limit_reached": capped,
            "dataset_exhaustive": not bool(capped) and not bool(keyword),
            "endpoint": endpoint,
            "keyword": keyword,
        }

    def detail(self, performance_id: str) -> dict[str, str]:
        if not re.fullmatch(r"PF[0-9]+", performance_id or ""):
            raise ValueError("공연 ID 형식이 올바르지 않습니다.")
        rows = self.get(f"pblprfr/{performance_id}", {})
        return rows[0] if rows else {}


def create_review_table(records: list[dict[str, str]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for field in RESEARCH_FIELDS:
        if field not in df.columns:
            df[field] = ""
    df = df[RESEARCH_FIELDS].copy()
    df.insert(1, "후보 아티스트(공연명 기준)", df["prfnm"].map(matched_artist))
    for name, label in VERIFICATION_COLUMNS.items():
        df[label] = ""
    return df


def export_excel(df: pd.DataFrame, metadata: dict) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="공연목록_검증대상")
        pd.DataFrame([
            {"항목": k, "값": str(v)} for k, v in metadata.items()
        ]).to_excel(writer, index=False, sheet_name="수집조건_한계")
    return out.getvalue()


def render_jpop_research(service_key: str) -> None:
    st.subheader("J-POP 내한공연 연구 · KOPIS 자료 수집")
    st.info(
        "이 탭은 연구용 후보 목록 구축 도구입니다. KOPIS에는 일본 국적 분류가 "
        "없으므로 공연명 후보 탐색 뒤 출연진 국적과 단독공연 여부를 공식 자료로 "
        "반드시 검증해야 합니다. 공연장 객석 수는 실제 관객 수가 아닙니다."
    )
    left, middle, right = st.columns([1, 2, 1])
    with left:
        year = st.selectbox("조사 연도", list(range(2019, 2025)), index=5, key="jpop_year")
    with middle:
        months = st.multiselect(
            "조사 월 (여러 달 선택 가능)", list(range(1, 13)),
            default=list(range(1, 13)), key="jpop_months"
        )
    with right:
        max_pages = st.number_input(
            "월별 최대 페이지", min_value=1, max_value=100, value=40,
            step=1, key="jpop_maxpages"
        )
    mode = st.radio(
        "수집 방식",
        ["대중음악 공연 전체 목록 수집 후 검토",
         "아티스트/공연명 키워드로 좁혀 검색"],
        horizontal=True,
        key="jpop_mode",
    )
    keyword = ""
    if mode.startswith("아티스트"):
        st.caption("한 번에 한 검색어를 조회합니다. 검색어에 없는 공연은 누락될 수 있습니다.")
        keyword = st.text_input("공연명 검색어", value="Ado", key="jpop_keyword").strip()
    st.caption(
        "KOPIS 최대 31일 조회 제한을 월별로 나누고, 최대 100건/페이지를 "
        "순회합니다. 넓은 범위는 API 요청이 많아 오래 걸릴 수 있습니다."
    )

    if st.button("공연자료 수집 시작", type="primary", key="jpop_collect"):
        if not months:
            st.warning("한 개 이상의 월을 선택해 주세요.")
        elif mode.startswith("아티스트") and not keyword:
            st.warning("검색어를 입력해 주세요.")
        else:
            bar = st.progress(0, text="KOPIS 공연목록 조회 중")
            def on_progress(done: int, total: int) -> None:
                bar.progress(done / total, text=f"조사 월 {done}/{total} 완료")
            try:
                client = KOPISClient(service_key)
                records, meta = client.collect(
                    year, months, keyword=keyword,
                    max_pages=int(max_pages), progress=on_progress
                )
                st.session_state["jpop_dataset"] = records
                st.session_state["jpop_dataset_meta"] = meta
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            finally:
                bar.empty()

    records = st.session_state.get("jpop_dataset")
    meta = st.session_state.get("jpop_dataset_meta")
    if records is None or meta is None:
        return
    st.markdown("### 수집된 공연 목록")
    st.caption(
        f"수집 연도: {meta['year']} · 선택 월: {meta['months']} · "
        f"API 요청: {meta['requests_made']}회 · 중복 제거 후 {len(records):,}건"
    )
    if meta["page_limit_reached"]:
        st.error(
            "일부 월에서 최대 페이지에 도달해 목록이 불완전합니다: "
            f"{meta['page_limit_reached']}. 최대 페이지 수를 늘려 다시 수집해 주세요."
        )
    if meta["keyword"]:
        st.warning("키워드 검색 결과는 해당 연도의 전체 공연 수를 의미하지 않습니다.")
    st.warning(
        "공연 목록은 국적·단독공연 검증 전 원자료입니다. "
        "J-POP 공연 수 또는 전체 시장 성장률로 그대로 인용하지 마세요."
    )
    if not records:
        st.info("조회 결과가 없습니다. 기간·검색어 또는 API 권한을 확인해 주세요.")
        return

    table = create_review_table(records)
    show_only_candidates = st.checkbox("세 주요 아티스트의 공연명 후보만 보기", value=False)
    if show_only_candidates:
        table = table[table["후보 아티스트(공연명 기준)"] != ""].copy()
    st.caption(
        "아래 검증 열은 편집 후 CSV/Excel로 저장할 수 있습니다. "
        "검색어 일치는 국적의 증거가 아닙니다."
    )
    edited = st.data_editor(
        table, hide_index=True, use_container_width=True,
        num_rows="fixed", key=f"jpop_review_{meta['year']}_{meta['keyword']}_{len(records)}"
    )
    st.download_button(
        "검토 목록 CSV 저장", edited.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"kopis_jpop_review_{meta['year']}.csv",
        mime="text/csv", key="jpop_csv"
    )
    st.download_button(
        "검토 목록 Excel 저장", export_excel(edited, meta),
        file_name=f"kopis_jpop_review_{meta['year']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="jpop_xlsx"
    )
    st.markdown("### 개별 공연 상세 조회")
    ids = [str(row.get("mt20id", "")) for row in records if row.get("mt20id")]
    chosen = st.selectbox("공연 ID", sorted(set(ids)), key="jpop_detail_id")
    if st.button("공연 상세정보 조회", key="jpop_detail_fetch"):
        try:
            detail = KOPISClient(service_key).detail(chosen)
            if not detail:
                st.warning("해당 공연의 상세 정보가 조회되지 않았습니다.")
            else:
                st.json({
                    k: detail.get(k, "") for k in
                    ("mt20id", "prfnm", "prfpdfrom", "prfpdto",
                     "prfcast", "fcltynm", "genrenm", "visit",
                     "entrpsnm", "entrpsnmH", "entrpsnmS",
                     "pcseguidance", "dtguidance")
                })
                st.caption(
                    "visit=Y는 내한 여부이며 일본 국적이나 실제 판매량을 "
                    "보증하지 않습니다."
                )
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
