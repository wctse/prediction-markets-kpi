from dotenv import load_dotenv

load_dotenv()

KALSHI_MARKET_TICKER_DEFAULT = "KXPRESNOMD-28-GN"
POLY_YES_TOKEN_ID_DEFAULT = "54533043819946592547517511176940999955633860128497669742211153063842200957669"
OPINION_ORDERBOOK_URL = (
    "https://proxy.opinion.trade/api/bsc/api/v2/order/market/depth"
    "?symbol_types=0"
    "&question_id=18762087dced88d2b9289562e72078999e35d57827ee9b51ba0619e5b92fb4ec"
    "&symbol=7406949728254171104471570547656954413364478589149651129444530374993752988616"
    "&chainId=56"
)

KALSHI_MARKET_URL = "https://kalshi.com/markets/kxpresnomd/democratic-primary-winner/kxpresnomd-28"
POLYMARKET_MARKET_URL = "https://polymarket.com/event/democratic-presidential-nominee-2028"
OPINION_MARKET_URL = OPINION_ORDERBOOK_URL

TITLE = "Prediction market orderbook - slippage ladder by execution size"
PLATFORM_COLORS = {
    "Kalshi": "#16C784",
    "Polymarket": "#3B82F6",
    "Opinion": "#F97316",
}
MERGED_MARKET_DATA_URL = "https://pdvxuqskfpozyrqt.public.blob.vercel-storage.com/kalshi_polymarket_merged.csv"
OPINION_KPI2_DUNE_QUERY_ID = 7567897
OPEN_INTEREST_SHARE_TITLE = "Open interest market share"
OPEN_INTEREST_ABSOLUTE_TITLE = "Open interest by platform (absolute)"
ROLLING_RATIO_TITLE = "7d rolling Volume / Open Interest ratio"
KPI_1_LABEL = "KPI 1 - Open Interest Market Share"
KPI_2_LABEL = "KPI 2 - Volume / Open Interest"
KPI_3_LABEL = "KPI 3 - Slippage ladder"
KPI_3_SUBTITLE = "2028 US Presidental Election Democratic nominee - Gavin Newsom"
KPI_3_MAX_TIER_USD = 25_000.0
