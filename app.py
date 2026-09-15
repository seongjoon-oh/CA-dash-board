import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
from datetime import datetime

# ==============================================================================
# 0. DART API Secrets 안전 호출 및 데이터 수집 함수
# ==============================================================================
try:
    DART_API_KEY = st.secrets["DART_API_KEY"]
except Exception:
    DART_API_KEY = None

@st.cache_data(ttl=300)
def fetch_realtime_dart_events(api_key):
    if not api_key:
        return pd.DataFrame([
            {
                "종목명": "API키 미등록",
                "이벤트 유형": "설정 필요",
                "공시제목": "Streamlit Secrets에 DART_API_KEY를 등록해주세요.",
                "접수일자": datetime.now().strftime("%Y%m%d"),
                "출처 URL": "https://share.streamlit.io"
            }
        ])

    today = datetime.now().strftime("%Y%m%d")
    url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}&bde_beg={today}&page_count=100"

    try:
        res = requests.get(url, timeout=5)
        data = res.json()

        if data.get("status") != "000":
            return pd.DataFrame([])

        raw_list = data.get("list", [])
        keyword_map = {
            "주식매수청구": "매수청구권",
            "전환가액": "CB Refixing",
            "배당": "배당 공시",
            "합병": "M&A / 구조조정",
            "자기주식": "자사주 취득/처분"
        }

        filtered_events = []
        for item in raw_list:
            report_nm = item.get("report_nm", "")
            detected_type = next((category for kw, category in keyword_map.items() if kw in report_nm), None)
            
            if detected_type:
                rcp_no = item.get("rcp_no")
                filtered_events.append({
                    "종목명": item.get("corp_name"),
                    "이벤트 유형": detected_type,
                    "공시제목": report_nm,
                    "접수일자": item.get("rcept_dt"),
                    "출처 URL": f"https://dart.fss.or.kr/dsaf001/main.do?rcp_no={rcp_no}"
                })

        return pd.DataFrame(filtered_events)
    except Exception:
        return pd.DataFrame([])

# ==============================================================================
# 1. UI 및 차트 구현
# ==============================================================================
st.set_page_config(page_title="Arbitrage Dashboard", layout="wide")
st.title("📈 AI 기반 현선물 차익거래 & Corporate Action 모니터링 대시보드")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("KOSPI200 선물", "352.40 pt", "+1.20 pt")
col2.metric("KOSPI200 현물", "351.95 pt", "+0.85 pt")
col3.metric("Market Basis", "+0.45 pt", "+0.15 pt")
col4.metric("Theoretical Basis", "+0.20 pt", "0.00 pt")
col5.metric("괴리율", "+0.25 pt", "+0.15 pt")

st.markdown("---")

left_col, right_col = st.columns([7, 3])

np.random.seed(42)
times = pd.date_range("09:00", "15:30", freq="1min")
base_basis = np.sin(np.linspace(0, 10, len(times))) * 0.5 + 0.2
df_chart = pd.DataFrame({"Time": times, "Market Basis": base_basis + np.random.normal(0, 0.1, len(times)), "Theoretical Basis": 0.20})

with left_col:
    st.subheader("📊 실시간 베이시스 추이")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_chart['Time'], y=df_chart['Market Basis'], mode='lines', name='Market Basis', line=dict(color='#00CC96')))
    fig.add_trace(go.Scatter(x=df_chart['Time'], y=df_chart['Theoretical Basis'], mode='lines', name='Theoretical Basis', line=dict(color='#EF553B', dash='dash')))
    fig.update_layout(height=380, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

with right_col:
    st.subheader("🤖 AI Arbitrage Signal")
    st.success("🟢 **추천 전략: 매도차익거래 (Reverse Arb)**")
    st.markdown("- **기대 순수익률**: `+0.38%`\n- **주요 원인**: DART 공시 기반 Put Option 가치 형성")
    st.button("⚡ 주문 시뮬레이션 집행", use_container_width=True)

st.markdown("---")
st.subheader("📋 DART 실시간 Corporate Action 모니터링")
df_dart = fetch_realtime_dart_events(DART_API_KEY)

if not df_dart.empty:
    st.dataframe(
        df_dart,
        column_config={"출처 URL": st.column_config.LinkColumn("공시 원문 링크", display_text="🔗 DART 원문 보기")},
        use_container_width=True, hide_index=True
    )
else:
    st.info("오늘 접수된 주요 Corporate Action 공시가 없습니다.")
