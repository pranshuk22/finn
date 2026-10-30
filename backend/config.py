"""Static configuration: companies, aliases, paths and the filing category map."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "finn.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# ticker -> (display name, sector, size). Verified on yfinance and Screener, see EVIDENCE E9.
PORTFOLIO: dict[str, tuple[str, str, str]] = {
    "RELIANCE": ("Reliance Industries", "Energy and telecom", "Large"),
    "TCS": ("Tata Consultancy Services", "IT services", "Large"),
    "HDFCBANK": ("HDFC Bank", "Banking", "Large"),
    "ICICIBANK": ("ICICI Bank", "Banking", "Large"),
    "INFY": ("Infosys", "IT services", "Large"),
    "LT": ("Larsen & Toubro", "Capital goods", "Large"),
    "ETERNAL": ("Eternal", "Consumer internet", "Large"),
    "TRENT": ("Trent", "Retail", "Large"),
    "BAJAJ-AUTO": ("Bajaj Auto", "Auto", "Large"),
    "TATACONSUM": ("Tata Consumer Products", "FMCG", "Large"),
    "DIXON": ("Dixon Technologies", "Electronics manufacturing", "Mid"),
    "POLYCAB": ("Polycab India", "Cables and wires", "Mid"),
    "PERSISTENT": ("Persistent Systems", "IT services", "Mid"),
    "SONACOMS": ("Sona BLW Precision Forgings", "Auto components", "Mid"),
    "MAXHEALTH": ("Max Healthcare", "Hospitals", "Mid"),
    "SUZLON": ("Suzlon Energy", "Wind energy", "Mid"),
    "KAYNES": ("Kaynes Technology", "Electronics manufacturing", "Small"),
    "GRAVITA": ("Gravita India", "Recycling", "Small"),
}

# Ad-hoc research picks, outside the portfolio. See EVIDENCE E13.
ADHOC = ["ASIANPAINT", "HAL", "PIDILITIND", "BAJFINANCE"]

# Lenders: EBITDA is not meaningful, so results cards skip it.
FINANCIALS = {"HDFCBANK", "ICICIBANK", "BAJFINANCE"}

# Old or common names -> current NSE symbol. ZOMATO.NS returns 404 (EVIDENCE E9).
ALIASES = {
    "ZOMATO": "ETERNAL",
    "L&T": "LT",
    "LARSEN": "LT",
    "BAJAJAUTO": "BAJAJ-AUTO",
    "SONA": "SONACOMS",
}


def resolve_ticker(raw: str) -> str:
    t = raw.strip().upper().removesuffix(".NS").removesuffix(".BO")
    return ALIASES.get(t, t)


CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]

# NSE `desc` labels that map to exactly one category. Every label here was seen in live
# NSE data (TCS full history plus all 18 tickers for October 2026, EVIDENCE E2). Anything
# not here goes to text rules, then to the model.
LABEL_MAP: dict[str, str] = {
    "Financial Result Updates": "results",
    "Integrated Filing- Financial": "results",
    "Investor Presentation": "results",
    "Limited Review Report": "results",
    "Clarification - Financial Results": "results",
    "Reply to Clarification- Financial results": "results",
    "Acquisition": "M&A",
    "Sale or disposal": "M&A",
    "Other Restructuring": "M&A",
    "Amalgamation/Merger": "M&A",
    "Scheme of Arrangement": "M&A",
    "Scheme of Amalgamation": "M&A",
    "Scheme of Amalgamation/Arrangement/Merger": "M&A",
    "Joint Venture": "M&A",
    "Incorporation": "M&A",
    "Buyback": "fund_raise",
    "Buyback - others": "fund_raise",
    "Closure of Buy Back": "fund_raise",
    "Post Buyback Public Announcement": "fund_raise",
    "Public Announcement - Buyback of Shares": "fund_raise",
    "Issue of Securities": "fund_raise",
    "Issue And Allotment of Preference Shares": "fund_raise",
    "Change in Director(s)": "management_change",
    "Change in Management": "management_change",
    "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent": "management_change",
    "Appointment": "management_change",
    "Appointment of Chairman": "management_change",
    "Appointment of Director": "management_change",
    "Appointment of Directors": "management_change",
    "Appointment of Managing Director and CEO": "management_change",
    "Re-appointment": "management_change",
    "Reappointment": "management_change",
    "Resignation": "management_change",
    "Resignation of Director/KMP/SMP": "management_change",
    "Retirement": "management_change",
    "Cessation": "management_change",
    "Corporate Insolvency Resolution Process": "litigation",
    "Action(s) taken or orders passed": "litigation",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company": "litigation",
    "Disclosure under SEBI Takeover Regulations": "insider_trading",
    "Disclosure under Insider Trading Regulation": "insider_trading",
    "Disc. under Reg.30 of SEBI (SAST) Reg.2011": "insider_trading",
    "Schedule of Analysts/Institutional Investor Meet/Con. Call": "investor_meetings",
    "Analysts Meet": "investor_meetings",
    "Transcript of Analysts/Institutional Investor Meet/Con. Call": "earnings_call",
    "Recording of Analysts/Institutional Investor Meet/Con. Call": "earnings_call",
    "Credit Rating": "credit_rating",
    "Credit Rating- New": "credit_rating",
    "Credit Rating- Revision": "credit_rating",
    "Rating": "credit_rating",
    "Dividend": "dividend",
    "Dividend Updates": "dividend",
    "Final Dividend": "dividend",
    "Interim Dividend": "dividend",
    "Interim Dividend/Record Date": "dividend",
    "Date of payment of dividend": "dividend",
    "Bonus": "bonus_split",
    "Bagging/Receiving of orders/contracts": "press_release",
    "News Clarification": "press_release",
    "Clarification of News": "press_release",
    "News Verification": "press_release",
    "Rumour Verification - Regulation 30(11)": "press_release",
    "Postal Ballot": "postal_ballot",
    "Results of Postal Ballot": "postal_ballot",
    "Shareholders meeting": "agm_egm",
    "AGM": "agm_egm",
    "AGM/Book Closure": "agm_egm",
    "AGM / Book Closure": "agm_egm",
    "Annual General Meeting": "agm_egm",
    "Annual General Meeting Updates": "agm_egm",
    "Extraordinary General Meeting Updates": "agm_egm",
    "Court Convened Meeting Updates": "agm_egm",
    "Minutes of AGM": "agm_egm",
    "Minutes of Annual General Meeting": "agm_egm",
    "Copy of Newspaper Publication": "unclassified",
    "Newspaper Advertisements": "unclassified",
    "Loss of Share Certificates": "unclassified",
    "Loss of share certificate": "unclassified",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018": "unclassified",
    "ESOP/ESOS/ESPS": "unclassified",
    "Committee Meeting Updates": "unclassified",
    "Monitoring Agency Report": "unclassified",
    "Corrigendum": "unclassified",
    "Amendment to AOA/MOA": "unclassified",
    "Annual Secretarial Compliance Report": "unclassified",
    "Business Responsibility & Sustainability Report (BRSR)": "unclassified",
    "Code of Conduct under SEBI(PIT) Reg., 2015": "unclassified",
    "Change in Company Secretary/Compliance Officer": "unclassified",
    "Registrar & Share Transfer Agent Update": "unclassified",
    "Regulation 44(3) of SEBI (LODR), Reg., 2015": "unclassified",
    "Declaration for audit reports with unmodified opinion(s)": "unclassified",
    "Appointment of Auditors": "unclassified",
    "Change in registered office": "unclassified",
    "Increase in authorised share capital/others": "unclassified",
}
