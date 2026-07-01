import streamlit as st
import datetime
import time
import requests
from bs4 import BeautifulSoup
from pykrx import stock
from email.utils import parsedate_to_datetime

# 스마트폰 화면 최적화 설정
st.set_page_config(page_title="반도체 매도 신호기", page_icon="📉", layout="centered")

st.title("📉 반도체 고점 신호 판독기 (디버그 버전)")
st.caption("삼성전자 & SK하이닉스 매도 타이밍 포착 · 실제 검색 건수 / 실패 여부 표시")
st.info("🏷️ 코드 버전: V7-OPENAPI-NEWS (이 문구가 안 보이면 옛 코드가 실행 중인 것)")

NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")
if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    st.error(
        "⚠️ 네이버 오픈API 키(NAVER_CLIENT_ID / NAVER_CLIENT_SECRET)가 설정되지 않았어요.\n\n"
        "1) developers.naver.com → Application 등록 → '검색' API 선택 (무료)\n"
        "2) 발급받은 Client ID/Secret을\n"
        "   Streamlit Cloud 앱 → Settings → Secrets 에 아래 형식으로 추가\n\n"
        "```\nNAVER_CLIENT_ID = \"여기에_입력\"\nNAVER_CLIENT_SECRET = \"여기에_입력\"\n```\n\n"
        "추가 후 앱을 재시작(Reboot)하면 뉴스 신호들이 정상 작동해요."
    )
st.markdown("---")

# 오늘 날짜 및 기간 설정
today = datetime.datetime.today().strftime('%Y%m%d')
start_date_7 = (datetime.datetime.today() - datetime.timedelta(days=7)).strftime('%Y%m%d')
start_date_30 = (datetime.datetime.today() - datetime.timedelta(days=30)).strftime('%Y%m%d')  # 20거래일 확보용


RECENT_NEWS_DAYS = 3  # '최근 며칠'을 버즈 발생 기준으로 볼지. 필요시 조정 가능.


def crawl_news_count(keyword):
    """
    네이버 뉴스 검색 결과 개수를 반환.
    예전엔 search.naver.com HTML을 직접 긁었는데, 이게 클라우드 IP에서 자주 차단(403/타임아웃)되어
    공식 '네이버 검색 오픈API'로 교체함. API는 봇 차단 대상이 아니라서 훨씬 안정적임.
    (단, 무료지만 Client ID/Secret 발급이 필요 - 위 상단 안내 참고)

    API는 '전체 기간 총 매칭 건수(total)'를 주는데, 그걸 그대로 쓰면 키워드가 옛날부터
    조금이라도 언급된 적 있으면 영구적으로 임계치를 넘어버려서 '최신 동향 포착'이라는
    원래 의도와 안 맞음. 그래서 최근 N일(RECENT_NEWS_DAYS) 안에 실제로 게재된 기사만
    pubDate로 골라서 카운트함 → '최근에 갑자기 늘었는가'를 더 정확히 반영.

    실패(인증 오류, 네트워크 오류 등) 시에는 0이 아니라 None을 반환해서
    '진짜 0건'과 '조회 실패'를 구분할 수 있게 한다.
    실패 시 원인 진단을 위해 st.session_state['news_crawl_debug']에 마지막 실패 정보를 남긴다.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        st.session_state.setdefault('news_crawl_debug', []).append(
            f"{keyword}: NAVER_CLIENT_ID/SECRET 미설정"
        )
        return None

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": 30, "sort": "date"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        status = response.status_code
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=RECENT_NEWS_DAYS)
        recent_count = 0
        for item in items:
            pub_date_str = item.get("pubDate", "")
            try:
                pub_dt = parsedate_to_datetime(pub_date_str)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
            except (TypeError, ValueError):
                continue
            if pub_dt >= cutoff:
                recent_count += 1
            else:
                # sort=date라 최신순으로 오므로, 기준일보다 오래된 게 나오면 그 뒤는 더 오래된 것들임
                break

        time.sleep(0.1)  # 공식 API라 차단 위험은 낮지만 과호출 방지용 최소 지연
        return recent_count
    except requests.exceptions.HTTPError:
        st.session_state.setdefault('news_crawl_debug', []).append(f"{keyword}: HTTP {status}")
        return None
    except requests.exceptions.Timeout:
        st.session_state.setdefault('news_crawl_debug', []).append(f"{keyword}: 타임아웃")
        return None
    except Exception as e:
        st.session_state.setdefault('news_crawl_debug', []).append(f"{keyword}: {type(e).__name__} {e}")
        return None


def get_foreign_flow_naver(code, max_days=5):
    """
    네이버 금융 종목별 외국인 수급 페이지(frgn.naver)에서
    최근 거래일들의 '외국인 순매매량(주식수)'을 가져와 합산.
    pykrx의 투자자별 수급 API가 클라우드 환경에서 막혀서 쓰는 대체 경로.
    추정 금액 = 그날 순매매량 × 그날 종가의 합 (정확한 거래대금이 아니라 근사치).
    held_shares = 가장 최근일 기준 외국인 보유주식수 (% 계산용 분모).
    실패 시 None.
    """
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        table = None
        for t in soup.find_all("table"):
            if "외국인" in t.get_text():
                table = t
                break
        if table is None:
            time.sleep(0.4)
            return None

        total_volume = 0.0
        total_value = 0.0
        held_shares = None
        count = 0
        for row in table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) < 6:
                continue
            texts = [td.get_text(strip=True) for td in tds]
            if not texts[0]:
                continue
            try:
                close_price = float(texts[1].replace(',', ''))
                foreign_vol = float(texts[-3].replace(',', '').replace('%', ''))
                held = float(texts[-2].replace(',', ''))
            except (ValueError, IndexError):
                continue
            if held_shares is None:
                held_shares = held  # 가장 최근(첫 행) 보유주식수
            total_volume += foreign_vol
            total_value += foreign_vol * close_price  # 그날 종가로 그날 순매매량을 곱함
            count += 1
            if count >= max_days:
                break

        time.sleep(0.4)
        if count == 0 or held_shares is None or held_shares == 0:
            return None
        pct = (total_volume / held_shares) * 100  # 보유주수 대비 순매매 비율(%)
        return {
            "volume": total_volume,
            "est_value": total_value,
            "days": count,
            "held_shares": held_shares,
            "pct": pct,
        }
    except Exception:
        time.sleep(0.4)
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
        # pykrx 투자자별 수급 API가 이 클라우드 환경에서 항상 빈 데이터를 반환하는 게 확인되어
        # (get_market_net_purchases_of_equities_by_ticker, get_market_trading_value_by_date 둘 다 실패)
        # 네이버 금융 종목별 수급 페이지를 직접 크롤링하는 방식으로 대체.
        # 기준: 고정 금액(원화) 대신 '외국인 보유주식수 대비 % 순매도'로 판정.
        # → 주가가 비싼 종목(SK하이닉스처럼 주당 수백만원)도 왜곡 없이 같은 기준 적용 가능.
        FOREIGN_OUTFLOW_PCT_THRESHOLD = 1.5  # 5거래일간 보유주식의 1.5% 이상 순매도 시 경고
        foreign_alert = False
        foreign_error = False
        details = []
        for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
            info = get_foreign_flow_naver(code)
            if info is None:
                details.append(f"{name} 조회실패")
                foreign_error = True
                counters['error'] += 1
                with st.expander(f"🔍 {name} 네이버 수급 진단 (디버그)"):
                    try:
                        diag_url = f"https://finance.naver.com/item/frgn.naver?code={code}"
                        diag_res = requests.get(diag_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                        diag_soup = BeautifulSoup(diag_res.text, 'html.parser')
                        n_tables = len(diag_soup.find_all("table"))
                        has_foreign_text = "외국인" in diag_res.text
                        st.write(f"HTTP 상태코드: {diag_res.status_code}")
                        st.write(f"응답 길이: {len(diag_res.text)}자")
                        st.write(f"테이블 개수: {n_tables}")
                        st.write(f"'외국인' 텍스트 포함 여부: {has_foreign_text}")
                    except Exception as diag_e:
                        st.write(f"진단 요청 자체 실패: {diag_e}")
                continue
            pct = info['pct']
            est = info['est_value']
            details.append(f"{name} {pct:+.2f}%(보유주 대비, 추정 {est/1e8:.0f}억, {info['days']}일치)")
            if pct <= -FOREIGN_OUTFLOW_PCT_THRESHOLD:
                foreign_alert = True

        detail_str = ", ".join(details)
        if foreign_alert:
            counters['trigger'] += 1
            results.append(("🚨 신호 켜짐", f"외국인 보유주 {FOREIGN_OUTFLOW_PCT_THRESHOLD}% 이상 순매도 [{detail_str}]"))
        elif foreign_error:
            results.append(("⚠️ 확인불가", f"네이버 수급 데이터 조회 실패 [{detail_str}]"))
        else:
            results.append(("✅ 안전", f"외국인 수급 양호 (기준: -{FOREIGN_OUTFLOW_PCT_THRESHOLD}% 미달) [{detail_str}]"))

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

    if 'news_crawl_debug' in st.session_state and st.session_state['news_crawl_debug']:
        with st.expander("🔍 뉴스 크롤링 실패 원인 진단 (디버그)"):
            for line in st.session_state['news_crawl_debug']:
                st.write(f"- {line}")
        st.session_state['news_crawl_debug'] = []

    if counters['trigger'] >= 3:
        st.error(f"🔥 위험! 총 {counters['trigger']}개 신호 켜짐: 매도를 적극 검토하세요!")
    else:
        st.success(f"🟢 안전! 총 {counters['trigger']}개 신호 켜짐: 자산을 계속 보유하세요.")

    st.markdown("### 📋 세부 점검 내역")
    for status, desc in results:
        st.write(f"**[{status}]** {desc}")
