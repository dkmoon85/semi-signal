Python
import streamlit as st
import datetime
import requests
from bs4 import BeautifulSoup
from pykrx import stock

# 스마트폰 화면 최적화 설정
st.set_page_config(page_title="반도체 매도 신호기", page_icon="📉", layout="centered")

st.title("📉 반도체 고점 신호 판독기")
st.caption("삼성전자 & SK하이닉스 매도 타이밍 포착")
st.markdown("---")

# 오늘 날짜 설정
today = datetime.datetime.today().strftime('%Y%m%d')
start_date = (datetime.datetime.today() - datetime.timedelta(days=7)).strftime('%Y%m%d')

def crawl_news_count(keyword):
    url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sm=tab_opt&sort=1"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        return len(soup.select('.news_tit'))
    except:
        return 0

# 폰에서 누를 버튼
if st.button("🔄 지금 매도 신호 점검하기", type="primary", use_container_width=True):
    
    with st.spinner("최신 뉴스 및 수급 데이터 분석 중..."):
        trigger_count = 0
        results = []

        # 1. 빅테크 투자 축소
        if crawl_news_count("데이터센터 속도 조절") > 2 or crawl_news_count("빅테크 AI 투자 축소") > 2:
            trigger_count += 1
            results.append(("🚨 신호 1 켜짐", "빅테크 AI 투자 속도 조절 언급 포착"))
        else:
            results.append(("✅ 안전", "빅테크 AI 투자 유지 중"))

        # 2. HBM 재고 및 가격
        if crawl_news_count("HBM 재고 증가") > 2 or crawl_news_count("HBM 가격 하락") > 2:
            trigger_count += 1
            results.append(("🚨 신호 2 켜짐", "HBM 재고 증가 및 가격 하락 신호"))
        else:
            results.append(("✅ 안전", "HBM 공급 부족/가격 안정 유지 중"))

        # 3. 중국 추격
        if crawl_news_count("CXMT 공급") > 2 or crawl_news_count("YMTC 반도체") > 2:
            trigger_count += 1
            results.append(("🚨 신호 3 켜짐", "중국 메모리 업체 물량 공세"))
        else:
            results.append(("✅ 안전", "중국 업체 위협 수준 낮음"))

        # 4. 주가 횡보 (실적 대비)
        results.append(("ℹ️ 수동 확인", "역대급 실적 뉴스에도 주가가 못 오르고 횡보하는지 확인 필요"))

        # 5. 외국인 자금 이탈
        foreign_alert = False
        for code in ["005930", "000660"]:
            try:
                df = stock.get_market_net_purchases_of_equities_by_ticker(start_date, today, "KOSPI")
                if code in df.index and df.loc[code, '외국인합계'] < -100000000000:
                    foreign_alert = True
            except:
                pass
        if foreign_alert:
            trigger_count += 1
            results.append(("🚨 신호 5 켜짐", "외국인 자금 대규모 이탈 (-1000억 이상)"))
        else:
            results.append(("✅ 안전", "외국인 수급 양호"))

        # 6. HBM 대체 기술
        if crawl_news_count("HBM 대체 기술") > 1 or crawl_news_count("HBM 없이 구동") > 1:
            trigger_count += 1
            results.append(("🚨 신호 6 켜짐", "HBM 대체 신기술 및 아키텍처 등장"))
        else:
            results.append(("✅ 안전", "HBM 대체 기술 미포착"))

        # 7. 증권사 리포트
        if crawl_news_count("반도체 구조적 성장 끝") > 1 or crawl_news_count("반도체 안정기 접어들어") > 1:
            trigger_count += 1
            results.append(("🚨 신호 7 켜짐", "증권사 보수적 리포트 증가"))
        else:
            results.append(("✅ 안전", "증권사 성장성 긍정 유지 중"))

    # --------------------------------------------------
    # 결과 화면 시각화 (스마트폰 최적화)
    # --------------------------------------------------
    st.markdown("---")
    st.subheader("📊 최종 판정 결과")
    
    # 스코어 표시
    if trigger_count >= 3:
        st.error(f"🔥 위험! 총 {trigger_count}개 신호 켜짐: 매도를 적극 검토하세요!")
    else:
        st.success(f"🟢 안전! 총 {trigger_count}개 신호 켜짐: 자산을 계속 보유하세요.")

    # 상세 내역을 접이식 메뉴로 깔끔하게 표시
    st.markdown("### 📋 세부 점검 내역")
    for status, desc in results:
        st.write(f"**[{status}]** {desc}")
