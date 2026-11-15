Cross-Currency Cost of Capital (WACC) Explorer
A Streamlit app that estimates a project's cost of equity, cost of debt and WACC in US dollars and in the currency of a selected country, side by side. It uses live data from Aswath Damodaran, the OECD and Trading Economics.

Default view
Software (System & Application) · United States as the selected country · U.S. tax rate · 6.5% equity risk premium · 30% debt financing.

Data sources (fetched live, latest available)
Input	Source	What is used
Industry unlevered beta	Damodaran, betas.xls	"Unlevered beta" column, US firms; date from the "Date updated" cell
USD BBB borrowing spread	Damodaran, ratings.html	Baa2/BBB default spread, large non-financial service firms; date from "Data used is as of …"
Corporate income tax rates	OECD Corporate Tax Statistics (report)	Combined (central + sub-central) statutory CIT rate, latest year, read from the OECD Data Explorer API (dataset DSD_TAX_CIT@DF_CIT, measure CIT_C)
10-year government bond yields	Trading Economics (bonds)	Latest 10Y yield and quote date from each country's /{country}/government-bond-yield page
Notes on retrieval:

The OECD report web page blocks automated requests. The app reads the same dataset from the OECD's official data API, which also has newer data (2025 for OECD members, 2024 for other jurisdictions).
Trading Economics' /bonds overview loads its table with JavaScript behind a bot check, so a script cannot read it. Each country's bond page shows the same quote in the server-rendered HTML, and the app scrapes that.
If Trading Economics' latest observation is from an earlier year (at the time of writing: Latvia, Qatar, Bulgaria), the app labels the yield stale and suggests a manual override.
Every input shows its source and data date in the app (Inputs used table and Sources & data dates tab).
Data are cached: bond yields for 3 hours, the other sources for 24 hours. Refresh data in the sidebar clears the cache and fetches everything again.
If a source cannot be reached, the app says so and switches that input to manual entry. It never substitutes made-up numbers.
Features
Select an industry (all Damodaran industries) and a target country (55 economies that have both an OECD tax rate and a Trading Economics 10-year bond page).
Adjust the equity risk premium and the target debt share D/(D+E).
Switch the project tax rate between the U.S. rate and the selected country's rate. One rate is applied in both currencies.
Manual overrides (toggle on/off) for the unlevered beta, the U.S. and foreign tax rates, the USD BBB spread and both 10-year yields. The foreign BBB spread can also be overridden; switched off, it shows the automatic parity-based value.
Side-by-side results (USD vs. local currency), a comparison chart, and an explanation of the main assumptions.
All-industry comparison: WACC or cost of equity, in USD or local currency, for every industry under the same assumptions, with the selected industry highlighted.
Downloads: results with inputs, sources and dates (CSV), and the all-industry table (CSV).
Economics
Notation: w_d = D/V (target debt share), t = project tax rate, ERP = mature-market equity risk premium, rf = 10-year government yield, s = BBB default spread.

1. Re-levering the industry beta (Hamada)

D/E = w_d / (1 − w_d)
β_L = β_U × [1 + (1 − t) × D/E]
2. US-dollar cost of capital

k_e(USD) = rf_US + β_L × ERP
k_d(USD) = rf_US + s_USD                      (pre-tax)
WACC(USD) = (1 − w_d) × k_e(USD) + w_d × k_d(USD) × (1 − t)
3. Local-currency cost of capital (Fisher effect / interest-rate parity)

The ratio of gross 10-year yields converts USD rates into the local currency:

1 + k_e(FC) = (1 + k_e(USD)) × (1 + rf_FC) / (1 + rf_US)
s_FC (automatic) = s_USD × (1 + rf_FC) / (1 + rf_US)
k_d(FC) = rf_FC + s_FC
WACC(FC) = (1 − w_d) × k_e(FC) + w_d × k_d(FC) × (1 − t)
With the automatic spread, the local pre-tax cost of debt equals the parity-converted USD cost of debt, so debt and equity are converted consistently. The implied local ERP is ERP × (1 + rf_FC) / (1 + rf_US). The app also shows the USD WACC converted directly by parity. The small difference from WACC(FC) comes from the tax shield acting on a different interest rate.

Main assumptions
Same project, two currencies. Beta, the mature-market ERP (set in USD), the capital structure and the tax rate are the same in both columns. Only the currency differs.
The 10-year yield differential measures expected inflation differences. If a country's government bond carries default risk (e.g. Türkiye, Brazil, Nigeria), its yield also contains a sovereign default spread, and that spread passes into the local-currency rates. No separate country risk premium is added: the app translates currency, it does not price the risk of operating in the country.
Industry beta is Damodaran's unlevered beta for US firms (unlevered by him at a 25% marginal tax rate) and is re-levered at the project's debt share and tax rate.
Cost of debt assumes the project borrows at a BBB rating whatever the debt share.
Tax rate is the OECD combined statutory rate. The same rate drives the beta re-levering and the debt tax shield.
WACC weights are target market-value weights.
Run locally
Requires Python 3.12.

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
Deploy on Streamlit Community Cloud
Push app.py, requirements.txt and README.md to the root of a GitHub repository.
Go to https://share.streamlit.io, click Create app, and choose the repository and branch.
Set Main file path to app.py.
Under Advanced settings, choose Python 3.12, then click Deploy.
No API keys or secrets are needed.

Files
File	Purpose
app.py	The Streamlit application: data fetchers, calculations, charts, downloads
requirements.txt	Python dependencies (python-calamine reads Damodaran's .xls; lxml parses HTML tables)
README.md	This document
Disclaimer
For educational use. Scraped web data can change format or be temporarily unavailable. Check key inputs against the original sources before relying on the results.
