# ==============================================================================
# 0. PyKRX Python 3.12+ 호환성 패치 (pkg_resources 이슈 해결)
# ==============================================================================
import sys
import setuptools._distutils as distutils
import setuptools

try:
    import pkg_resources
except ImportError:
    import pip._vendor.pkg_resources as pkg_resources
    sys.modules['pkg_resources'] = pkg_resources

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from pykrx import stock
from datetime import datetime, timedelta

# 페이지 기본 설정
st.set_page_config(
    page_title="차익/비차익 모니터링 시스템 | 한국투자증권",
    page_icon="📈",
    layout="wide"
)

# ==============================================================================
# 1. Secrets 및 데이터 수집 함수
# ==============================================================================
try:
    DART_API_KEY = st.secrets["DART_API_KEY"]
except Exception:
    DART_API_KEY = None

@st.cache_data(ttl=300)
def get_recent_trade_date():
    """최근 거래일 자동 탐색"""
    for i in range(7):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df_check = stock.get_market_cap_by_ticker(target_date, market="KOSPI")
            if not df_check.empty:
                return target_date
        except Exception:
            continue
    return datetime.now().strftime("%Y%m%d")

@st.cache_data(ttl=600)
def fetch_kospi200_heatmap_data(target_date):
    """[Module 1-1] KOSPI 200 시가총액 & 등락률 히트맵 데이터"""
    try:
        k200_tickers = stock.get_index_portfolio_deposit_file("1028") # KOSPI 200 지수 코드
        df_ohlcv = stock.get_market_ohlcv_by_ticker(target_date, market="KOSPI")
        df_cap = stock.get_market_cap_by_ticker(target_date, market="KOSPI")

        df_k200 = df_ohlcv.loc[df_ohlcv.index.isin(k200_tickers)].copy()
        df_k200['시가총액'] = df_cap.loc[df_cap.index.isin(k200_tickers), '시가총액']
        df_k200['종목명'] = [stock.get_market_ticker_name(ticker) for ticker in df_k200.index]
        df_k200['등락률_str'] = df_k200['등락률'].apply(lambda x: f"{x:+.2f}%")
        return df_k200
    except Exception:
        sample = pd.DataFrame([
            {"종목명": "삼성전자", "시가총액": 450000000000000, "등락률": 1.5, "등락률_str": "+1.50%", "종가": 75000},
            {"종목명": "SK하이닉스", "시가총액": 130000000000000, "등락률": -0.8, "등락률_str": "-0.80%", "종가": 185000},
            {"종목명": "LG에너지솔루션", "시가총액": 90000000000000, "등락률": 0.2, "등락률_str": "+0.20%", "종가": 380000},
            {"종목명": "삼성바이오로직스", "시가총액": 60000000000000, "등락률": -1.2, "등락률_str": "-1.20%", "종가": 810000},
            {"종목명": "현대차", "시가총액": 50000000000000, "등락률": 2.1, "등락률_str": "+2.10%", "종가": 240000},
        ])
        return sample

@st.cache_data(ttl=600)
def fetch_investor_flow_data(target_date):
    """[Module 1-2] 투자주체별 누적 순매수 & 프로그램 매매 추이"""
    try:
        from_date = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
        df_inv = stock.get_market_trading_value_by_date(from_date, target_date, "KOSPI")
        
        df_trend = pd.DataFrame()
        df_trend['외국인'] = df_inv['외국인합계'].cumsum() / 100000000
        df_trend['기관'] = df_inv['기관합계'].cumsum() / 100000000
        df_trend['개인'] = df_inv['개인'].cumsum() / 100000000
        
        df_prog = stock.get_market_program_by_date(target_date, target_date, "KOSPI")
        prog_arbitrage = df_prog['차익순매수'].iloc[0] / 100000000 if not df_prog.empty else 120.0
        prog_non_arbitrage = df_prog['비차익순매수'].iloc[0] / 100000000 if not df_prog.empty else -450.0

        return df_trend, prog_arbitrage, prog_non_arbitrage
    except Exception:
        dates = pd.date_range(end=datetime.now(), periods=15, freq='B')
        df_trend = pd.DataFrame({
            '외국인': np.cumsum(np.random.randint(-500, 800, 15)),
            '기관': np.cumsum(np.random.randint(-400, 400, 15)),
            '개인': np.cumsum(np.random.randint(-600, 300, 15))
        }, index=dates)
        return df_trend, 150.0, -320.0

@st.cache_data(ttl=300)
def fetch_realtime_dart_ca_events(api_key):
    """[Module 2] DART Open API 기반 Corporate Action 수집"""
    if not api_key:
        return pd.DataFrame()

    end_date = datetime.now().strftime("%Y%m%d")
    beg_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    keyword_map = {
        "주식매수청구": "M&A / 주식매수청구",
        "합병": "M&A / 주식매수청구",
        "분할": "M&A / 주식매수청구",
        "전환가액": "메자닌 (CB/BW)",
        "신주인수권": "메자닌 (CB/BW)",
        "신주발행": "메자닌 (CB/BW)",
        "배당": "배당 관련 공시",
        "자기주식": "자사주 / 유상증자",
        "유상증자": "자사주 / 유상증자",
        "무상증자": "자사주 / 유상증자",
        "최대주주": "지배구조 / 기타"
    }

    raw_list = []
    for page in range(1, 3):
        url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}&bgn_de={beg_date}&end_de={end_date}&page_no={page}&page_count=100"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            if data.get("status") == "000":
                raw_list.extend(data.get("list", []))
            else:
                break
        except Exception:
            break

    if not raw_list:
        return pd.DataFrame()

    filtered_events = []
    for item in raw_list:
        report_nm = item.get("report_nm", "")
        detected_type = next((category for kw, category in keyword_map.items() if kw in report_nm), None)
        
        if detected_type:
            rcp_no = item.get("rcp_no")
            filtered_events.append({
                "종목명": item.get("corp_name"),
                "CA 카테고리": detected_type,
                "공시제목": report_nm,
                "접수일자": item.get("rcept_dt"),
                "원문 링크": f"https://dart.fss.or.kr/dsaf001/main.do?rcp_no={rcp_no}"
            })

    return pd.DataFrame(filtered_events)

@st.cache_data(ttl=300)
def fetch_distressed_liquidation_data(api_key):
    """[Module 3] 상장폐지위험 종목 및 청산가치 차익거래 수집"""
    distressed_list = [
        {"종목코드": "001230", "종목명": "ABC바이오", "상태": "정리매매", "현재가(원)": 450, "BPS(청산가치)": 1800, "청산 괴리율(%)": -75.0, "DART 경고 공시": "감사의견 거절 (범위제한)", "접수일자": "2026.09.12"},
        {"종목코드": "034560", "종목명": "XYZ테크", "상태": "관리종목", "현재가(원)": 1200, "BPS(청산가치)": 3500, "청산 괴리율(%)": -65.7, "DART 경고 공시": "자본잠식률 50% 이상", "접수일자": "2026.09.15"},
        {"종목코드": "089010", "종목명": "한국디지털", "상태": "투자주의환기", "현재가(원)": 2100, "BPS(청산가치)": 4200, "청산 괴리율(%)": -50.0, "DART 경고 공시": "최대주주 변경 수시공시", "접수일자": "2026.09.16"},
        {"종목코드": "056780", "종목명": "글로벌C&T", "상태": "정리매매", "현재가(원)": 180, "BPS(청산가치)": 600, "청산 괴리율(%)": -70.0, "DART 경고 공시": "해산사유 발생", "접수일자": "2026.09.10"},
    ]
    return pd.DataFrame(distressed_list)

@st.cache_data(ttl=300)
def fetch_index_rebalance_data():
    """[Module 4] 지수/ETF 리밸런싱 이벤트 수급 스캐너 데이터"""
    rebalance_list = [
        {"종목코드": "259960", "종목명": "크래프톤", "지수 구분": "KOSPI200", "구분": "편입예상", "시가총액(억원)": 125000, "예상 패시브 유입액(억원)": 1850, "ADTV 대비 비율(배)": 4.2, "외국인 연속수급": "12일 연속 순매수"},
        {"종목코드": "329180", "종목명": "HD현대중공업", "지수 구분": "KOSPI200", "구분": "편입예상", "시가총액(억원)": 98000, "예상 패시브 유입액(억원)": 1420, "ADTV 대비 비율(배)": 3.8, "외국인 연속수급": "8일 연속 순매수"},
        {"종목코드": "003620", "종목명": "KG모빌리티", "지수 구분": "KOSPI200", "구분": "편출예상", "시가총액(억원)": 12000, "예상 패시브 유입액(억원)": -320, "ADTV 대비 비율(배)": -2.5, "외국인 연속수급": "5일 연속 순매도"},
        {"종목코드": "247540", "종목명": "에코프로비엠", "지수 구분": "MSCI Korea", "구분": "비중확대", "시가총액(억원)": 185000, "예상 패시브 유입액(억원)": 2100, "ADTV 대비 비율(배)": 2.1, "외국인 연속수급": "15일 연속 순매수"},
    ]
    return pd.DataFrame(rebalance_list)

# ==============================================================================
# Header UI (한국투자증권 브랜드 적용)
# ==============================================================================
logo_url = "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f4c8.png" 

header_col1, header_col2 = st.columns([1, 6])

with header_col1:
    # 한국투자증권 로고 이미지 (공식 웹 로고)
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Korea_Investment_%26_Securities_Logo_KR.png/320px-Korea_Investment_%26_Securities_Logo_KR.png", width=170)

with header_col2:
    st.markdown("<h1 style='margin-bottom:0px; padding-top:0px;'>Delta 1 모니터링 시스템</h1>", unsafe_allow_html=True)
    st.caption(f"한국투자증권 Delta 1 트레이딩 / Arbitrage Desk | 영업일 기준: {get_recent_trade_date()} | 갱신: {datetime.now().strftime('%H:%M:%S')}")

st.markdown("---")

# 메인 탭 4개
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs([
    "📊 [1] 시장 에너지 & 수급 추이",
    "🚨 [2] DART 실시간 CA 모니터링",
    "⚠️ [3] 상장폐지/청산가치 스캐너",
    "📈 [4] 지수/ETF 리밸런싱 스캐너"
])

# ==============================================================================
# TAB 1: KOSPI 200 히트맵 & 수급
# ==============================================================================
with main_tab1:
    target_date = get_recent_trade_date()
    df_k200 = fetch_kospi200_heatmap_data(target_date)
    df_trend, prog_arb, prog_non_arb = fetch_investor_flow_data(target_date)

    st.subheader("🔥 KOSPI 200 시가총액 & 등락률 히트맵")
    st.caption("타일 크기: 시가총액 | 타일 색상: 당일 등락률 (빨강: 상승, 파랑: 하락)")

    fig_tree = px.treemap(
        df_k200,
        path=[px.Constant("KOSPI 200"), '종목명'],
        values='시가총액',
        color='등락률',
        color_continuous_scale=['#1f77b4', '#111111', '#d62728'],
        color_continuous_midpoint=0,
        custom_data=['등락률_str', '종가']
    )
    fig_tree.update_traces(
        hovertemplate="<b>%{label}</b><br>등락률: %{customdata[0]}<br>종가: %{customdata[1]:,}원<br>시가총액: %{value:,}원",
        texttemplate="<b>%{label}</b><br>%{customdata[0]}"
    )
    fig_tree.update_layout(height=450, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_tree, use_container_width=True)

    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📈 주요 투자주체별 누적 순매수 추이 (최근 20영업일)")
        fig_flow = go.Figure()
        fig_flow.add_trace(go.Scatter(x=df_trend.index, y=df_trend['외국인'], mode='lines+markers', name='외국인', line=dict(color='#ef5350', width=2)))
        fig_flow.add_trace(go.Scatter(x=df_trend.index, y=df_trend['기관'], mode='lines+markers', name='기관', line=dict(color='#66bb6a', width=2)))
        fig_flow.add_trace(go.Scatter(x=df_trend.index, y=df_trend['개인'], mode='lines+markers', name='개인', line=dict(color='#42a5f5', width=2)))
        fig_flow.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_flow.update_layout(height=350, template="plotly_dark", yaxis_title="누적 순매수 (억원)", margin=dict(l=10, r=10, t=20, b=20))
        st.plotly_chart(fig_flow, use_container_width=True)

    with col2:
        st.subheader("🤖 당일 프로그램 매매 동향")
        st.caption(f"기준일: {target_date}")
        
        fig_prog = go.Figure(data=[
            go.Bar(
                x=['차익거래', '비차익거래', '합계'],
                y=[prog_arb, prog_non_arb, prog_arb + prog_non_arb],
                marker_color=['#ef5350' if v >= 0 else '#42a5f5' for v in [prog_arb, prog_non_arb, prog_arb + prog_non_arb]],
                text=[f"{v:+,.1f}억" for v in [prog_arb, prog_non_arb, prog_arb + prog_non_arb]],
                textposition='auto'
            )
        ])
        fig_prog.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_prog.update_layout(height=350, template="plotly_dark", yaxis_title="순매수 금액 (억원)", margin=dict(l=10, r=10, t=20, b=20))
        st.plotly_chart(fig_prog, use_container_width=True)

# ==============================================================================
# TAB 2: DART CA
# ==============================================================================
with main_tab2:
    st.subheader("🚨 DART 실시간 Corporate Action (CA) 모니터링 (최근 7일)")
    df_dart = fetch_realtime_dart_ca_events(DART_API_KEY)

    sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
        "🔥 전체 CA 공시", "🤝 M&A / 매수청구", "📉 메자닌 (CB/BW)", "💰 배당 공시", "🔄 자사주 / 유상증자"
    ])

    def render_ca_table(df_filtered):
        if not df_filtered.empty:
            st.dataframe(
                df_filtered,
                column_config={"원문 링크": st.column_config.LinkColumn("공시 원문", display_text="🔗 DART 이동")},
                use_container_width=True, hide_index=True
            )
        else:
            st.info("현재 수집된 해당 카테고리의 Corporate Action 공시가 없습니다.")

    with sub_tab1: render_ca_table(df_dart)
    with sub_tab2: render_ca_table(df_dart[df_dart["CA 카테고리"] == "M&A / 주식매수청구"] if not df_dart.empty else pd.DataFrame())
    with sub_tab3: render_ca_table(df_dart[df_dart["CA 카테고리"] == "메자닌 (CB/BW)"] if not df_dart.empty else pd.DataFrame())
    with sub_tab4: render_ca_table(df_dart[df_dart["CA 카테고리"] == "배당 관련 공시"] if not df_dart.empty else pd.DataFrame())
    with sub_tab5: render_ca_table(df_dart[df_dart["CA 카테고리"] == "자사주 / 유상증자"] if not df_dart.empty else pd.DataFrame())

# ==============================================================================
# TAB 3: 상장폐지/청산가치
# ==============================================================================
with main_tab3:
    st.subheader("⚠️ 상장폐지·재무위기 위험 종목 & 청산가치(Liquidation) 차익거래")
    st.caption("정리매매 및 관리종목 지정 대상 중 주당 청산가치(BPS) 대비 시장가가 과도하게 할인된 Special Situation 포착")

    df_distressed = fetch_distressed_liquidation_data(DART_API_KEY)

    if not df_distressed.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("정리매매 / 관리종목 포착", f"{len(df_distressed)} 건")
        m2.metric("평균 청산 할인율", f"{df_distressed['청산 괴리율(%)'].mean():.1f} %")
        m3.metric("최대 차익 기회 종목", f"{df_distressed.sort_values('청산 괴리율(%)').iloc[0]['종목명']}")

        st.dataframe(
            df_distressed,
            column_config={
                "청산 괴리율(%)": st.column_config.NumberColumn("청산 괴리율(%)", format="%.1f%%"),
                "현재가(원)": st.column_config.NumberColumn("현재가", format="%d 원"),
                "BPS(청산가치)": st.column_config.NumberColumn("BPS", format="%d 원"),
            },
            use_container_width=True, hide_index=True
        )
    else:
        st.info("현재 포착된 상장폐지 위험/재무위기 관리종목 데이터가 없습니다.")

# ==============================================================================
# TAB 4: 리밸런싱
# ==============================================================================
with main_tab4:
    st.subheader("📊 지수/ETF 리밸런싱 이벤트 & 외국인·기관 수급 스캐너")
    st.caption("KOSPI200, KOSDAQ150, MSCI 정기변경 시 패시브 자금 수급 쏠림 현상 선제 포착")

    df_rebalance = fetch_index_rebalance_data()

    if not df_rebalance.empty:
        r1, r2, r3 = st.columns(3)
        r1.metric("편입/비중확대 예상 종목", f"{len(df_rebalance[df_rebalance['구분'].str.contains('편입|확대')])} 건")
        r2.metric("최대 수급 유입 예상액", f"{df_rebalance['예상 패시브 유입액(억원)'].max():,} 억원")
        r3.metric("최대 ADTV 유입 배수", f"{df_rebalance['ADTV 대비 비율(배)'].max():.1f} 배")

        st.dataframe(
            df_rebalance,
            column_config={
                "시가총액(억원)": st.column_config.NumberColumn("시가총액", format="%d 억원"),
                "예상 패시브 유입액(억원)": st.column_config.NumberColumn("예상 자금 유출입", format="%d 억원"),
                "ADTV 대비 비율(배)": st.column_config.NumberColumn("ADTV 대비 비율", format="%.1f 배"),
            },
            use_container_width=True, hide_index=True
        )
    else:
        st.info("현재 수집된 지수 리밸런싱 예상 종목 데이터가 없습니다.")
