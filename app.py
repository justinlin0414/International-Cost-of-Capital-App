"""
Cross-Currency Cost of Capital (WACC) Explorer
==============================================

Streamlit app that estimates a project's cost of equity, cost of debt and WACC in
US dollars and in the currency of a selected country.

Live data
---------
* Industry unlevered betas (US firms) ... Aswath Damodaran, betas.xls
* BBB (Baa2) default spread ............ Aswath Damodaran, ratings.html (large non-financial firms)
* Statutory corporate income tax rates . OECD Corporate Tax Statistics (combined central + sub-central rate)
* 10-year government bond yields ....... Trading Economics country bond pages

Economics
---------
D/V = w_d,  E/V = 1 - w_d,  D/E = w_d / (1 - w_d)
Levered beta (Hamada):  b_L = b_U * [1 + (1 - t) * D/E]
USD:  k_e = rf_US + b_L * ERP
      k_d = rf_US + s_US                                    (pre-tax)
      WACC = (E/V) * k_e + (D/V) * k_d * (1 - t)
Local currency (Fisher / interest-rate parity):
      1 + k_e,FC = (1 + k_e,USD) * (1 + rf_FC) / (1 + rf_US)
      s_FC (auto) = s_US * (1 + rf_FC) / (1 + rf_US), so that 1 + k_d,FC = (1 + k_d,USD) * (1 + rf_FC) / (1 + rf_US)
      k_d,FC = rf_FC + s_FC
      WACC_FC = (E/V) * k_e,FC + (D/V) * k_d,FC * (1 - t)
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Sources and configuration
# ---------------------------------------------------------------------------
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
OECD_REPORT_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/"
    "statutory-corporate-income-tax-rates_440f9286.html"
)
# OECD Data Explorer API for the same dataset: combined (central + sub-central) statutory CIT rate,
# general government, latest observation per jurisdiction.
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,1.0/.A.CIT_C.ST..S13.."
    "?lastNObservations=1&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

REQUEST_TIMEOUT = 45
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
TTL_STATIC = 24 * 60 * 60  # betas, spreads and tax rates change rarely
TTL_MARKET = 3 * 60 * 60  # bond yields

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "USA"
DEFAULT_ERP = 6.5  # percent
DEFAULT_DEBT_SHARE = 30  # percent of firm value

COLOR_USD = "#2a78d6"
COLOR_FC = "#eb6834"
COLOR_MUTED = "#b4b2a9"

# ISO3 -> (display name, Trading Economics slug, ISO 4217 currency).
# Economies with both an OECD statutory CIT rate and a Trading Economics 10-year government bond page.
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "USA": ("United States", "united-states", "USD"),
    "AUS": ("Australia", "australia", "AUD"),
    "AUT": ("Austria", "austria", "EUR"),
    "BEL": ("Belgium", "belgium", "EUR"),
    "BRA": ("Brazil", "brazil", "BRL"),
    "BGR": ("Bulgaria", "bulgaria", "EUR"),
    "CAN": ("Canada", "canada", "CAD"),
    "CHL": ("Chile", "chile", "CLP"),
    "CHN": ("China", "china", "CNY"),
    "COL": ("Colombia", "colombia", "COP"),
    "HRV": ("Croatia", "croatia", "EUR"),
    "CZE": ("Czechia", "czech-republic", "CZK"),
    "DNK": ("Denmark", "denmark", "DKK"),
    "FIN": ("Finland", "finland", "EUR"),
    "FRA": ("France", "france", "EUR"),
    "DEU": ("Germany", "germany", "EUR"),
    "GRC": ("Greece", "greece", "EUR"),
    "HKG": ("Hong Kong (China)", "hong-kong", "HKD"),
    "HUN": ("Hungary", "hungary", "HUF"),
    "ISL": ("Iceland", "iceland", "ISK"),
    "IND": ("India", "india", "INR"),
    "IDN": ("Indonesia", "indonesia", "IDR"),
    "IRL": ("Ireland", "ireland", "EUR"),
    "ISR": ("Israel", "israel", "ILS"),
    "ITA": ("Italy", "italy", "EUR"),
    "JPN": ("Japan", "japan", "JPY"),
    "KEN": ("Kenya", "kenya", "KES"),
    "KOR": ("Korea", "south-korea", "KRW"),
    "LVA": ("Latvia", "latvia", "EUR"),
    "LTU": ("Lithuania", "lithuania", "EUR"),
    "MYS": ("Malaysia", "malaysia", "MYR"),
    "MEX": ("Mexico", "mexico", "MXN"),
    "NLD": ("Netherlands", "netherlands", "EUR"),
    "NZL": ("New Zealand", "new-zealand", "NZD"),
    "NGA": ("Nigeria", "nigeria", "NGN"),
    "NOR": ("Norway", "norway", "NOK"),
    "PAK": ("Pakistan", "pakistan", "PKR"),
    "PER": ("Peru", "peru", "PEN"),
    "PHL": ("Philippines", "philippines", "PHP"),
    "POL": ("Poland", "poland", "PLN"),
    "PRT": ("Portugal", "portugal", "EUR"),
    "QAT": ("Qatar", "qatar", "QAR"),
    "ROU": ("Romania", "romania", "RON"),
    "SGP": ("Singapore", "singapore", "SGD"),
    "SVK": ("Slovak Republic", "slovakia", "EUR"),
    "SVN": ("Slovenia", "slovenia", "EUR"),
    "ZAF": ("South Africa", "south-africa", "ZAR"),
    "ESP": ("Spain", "spain", "EUR"),
    "SWE": ("Sweden", "sweden", "SEK"),
    "CHE": ("Switzerland", "switzerland", "CHF"),
    "THA": ("Thailand", "thailand", "THB"),
    "TUR": ("Türkiye", "turkey", "TRY"),
    "GBR": ("United Kingdom", "united-kingdom", "GBP"),
    "VNM": ("Viet Nam", "vietnam", "VND"),
    "ZMB": ("Zambia", "zambia", "ZMW"),
}

_HTTP = requests.Session()
_HTTP.headers.update(BROWSER_HEADERS)


class DataFetchError(RuntimeError):
    """Raised when a source cannot be downloaded or parsed."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _get(url: str) -> requests.Response:
    try:
        response = _HTTP.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise DataFetchError(f"Could not reach {url}: {exc}") from exc
    if response.status_code != 200:
        raise DataFetchError(f"{url} returned HTTP {response.status_code}")
    return response


def _percent_to_float(text: object) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(text))
    return float(match.group()) / 100.0 if match else None


# ---------------------------------------------------------------------------
# Data fetchers (cached; the Refresh button clears the cache)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=TTL_STATIC, show_spinner=False)
def fetch_betas() -> tuple[pd.DataFrame, dict]:
    """Industry table from Damodaran's betas.xls ('Industry Averages' sheet)."""
    response = _get(BETAS_URL)
    try:
        raw = pd.read_excel(io.BytesIO(response.content), sheet_name="Industry Averages", header=None, engine="calamine")
    except Exception as exc:  # noqa: BLE001 - any parser failure means the file layout changed
        raise DataFetchError(f"Could not read betas.xls: {exc}") from exc

    first_col = raw.iloc[:, 0].astype(str).str.strip()
    header_rows = raw.index[first_col == "Industry Name"]
    if len(header_rows) == 0:
        raise DataFetchError("Could not find the 'Industry Name' header row in betas.xls.")
    header_row = header_rows[0]
    headers = [str(h).strip() for h in raw.iloc[header_row]]
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = headers

    required = {"Industry Name", "Number of firms", "Beta", "D/E Ratio", "Unlevered beta"}
    missing = required - set(headers)
    if missing:
        raise DataFetchError(f"betas.xls is missing columns: {', '.join(sorted(missing))}")

    out = pd.DataFrame(
        {
            "industry": table["Industry Name"].astype(str).str.strip(),
            "firms": pd.to_numeric(table["Number of firms"], errors="coerce"),
            "levered_beta_avg": pd.to_numeric(table["Beta"], errors="coerce"),
            "de_ratio": pd.to_numeric(table["D/E Ratio"], errors="coerce"),
            "unlevered_beta": pd.to_numeric(table["Unlevered beta"], errors="coerce"),
        }
    )
    out = out[out["unlevered_beta"].notna() & (out["industry"] != "nan")]
    out = out[~out["industry"].str.startswith("Total Market")].reset_index(drop=True)

    updated = None
    for _, row in raw.iloc[:header_row].iterrows():
        if str(row.iloc[0]).strip().lower().startswith("date updated"):
            value = row.iloc[1]
            updated = pd.Timestamp(value).strftime("%Y-%m-%d") if pd.notna(value) else None
            break
    return out, {"as_of": updated or "not stated", "fetched": _now_utc(), "url": BETAS_URL}


@st.cache_data(ttl=TTL_STATIC, show_spinner=False)
def fetch_bbb_spread() -> tuple[float, dict]:
    """Baa2/BBB default spread for large non-financial service firms from Damodaran's ratings page."""
    response = _get(RATINGS_URL)
    html = response.content.decode(response.encoding or "utf-8", errors="replace")
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError as exc:
        raise DataFetchError("No tables found on the ratings page.") from exc

    for table in tables:
        cells = table.map(lambda v: "" if pd.isna(v) else str(v))
        text = " ".join(cells.to_numpy().ravel()).lower()
        if "non-financial" not in text or "baa2/bbb" not in text:
            continue
        for _, row in cells.iterrows():
            values = list(row)
            for position, cell in enumerate(values):
                # The first Baa2/BBB cell in a row belongs to the left (non-financial) block.
                if cell.strip().lower() == "baa2/bbb" and position + 1 < len(values):
                    spread = _percent_to_float(values[position + 1])
                    if spread is not None:
                        as_of = re.search(r"Data used is as of\s*:?\s*([A-Za-z]+\s+\d{4})", re.sub(r"\s+", " ", html))
                        return spread, {
                            "as_of": as_of.group(1) if as_of else "not stated",
                            "fetched": _now_utc(),
                            "url": RATINGS_URL,
                        }
    raise DataFetchError("Could not find the Baa2/BBB spread for non-financial firms on the ratings page.")


@st.cache_data(ttl=TTL_STATIC, show_spinner=False)
def fetch_tax_rates() -> tuple[pd.DataFrame, dict]:
    """Latest combined statutory corporate income tax rate per jurisdiction (OECD)."""
    response = _get(OECD_API_URL)
    try:
        data = pd.read_csv(io.StringIO(response.text))
    except Exception as exc:  # noqa: BLE001
        raise DataFetchError(f"Could not parse the OECD response: {exc}") from exc
    needed = {"REF_AREA", "TIME_PERIOD", "OBS_VALUE"}
    if not needed.issubset(data.columns):
        raise DataFetchError("Unexpected OECD response layout.")
    if "MEASURE" in data.columns:
        data = data[data["MEASURE"] == "CIT_C"]
    data = data.sort_values("TIME_PERIOD").drop_duplicates("REF_AREA", keep="last")
    out = pd.DataFrame(
        {
            "iso3": data["REF_AREA"].astype(str),
            "name": data["Reference area"].astype(str) if "Reference area" in data.columns else data["REF_AREA"],
            "year": pd.to_numeric(data["TIME_PERIOD"], errors="coerce").astype("Int64"),
            "rate": pd.to_numeric(data["OBS_VALUE"], errors="coerce") / 100.0,
        }
    ).dropna(subset=["rate"])
    return out.set_index("iso3"), {"fetched": _now_utc(), "url": OECD_API_URL}


def _parse_te_date(label: str, end_year: int | None) -> str | None:
    """Turn Trading Economics' 'Nov/13' (or an intraday time) into an ISO date."""
    label = str(label).strip()
    today = date.today()
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", label):
        return today.isoformat()
    match = re.fullmatch(r"([A-Za-z]{3})/(\d{1,2})", label)
    if not match:
        return None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    month_name, day = match.group(1).lower(), int(match.group(2))
    if month_name not in months:
        return None
    month = months.index(month_name) + 1
    year = end_year or today.year
    for candidate_year in (year, year - 1):  # a quote dated after today belongs to the previous year
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate.isoformat()
    return None


@st.cache_data(ttl=TTL_MARKET, show_spinner=False)
def fetch_bond_yield(iso3: str) -> tuple[float, dict]:
    """Latest 10-year government bond yield from the country's Trading Economics bond page."""
    name, slug, _ = COUNTRIES[iso3]
    url = TE_COUNTRY_URL.format(slug=slug)
    response = _get(url)
    html = response.text

    match = re.search(r"TEChartsMeta\s*=\s*(\[.*?\]);", html, re.S)
    if not match:
        raise DataFetchError(f"No bond quote found on {url} (the page layout may have changed or access was blocked).")
    try:
        meta = json.loads(match.group(1))[0]
        value = float(meta["last"]) / 100.0
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise DataFetchError(f"Could not read the bond quote on {url}.") from exc

    instrument = str(meta.get("full_name") or meta.get("name") or "").strip()
    quote_name = str(meta.get("name") or "").strip()
    quote_date, end_year, frequency = None, None, None
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        tables = []
    for table in tables:
        columns = [str(c) for c in table.columns]
        if "Actual" in columns and "Dates" in columns and len(table):
            span = re.findall(r"\d{4}", str(table.iloc[0][table.columns[columns.index("Dates")]]))
            end_year = int(span[-1]) if span else None
            if "Frequency" in columns:
                frequency = str(table.iloc[0][table.columns[columns.index("Frequency")]])
            break
    for table in tables:
        columns = [str(c) for c in table.columns]
        if "Date" in columns and len(table.columns) >= 3:
            first = table.columns[0]
            rows = table[table[first].astype(str).str.strip() == quote_name]
            if len(rows):
                quote_date = _parse_te_date(rows.iloc[0][table.columns[columns.index("Date")]], end_year)
                break

    if "10" not in instrument and "10" not in str(meta.get("symbol", "")):
        raise DataFetchError(f"The quote on {url} is not a 10-year bond ({instrument}).")

    stale = end_year is not None and end_year < date.today().year
    as_of = quote_date or (f"latest in {end_year}" if end_year else "not stated")
    return value, {
        "as_of": as_of,
        "stale": stale,
        "frequency": frequency,
        "instrument": instrument or f"{name} 10Y",
        "fetched": _now_utc(),
        "url": url,
    }


def safe_fetch(func, *args):
    """Run a fetcher and return (result, error_message)."""
    try:
        return func(*args), None
    except DataFetchError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - never let one source crash the app
        return None, f"Unexpected error: {exc}"


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------
def cost_of_capital(
    beta_u: np.ndarray | float,
    tax: float,
    debt_share: float,
    erp: float,
    rf_us: float,
    rf_fc: float,
    spread_us: float,
    spread_fc: float | None,
) -> dict[str, np.ndarray | float]:
    """Cost of equity, debt and WACC in USD and local currency. All rates as decimals.

    spread_fc=None uses the parity-consistent spread s_US * (1 + rf_FC) / (1 + rf_US).
    """
    beta_u = np.asarray(beta_u, dtype=float)
    w_d = debt_share
    w_e = 1.0 - w_d
    de_ratio = w_d / w_e
    beta_l = beta_u * (1.0 + (1.0 - tax) * de_ratio)
    parity = (1.0 + rf_fc) / (1.0 + rf_us)

    ke_usd = rf_us + beta_l * erp
    kd_usd = rf_us + spread_us
    wacc_usd = w_e * ke_usd + w_d * kd_usd * (1.0 - tax)

    spread_fc_auto = spread_us * parity
    spread_fc_used = spread_fc_auto if spread_fc is None else spread_fc
    ke_fc = (1.0 + ke_usd) * parity - 1.0
    kd_fc = rf_fc + spread_fc_used
    wacc_fc = w_e * ke_fc + w_d * kd_fc * (1.0 - tax)

    return {
        "w_e": w_e,
        "w_d": w_d,
        "de_ratio": de_ratio,
        "beta_l": beta_l,
        "parity": parity,
        "ke_usd": ke_usd,
        "kd_usd": kd_usd,
        "kd_usd_at": kd_usd * (1.0 - tax),
        "wacc_usd": wacc_usd,
        "spread_fc_auto": spread_fc_auto,
        "spread_fc": spread_fc_used,
        "erp_fc": erp * parity,
        "premium_usd": beta_l * erp,
        "premium_fc": ke_fc - rf_fc,
        "ke_fc": ke_fc,
        "kd_fc": kd_fc,
        "kd_fc_at": kd_fc * (1.0 - tax),
        "wacc_fc": wacc_fc,
        "wacc_parity": (1.0 + wacc_usd) * parity - 1.0,
    }


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def pct(value: float, digits: int = 2) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value * 100:.{digits}f}%"


def override_input(
    label: str,
    fetched: float | None,
    key: str,
    *,
    percent: bool,
    min_value: float,
    max_value: float,
    step: float,
    help_text: str,
) -> tuple[float | None, bool]:
    """Toggle + number input. Returns (value as decimal or beta, is_manual).

    If the fetch failed, manual input is forced and starts empty.
    """
    forced = fetched is None
    manual = st.toggle(
        f"Override {label}",
        value=forced,
        key=f"tog_{key}",
        disabled=forced,
        help=help_text if not forced else "Automatic fetch failed, so a manual value is required.",
    )
    scale = 100.0 if percent else 1.0
    if manual:
        default = None if fetched is None else round(fetched * scale, 4)
        value = st.number_input(
            f"{label} ({'%' if percent else 'value'})",
            min_value=min_value,
            max_value=max_value,
            value=default,
            step=step,
            format="%.4f" if not percent else "%.3f",
            key=f"num_{key}",
            placeholder="Enter a value",
        )
        return (None if value is None else value / scale), True
    shown = f"{fetched * 100:.3f}%" if percent else f"{fetched:.4f}"
    st.caption(f"Using fetched value: **{shown}**")
    return fetched, False


def comparison_chart(res: dict, fc_label: str) -> go.Figure:
    metrics = ["Cost of<br>equity", "Pre-tax<br>cost of debt", "After-tax<br>cost of debt", "WACC"]
    usd = [res["ke_usd"], res["kd_usd"], res["kd_usd_at"], res["wacc_usd"]]
    fc = [res["ke_fc"], res["kd_fc"], res["kd_fc_at"], res["wacc_fc"]]
    fig = go.Figure()
    for name, values, color in (("USD", usd, COLOR_USD), (fc_label, fc, COLOR_FC)):
        fig.add_trace(
            go.Bar(
                x=metrics,
                y=[float(v) * 100 for v in values],
                name=name,
                marker={"color": color, "cornerradius": 4},
                text=[f"{float(v) * 100:.2f}%" for v in values],
                textposition="outside",
                cliponaxis=False,
                hovertemplate=f"{name}: <b>%{{y:.2f}}%</b><extra></extra>",
            )
        )
    top = max(max(float(v) for v in usd), max(float(v) for v in fc)) * 100
    fig.update_layout(
        barmode="group",
        bargap=0.28,
        bargroupgap=0.06,
        height=420,
        margin={"l": 50, "r": 20, "t": 30, "b": 40},
        xaxis={"tickangle": 0},
        yaxis={"title": "Percent per year", "ticksuffix": "%", "range": [0, top * 1.18], "gridwidth": 1},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    return fig


def industry_chart(table: pd.DataFrame, column: str, label: str, selected: str) -> go.Figure:
    data = table.sort_values(column)
    colors = [COLOR_USD if name == selected else COLOR_MUTED for name in data["Industry"]]
    fig = go.Figure(
        go.Bar(
            x=data[column],
            y=data["Industry"],
            orientation="h",
            marker={"color": colors, "cornerradius": 3},
            hovertemplate="%{y}<br>" + label + ": <b>%{x:.2f}%</b><extra></extra>",
        )
    )
    sel = data[data["Industry"] == selected]
    if len(sel):
        fig.add_annotation(
            x=float(sel[column].iloc[0]),
            y=selected,
            text=f"  {selected}: {float(sel[column].iloc[0]):.2f}%",
            showarrow=False,
            xanchor="left",
            font={"size": 12},
        )
    fig.update_layout(
        height=max(500, 17 * len(data) + 80),
        margin={"l": 10, "r": 160, "t": 20, "b": 40},
        xaxis={"title": label, "ticksuffix": "%", "side": "top"},
        yaxis={"tickfont": {"size": 11}, "automargin": True},
        bargap=0.25,
        showlegend=False,
    )
    return fig


def results_frame(res: dict, rf_us: float, rf_fc: float, erp: float, tax: float, fc_code: str) -> pd.DataFrame:
    rows = [
        ("Risk-free rate (10Y government yield)", rf_us, rf_fc),
        ("Levered beta", float(res["beta_l"]), float(res["beta_l"])),
        ("Equity risk premium (ERP)", erp, float(res["erp_fc"])),
        ("Equity premium over risk-free (β_L × ERP)", float(res["premium_usd"]), float(res["premium_fc"])),
        ("Cost of equity", float(res["ke_usd"]), float(res["ke_fc"])),
        ("BBB default spread", float(res["kd_usd"]) - rf_us, float(res["spread_fc"])),
        ("Pre-tax cost of debt", float(res["kd_usd"]), float(res["kd_fc"])),
        ("Project tax rate", tax, tax),
        ("After-tax cost of debt", float(res["kd_usd_at"]), float(res["kd_fc_at"])),
        ("Equity weight E/V", res["w_e"], res["w_e"]),
        ("Debt weight D/V", res["w_d"], res["w_d"]),
        ("WACC", float(res["wacc_usd"]), float(res["wacc_fc"])),
    ]
    frame = pd.DataFrame(rows, columns=["Component", "USD", fc_code])
    return frame


def format_results(frame: pd.DataFrame) -> pd.DataFrame:
    shown = frame.copy()
    for col in shown.columns[1:]:
        shown[col] = [
            f"{v:.3f}" if comp == "Levered beta" else f"{v * 100:.2f}%" for comp, v in zip(shown["Component"], shown[col])
        ]
    return shown


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Cross-Currency WACC", page_icon="📊", layout="wide")
    st.title("Cross-Currency Cost of Capital")
    st.caption(
        "Cost of equity, cost of debt and WACC for a project in US dollars and in a selected country's currency, "
        "built from live Damodaran, OECD and Trading Economics data."
    )

    # ---------------- Data ----------------
    with st.sidebar:
        st.header("Data")
        if st.button("🔄 Refresh data", width="stretch", help="Clear the cache and fetch every source again."):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Fetching betas, spreads, tax rates and bond yields…"):
        betas_res, betas_err = safe_fetch(fetch_betas)
        spread_res, spread_err = safe_fetch(fetch_bbb_spread)
        tax_res, tax_err = safe_fetch(fetch_tax_rates)

    if betas_res is None:
        st.error(f"Industry betas could not be loaded, so the industry list is unavailable. {betas_err}")
        st.stop()
    betas, betas_meta = betas_res
    industries = betas["industry"].tolist()

    # ---------------- Project inputs ----------------
    with st.sidebar:
        st.header("Project")
        industry = st.selectbox(
            "Industry (Damodaran, US firms)",
            industries,
            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0,
        )
        codes = list(COUNTRIES)
        iso3 = st.selectbox(
            "Target country",
            codes,
            index=codes.index(DEFAULT_COUNTRY),
            format_func=lambda c: f"{COUNTRIES[c][0]} ({COUNTRIES[c][2]})",
        )
        erp_pct = st.number_input(
            "Equity risk premium, mature market (%)", min_value=0.0, max_value=20.0, value=DEFAULT_ERP, step=0.25,
            help="Applied to the levered beta in USD. The local-currency premium follows from the parity conversion.",
        )
        debt_pct = st.slider(
            "Target debt share D/(D+E) (%)", min_value=0, max_value=90, value=DEFAULT_DEBT_SHARE, step=1,
        )

    country_name, _, fc_code = COUNTRIES[iso3]
    is_us = iso3 == "USA"
    fc_label = f"{fc_code} ({country_name})"
    local = fc_code if not is_us else "USD (local)"  # column label for the selected-country currency

    with st.spinner("Fetching 10-year government bond yields…"):
        us_yield_res, us_yield_err = safe_fetch(fetch_bond_yield, "USA")
        fc_yield_res, fc_yield_err = (us_yield_res, us_yield_err) if is_us else safe_fetch(fetch_bond_yield, iso3)

    beta_fetched = float(betas.loc[betas["industry"] == industry, "unlevered_beta"].iloc[0])
    spread_fetched = spread_res[0] if spread_res else None
    tax_table = tax_res[0] if tax_res else None
    tax_us_fetched = float(tax_table.loc["USA", "rate"]) if tax_table is not None and "USA" in tax_table.index else None
    tax_fc_fetched = float(tax_table.loc[iso3, "rate"]) if tax_table is not None and iso3 in tax_table.index else None
    rf_us_fetched = us_yield_res[0] if us_yield_res else None
    rf_fc_fetched = fc_yield_res[0] if fc_yield_res else None

    # ---------------- Tax switch ----------------
    with st.sidebar:
        st.header("Project tax rate")
        tax_choice = st.radio(
            "Tax the project at the rate of",
            ["United States", country_name] if not is_us else ["United States"],
            horizontal=True,
            key=f"tax_choice_{iso3}",
            help="One tax rate is used for both currencies: in the levered beta and in the after-tax cost of debt.",
        )

    # ---------------- Manual overrides ----------------
    with st.sidebar:
        st.header("Manual overrides")
        st.caption("Switch on to replace a fetched value with your own.")
        with st.expander("Unlevered beta", expanded=betas_err is not None):
            beta_u, beta_manual = override_input(
                "unlevered beta", beta_fetched, f"beta_{industry}", percent=False,
                min_value=0.0, max_value=5.0, step=0.01, help_text="Damodaran 'Unlevered beta' for the industry.",
            )
        with st.expander("Corporate tax rates", expanded=tax_err is not None):
            tax_us, tax_us_manual = override_input(
                "U.S. tax rate", tax_us_fetched, "tax_USA", percent=True,
                min_value=0.0, max_value=60.0, step=0.1, help_text="OECD combined statutory CIT rate.",
            )
            if is_us:
                tax_fc, tax_fc_manual = tax_us, tax_us_manual
            else:
                tax_fc, tax_fc_manual = override_input(
                    f"{country_name} tax rate", tax_fc_fetched, f"tax_{iso3}", percent=True,
                    min_value=0.0, max_value=60.0, step=0.1, help_text="OECD combined statutory CIT rate.",
                )
        with st.expander("Government bond yields (10Y)", expanded=us_yield_err is not None or fc_yield_err is not None):
            rf_us, rf_us_manual = override_input(
                "U.S. 10Y yield", rf_us_fetched, "rf_USA", percent=True,
                min_value=-2.0, max_value=100.0, step=0.01, help_text="Trading Economics, US 10-year Treasury note.",
            )
            if is_us:
                rf_fc, rf_fc_manual = rf_us, rf_us_manual
            else:
                rf_fc, rf_fc_manual = override_input(
                    f"{country_name} 10Y yield", rf_fc_fetched, f"rf_{iso3}", percent=True,
                    min_value=-2.0, max_value=100.0, step=0.01,
                    help_text=f"Trading Economics, {country_name} 10-year government bond.",
                )
        with st.expander("BBB borrowing spreads", expanded=spread_err is not None):
            spread_us, spread_us_manual = override_input(
                "USD BBB spread", spread_fetched, "spread_USD", percent=True,
                min_value=0.0, max_value=20.0, step=0.01,
                help_text="Damodaran Baa2/BBB default spread, large non-financial firms.",
            )
            spread_fc_manual = st.toggle(
                f"Override {fc_code} BBB spread",
                value=False,
                key=f"tog_spread_{iso3}",
                help="Off: the spread is derived from the USD spread by interest-rate parity.",
            )
            spread_fc_input = None
            if spread_fc_manual:
                default_fc = None
                if spread_us is not None and rf_us is not None and rf_fc is not None:
                    default_fc = round(spread_us * (1 + rf_fc) / (1 + rf_us) * 100, 4)
                value = st.number_input(
                    f"{fc_code} BBB spread (%)", min_value=0.0, max_value=50.0, value=default_fc, step=0.01,
                    format="%.3f", key=f"num_spread_{iso3}", placeholder="Enter a value",
                )
                spread_fc_input = None if value is None else value / 100.0

    # ---------------- Validate inputs ----------------
    missing = [
        name
        for name, value in (
            ("unlevered beta", beta_u),
            ("U.S. tax rate", tax_us),
            (f"{country_name} tax rate", tax_fc),
            ("U.S. 10Y yield", rf_us),
            (f"{country_name} 10Y yield", rf_fc),
            ("USD BBB spread", spread_us),
        )
        if value is None
    ]
    if is_us:  # the target-country inputs are the U.S. inputs
        missing = [m for m in missing if not m.startswith(country_name)]
    if spread_fc_manual and spread_fc_input is None:
        missing.append(f"{fc_code} BBB spread")
    for err in (spread_err, tax_err, us_yield_err, None if is_us else fc_yield_err):
        if err:
            st.warning(f"Automatic fetch failed: {err}")
    if missing:
        st.info(f"Enter a manual value for: {', '.join(missing)} (sidebar → Manual overrides).")
        st.stop()

    tax = tax_us if tax_choice == "United States" else tax_fc
    erp = erp_pct / 100.0
    debt_share = debt_pct / 100.0
    res = cost_of_capital(beta_u, tax, debt_share, erp, rf_us, rf_fc, spread_us, spread_fc_input)

    # ---------------- Headline ----------------
    st.markdown(
        f"**{industry}** project · target country **{country_name}** · tax rate of **{tax_choice}** ({pct(tax)}) · "
        f"ERP **{pct(erp)}** · debt share **{debt_pct}%**"
    )
    if us_yield_res and us_yield_res[1]["stale"] and not rf_us_manual:
        st.warning("The U.S. 10Y quote on Trading Economics looks stale. Consider a manual override.")
    if not is_us and fc_yield_res and fc_yield_res[1]["stale"] and not rf_fc_manual:
        st.warning(
            f"Trading Economics' {country_name} 10Y series is stale (last observation: {fc_yield_res[1]['as_of']}). "
            "Consider entering a current yield under Manual overrides."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost of equity · USD", pct(float(res["ke_usd"])))
    c2.metric(f"Cost of equity · {fc_code}", pct(float(res["ke_fc"])),
              None if is_us else f"{(float(res['ke_fc']) - float(res['ke_usd'])) * 10000:+.0f} bp vs USD",
              delta_color="off")
    c3.metric("WACC · USD", pct(float(res["wacc_usd"])))
    c4.metric(f"WACC · {fc_code}", pct(float(res["wacc_fc"])),
              None if is_us else f"{(float(res['wacc_fc']) - float(res['wacc_usd'])) * 10000:+.0f} bp vs USD",
              delta_color="off")
    if is_us:
        st.caption("The target country is the United States, so both currency columns are identical.")

    tab_results, tab_industries, tab_method, tab_sources = st.tabs(
        ["Results", "All industries", "Assumptions & method", "Sources & data dates"]
    )

    # ---------------- Results tab ----------------
    with tab_results:
        left, right = st.columns([1.05, 1])
        frame = results_frame(res, rf_us, rf_fc, erp, tax, local)
        with left:
            st.subheader("Side-by-side results")
            st.dataframe(format_results(frame), hide_index=True, width="stretch", height=457)
        with right:
            st.subheader("Comparison")
            st.plotly_chart(comparison_chart(res, fc_label), width="stretch", config={"displaylogo": False})

        st.markdown(
            f"""
**How the two columns are linked.** Beta, the debt share and the tax rate are identical in both columns, and the ERP is set in USD.
The only difference is the currency, and that difference is carried by the 10-year government yields:
(1 + rf_{fc_code}) / (1 + rf_USD) = {float(res['parity']):.4f}.
Each USD rate *k* becomes (1 + *k*) × {float(res['parity']):.4f} − 1 in {fc_code}.
Unlevered beta {beta_u:.3f} is re-levered at D/E = {float(res['de_ratio']):.3f} to **{float(res['beta_l']):.3f}**.
"""
        )
        if spread_fc_input is not None:
            st.caption(
                f"{fc_code} BBB spread is a manual input ({pct(spread_fc_input)}). "
                f"The parity-consistent value would be {pct(float(res['spread_fc_auto']))}."
            )
        else:
            st.caption(
                f"{fc_code} BBB spread is calculated automatically: {pct(spread_us)} × {float(res['parity']):.4f} = "
                f"{pct(float(res['spread_fc_auto']))}. Converting the USD WACC directly by parity gives "
                f"{pct(float(res['wacc_parity']))}. The small gap to {pct(float(res['wacc_fc']))} is the tax shield "
                "acting on a different interest rate."
            )

        inputs = pd.DataFrame(
            [
                ("Industry", industry, "", ""),
                ("Target country", f"{country_name} ({fc_code})", "", ""),
                ("Unlevered beta", f"{beta_u:.4f}", "Manual" if beta_manual else "Damodaran betas.xls", betas_meta["as_of"]),
                ("U.S. corporate tax rate", pct(tax_us), "Manual" if tax_us_manual else "OECD", "" if tax_us_manual or tax_table is None else str(tax_table.loc["USA", "year"])),
                (f"{country_name} corporate tax rate", pct(tax_fc), "Manual" if tax_fc_manual else "OECD", "" if tax_fc_manual or tax_table is None or iso3 not in tax_table.index else str(tax_table.loc[iso3, "year"])),
                ("Project tax rate used", pct(tax), f"{tax_choice} rate", ""),
                ("Equity risk premium", pct(erp), "User input", ""),
                ("Debt share D/V", f"{debt_pct}%", "User input", ""),
                ("U.S. 10Y yield", pct(rf_us, 3), "Manual" if rf_us_manual else "Trading Economics", "" if rf_us_manual or not us_yield_res else us_yield_res[1]["as_of"]),
                (f"{country_name} 10Y yield", pct(rf_fc, 3), "Manual" if rf_fc_manual else "Trading Economics", "" if rf_fc_manual or not fc_yield_res else fc_yield_res[1]["as_of"]),
                ("USD BBB spread", pct(spread_us), "Manual" if spread_us_manual else "Damodaran ratings.html", "" if spread_us_manual or not spread_res else spread_res[1]["as_of"]),
                (f"{fc_code} BBB spread", pct(float(res["spread_fc"])), "Manual" if spread_fc_input is not None else "Parity calculation", ""),
            ],
            columns=["Input", "Value", "Source", "Data date"],
        )
        st.subheader("Inputs used")
        st.dataframe(inputs, hide_index=True, width="stretch")

        # Results as decimals (0.05 = 5%) for spreadsheets, followed by the inputs with their sources and dates.
        export = pd.concat(
            [
                frame.rename(columns={"Component": "Item"}).assign(Section="Result"),
                inputs.rename(columns={"Input": "Item"}).assign(Section="Input"),
            ],
            ignore_index=True,
        )[["Section", "Item", "USD", local, "Value", "Source", "Data date"]]
        st.download_button(
            "Download results (CSV)",
            data=export.to_csv(index=False).encode("utf-8"),
            file_name=f"wacc_{iso3}_{re.sub(r'[^A-Za-z0-9]+', '_', industry).strip('_')}.csv",
            mime="text/csv",
            type="primary",
        )

    # ---------------- All-industry tab ----------------
    with tab_industries:
        st.caption(
            "Every Damodaran industry under the same assumptions (tax rate, debt share, ERP, yields, spreads). "
            "Each industry uses its fetched unlevered beta; a beta override applies only to the selected industry."
        )
        betas_used = betas["unlevered_beta"].to_numpy(dtype=float).copy()
        betas_used[betas["industry"].to_numpy() == industry] = beta_u
        all_res = cost_of_capital(betas_used, tax, debt_share, erp, rf_us, rf_fc, spread_us, spread_fc_input)
        industry_table = pd.DataFrame(
            {
                "Industry": betas["industry"],
                "Firms": betas["firms"].astype("Int64"),
                "Unlevered beta": betas_used,
                "Levered beta": all_res["beta_l"],
                "Cost of equity USD (%)": all_res["ke_usd"] * 100,
                f"Cost of equity {local} (%)": all_res["ke_fc"] * 100,
                "WACC USD (%)": all_res["wacc_usd"] * 100,
                f"WACC {local} (%)": all_res["wacc_fc"] * 100,
            }
        )
        if is_us:  # identical columns add nothing
            industry_table = industry_table.drop(columns=[f"Cost of equity {local} (%)", f"WACC {local} (%)"])
        col_a, col_b = st.columns(2)
        metric = col_a.radio("Measure", ["WACC", "Cost of equity"], horizontal=True)
        currency = col_b.radio("Currency", ["USD", local] if not is_us else ["USD"], horizontal=True)
        column = f"{metric} {currency} (%)"
        st.plotly_chart(
            industry_chart(industry_table, column, f"{metric}, {currency}", industry),
            width="stretch",
            config={"displaylogo": False},
        )
        st.dataframe(
            industry_table.sort_values(column, ascending=False),
            hide_index=True,
            width="stretch",
            column_config={
                "Unlevered beta": st.column_config.NumberColumn(format="%.3f"),
                "Levered beta": st.column_config.NumberColumn(format="%.3f"),
                **{c: st.column_config.NumberColumn(format="%.2f") for c in industry_table.columns if c.endswith("(%)")},
            },
        )
        st.download_button(
            "Download all-industry comparison (CSV)",
            data=industry_table.to_csv(index=False, float_format="%.6g").encode("utf-8"),
            file_name=f"wacc_all_industries_{iso3}.csv",
            mime="text/csv",
        )

    # ---------------- Method tab ----------------
    with tab_method:
        st.markdown("#### Formulas")
        st.latex(r"\frac{D}{E} = \frac{w_d}{1-w_d}, \qquad \beta_L = \beta_U \left[1 + (1-t)\frac{D}{E}\right]")
        st.latex(r"k_e^{USD} = r_f^{US} + \beta_L \cdot ERP, \qquad k_d^{USD} = r_f^{US} + s^{USD}")
        st.latex(r"1 + k_e^{FC} = \left(1 + k_e^{USD}\right)\frac{1 + r_f^{FC}}{1 + r_f^{US}}, \qquad "
                 r"s^{FC}_{auto} = s^{USD}\,\frac{1 + r_f^{FC}}{1 + r_f^{US}}, \qquad k_d^{FC} = r_f^{FC} + s^{FC}")
        st.latex(r"WACC = (1-w_d)\,k_e + w_d\,k_d\,(1-t) \quad \text{(in each currency)}")
        st.markdown(
            """
#### Main assumptions
1. **Same project, two currencies.** Business risk (beta), the mature-market ERP (set in USD), the capital
   structure and the tax rate are the same in both columns. Only the currency of the cash flows differs.
2. **Currency conversion by the Fisher effect / interest-rate parity.** The ratio of gross 10-year government
   yields measures the expected long-run inflation differential. Cost of equity converts multiplicatively.
   The automatic local BBB spread is the USD spread scaled by the same ratio, so the local pre-tax cost of debt
   equals the parity-converted USD cost of debt.
   The implied local-currency ERP is ERP × (1 + rf_FC) / (1 + rf_US).
3. **Risk-free rates are 10-year local-currency government yields.** If a government bond carries default
   risk (e.g. Türkiye, Brazil, Nigeria), its yield also contains a sovereign default spread, and that spread
   passes into the local-currency rates. No separate country risk premium is added: the app translates
   currency, it does not price the risk of operating in the country.
4. **Industry beta.** Damodaran's *unlevered* beta for US firms (unlevered by him at a 25% marginal tax
   rate). It is re-levered with the Hamada formula at the target debt share and the chosen project tax rate.
5. **Cost of debt.** Risk-free rate + Damodaran's Baa2/BBB default spread for large non-financial firms. The
   project is assumed to borrow at a BBB rating whatever the debt share.
6. **Tax rate.** OECD combined (central + sub-central) statutory corporate income tax rate, latest year
   available. The same rate drives the beta re-levering and the debt tax shield.
7. **WACC weights** are target market-value weights: D/V = debt share, E/V = 1 − debt share.
"""
        )

    # ---------------- Sources tab ----------------
    with tab_sources:
        rows = [
            ("Industry unlevered betas (US)", "Aswath Damodaran — betas.xls, 'Unlevered beta' column",
             betas_meta["url"], f"Updated {betas_meta['as_of']}", betas_meta["fetched"], "OK"),
            ("BBB default spread (USD)", "Aswath Damodaran — ratings.html, Baa2/BBB, large non-financial firms",
             RATINGS_URL, f"Data as of {spread_res[1]['as_of']}" if spread_res else "—",
             spread_res[1]["fetched"] if spread_res else "—", "OK" if spread_res else f"Failed: {spread_err}"),
            ("Corporate income tax rates", "OECD Corporate Tax Statistics — combined statutory CIT rate (Data Explorer API)",
             OECD_API_URL,
             (f"US {tax_table.loc['USA', 'year']}" + ("" if is_us or iso3 not in tax_table.index else f", {country_name} {tax_table.loc[iso3, 'year']}"))
             if tax_table is not None else "—",
             tax_res[1]["fetched"] if tax_res else "—", "OK" if tax_res else f"Failed: {tax_err}"),
            ("U.S. 10Y government bond yield", us_yield_res[1]["instrument"] if us_yield_res else "Trading Economics",
             TE_COUNTRY_URL.format(slug="united-states"), us_yield_res[1]["as_of"] if us_yield_res else "—",
             us_yield_res[1]["fetched"] if us_yield_res else "—", "OK" if us_yield_res else f"Failed: {us_yield_err}"),
        ]
        if not is_us:
            rows.append(
                (f"{country_name} 10Y government bond yield",
                 fc_yield_res[1]["instrument"] if fc_yield_res else "Trading Economics",
                 TE_COUNTRY_URL.format(slug=COUNTRIES[iso3][1]),
                 fc_yield_res[1]["as_of"] if fc_yield_res else "—",
                 fc_yield_res[1]["fetched"] if fc_yield_res else "—",
                 ("Stale series" if fc_yield_res and fc_yield_res[1]["stale"] else "OK") if fc_yield_res else f"Failed: {fc_yield_err}")
            )
        st.dataframe(
            pd.DataFrame(rows, columns=["Data", "Source", "Link", "Data date", "Fetched", "Status"]),
            hide_index=True,
            width="stretch",
            column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")},
        )
        st.markdown(
            f"""
- The OECD publishes these rates in the [Corporate Tax Statistics report]({OECD_REPORT_URL}). The app reads the
  same dataset (`OECD.CTP.TPS:DSD_TAX_CIT@DF_CIT`, measure `CIT_C`) from the OECD Data Explorer API, which is
  machine-readable and has the latest year.
- Trading Economics' [bonds overview]({TE_BONDS_URL}) loads its table with JavaScript behind a bot check, so
  the app reads each country's 10-year bond page, which shows the same quote.
- Data are cached (bond yields 3 hours, other sources 24 hours). **Refresh data** in the sidebar fetches
  everything again.
"""
        )
        if tax_table is not None:
            with st.expander("All OECD statutory corporate tax rates (latest year)"):
                st.dataframe(
                    tax_table.reset_index().rename(columns={"iso3": "ISO3", "name": "Jurisdiction", "year": "Year", "rate": "Rate"})
                    .assign(Rate=lambda d: d["Rate"] * 100).sort_values("Jurisdiction"),
                    hide_index=True,
                    width="stretch",
                    column_config={"Rate": st.column_config.NumberColumn("Rate (%)", format="%.2f")},
                )


if __name__ == "__main__":
    main()
