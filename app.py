import streamlit as st
import datetime
import requests
from bs4 import BeautifulSoup
from pykrx import stock

# 스마트폰 화면 최적화 설정
st.set_page_config(page_title="반도체 매도 신호기", page_icon="📉", layout="centered")

st.title("📉 반도체 고점 신호 판독기 (디버그 버전)")
st.caption("삼성전자 & SK하이닉스 매도 타이밍 포착 · 실제 검색 건수 / 실패 여부 표시")
st.markdown("---")

# 오늘 날짜 및 기간 설정
today = datetime.datetime.today().strftime('%Y%m%d')
start_date_7 = (datetime.datetime.today() - datetime.timedelta(days=7)).strftime('%Y%m%d')
start_date_30 = (datetime.datetime.today() - datetime.timedelta(days=30)).strftime('%Y%m%d')  # 20거래일 확보용


def crawl_news_count(keyword):
    """
    네이버 뉴스 검색 결과 개수를 반환.
    실패(네트워크 오류, 차단, 파싱 실패 등) 시에는 0이 아니라 None을 반환해서
    '진짜 0건'과 '크롤링 실패'를 구분할 수 있게 한다.
    """
    url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sm=tab_opt&sort=1"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        return len(soup.select('.news_tit'))
    except Exception:
        return None


def fmt(n):
    """카운트를 표시용 문자열로. None이면 실패 표시."""
    return "⚠️실패" if n is None else f"{n}건"


def check_pair_signal(label_safe, label_alert, kw1, kw2, threshold, results, counters):
    """뉴스 키워드 2개로 판정하는 신호의 공통 처리 함수."""
    n1 = crawl_news_count(kw1)
    n2 = crawl_news_count(kw2)
    if n1 is None or n2 is None:
        counters['error'] += 1
        results.append(("⚠️ 확인불가", f"크롤링 실패 (\"{kw1}\": {fmt(n1)}, \"{kw2}\": {fmt(n2)})"))
        return
    if n1 > threshold or n2 > threshold:
        counters['trigger'] += 1
        results.append(("🚨 신호 켜짐", f"{label_alert} (기사 {n1}+{n2}건)"))
    else:
        results.append(("✅ 안전", f"{label_safe} (기사 {n1}+{n2}건)"))


# 폰에서 누를 버튼
if st.button("🔄 지금 매도 신호 점검하기", type="primary", use_container_width=True):

    with st.spinner("최신 뉴스 및 20일간의 주가/수급 분석 중..."):
        counters = {'trigger': 0, 'error': 0}
        results = []

        # 1. 빅테크 투자 축소
        check_pair_signal(
            "빅테크 AI 투자 유지 중", "빅테크 AI 투자 속도 조절 언급 포착",
            "데이터센터 속도 조절", "빅테크 AI 투자 축소", 2, results, counters
        )

        # 2. HBM 재고 및 가격
        check_pair_signal(
            "HBM 공급 부족/가격 안정 유지 중", "HBM 재고 증가 및 가격 하락 신호",
            "HBM 재고 증가", "HBM 가격 하락", 2, results, counters
        )

        # 3. 중국 추격
        check_pair_signal(
            "중국 업체 위협 수준 낮음", "중국 메모리 업체 물량 공세",
            "CXMT 공급", "YMTC 반도체", 2, results, counters
        )

        # 4. 주가 횡보 (실적 대비)
        earning_flat_alert = False
        for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
            try:
                df_20 = stock.get_market_ohlcv_by_date(start_date_30, today, code)
                if len(df_20) < 15:
                    results.append(("⚠️ 확인불가", f"{name}: 가격 데이터 부족 ({len(df_20)}일치)"))
                    continue

                high_20 = df_20['고가'].max()
                low_20 = df_20['저가'].min()
                price_range_pct = ((high_20 - low_20) / high_20) * 100

                nc1 = crawl_news_count(f"{name} 호실적")
                nc2 = crawl_news_count(f"{name} 어닝서프라이즈")
                if nc1 is None or nc2 is None:
                    counters['error'] += 1
                    results.append(("⚠️ 확인불가", f"{name}: 뉴스 크롤링 실패 (변동폭 {price_range_pct:.1f}%)"))
                    continue

                news_count = nc1 + nc2
                if price_range_pct <= 3.0 and news_count >= 5:
                    earning_flat_alert = True
                    results.append(("🚨 신호 켜짐", f"{name}: 호실적기사 {news_count}건인데 변동폭 {price_range_pct:.1f}% (횡보)"))
                else:
                    results.append(("ℹ️ 참고", f"{name}: 변동폭 {price_range_pct:.1f}%, 호실적기사 {news_count}건 (기준: 변동폭≤3%, 기사≥5건)"))
            except Exception as e:
                counters['error'] += 1
                results.append(("⚠️ 확인불가", f"{name}: pykrx 조회 실패 ({e})"))

        if earning_flat_alert:
            counters['trigger'] += 1

        # 5. 외국인 자금 이탈
        # 주의: investor 파라미터를 안 주면 기본값이 '개인'으로 들어가서 전혀 다른 데이터를 보게 됨.
        # 반드시 investor="외국인"을 명시해야 하고, 컬럼명도 '외국인합계'가 아니라 '순매수거래대금'.
        try:
            df = stock.get_market_net_purchases_of_equities_by_ticker(
                start_date_7, today, "KOSPI", "외국인"
            )
            foreign_alert = False
            details = []
            for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
                if code in df.index:
                    val = df.loc[code, '순매수거래대금']
                    details.append(f"{name} {val/1e8:.0f}억")
                    if val < -100_000_000_000:
                        foreign_alert = True
                else:
                    # 외국인 기준 순매수/순매도 상위 종목 리스트에 안 들었다는 뜻.
                    # 보통 삼성전자/하이닉스는 거래량이 워낙 커서 거의 항상 포함됨 -
                    # 그래도 안 보이면 일단 '확인불가'로 분류 (안전으로 단정하지 않음).
                    details.append(f"{name} 데이터없음")
                    counters['error'] += 1
            detail_str = ", ".join(details)
            missing = "데이터없음" in detail_str
            if foreign_alert:
                counters['trigger'] += 1
                results.append(("🚨 신호 켜짐", f"외국인 자금 대규모 이탈 (-1000억 이상) [{detail_str}]"))
            elif missing:
                results.append(("⚠️ 확인불가", f"일부 종목 데이터 누락, 안전 단정 불가 [{detail_str}]"))
                with st.expander("🔍 외국인 수급 원본 데이터 확인 (디버그)"):
                    st.write(f"조회 기간: {start_date_7} ~ {today}")
                    st.write(f"반환된 행 개수: {len(df)}")
                    st.write(f"반환된 티커 목록: {list(df.index)}")
                    st.dataframe(df)
            else:
                results.append(("✅ 안전", f"외국인 수급 양호 [{detail_str}]"))
        except Exception as e:
            counters['error'] += 1
            results.append(("⚠️ 확인불가", f"외국인 수급 조회 실패 ({e})"))

        # 6. HBM 대체 기술
        check_pair_signal(
            "HBM 대체 기술 미포착", "HBM 대체 신기술 및 아키텍처 등장",
            "HBM 대체 기술", "HBM 없이 구동", 1, results, counters
        )

        # 7. 증권사 리포트
        check_pair_signal(
            "증권사 성장성 긍정 유지 중", "증권사 보수적 리포트 증가",
            "반도체 구조적 성장 끝", "반도체 안정기 접어들어", 1, results, counters
        )

    # 결과 화면 시각화
    st.markdown("---")
    st.subheader("📊 최종 판정 결과")

    if counters['error'] > 0:
        st.warning(
            f"⚠️ {counters['error']}개 항목에서 크롤링/데이터 조회가 실패했습니다. "
            f"이 항목들은 '안전'이 아니라 '확인 불가'이니 판단에서 제외하고 보세요."
        )

    if counters['trigger'] >= 3:
        st.error(f"🔥 위험! 총 {counters['trigger']}개 신호 켜짐: 매도를 적극 검토하세요!")
    else:
        st.success(f"🟢 안전! 총 {counters['trigger']}개 신호 켜짐: 자산을 계속 보유하세요.")

    st.markdown("### 📋 세부 점검 내역")
    for status, desc in results:
        st.write(f"**[{status}]** {desc}")
