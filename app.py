import base64
import json
import re
import hashlib
import sqlite3
import streamlit as st
from datetime import date, datetime
from html import escape
from io import BytesIO
from numbers import Number
from pathlib import Path
from urllib.parse import quote

APP_VERSION = "v0.1.41"
DEVELOPER = "Matheus Augusto de Lima Basilio"
ROLE = "Quality Specialist"
MANAGER = "曹毅"
BASE_DIR = Path(__file__).resolve().parent
RULES_PATH = BASE_DIR / "config" / "rules.json"
ASSEMBLY_SAMPLE_DIR = BASE_DIR / "sample_data" / "assembly"
DATA_STORE_DIR = BASE_DIR / "data_store"
QUALITY_DB_PATH = DATA_STORE_DIR / "jovi_quality.db"
ASSEMBLY_FILE_STORE_DIR = DATA_STORE_DIR / "assembly"
ASSEMBLY_MONITORED_DIR = BASE_DIR / "auto_import" / "assembly"
HOME_ASSET_DIR = BASE_DIR / "assets" / "home"
HOME_MODULE_IMAGES = {
    "Learning Area": "learning_area.png",
    "SMT": "smt.png",
    "Assembly": "assembly.png",
    "IQC": "iqc.png",
}

st.set_page_config(
    page_title="Jovi Quality Portal",
    page_icon="JOVI",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODULES = {
    "Home": {"color": "#1D5FBF", "tabs": []},
    "Learning Area": {"color": "#1D5FBF", "tabs": ["Overview", "Procedures", "Process Map", "KPI's"]},
    "SMT": {"color": "#0D7A45", "tabs": ["Overview", "KPI Track", "Quality Dashboard", "BOM Comparison Tool - SMT"]},
    "Assembly": {"color": "#6532C8", "tabs": ["Overview", "KPI Track", "Quality Dashboard", "BOM Comparison Tool - Assy"]},
    "IQC": {"color": "#B45309", "tabs": ["Overview"]},
    "About": {"color": "#1D5FBF", "tabs": []},
}

VERSION_HISTORY = [
    ("v0.1.41", "Changed SMT input deduplication to period scope: filter Operate Time first, then count each PCB No. once inside the selected date/time interval."),
    ("v0.1.40", "Added real SMT daily input analysis using Operate Time as the input timestamp and counting each PCB No. only once at its earliest valid occurrence."),
    ("v0.1.39", "Prevented summarized Assembly inputs from being used at a finer time scale: weekly input is never treated as daily input, and monthly input is never split into weekly or daily estimates."),
    ("v0.1.38", "Separated BOM comparison by process: renamed the existing SMT tool and added the Assembly v2.0.7 Microsiga vs Jovi comparison rules in its own Assembly tab."),
    ("v0.1.37", "Moved Assembly input period consolidation before the date filter so weekly replacement files supersede older daily rows in every selected period."),
    ("v0.1.36", "Added formal Assembly input period control: exclusive EndDate handling, replacement of older covered input periods, and blocking of ambiguous overlaps."),
    ("v0.1.35", "Corrected Assembly production/input counting by requiring input periods to be fully inside the selected date range and ignoring older overlapping input rows when newer summaries exist."),
    ("v0.1.34", "Cached the full Assembly analysis result for stored local files so switching dashboard sections does not recalculate all metrics."),
    ("v0.1.33", "Further improved Assembly loading by using the latest cumulative defects file when it supersedes older stored defect extracts and by optimizing multi-file consolidation."),
    ("v0.1.32", "Skipped Assembly analysis calculation while the Upload Data section is open, keeping import management faster."),
    ("v0.1.31", "Reduced Assembly rerun overhead by checking the monitored import folder once per session instead of on every interaction."),
    ("v0.1.30", "Changed Assembly dashboard navigation to render only the selected section instead of calculating all tabs on every rerun."),
    ("v0.1.29", "Cached Assembly source file reads and moved Details CSV generation behind a prepare action to reduce dashboard reload time."),
    ("v0.1.28", "Improved Assembly dashboard loading speed by removing the large Details table rendering and generating the full Excel export only on request."),
    ("v0.1.27", "Optimized Assembly defect consolidation to avoid slow row-by-row processing and skip merge work when only one defect source is loaded."),
    ("v0.1.26", "Added Assembly defect update consolidation so repeated defect records are merged with latest non-blank fields, plus downloads for the currently displayed detail rows."),
    ("v0.1.25", "Made Assembly trend charts adapt their time scale to the selected period: daily for short ranges, weekly for medium ranges, and monthly for long ranges."),
    ("v0.1.24", "Added an Assembly Quality Dashboard calendar date-range selector and applied the selected period to production and defect analysis."),
    ("v0.1.23", "Repositioned Assembly line-chart legends below the chart area so they do not overlap the Plotly modebar."),
    ("v0.1.22", "Corrected Assembly period detection so production and defect months are read from file data columns instead of file names, with day/month date parsing."),
    ("v0.1.21", "Redesigned the BOM Comparison Tool screen with a guided workflow layout, detected-column cards, cleaner compare action, and compact executive summary metrics."),
    ("v0.1.20", "Invalidated stale BOM Comparison Tool session results after tool updates so uploaded files are recalculated with the latest logic."),
    ("v0.1.19", "Forced the BOM Comparison Tool module to reload inside the portal so Streamlit does not keep stale comparison/rendering code in memory."),
    ("v0.1.18", "Fixed BOM Comparison Tool rendering issues by compacting metric card HTML, updating Styler compatibility, and forcing column selector refresh for uploaded files."),
    ("v0.1.17", "Aligned the BOM Comparison Tool with the latest functional version by always normalizing comma-separated refs in Table 1 and adding the PQC_Check review/export flow."),
    ("v0.1.16", "Improved the BOM Comparison Tool for exported BOM files by resetting automatic column selections and splitting comma-separated refs in Table 1 when detected."),
    ("v0.1.15", "Fixed the BOM Comparison Tool file loading so note/comment rows before the real headers are ignored for both Table 1 and Table 2."),
    ("v0.1.14", "Integrated the SMT BOM Comparison Tool into the portal, preserving its comparison logic and adapting the interface to the Jovi corporate layout."),
    ("v0.1.13", "Added the first Jovi smartphone SMT knowledge structure to Learning Area with fundamentals, defects, troubleshooting, procedures, process map, and KPI learning content."),
    ("v0.1.12", "Added generated home module images for Learning Area, SMT, Assembly, and IQC."),
    ("v0.1.11", "Fixed the topbar clipping and kept only the version visible in the top-right corner."),
    ("v0.1.10", "Compacted the Home layout so the hero, module cards, and footer fit on a standard desktop viewport without scrolling."),
    ("v0.1.9", "Changed the sidebar to a collapsible module menu so sub-items stay hidden until the module is expanded."),
    ("v0.1.8", "Adjusted Home module card height and Enter button spacing to prevent clipped button text."),
    ("v0.1.7", "Added a local Assembly data store, monitored folder import, duplicate file protection, and stored-data analysis mode."),
    ("v0.1.6", "Integrated the SKD Quality Dashboard into Assembly with Jan-Jun/2026 real data, Rejudge OK logic, confirmed PPM, ManDo, rankings, rules, upload, and export."),
    ("v0.1.5", "Optimized screen transitions by removing heavy startup imports and replacing demo charts with lightweight visual components."),
    ("v0.1.4", "Improved the sidebar by removing broken icons/text, standardizing contrast, and stabilizing visual navigation."),
    ("v0.1.3", "Removed duplicated version text above the Home title and adjusted sidebar rendering."),
    ("v0.1.2", "Improved sidebar text visibility and contrast."),
    ("v0.1.1", "Added About page, required credits, visible version, fixed corporate light theme, and standard sidebar pattern."),
    ("v0.1.0", "Created the initial portal structure with Learning Area, SMT, Assembly, and IQC modules."),
]


def apply_global_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy: #061B36;
            --navy-2: #08284F;
            --blue: #1D5FBF;
            --blue-2: #2F80ED;
            --text: #0B1F3A;
            --muted: #17243A;
            --border: #D9E1EF;
            --card: #FFFFFF;
            --bg: #F4F7FB;
        }

        html, body, [class*="css"] {
            font-family: "Segoe UI", Arial, sans-serif !important;
        }

        .stApp {
            background: var(--bg) !important;
            color: var(--text) !important;
        }

        [data-testid="stMainBlockContainer"] {
            padding-top: 3.25rem !important;
            padding-bottom: 0.8rem !important;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, var(--navy) 0%, #04162D 100%) !important;
            border-right: 1px solid rgba(255,255,255,0.10);
        }

        section[data-testid="stSidebar"] > div {
            background: transparent !important;
            padding: 1.15rem 0.85rem 1rem 0.85rem !important;
        }

        section[data-testid="stSidebar"] * {
            color: #FFFFFF !important;
        }

        .sidebar-logo {
            padding: 0.25rem 0.2rem 0.95rem 0.2rem;
            border-bottom: 1px solid rgba(255,255,255,0.16);
            margin-bottom: 0.75rem;
        }
        .sidebar-logo .jovi {
            font-size: 1.8rem;
            line-height: 1;
            font-weight: 900;
            letter-spacing: 0.05em;
            color: #FFFFFF !important;
        }
        .sidebar-logo .subtitle {
            font-size: 0.67rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            margin-top: 0.45rem;
            color: #FFFFFF !important;
        }

        .sidebar-nav {
            display: flex;
            flex-direction: column;
            gap: 0.16rem;
        }
        .sidebar-nav a {
            color: #FFFFFF !important;
            text-decoration: none !important;
        }
        .nav-group {
            margin: 0.02rem 0;
        }
        .nav-group summary {
            list-style: none;
        }
        .nav-group summary::-webkit-details-marker {
            display: none;
        }
        .nav-item,
        .sub-item {
            border: 1px solid transparent;
            box-sizing: border-box;
            color: #F8FBFF !important;
            transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
        }
        .nav-item {
            min-height: 42px;
            display: flex;
            align-items: center;
            padding: 0.45rem 0.85rem;
            margin: 0.02rem 0;
            border-radius: 0.45rem;
            font-size: 0.86rem;
            font-weight: 800;
            line-height: 1.2;
        }
        .nav-summary {
            cursor: pointer;
            justify-content: space-between;
            gap: 0.7rem;
            user-select: none;
        }
        .nav-summary::after {
            content: "›";
            color: #EAF3FF;
            font-size: 1.15rem;
            font-weight: 900;
            line-height: 1;
            transition: transform 140ms ease;
        }
        .nav-summary:focus {
            outline: none;
            border-color: rgba(96, 165, 250, 0.72);
            box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.24);
        }
        .nav-group[open] .nav-summary::after {
            transform: rotate(90deg);
        }
        .nav-item:hover {
            background: rgba(66, 153, 225, 0.20);
            border-color: rgba(255,255,255,0.14);
        }
        .nav-item.active {
            background: linear-gradient(135deg, var(--blue), var(--blue-2));
            border-color: rgba(147,197,253,0.70);
            box-shadow: 0 8px 18px rgba(29,95,191,0.32);
        }
        .sub-nav {
            border-left: 1px solid rgba(255,255,255,0.16);
            display: flex;
            flex-direction: column;
            gap: 0.12rem;
            margin: 0.12rem 0 0.48rem 0.74rem;
            padding-left: 0.56rem;
        }
        .sub-item {
            border-radius: 0.35rem;
            min-height: 34px;
            display: flex;
            align-items: center;
            padding: 0.34rem 0.62rem;
            font-size: 0.78rem;
            font-weight: 800;
            line-height: 1.18;
            color: #DDEBFF !important;
        }
        .sub-item:hover {
            background: rgba(66, 153, 225, 0.18);
            color: #FFFFFF !important;
        }
        .sub-item.active {
            background: rgba(47, 128, 237, 0.34);
            border-color: rgba(96, 165, 250, 0.52);
            color: #FFFFFF !important;
        }
        .sidebar-spacer { height: 1rem; }
        .sidebar-bottom {
            margin-top: 0.95rem;
            padding: 0.85rem 0.2rem 0.1rem 0.2rem;
            border-top: 1px solid rgba(255,255,255,0.16);
            font-size: 0.75rem;
            font-weight: 800;
            color: #EAF3FF !important;
        }

        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            min-height: 48px;
            padding: 0.62rem 0.95rem;
            margin-bottom: 0.65rem;
            box-shadow: 0 4px 18px rgba(16, 24, 40, 0.06);
            box-sizing: border-box;
            overflow: visible;
        }
        .topbar .brand {
            font-weight: 900;
            color: var(--blue);
            letter-spacing: 0.04em;
        }
        .topbar .title {
            color: #071F41;
            font-size: 0.94rem;
            font-weight: 900;
            line-height: 1.25;
            min-width: 0;
        }
        .topbar .meta {
            color: var(--muted);
            font-size: 0.86rem;
            font-weight: 900;
            line-height: 1.2;
            white-space: nowrap;
        }

        .hero {
            text-align: center;
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 0.85rem;
            padding: 0.95rem 1rem;
            box-shadow: 0 4px 18px rgba(16, 24, 40, 0.06);
        }
        .hero h1 {
            color: #071F41;
            margin: 0.15rem 0 0.2rem 0;
            font-size: 1.95rem;
            font-weight: 900;
            letter-spacing: -0.02em;
        }
        .hero h3 {
            color: var(--blue);
            margin: 0.35rem 0 0.2rem 0;
            font-weight: 900;
            font-size: 1.45rem;
        }
        .hero p { color: var(--muted); font-size: 0.96rem; margin: 0.35rem 0 0.1rem 0; }

        .card {
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            padding: 0.9rem;
            box-shadow: 0 4px 18px rgba(16, 24, 40, 0.06);
            min-height: 145px;
        }
        .module-card {
            text-align: center;
            box-sizing: border-box;
            height: 246px;
            min-height: 246px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.55rem;
            overflow: visible;
        }
        .home-module-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.85rem;
            margin-top: 0.65rem;
        }
        .module-icon {
            width: 62px;
            height: 62px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 0.45rem auto;
            font-size: 1.65rem;
            font-weight: 900;
        }
        .module-image-wrap {
            width: 76px;
            height: 76px;
            border: 1px solid rgba(11, 31, 58, 0.08);
            border-radius: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 0.42rem auto;
            overflow: hidden;
            box-shadow: 0 8px 18px rgba(15, 35, 65, 0.10);
        }
        .module-image {
            width: 100%;
            height: 100%;
            display: block;
            object-fit: cover;
        }
        .module-card h3,
        .module-title {
            margin: 0.35rem 0;
            color: #071F41;
            line-height: 1.2;
            font-size: 1.28rem;
            font-weight: 900;
        }
        .module-card p,
        .module-desc {
            color: var(--muted);
            font-size: 0.81rem;
            line-height: 1.32;
            min-height: 58px;
            margin: 0.35rem 0 0 0;
        }
        .fake-btn {
            color: #FFFFFF !important;
            border-radius: 0.45rem;
            box-sizing: border-box;
            min-height: 36px;
            padding: 0 1.2rem;
            font-weight: 800;
            font-size: 0.84rem;
            line-height: 1.2;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            align-self: center;
            flex-shrink: 0;
            margin-top: 0.18rem;
            box-shadow: 0 8px 16px rgba(16, 24, 40, 0.12);
            text-decoration: none !important;
            cursor: pointer;
        }
        a.fake-btn,
        a.fake-btn:link,
        a.fake-btn:active,
        .fake-btn:visited {
            color: #FFFFFF !important;
            text-decoration: none !important;
            background: linear-gradient(135deg, var(--btn-color), #071F41) !important;
            border: 1px solid rgba(255,255,255,0.16);
        }
        .fake-btn:hover {
            color: #FFFFFF !important;
            filter: brightness(1.06);
        }
        @media (max-width: 1200px) {
            .module-card {
                height: auto;
                min-height: 246px;
            }
        }
        @media (max-width: 640px) {
            .home-module-grid {
                grid-template-columns: 1fr;
            }
            .module-card {
                min-height: 238px;
            }
        }
        .section-title {
            color: #071F41;
            font-weight: 900;
            margin: 0.4rem 0 0.9rem 0;
        }
        .learning-hero {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 1rem 1.1rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            margin-bottom: 0.9rem;
        }
        .learning-hero h3 {
            color: #0B1F3A;
            margin: 0 0 0.35rem 0;
            font-size: 1.05rem;
        }
        .learning-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 0.9rem;
            margin-top: 0.8rem;
        }
        .learning-card {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 0.95rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
        }
        .learning-card h4 {
            color: #0B1F3A;
            margin: 0 0 0.45rem 0;
            font-size: 0.98rem;
            line-height: 1.2;
        }
        .learning-card p,
        .learning-card li {
            color: #17243A;
            font-size: 0.84rem;
            line-height: 1.42;
        }
        .learning-card ul {
            margin: 0.45rem 0 0 1rem;
            padding: 0;
        }
        .topic-pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-top: 0.6rem;
        }
        .topic-pill {
            background: #EAF0F8;
            border: 1px solid #C8D3E3;
            border-radius: 999px;
            color: #0B1F3A;
            font-size: 0.72rem;
            font-weight: 900;
            padding: 0.25rem 0.5rem;
        }
        .process-flow {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.8rem;
            margin-top: 0.8rem;
        }
        .flow-step {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-left: 4px solid #0D7A45;
            border-radius: 0.65rem;
            padding: 0.8rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
        }
        .flow-step .step-no {
            color: #0D7A45;
            font-size: 0.72rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .flow-step h4 {
            color: #0B1F3A;
            margin: 0.25rem 0;
            font-size: 0.95rem;
        }
        .flow-step p {
            color: #17243A;
            font-size: 0.82rem;
            line-height: 1.38;
            margin: 0;
        }
        .metric-card {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 1rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
        }
        .metric-label { color: #0B1F3A; font-size: 0.78rem; font-weight: 900; text-transform: uppercase; }
        .metric-value { color: #061B36; font-size: 1.65rem; font-weight: 900; margin-top: 0.15rem; }
        div[data-testid="stPlotlyChart"] {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 0.7rem 0.75rem 0.55rem 0.75rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            box-sizing: border-box !important;
            overflow: hidden !important;
            width: 100% !important;
        }
        div[data-testid="stPlotlyChart"] > div,
        div[data-testid="stPlotlyChart"] .js-plotly-plot,
        div[data-testid="stPlotlyChart"] .plot-container,
        div[data-testid="stPlotlyChart"] .svg-container {
            max-width: 100% !important;
            overflow: hidden !important;
            box-sizing: border-box !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-container {
            top: 0.45rem !important;
            right: 0.45rem !important;
            max-width: calc(100% - 1rem) !important;
            overflow: visible !important;
            z-index: 5 !important;
        }
        div[data-testid="stPlotlyChart"] .modebar {
            display: block !important;
            max-width: 100% !important;
            overflow: visible !important;
        }
        div[data-testid="stHorizontalBlock"] > div {
            min-width: 0 !important;
        }
        div[data-testid="stDataFrame"] {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 0.25rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            overflow: auto;
        }
        div[data-testid="stDataFrame"] div[role="columnheader"] {
            background: #EAF0F8 !important;
            color: #0B1F3A !important;
            font-weight: 900 !important;
        }
        div[data-testid="stDataFrame"] div[role="columnheader"] * {
            color: #0B1F3A !important;
            font-weight: 900 !important;
        }
        div[data-testid="stDataFrame"] div[role="gridcell"] {
            color: #0B1F3A !important;
        }
        .data-table-wrap {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            margin-top: 0.8rem;
            max-height: 520px;
            overflow: auto;
        }
        .data-table {
            border-collapse: collapse;
            width: 100%;
            min-width: 860px;
            font-size: 0.84rem;
        }
        .data-table th {
            background: #EAF0F8;
            border-bottom: 1px solid #C8D3E3;
            color: #0B1F3A;
            font-weight: 900;
            padding: 0.68rem 0.7rem;
            position: sticky;
            text-align: left;
            top: 0;
            z-index: 2;
        }
        .data-table td {
            border-bottom: 1px solid #E4EAF4;
            color: #0B1F3A;
            padding: 0.62rem 0.7rem;
            vertical-align: top;
        }
        .data-table tr:nth-child(even) td {
            background: #F8FAFD;
        }
        .data-table td.numeric {
            font-variant-numeric: tabular-nums;
            text-align: right;
        }
        .stTabs [data-baseweb="tab-list"] {
            background: #FFFFFF;
            border: 1px solid #D2DCEB;
            border-radius: 0.75rem;
            padding: 0.35rem;
            box-shadow: 0 4px 16px rgba(15, 35, 65, 0.05);
        }
        .stTabs [data-baseweb="tab"] {
            color: #0B1F3A;
            font-weight: 900;
        }
        .stTabs [aria-selected="true"] {
            background: #EEF4FF;
            border-radius: 0.55rem;
            color: #1D5FBF !important;
        }
        .chart-card {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 1rem 1.1rem 1.15rem 1.1rem;
            margin-top: 1rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            min-height: 340px;
        }
        .chart-card h3 {
            color: #071F41;
            margin: 0 0 0.85rem 0;
        }
        .trend-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 1rem;
            align-items: end;
            min-height: 220px;
            padding: 1rem;
            background: #F8FAFD;
            border: 1px solid #E7EDF6;
            border-radius: 0.65rem;
        }
        .trend-column {
            display: flex;
            min-width: 0;
            flex-direction: column;
            justify-content: flex-end;
            gap: 0.55rem;
            height: 100%;
        }
        .trend-bar {
            border-radius: 0.45rem 0.45rem 0.18rem 0.18rem;
            min-height: 34px;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.24);
        }
        .trend-label {
            color: var(--muted);
            font-size: 0.78rem;
            font-weight: 800;
            text-align: center;
        }
        .defect-bars {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            padding: 0.9rem;
            background: #F8FAFD;
            border: 1px solid #E7EDF6;
            border-radius: 0.65rem;
        }
        .defect-row {
            display: grid;
            grid-template-columns: minmax(120px, 190px) 1fr 42px;
            gap: 0.8rem;
            align-items: center;
        }
        .defect-name {
            color: #0B1F3A;
            font-size: 0.84rem;
            font-weight: 800;
        }
        .defect-track {
            height: 15px;
            overflow: hidden;
            border-radius: 999px;
            background: #E4EAF4;
        }
        .defect-fill {
            height: 100%;
            border-radius: 999px;
        }
        .defect-value {
            color: var(--muted);
            font-size: 0.82rem;
            font-weight: 900;
            text-align: right;
        }
        .footer {
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            padding: 0.85rem 1rem;
            margin-top: 1.2rem;
            color: var(--muted);
            font-size: 0.84rem;
            text-align: center;
        }
        .home-footer {
            padding: 0.42rem 0.75rem;
            margin-top: 0.55rem;
            border-radius: 0.55rem;
            font-size: 0.72rem;
            line-height: 1.25;
        }
        .small-muted { color: #17243A; font-size: 0.85rem; font-weight: 650; }
        hr { border-color: var(--border) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "module" not in st.session_state:
        st.session_state.module = "Home"
    if "tab" not in st.session_state:
        st.session_state.tab = ""


def get_query_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def sync_navigation_from_query() -> None:
    module = get_query_value("module", st.session_state.module)
    if module not in MODULES:
        module = "Home"

    tabs = MODULES[module]["tabs"]
    tab = get_query_value("tab", st.session_state.tab)
    if tabs and tab not in tabs:
        tab = tabs[0]
    if not tabs:
        tab = ""

    st.session_state.module = module
    st.session_state.tab = tab


def nav_href(module: str, tab: str = "") -> str:
    href = f"?module={quote(module)}"
    if tab:
        href += f"&tab={quote(tab)}"
    return href


def nav_link(label: str, href: str, classes: str) -> str:
    return f'<a href="{href}" target="_self"><div class="{classes}">{escape(label)}</div></a>'


def sidebar() -> None:
    with st.sidebar:
        menu_html = [
            """
            <div class="sidebar-logo">
                <div class="jovi">JOVI</div>
                <div class="subtitle">QUALITY PORTAL</div>
            </div>
            <nav class="sidebar-nav">
            """,
        ]

        for module, cfg in MODULES.items():
            is_active_module = st.session_state.module == module
            first_tab = cfg["tabs"][0] if cfg["tabs"] else ""
            item_class = "nav-item active" if is_active_module else "nav-item"

            if cfg["tabs"]:
                open_attr = " open" if is_active_module else ""
                summary_class = f"{item_class} nav-summary"
                menu_html.append(f'<details class="nav-group"{open_attr}>')
                menu_html.append(f'<summary class="{summary_class}">{escape(module)}</summary>')
                menu_html.append("<div class='sub-nav'>")
                for tab in cfg["tabs"]:
                    is_active_tab = is_active_module and st.session_state.tab == tab
                    sub_class = "sub-item active" if is_active_tab else "sub-item"
                    menu_html.append(nav_link(tab, nav_href(module, tab), sub_class))
                menu_html.append("</div>")
                menu_html.append("</details>")
            else:
                menu_html.append(nav_link(module, nav_href(module, first_tab), item_class))

        menu_html.append(
            f"""
            </nav>
            <div class="sidebar-bottom">
                <div>{APP_VERSION}</div>
                <div style="margin-top:0.8rem;">⌾&nbsp;&nbsp;Logout</div>
            </div>
            """
        )
        st.markdown("".join(menu_html), unsafe_allow_html=True)


def topbar() -> None:
    st.markdown(
        f"""
        <div class="topbar">
            <div class="title"><span class="brand">JOVI</span>&nbsp;&nbsp;QUALITY PORTAL</div>
            <div class="meta">{APP_VERSION}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer() -> None:
    footer_class = "footer home-footer" if st.session_state.get("module") == "Home" else "footer"
    st.markdown(
        f"""
        <div class="{footer_class}">
            <b>Jovi Quality Portal {APP_VERSION}</b><br>
            Developed by: {DEVELOPER} &nbsp; | &nbsp; Role: {ROLE} &nbsp; | &nbsp; Manager: {MANAGER}
        </div>
        """,
        unsafe_allow_html=True,
    )


def module_card(title: str, desc: str, color: str, icon: str, href: str) -> None:
    st.markdown(
        f"""
        <div class="card module-card">
            <div>
                <div class="module-icon" style="background:{color}18;color:{color};">{icon}</div>
                <h3>{title}</h3>
                <p>{desc}</p>
            </div>
            <a class="fake-btn" href="{href}" target="_self" style="--btn-color:{color};">Enter</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def asset_data_uri(path_text: str) -> str:
    path = Path(path_text)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def module_card_html(title: str, desc: str, color: str, icon: str, href: str) -> str:
    image_name = HOME_MODULE_IMAGES.get(title, "")
    image_path = HOME_ASSET_DIR / image_name if image_name else None
    if image_path and image_path.exists():
        media = (
            f'<div class="module-image-wrap" style="background:{color}10;border-color:{color}33;">'
            f'<img class="module-image" src="{asset_data_uri(str(image_path))}" alt="{escape(title)} module image" />'
            f'</div>'
        )
    else:
        media = f'<div class="module-icon" style="background:{color}18;color:{color};">{escape(icon)}</div>'

    return (
        f'<div class="card module-card">'
        f'<div>'
        f'{media}'
        f'<div class="module-title">{escape(title)}</div>'
        f'<div class="module-desc">{escape(desc)}</div>'
        f'</div>'
        f'<a class="fake-btn" href="{escape(href)}" target="_self" style="--btn-color:{color};">Enter</a>'
        f'</div>'
    )


def trend_chart(color: str) -> None:
    points = [("W1", "97,8%", 64), ("W2", "98,2%", 74), ("W3", "97,6%", 58), ("W4", "98,8%", 88), ("W5", "98,3%", 78)]
    columns = "".join(
        f"""
        <div class="trend-column">
            <div class="small-muted" style="text-align:center;font-weight:900;">{value}</div>
            <div class="trend-bar" style="height:{height}%;background:linear-gradient(180deg,{color},#0B1F3A);"></div>
            <div class="trend-label">{week}</div>
        </div>
        """
        for week, value, height in points
    )
    st.markdown(
        f"""
        <div class="chart-card">
            <h3>FPY Trend</h3>
            <div class="trend-grid">{columns}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def defect_chart(color: str) -> None:
    defects = [
        ("Solder Bridge", 35),
        ("Missing Part", 25),
        ("Wrong Assembly", 20),
        ("Scratches", 12),
        ("Others", 8),
    ]
    max_qty = max(qty for _, qty in defects)
    rows = "".join(
        f"""
        <div class="defect-row">
            <div class="defect-name">{escape(name)}</div>
            <div class="defect-track">
                <div class="defect-fill" style="width:{qty / max_qty * 100:.0f}%;background:linear-gradient(90deg,{color},#2F80ED);"></div>
            </div>
            <div class="defect-value">{qty}</div>
        </div>
        """
        for name, qty in defects
    )
    st.markdown(
        f"""
        <div class="chart-card">
            <h3>Top Defects</h3>
            <div class="defect-bars">{rows}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


DEFAULT_RULES = {
    "defect_sheet": "QueryData",
    "date_column": "TestTime",
    "model_column": "model",
    "line_column": "TestLine",
    "phenomenon_column": "Fault Phenomenon",
    "rejudge_column": "Maintenance",
    "additional_rejudge_columns": ["Fault reason", "RepaireRemark"],
    "rejudge_ok_keywords": ["Re-Judge Ok", "Rejudge OK", "Re-Judge OK", "rejudge ok", "Good machine rejudge ok"],
    "mando_column": "DutyType",
    "mando_keywords": ["ManDo", "Mando", "Man Do", "Man-do", "Man_Do"],
    "defect_merge_key_columns": ["PCB", "Barcode", "TestTime", "TestOperation", "Fault Phenomenon"],
    "minimum_model_input_for_priority": 100,
    "date_start": "2026-01-01",
    "date_end": "2026-12-31",
}

MONTH_LABELS = {
    1: "Jan/2026",
    2: "Feb/2026",
    3: "Mar/2026",
    4: "Apr/2026",
    5: "May/2026",
    6: "Jun/2026",
    7: "Jul/2026",
    8: "Aug/2026",
    9: "Sep/2026",
    10: "Oct/2026",
    11: "Nov/2026",
    12: "Dec/2026",
}


def load_rules() -> dict:
    if not RULES_PATH.exists():
        return DEFAULT_RULES.copy()
    try:
        loaded = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_RULES.copy()
    return {**DEFAULT_RULES, **loaded}


def save_rules(rules: dict) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


def compact_text(value: object) -> str:
    return re.sub(r"[\s\-_]+", "", str(value).strip().lower())


def keyword_mask(series, keywords: list[str]):
    compact_keywords = [compact_text(keyword) for keyword in keywords if str(keyword).strip()]
    normalized = series.fillna("").astype(str).map(compact_text)
    if not compact_keywords:
        return normalized == "__no_keyword__"
    pattern = "|".join(re.escape(keyword) for keyword in compact_keywords)
    return normalized.str.contains(pattern, regex=True, na=False)


def parse_number_series(series):
    import pandas as pd

    cleaned = series.fillna("0").astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def is_blank_value(value: object) -> bool:
    import pandas as pd

    if pd.isna(value):
        return True
    return str(value).strip().lower() in {"", "nan", "none", "null", "nat"}


def parse_date_series(series):
    import pandas as pd

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    text_values = series.astype(str).str.strip()
    year_first_mask = text_values.str.match(r"^\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}", na=False)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if year_first_mask.any():
        try:
            parsed.loc[year_first_mask] = pd.to_datetime(
                series.loc[year_first_mask],
                errors="coerce",
                yearfirst=True,
                dayfirst=False,
                format="mixed",
            )
        except TypeError:
            parsed.loc[year_first_mask] = pd.to_datetime(
                series.loc[year_first_mask],
                errors="coerce",
                yearfirst=True,
                dayfirst=False,
            )
    remaining_mask = ~year_first_mask
    if remaining_mask.any():
        try:
            parsed.loc[remaining_mask] = pd.to_datetime(
                series.loc[remaining_mask],
                errors="coerce",
                dayfirst=True,
                format="mixed",
            )
        except TypeError:
            parsed.loc[remaining_mask] = pd.to_datetime(series.loc[remaining_mask], errors="coerce", dayfirst=True)
    numeric = pd.to_numeric(series, errors="coerce")
    serial_mask = numeric.between(20_000, 60_000)
    if serial_mask.any():
        serial_dates = pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce")
        parsed = parsed.copy()
        parsed.loc[serial_mask & serial_dates.notna()] = serial_dates.loc[serial_mask & serial_dates.notna()]
    return parsed


def coerce_timestamp(value, fallback: str):
    import pandas as pd

    parsed = parse_date_series(pd.Series([value])).iloc[0]
    if pd.isna(parsed):
        parsed = pd.Timestamp(fallback)
    return pd.Timestamp(parsed)


def analysis_period_bounds(rules: dict):
    import pandas as pd

    start = coerce_timestamp(rules.get("date_start", "2026-01-01"), "2026-01-01").normalize()
    end = coerce_timestamp(rules.get("date_end", "2026-12-31"), "2026-12-31").normalize()
    if end < start:
        start, end = end, start
    end = end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return start, end


def production_input_granularity(production) -> dict:
    import pandas as pd

    if production is None or production.empty:
        return {"grain": "day", "max_span_days": 0, "summarized_rows": 0}

    starts = pd.to_datetime(production["ProductionStart"], errors="coerce").dt.normalize()
    ends = pd.to_datetime(production["ProductionEnd"], errors="coerce").dt.normalize()
    spans = (ends - starts).dt.days.fillna(0).clip(lower=0)
    max_span_days = int(spans.max()) if not spans.empty else 0
    summarized_rows = int(spans.gt(0).sum())
    if max_span_days == 0:
        grain = "day"
    elif max_span_days <= 7:
        grain = "week"
    else:
        grain = "month"
    return {"grain": grain, "max_span_days": max_span_days, "summarized_rows": summarized_rows}


def trend_granularity(start, end, production=None) -> dict:
    days = max(int((end.normalize() - start.normalize()).days) + 1, 1)
    if days <= 31:
        requested_grain = "day"
    elif days <= 180:
        requested_grain = "week"
    else:
        requested_grain = "month"

    input_resolution = production_input_granularity(production)
    grain_order = {"day": 0, "week": 1, "month": 2}
    grain = max((requested_grain, input_resolution["grain"]), key=grain_order.get)
    labels = {
        "day": ("Daily", "by day"),
        "week": ("Weekly", "by week"),
        "month": ("Monthly", "by month"),
    }
    label, title = labels[grain]
    return {
        "grain": grain,
        "label": label,
        "title": title,
        "requested_grain": requested_grain,
        "input_grain": input_resolution["grain"],
        "input_max_span_days": input_resolution["max_span_days"],
        "summarized_input_rows": input_resolution["summarized_rows"],
        "input_resolution_limited": grain_order[grain] > grain_order[requested_grain],
    }


def add_trend_period(df, date_column: str, settings: dict):
    data = df.copy()
    dates = parse_date_series(data[date_column]).dt.normalize()
    grain = settings["grain"]
    if grain == "day":
        data["PeriodDate"] = dates
    elif grain == "week":
        data["PeriodDate"] = dates.dt.to_period("W-SUN").dt.start_time
    else:
        data["PeriodDate"] = dates.dt.to_period("M").dt.to_timestamp()
    return data.dropna(subset=["PeriodDate"])


def format_trend_period(value, grain: str) -> str:
    ts = value if hasattr(value, "strftime") else coerce_timestamp(value, "2026-01-01")
    if grain == "day":
        return ts.strftime("%d/%m")
    if grain == "week":
        return f"Week {ts.strftime('%d/%m')}"
    return MONTH_LABELS.get(ts.month, ts.strftime("%b/%Y"))


def build_skd_trend(production, filtered, start, end) -> tuple:
    import pandas as pd

    settings = trend_granularity(start, end, production)
    grain = settings["grain"]
    production_period = add_trend_period(production, "ProductionStart", settings)
    production_trend = production_period.groupby("PeriodDate", as_index=False).agg(
        Produced=("Produced", "sum"),
        BadMachine=("BadMachine", "sum"),
    )

    defect_period = add_trend_period(filtered, "_Date", settings)
    defect_trend = defect_period.groupby("PeriodDate", as_index=False).agg(
        TotalRecords=("Item", "count"),
        RejudgeOK=("IsRejudgeOK", "sum"),
        ConfirmedDefects=("ConfirmedDefect", "sum"),
        ManDoDefects=("IsManDo", "sum"),
    )

    trend = production_trend.merge(defect_trend, on="PeriodDate", how="outer").fillna(0)
    if trend.empty:
        return trend, settings
    trend = trend.sort_values("PeriodDate")
    trend["Period"] = trend["PeriodDate"].map(lambda value: format_trend_period(value, grain))
    trend["ConfirmedPPM"] = trend["ConfirmedDefects"] / trend["Produced"].replace(0, pd.NA) * 1_000_000
    trend["ManDoPPM"] = trend["ManDoDefects"] / trend["Produced"].replace(0, pd.NA) * 1_000_000
    return trend, settings


def intervals_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a <= end_b and end_a >= start_b


def interval_contains(container_start, container_end, inner_start, inner_end) -> bool:
    return container_start <= inner_start and container_end >= inner_end


def resolve_production_overlaps(production_detail):
    import pandas as pd

    if production_detail.empty:
        empty_stats = {
            "input_rows": 0,
            "active_rows": 0,
            "replaced_rows": 0,
            "conflict_rows": 0,
            "blocked_rows": 0,
        }
        return production_detail.copy(), empty_stats, production_detail.copy()

    audit_rows = []
    active_rows = []
    sort_cols = ["Model", "SourceOrder", "ProductionStart", "ProductionEnd", "SourceFile"]
    sorted_rows = production_detail.sort_values(sort_cols, ascending=[True, True, True, True, True])

    for _model, group in sorted_rows.groupby("Model", sort=False):
        active_for_model = []
        for row_index, row in group.iterrows():
            row_dict = row.to_dict()
            row_dict["_AuditRowId"] = row_index
            overlapping = [
                active
                for active in active_for_model
                if intervals_overlap(row["ProductionStart"], row["ProductionEnd"], active["ProductionStart"], active["ProductionEnd"])
            ]

            if not overlapping:
                row_dict["InputStatus"] = "Active"
                row_dict["InputDecision"] = "Accepted: no overlap."
                active_for_model.append(row_dict)
                audit_rows.append(row_dict.copy())
                continue

            covers_all_overlaps = all(
                interval_contains(row["ProductionStart"], row["ProductionEnd"], active["ProductionStart"], active["ProductionEnd"])
                for active in overlapping
            )
            same_period = all(
                row["ProductionStart"] == active["ProductionStart"] and row["ProductionEnd"] == active["ProductionEnd"]
                for active in overlapping
            )

            if covers_all_overlaps or same_period:
                replaced_ids = {active["_AuditRowId"] for active in overlapping}
                for audit in audit_rows:
                    if audit.get("_AuditRowId") in replaced_ids and audit.get("InputStatus") == "Active":
                        audit["InputStatus"] = "Replaced"
                        audit["InputDecision"] = f"Replaced by newer input file {row['SourceFile']}."
                active_for_model = [active for active in active_for_model if active["_AuditRowId"] not in replaced_ids]
                row_dict["InputStatus"] = "Active"
                row_dict["InputDecision"] = "Accepted: replaces older covered input period."
                active_for_model.append(row_dict)
                audit_rows.append(row_dict.copy())
                continue

            inside_existing = any(
                interval_contains(active["ProductionStart"], active["ProductionEnd"], row["ProductionStart"], row["ProductionEnd"])
                for active in overlapping
            )
            row_dict["InputStatus"] = "Blocked"
            row_dict["InputDecision"] = (
                "Blocked: period is inside an existing active input period."
                if inside_existing
                else "Blocked: partial overlap with an existing active input period."
            )
            audit_rows.append(row_dict.copy())

        active_rows.extend(active_for_model)

    resolved = pd.DataFrame(active_rows) if active_rows else production_detail.head(0).copy()
    audit = pd.DataFrame(audit_rows) if audit_rows else production_detail.head(0).copy()
    if "_AuditRowId" in resolved.columns:
        resolved = resolved.drop(columns=["_AuditRowId"])
    if "_AuditRowId" in audit.columns:
        audit = audit.drop(columns=["_AuditRowId"])
    status_counts = audit["InputStatus"].value_counts().to_dict() if "InputStatus" in audit.columns else {}
    stats = {
        "input_rows": int(len(production_detail)),
        "active_rows": int(status_counts.get("Active", 0)),
        "replaced_rows": int(status_counts.get("Replaced", 0)),
        "conflict_rows": int(status_counts.get("Blocked", 0)),
        "blocked_rows": int(status_counts.get("Blocked", 0)),
    }
    return resolved, stats, audit


def normalize_merge_value(value: object) -> str:
    import pandas as pd

    if is_blank_value(value):
        return ""
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    looks_like_date = bool(
        re.search(r"\d{1,4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,4}", text)
        or re.search(r"\d{1,2}:\d{2}", text)
    )
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if looks_like_date or pd.notna(numeric) and 20_000 <= float(numeric) <= 60_000:
        parsed = parse_date_series(pd.Series([value])).iloc[0]
        if pd.notna(parsed):
            return pd.Timestamp(parsed).strftime("%Y-%m-%d %H:%M:%S")
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def normalize_merge_series(series, column_name: str):
    values = series.fillna("").astype(str).str.strip()
    normalized = values.str.replace(r"\s+", " ", regex=True).str.upper()
    blank_mask = values.str.lower().isin({"", "nan", "none", "null", "nat"})
    normalized = normalized.mask(blank_mask, "")

    compact_name = compact_text(column_name)
    if "date" in compact_name or "time" in compact_name:
        parsed = parse_date_series(series)
        formatted = parsed.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
        normalized = formatted.where(formatted != "", normalized)
    return normalized


def configured_key_group(rules: dict, columns) -> list[str]:
    configured = [column for column in rules.get("defect_merge_key_columns", []) if str(column).strip()]
    return configured if configured and all(column in columns for column in configured) else []


def defect_merge_key_groups(rules: dict, columns) -> list[list[str]]:
    candidates = [
        configured_key_group(rules, columns),
        ["PCB", "Barcode", "TestTime", "TestOperation", "Fault Phenomenon"],
        ["PCB", "TestTime", "TestOperation", "Fault Phenomenon"],
        ["Barcode", "TestTime", "TestOperation", "Fault Phenomenon"],
        ["PCB", "Barcode", "TestTime"],
        ["PCB", "TestTime"],
        ["Barcode", "TestTime"],
        ["SingleCode"],
        ["Item"],
    ]
    groups = []
    for group in candidates:
        if group and all(column in columns for column in group) and group not in groups:
            groups.append(group)
    return groups


def row_merge_key(row, key_groups: list[list[str]]) -> str:
    for group in key_groups:
        values = [normalize_merge_value(row[column]) for column in group]
        if all(values):
            return f"{'+'.join(group)}::{'|'.join(values)}"
    return ""


def build_merge_keys(data, key_groups: list[list[str]]):
    import pandas as pd

    merge_key = pd.Series("", index=data.index, dtype="object")
    applied_label = "-"
    for group in key_groups:
        normalized_parts = [normalize_merge_series(data[column], column) for column in group]
        valid = normalized_parts[0] != ""
        candidate = normalized_parts[0].copy()
        for part in normalized_parts[1:]:
            valid &= part != ""
            candidate = candidate.str.cat(part, sep="|")
        fill_mask = (merge_key == "") & valid
        if fill_mask.any():
            merge_key.loc[fill_mask] = f"{'+'.join(group)}::" + candidate.loc[fill_mask]
            if applied_label == "-":
                applied_label = " + ".join(group)
    return merge_key, applied_label


def merge_defect_group(group):
    merged = group.iloc[0].copy()
    internal_cols = {"MergeKey", "MergedUpdates", "SourceFiles"}
    for _, row in group.iloc[1:].iterrows():
        for column in group.columns:
            if column in internal_cols:
                continue
            if not is_blank_value(row[column]):
                merged[column] = row[column]
    merged["MergedUpdates"] = max(len(group) - 1, 0)
    source_files = [str(value) for value in group.get("SourceFile", []) if not is_blank_value(value)]
    merged["SourceFiles"] = " | ".join(dict.fromkeys(source_files))
    return merged


def consolidate_defect_updates(defects, rules: dict):
    import pandas as pd

    if defects.empty:
        return defects.copy(), {"input_rows": 0, "output_rows": 0, "merged_updates": 0, "key_columns": "-"}
    data = defects.copy()
    content_cols = [column for column in data.columns if column not in {"SourceFile", "SourceRow"}]
    data = data.drop_duplicates(subset=content_cols, keep="last")
    source_count = data["SourceFile"].nunique() if "SourceFile" in data.columns else 1
    if source_count <= 1:
        data["MergedUpdates"] = 0
        data["SourceFiles"] = data.get("SourceFile", "")
        return data, {"input_rows": len(defects), "output_rows": len(data), "merged_updates": 0, "key_columns": "single source"}
    key_groups = defect_merge_key_groups(rules, data.columns)
    if not key_groups:
        data["MergedUpdates"] = 0
        data["SourceFiles"] = data.get("SourceFile", "")
        return data, {"input_rows": len(data), "output_rows": len(data), "merged_updates": 0, "key_columns": "-"}

    data["MergeKey"], applied_key_label = build_merge_keys(data, key_groups)
    keyed = data[data["MergeKey"] != ""].copy()
    unkeyed = data[data["MergeKey"] == ""].copy()
    if "SourceFile" in keyed.columns:
        source_counts = keyed.groupby("MergeKey", sort=False)["SourceFile"].nunique()
    else:
        source_counts = keyed.groupby("MergeKey", sort=False).size()
    keys_to_merge = source_counts[source_counts > 1].index

    unchanged = keyed[~keyed["MergeKey"].isin(keys_to_merge)].copy()
    if not unchanged.empty:
        unchanged["MergedUpdates"] = 0
        unchanged["SourceFiles"] = unchanged.get("SourceFile", "")

    to_merge = keyed[keyed["MergeKey"].isin(keys_to_merge)].copy()
    if to_merge.empty:
        merged = unchanged
    else:
        value_cols = [column for column in to_merge.columns if column not in {"MergeKey", "MergedUpdates", "SourceFiles"}]
        work = to_merge[["MergeKey", *value_cols]].copy()
        for column in value_cols:
            work[column] = work[column].mask(work[column].map(is_blank_value))
        filled_values = work[value_cols].groupby(work["MergeKey"], sort=False).ffill()
        merged_latest = filled_values.groupby(work["MergeKey"], sort=False).tail(1).copy()
        merged_latest["MergeKey"] = work.loc[merged_latest.index, "MergeKey"].values
        merge_sizes = to_merge.groupby("MergeKey", sort=False).size()
        if "SourceFile" in to_merge.columns:
            source_files = to_merge.groupby("MergeKey", sort=False)["SourceFile"].agg(
                lambda values: " | ".join(dict.fromkeys(str(value) for value in values if not is_blank_value(value)))
            )
        else:
            source_files = pd.Series("", index=merge_sizes.index)
        merged_latest["MergedUpdates"] = merged_latest["MergeKey"].map(merge_sizes.sub(1)).fillna(0).astype(int)
        merged_latest["SourceFiles"] = merged_latest["MergeKey"].map(source_files).fillna("")
        merged = pd.concat([unchanged, merged_latest], ignore_index=True)
    if not unkeyed.empty:
        unkeyed["MergedUpdates"] = 0
        unkeyed["SourceFiles"] = unkeyed.get("SourceFile", "")
        merged = pd.concat([merged, unkeyed], ignore_index=True)

    stats = {
        "input_rows": int(len(data)),
        "output_rows": int(len(merged)),
        "merged_updates": int(len(data) - len(merged)),
        "key_columns": applied_key_label,
    }
    return merged.drop(columns=["MergeKey"], errors="ignore"), stats


def production_date_candidates(columns) -> list[str]:
    preferred = [
        "BeginDate",
        "StartDate",
        "ProductionDate",
        "InputDate",
        "Date",
        "EndDate",
        "BeginTime",
        "StartTime",
    ]
    by_compact = {compact_text(column): column for column in columns}
    candidates = [by_compact[compact_text(column)] for column in preferred if compact_text(column) in by_compact]
    for column in columns:
        normalized = compact_text(column)
        if ("date" in normalized or "time" in normalized) and column not in candidates:
            candidates.append(column)
    return candidates


def infer_production_dates(df, name: str):
    candidates = production_date_candidates(df.columns)
    for column in candidates:
        parsed = parse_date_series(df[column])
        if parsed.notna().any():
            return parsed, column
    expected = ", ".join(["BeginDate", "EndDate", "Date", "ProductionDate"])
    raise RuntimeError(
        f"File {name} needs a valid production date column ({expected}). "
        "The period is read from the file data and is not inferred from the file name."
    )


def infer_production_end_dates(df, start_dates):
    by_compact = {compact_text(column): column for column in df.columns}
    for column in ["EndDate", "FinishDate", "CloseDate", "EndTime", "FinishTime"]:
        match = by_compact.get(compact_text(column))
        if match:
            parsed = parse_date_series(df[match])
            if parsed.notna().any():
                return parsed.fillna(start_dates)
    return start_dates


def normalize_production_period_end(start_dates, end_dates):
    import pandas as pd

    start = pd.to_datetime(start_dates, errors="coerce").dt.normalize()
    end = pd.to_datetime(end_dates, errors="coerce").dt.normalize().fillna(start)
    end = end.where(end >= start, start)
    period_end_is_exclusive = end > start
    return end.where(~period_end_is_exclusive, end - pd.Timedelta(days=1))


def read_csv_flexible(source):
    import pandas as pd

    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            return pd.read_csv(source, sep=None, engine="python", encoding=encoding)
        except UnicodeDecodeError:
            continue
    if hasattr(source, "seek"):
        source.seek(0)
    return pd.read_csv(source, sep=None, engine="python", encoding="latin1")


def read_production_file(source, name: str):
    if isinstance(source, Path):
        stat = source.stat()
        return read_production_file_path_cached(str(source), name, stat.st_size, stat.st_mtime_ns)
    data = read_source_bytes(source)
    return read_production_file_bytes_cached(data, name)


@st.cache_data(show_spinner=False)
def read_production_file_path_cached(path_text: str, name: str, file_size: int, modified_ns: int):
    return read_production_file_uncached(Path(path_text), name)


@st.cache_data(show_spinner=False)
def read_production_file_bytes_cached(data: bytes, name: str):
    source = BytesIO(data)
    source.name = name
    return read_production_file_uncached(source, name)


def read_production_file_uncached(source, name: str):
    import pandas as pd

    source_name = Path(name).name
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        df = read_csv_flexible(source)
    elif suffix in {".xlsx", ".xls"}:
        try:
            df = pd.read_excel(source)
        except ImportError as exc:
            raise RuntimeError("To read legacy .xls uploads, install the xlrd dependency from requirements.txt.") from exc
    else:
        raise RuntimeError(f"Unsupported input format: {suffix}")

    required = {"model", "Input"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"File {name} is missing required columns: {', '.join(sorted(missing))}")

    result = df.copy()
    result["Model"] = result["model"].astype(str).str.strip()
    result["Produced"] = parse_number_series(result["Input"])
    result["BadMachine"] = parse_number_series(result["BadMachine"]) if "BadMachine" in result.columns else 0
    production_dates, _date_column = infer_production_dates(result, name)
    production_dates = production_dates.dt.normalize()
    raw_end_dates = infer_production_end_dates(result, production_dates)
    result["ProductionStart"] = production_dates
    result["ProductionEndRaw"] = raw_end_dates
    result["ProductionEnd"] = normalize_production_period_end(production_dates, raw_end_dates)
    result["MonthNo"] = production_dates.dt.month
    result["Month"] = result["MonthNo"].map(MONTH_LABELS)
    result["SourceFile"] = source_name
    result = result.dropna(subset=["Month"])
    return result[
        [
            "Month",
            "MonthNo",
            "ProductionStart",
            "ProductionEndRaw",
            "ProductionEnd",
            "Model",
            "Produced",
            "BadMachine",
            "SourceFile",
        ]
    ]


def read_defects_file(source, rules: dict):
    source_name = Path(getattr(source, "name", str(source))).name
    if isinstance(source, Path):
        stat = source.stat()
        return read_defects_file_path_cached(str(source), source_name, stat.st_size, stat.st_mtime_ns, rules["defect_sheet"])
    data = read_source_bytes(source)
    return read_defects_file_bytes_cached(data, source_name, rules["defect_sheet"])


@st.cache_data(show_spinner=False)
def read_defects_file_path_cached(path_text: str, source_name: str, file_size: int, modified_ns: int, sheet_name: str):
    return read_defects_file_uncached(Path(path_text), source_name, sheet_name)


@st.cache_data(show_spinner=False)
def read_defects_file_bytes_cached(data: bytes, source_name: str, sheet_name: str):
    source = BytesIO(data)
    source.name = source_name
    return read_defects_file_uncached(source, source_name, sheet_name)


def read_defects_file_uncached(source, source_name: str, sheet_name: str):
    import pandas as pd

    try:
        df = pd.read_excel(source, sheet_name=sheet_name, engine="openpyxl")
    except ValueError:
        df = pd.read_excel(source, sheet_name=0, engine="openpyxl")
    df["SourceFile"] = source_name
    df["SourceRow"] = range(2, len(df) + 2)
    return df


def sample_sources() -> tuple[Path, list[Path]]:
    defect_file = ASSEMBLY_SAMPLE_DIR / "SKD - Defects - Jan to Jun.xlsx"
    input_files = sorted(ASSEMBLY_SAMPLE_DIR.glob("SKD - Input - *.csv"))
    return defect_file, input_files


def init_quality_store() -> None:
    DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assembly_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                modified_at TEXT,
                imported_at TEXT NOT NULL,
                source_method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'imported'
            )
            """
        )


def read_source_bytes(source) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    if hasattr(source, "getvalue"):
        return source.getvalue()

    position = source.tell() if hasattr(source, "tell") else None
    if hasattr(source, "seek"):
        source.seek(0)
    data = source.read()
    if position is not None and hasattr(source, "seek"):
        source.seek(position)
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


def safe_filename(name: str) -> str:
    clean = Path(name).name
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", clean).strip(" ._") or "assembly_file"


def classify_assembly_file(path: Path) -> str | None:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if "defect" in name and suffix in {".xlsx", ".xls"}:
        return "defects"
    if any(keyword in name for keyword in ("input", "production", "produced")) and suffix in {".csv", ".xls", ".xlsx"}:
        return "input"
    return None


def persist_assembly_source(source, data_type: str, source_method: str) -> dict:
    init_quality_store()
    if data_type not in {"defects", "input"}:
        raise RuntimeError(f"Unsupported Assembly data type: {data_type}")

    original_name = safe_filename(getattr(source, "name", str(source)))
    modified_at = ""
    file_size_hint = None
    if isinstance(source, Path):
        stat = source.stat()
        file_size_hint = stat.st_size
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")

    if file_size_hint is not None:
        with sqlite3.connect(QUALITY_DB_PATH) as conn:
            existing_by_meta = conn.execute(
                """
                SELECT original_name, imported_at
                FROM assembly_files
                WHERE original_name = ? AND file_size = ? AND modified_at = ? AND status = 'imported'
                """,
                (original_name, file_size_hint, modified_at),
            ).fetchone()
        if existing_by_meta:
            return {
                "status": "skipped",
                "data_type": data_type,
                "name": original_name,
                "message": f"Already imported as {existing_by_meta[0]} on {existing_by_meta[1]}.",
            }

    data = read_source_bytes(source)
    file_hash = hashlib.sha256(data).hexdigest()
    imported_at = datetime.now().isoformat(timespec="seconds")
    stored_name = f"{data_type}_{file_hash[:12]}_{original_name}"
    stored_dir = ASSEMBLY_FILE_STORE_DIR / data_type
    stored_dir.mkdir(parents=True, exist_ok=True)
    stored_path = stored_dir / stored_name

    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        existing = conn.execute(
            "SELECT original_name, imported_at FROM assembly_files WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        if existing:
            return {
                "status": "skipped",
                "data_type": data_type,
                "name": original_name,
                "message": f"Already imported as {existing[0]} on {existing[1]}.",
            }

        stored_path.write_bytes(data)
        conn.execute(
            """
            INSERT INTO assembly_files (
                data_type, original_name, stored_name, stored_path, file_hash,
                file_size, modified_at, imported_at, source_method, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported')
            """,
            (
                data_type,
                original_name,
                stored_name,
                str(stored_path),
                file_hash,
                len(data),
                modified_at,
                imported_at,
                source_method,
            ),
        )

    return {
        "status": "imported",
        "data_type": data_type,
        "name": original_name,
        "message": "Imported to the local data store.",
    }


def import_assembly_monitored_folder() -> list[dict]:
    ASSEMBLY_MONITORED_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted(ASSEMBLY_MONITORED_DIR.iterdir()):
        if not path.is_file():
            continue
        data_type = classify_assembly_file(path)
        if not data_type:
            results.append(
                {
                    "status": "ignored",
                    "data_type": "-",
                    "name": path.name,
                    "message": "File name does not match Assembly defects/input pattern.",
                }
            )
            continue
        results.append(persist_assembly_source(path, data_type, "monitored folder"))
    return results


def stored_assembly_sources() -> tuple[list[Path], list[Path]]:
    init_quality_store()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT data_type, stored_path
            FROM assembly_files
            WHERE status = 'imported'
            ORDER BY imported_at, id
            """
        ).fetchall()

    defects = []
    inputs = []
    for data_type, stored_path in rows:
        path = Path(stored_path)
        if not path.exists():
            continue
        if data_type == "defects":
            defects.append(path)
        elif data_type == "input":
            inputs.append(path)
    return defects, inputs


def select_defect_sources(defects: list[Path]) -> tuple[list[Path], str]:
    if len(defects) <= 1:
        return defects, "Stored defects file"

    latest = defects[-1]
    previous = defects[:-1]
    try:
        latest_size = latest.stat().st_size
        previous_max_size = max(path.stat().st_size for path in previous)
    except OSError:
        return defects, "All stored defects files"

    if previous_max_size and latest_size >= previous_max_size * 0.75:
        return [latest], f"Latest cumulative defects file: {latest.name}"
    return defects, "All stored defects files"


def assembly_store_status() -> dict:
    init_quality_store()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT data_type, COUNT(*), COALESCE(SUM(file_size), 0)
            FROM assembly_files
            WHERE status = 'imported'
            GROUP BY data_type
            """
        ).fetchall()
        latest = conn.execute(
            """
            SELECT imported_at
            FROM assembly_files
            WHERE status = 'imported'
            ORDER BY imported_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    status = {
        "defects": 0,
        "input": 0,
        "bytes": 0,
        "latest": latest[0] if latest else "-",
        "ready": False,
    }
    for data_type, count, file_size in rows:
        status[data_type] = count
        status["bytes"] += file_size
    status["ready"] = status["defects"] > 0 and status["input"] > 0
    return status


def import_results_table(results: list[dict]) -> None:
    import pandas as pd

    if not results:
        st.info("No files were found in the monitored Assembly folder.")
        return
    view = pd.DataFrame(results)
    view = view.rename(columns={"status": "Status", "data_type": "Type", "name": "File", "message": "Message"})
    styled_table(view[["Status", "Type", "File", "Message"]])


def analyze_skd_quality(defect_source, input_sources: list, rules: dict, source_label: str) -> dict:
    import pandas as pd

    defect_sources = defect_source if isinstance(defect_source, (list, tuple)) else [defect_source]
    defect_frames = [read_defects_file(source, rules) for source in defect_sources]
    if not defect_frames:
        raise RuntimeError("No defects file was provided.")
    defects_raw = pd.concat(defect_frames, ignore_index=True)
    defects, defect_merge_stats = consolidate_defect_updates(defects_raw, rules)
    production_frames = []
    for source_order, item in enumerate(input_sources):
        name = getattr(item, "name", str(item))
        production_frame = read_production_file(item, name).copy()
        production_frame["SourceOrder"] = source_order
        production_frames.append(production_frame)
    if not production_frames:
        raise RuntimeError("No production/input file was provided.")

    start, end = analysis_period_bounds(rules)
    production_detail_all = pd.concat(production_frames, ignore_index=True)
    production_detail_all = production_detail_all[
        production_detail_all["ProductionStart"].notna()
        & production_detail_all["ProductionEnd"].notna()
    ].copy()
    production_detail_all, production_input_stats, production_input_audit = resolve_production_overlaps(production_detail_all)
    production_detail = production_detail_all[
        (production_detail_all["ProductionStart"] >= start)
        & (production_detail_all["ProductionEnd"] <= end)
    ].copy()
    if production_detail.empty:
        raise RuntimeError("No production/input records were found for the selected analysis period.")
    input_audit_in_period = production_input_audit[
        (production_input_audit["ProductionStart"] >= start)
        & (production_input_audit["ProductionEnd"] <= end)
    ].copy() if not production_input_audit.empty else production_input_audit.copy()
    selected_status_counts = (
        input_audit_in_period["InputStatus"].value_counts().to_dict()
        if "InputStatus" in input_audit_in_period.columns
        else {}
    )
    production_input_stats = {
        **production_input_stats,
        "selected_input_rows": int(len(input_audit_in_period)),
        "selected_active_rows": int(selected_status_counts.get("Active", 0)),
        "selected_replaced_rows": int(selected_status_counts.get("Replaced", 0)),
        "selected_blocked_rows": int(selected_status_counts.get("Blocked", 0)),
    }
    production = production_detail.groupby(["Month", "MonthNo", "Model"], as_index=False).agg(
        Produced=("Produced", "sum"),
        BadMachine=("BadMachine", "sum"),
    )

    date_col = rules["date_column"]
    model_col = rules["model_column"]
    line_col = rules["line_column"]
    phenomenon_col = rules["phenomenon_column"]
    mando_col = rules["mando_column"]
    required_cols = [date_col, model_col, line_col, phenomenon_col, rules["rejudge_column"], mando_col]
    missing_cols = [col for col in required_cols if col not in defects.columns]
    if missing_cols:
        raise RuntimeError(f"Defects file is missing required columns: {', '.join(missing_cols)}")

    filtered = defects.copy()
    filtered["_Date"] = parse_date_series(filtered[date_col])
    filtered = filtered[filtered["_Date"].between(start, end)].copy()
    filtered["MonthNo"] = filtered["_Date"].dt.month
    filtered["Month"] = filtered["MonthNo"].map(MONTH_LABELS)
    filtered["Model"] = filtered[model_col].fillna("Unknown").astype(str).str.strip()
    filtered["Line"] = filtered[line_col].fillna("Unknown").astype(str).str.strip()
    filtered["Phenomenon"] = filtered[phenomenon_col].fillna("Unknown").astype(str).str.strip()

    rejudge_columns = [rules["rejudge_column"], *rules.get("additional_rejudge_columns", [])]
    rejudge_text = pd.Series("", index=filtered.index, dtype="object")
    for col in rejudge_columns:
        if col in filtered.columns:
            rejudge_text = rejudge_text + " " + filtered[col].fillna("").astype(str)
    filtered["IsRejudgeOK"] = keyword_mask(rejudge_text, rules["rejudge_ok_keywords"])
    filtered["ConfirmedDefect"] = ~filtered["IsRejudgeOK"]
    filtered["IsManDo"] = filtered["ConfirmedDefect"] & keyword_mask(filtered[mando_col], rules["mando_keywords"])
    trend, trend_settings = build_skd_trend(production_detail, filtered, start, end)

    month_order = sorted(production["MonthNo"].dropna().unique())
    ordered_months = [MONTH_LABELS[int(month)] for month in month_order if int(month) in MONTH_LABELS]

    monthly_defects = filtered.groupby(["Month", "MonthNo"], as_index=False).agg(
        TotalRecords=("Item", "count"),
        RejudgeOK=("IsRejudgeOK", "sum"),
        ConfirmedDefects=("ConfirmedDefect", "sum"),
        ManDoDefects=("IsManDo", "sum"),
    )
    monthly_production = production.groupby(["Month", "MonthNo"], as_index=False).agg(
        Produced=("Produced", "sum"),
        BadMachine=("BadMachine", "sum"),
    )
    monthly = monthly_production.merge(monthly_defects, on=["Month", "MonthNo"], how="left").fillna(0)
    monthly["ConfirmedPPM"] = monthly["ConfirmedDefects"] / monthly["Produced"].replace(0, pd.NA) * 1_000_000
    monthly["ManDoPPM"] = monthly["ManDoDefects"] / monthly["Produced"].replace(0, pd.NA) * 1_000_000
    monthly["StraightRate"] = (monthly["Produced"] - monthly["BadMachine"]) / monthly["Produced"].replace(0, pd.NA)
    monthly = monthly.sort_values("MonthNo")

    confirmed = filtered[filtered["ConfirmedDefect"]].copy()
    model_defects = filtered.groupby("Model", as_index=False).agg(
        TotalRecords=("Item", "count"),
        RejudgeOK=("IsRejudgeOK", "sum"),
        ConfirmedDefects=("ConfirmedDefect", "sum"),
        ManDoDefects=("IsManDo", "sum"),
    )
    model_production = production.groupby("Model", as_index=False).agg(Produced=("Produced", "sum"))
    model_summary = model_production.merge(model_defects, on="Model", how="left").fillna(0)
    model_summary["ConfirmedPPM"] = model_summary["ConfirmedDefects"] / model_summary["Produced"].replace(0, pd.NA) * 1_000_000
    model_summary["ManDoPPM"] = model_summary["ManDoDefects"] / model_summary["Produced"].replace(0, pd.NA) * 1_000_000
    min_input = int(rules.get("minimum_model_input_for_priority", 100))
    model_summary["PriorityEligible"] = model_summary["Produced"] >= min_input
    model_summary["ImpactScore"] = model_summary["ManDoDefects"] * (1 + (model_summary["ManDoPPM"].fillna(0) / 50_000).clip(upper=1))

    model_month = confirmed.groupby(["Month", "MonthNo", "Model"], as_index=False).agg(ConfirmedDefects=("Item", "count"))
    mando_model_month = filtered[filtered["IsManDo"]].groupby(["Month", "MonthNo", "Model"], as_index=False).agg(ManDoDefects=("Item", "count"))
    model_month = production.merge(model_month, on=["Month", "MonthNo", "Model"], how="left").merge(
        mando_model_month, on=["Month", "MonthNo", "Model"], how="left"
    ).fillna(0)
    model_month["ConfirmedPPM"] = model_month["ConfirmedDefects"] / model_month["Produced"].replace(0, pd.NA) * 1_000_000
    model_month["ManDoPPM"] = model_month["ManDoDefects"] / model_month["Produced"].replace(0, pd.NA) * 1_000_000

    line_summary = confirmed.groupby("Line", as_index=False).agg(
        ConfirmedDefects=("Item", "count"),
        ManDoDefects=("IsManDo", "sum"),
    ).sort_values("ConfirmedDefects", ascending=False)
    total_confirmed = max(int(confirmed.shape[0]), 1)
    line_summary["Share"] = line_summary["ConfirmedDefects"] / total_confirmed

    defect_pareto = confirmed.groupby("Phenomenon", as_index=False).agg(ConfirmedDefects=("Item", "count")).sort_values(
        "ConfirmedDefects", ascending=False
    )
    mando_pareto = filtered[filtered["IsManDo"]].groupby("Phenomenon", as_index=False).agg(ManDoDefects=("Item", "count")).sort_values(
        "ManDoDefects", ascending=False
    )

    totals = {
        "source": source_label,
        "produced": int(production["Produced"].sum()),
        "bad_machine": int(production["BadMachine"].sum()),
        "total_records": int(filtered.shape[0]),
        "rejudge_ok": int(filtered["IsRejudgeOK"].sum()),
        "confirmed_defects": int(filtered["ConfirmedDefect"].sum()),
        "mando_defects": int(filtered["IsManDo"].sum()),
    }
    totals["rejudge_rate"] = totals["rejudge_ok"] / totals["total_records"] if totals["total_records"] else 0
    totals["confirmed_ppm"] = totals["confirmed_defects"] / totals["produced"] * 1_000_000 if totals["produced"] else 0
    totals["mando_share"] = totals["mando_defects"] / totals["confirmed_defects"] if totals["confirmed_defects"] else 0
    totals["mando_ppm"] = totals["mando_defects"] / totals["produced"] * 1_000_000 if totals["produced"] else 0
    totals["straight_rate"] = (totals["produced"] - totals["bad_machine"]) / totals["produced"] if totals["produced"] else 0
    totals["worst_ppm_month"] = monthly.sort_values("ConfirmedPPM", ascending=False).iloc[0]["Month"] if not monthly.empty else "-"
    totals["worst_volume_month"] = monthly.sort_values("ConfirmedDefects", ascending=False).iloc[0]["Month"] if not monthly.empty else "-"
    totals["worst_mando_month"] = monthly.sort_values("ManDoPPM", ascending=False).iloc[0]["Month"] if not monthly.empty else "-"
    trend_rank = trend.copy()
    if trend_rank.empty:
        totals["worst_ppm_period"] = "-"
        totals["worst_volume_period"] = "-"
        totals["worst_mando_period"] = "-"
    else:
        trend_rank[["ConfirmedPPM", "ConfirmedDefects", "ManDoPPM"]] = trend_rank[
            ["ConfirmedPPM", "ConfirmedDefects", "ManDoPPM"]
        ].fillna(0)
        totals["worst_ppm_period"] = trend_rank.sort_values("ConfirmedPPM", ascending=False).iloc[0]["Period"]
        totals["worst_volume_period"] = trend_rank.sort_values("ConfirmedDefects", ascending=False).iloc[0]["Period"]
        totals["worst_mando_period"] = trend_rank.sort_values("ManDoPPM", ascending=False).iloc[0]["Period"]

    return {
        "totals": totals,
        "monthly": monthly,
        "trend": trend,
        "trend_settings": trend_settings,
        "production": production,
        "model_summary": model_summary,
        "model_month": model_month,
        "line_summary": line_summary,
        "defect_pareto": defect_pareto,
        "mando_pareto": mando_pareto,
        "raw": filtered,
        "defect_merge_stats": defect_merge_stats,
        "production_input_stats": production_input_stats,
        "production_input_audit": production_input_audit,
        "rules": rules,
        "ordered_months": ordered_months,
    }


def path_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


@st.cache_data(show_spinner=False)
def analyze_skd_quality_paths_cached(
    defect_paths: tuple[str, ...],
    input_paths: tuple[str, ...],
    path_signatures: tuple,
    rules_text: str,
    source_label: str,
) -> dict:
    rules = json.loads(rules_text)
    return analyze_skd_quality([Path(path) for path in defect_paths], [Path(path) for path in input_paths], rules, source_label)


def analyze_skd_quality_cached(defect_source, input_sources: list, rules: dict, source_label: str) -> dict:
    defect_sources = defect_source if isinstance(defect_source, (list, tuple)) else [defect_source]
    if all(isinstance(source, Path) for source in defect_sources) and all(isinstance(source, Path) for source in input_sources):
        defect_paths = tuple(str(source) for source in defect_sources)
        input_paths = tuple(str(source) for source in input_sources)
        signatures = tuple(path_signature(source) for source in [*defect_sources, *input_sources])
        rules_text = json.dumps(rules, sort_keys=True, ensure_ascii=False)
        return analyze_skd_quality_paths_cached(defect_paths, input_paths, signatures, rules_text, source_label)
    return analyze_skd_quality(defect_source, input_sources, rules, source_label)


def fmt_int(value: float) -> str:
    return f"{float(value):,.0f}"


def fmt_ppm(value: float) -> str:
    return f"{float(value):,.0f}"


def fmt_pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def fmt_compact(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 1000:
        return f"{value / 1000:.0f}k"
    return f"{value:.0f}"


def styled_table(df, max_rows: int | None = None) -> None:
    import pandas as pd

    view = df.head(max_rows).copy() if max_rows else df.copy()
    headers = "".join(f"<th>{escape(str(col))}</th>" for col in view.columns)
    body_rows = []
    for _, row in view.iterrows():
        cells = []
        for value in row:
            is_number = isinstance(value, Number) and not isinstance(value, bool)
            if pd.isna(value):
                display = ""
            elif is_number:
                display = f"{float(value):,.0f}" if float(value).is_integer() else f"{float(value):,.2f}"
            else:
                display = str(value)
            class_name = " class='numeric'" if is_number else ""
            cells.append(f"<td{class_name}>{escape(display)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    st.markdown(
        f"""
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr>{headers}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def skd_metric_card(label: str, value: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-value">{escape(value)}</div>
            <div class="small-muted">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def make_skd_export(analysis: dict) -> BytesIO:
    import pandas as pd

    output = BytesIO()
    raw_cols = [
        "Item",
        "PCB",
        "Barcode",
        "SingleCode",
        "TestTime",
        "TestOperation",
        "Month",
        "Model",
        "Line",
        "Phenomenon",
        "DutyType",
        "Maintenance",
        "Fault reason",
        "RepaireRemark",
        "IsRejudgeOK",
        "ConfirmedDefect",
        "IsManDo",
        "MergedUpdates",
        "SourceFile",
        "SourceFiles",
    ]
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        analysis["monthly"].to_excel(writer, index=False, sheet_name="Monthly Summary")
        analysis["trend"].to_excel(writer, index=False, sheet_name="Trend")
        analysis["model_summary"].to_excel(writer, index=False, sheet_name="Model Summary")
        analysis["defect_pareto"].to_excel(writer, index=False, sheet_name="Defect Pareto")
        analysis["monthly"][["Month", "TotalRecords", "RejudgeOK", "ConfirmedDefects"]].to_excel(
            writer, index=False, sheet_name="Rejudge Summary"
        )
        analysis["monthly"][["Month", "Produced", "ManDoDefects", "ManDoPPM"]].to_excel(
            writer, index=False, sheet_name="ManDo Monthly"
        )
        analysis["model_summary"][["Model", "Produced", "ManDoDefects", "ManDoPPM", "ImpactScore"]].to_excel(
            writer, index=False, sheet_name="ManDo Model"
        )
        analysis["mando_pareto"].to_excel(writer, index=False, sheet_name="ManDo Defects")
        analysis["raw"][[col for col in raw_cols if col in analysis["raw"].columns]].to_excel(
            writer, index=False, sheet_name="Raw Filtered Data"
        )
        pd.DataFrame([analysis.get("defect_merge_stats", {})]).to_excel(
            writer, index=False, sheet_name="Consolidation"
        )
        pd.DataFrame([analysis.get("production_input_stats", {})]).to_excel(
            writer, index=False, sheet_name="Input Consolidation"
        )
        analysis.get("production_input_audit", pd.DataFrame()).to_excel(
            writer, index=False, sheet_name="Input Period Audit"
        )
    output.seek(0)
    return output


def make_table_export(df, sheet_name: str = "Displayed Data") -> BytesIO:
    import pandas as pd

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    output.seek(0)
    return output


PLOTLY_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"scale": 2},
}


def show_chart(fig) -> None:
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def skd_line_chart(df, x_col: str, y_cols: list[str], title: str, color: str):
    import plotly.graph_objects as go

    fig = go.Figure()
    palette = [color, "#0B1F3A", "#B45309", "#1D5FBF"]
    for idx, y_col in enumerate(y_cols):
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines+markers+text",
                name=y_col,
                line=dict(width=3, color=palette[idx % len(palette)]),
                text=[fmt_compact(value) for value in df[y_col]],
                textposition="top center" if idx == 0 else "bottom center",
                textfont=dict(size=11, color=palette[idx % len(palette)]),
            )
        )
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left"),
        template="plotly_white",
        height=370,
        autosize=True,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=dict(l=20, r=20, t=55, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5),
    )
    fig.update_xaxes(showgrid=False, linecolor="#C8D3E3", tickfont=dict(color="#17243A"))
    fig.update_yaxes(gridcolor="#DDE5F0", linecolor="#C8D3E3", tickfont=dict(color="#17243A"))
    return fig


def skd_bar_chart(df, x_col: str, y_col: str, title: str, color: str, orientation: str = "v"):
    import plotly.express as px

    if orientation == "h":
        fig = px.bar(df, x=y_col, y=x_col, orientation="h", title=title, color_discrete_sequence=[color])
        fig.update_layout(yaxis=dict(autorange="reversed"))
        fig.update_traces(
            text=[fmt_compact(value) for value in df[y_col]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11, color="#0B1F3A"),
        )
    else:
        fig = px.bar(df, x=x_col, y=y_col, title=title, color_discrete_sequence=[color])
        fig.update_traces(
            text=[fmt_compact(value) for value in df[y_col]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11, color="#0B1F3A"),
        )
    fig.update_layout(
        template="plotly_white",
        height=360,
        autosize=True,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=dict(l=20, r=42, t=55, b=28),
        showlegend=False,
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    fig.update_xaxes(gridcolor="#DDE5F0", linecolor="#C8D3E3", tickfont=dict(color="#17243A"), automargin=True)
    fig.update_yaxes(gridcolor="#DDE5F0", linecolor="#C8D3E3", tickfont=dict(color="#17243A"), automargin=True)
    return fig


def skd_rejudge_rate_chart(rejudge_ok: int, confirmed_defects: int):
    import plotly.graph_objects as go

    total = max(rejudge_ok + confirmed_defects, 1)
    values = [rejudge_ok / total * 100, confirmed_defects / total * 100]
    counts = [rejudge_ok, confirmed_defects]
    labels = ["Rejudge OK", "Confirmed defects"]
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker=dict(color=["#1D5FBF", "#6532C8"], line=dict(color="#0B1F3A", width=0.5)),
                text=[f"{value:.1f}% · {fmt_int(count)}" for value, count in zip(values, counts)],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color="#FFFFFF", size=13),
                hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        template="plotly_white",
        height=340,
        autosize=True,
        title="Rejudge OK Rate",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=dict(l=45, r=20, t=55, b=55),
        showlegend=False,
        xaxis_title="",
        yaxis_title="% of total records",
    )
    fig.update_xaxes(showgrid=False, linecolor="#C8D3E3", tickfont=dict(color="#0B1F3A"))
    fig.update_yaxes(range=[0, 100], gridcolor="#DDE5F0", linecolor="#C8D3E3", ticksuffix="%", tickfont=dict(color="#17243A"))
    return fig


def assembly_period_selector(rules: dict, color: str) -> dict:
    start_default = coerce_timestamp(rules.get("date_start", "2026-01-01"), "2026-01-01").date()
    end_default = coerce_timestamp(rules.get("date_end", "2026-12-31"), "2026-12-31").date()
    today = date.today()
    if start_default <= today < end_default:
        end_default = today
    if end_default < start_default:
        start_default, end_default = end_default, start_default

    st.markdown(
        f"""
        <div class="card" style="min-height:auto;border-left:4px solid {color};margin-bottom:0.55rem;">
            <h3 style="margin:0 0 0.25rem 0;color:#0B1F3A;">Analysis period</h3>
            <p class="small-muted" style="margin:0;">Choose the start and end dates used by all Assembly dashboard charts, tables, and PPM calculations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    control_col, note_col = st.columns([1.05, 1.95])
    with control_col:
        selected_period = st.date_input(
            "Date range",
            value=(start_default, end_default),
            format="DD/MM/YYYY",
            key="assembly_analysis_period",
        )

    if isinstance(selected_period, (tuple, list)):
        if len(selected_period) >= 2:
            start_date, end_date = selected_period[0], selected_period[1]
        elif len(selected_period) == 1:
            start_date = end_date = selected_period[0]
        else:
            start_date, end_date = start_default, end_default
    else:
        start_date = end_date = selected_period

    if not isinstance(start_date, date) or not isinstance(end_date, date):
        start_date, end_date = start_default, end_default
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    with note_col:
        st.caption(
            f"Active filter: {start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}. "
            "The period is read from file data columns, not from file names."
        )

    active_rules = rules.copy()
    active_rules["date_start"] = start_date.isoformat()
    active_rules["date_end"] = end_date.isoformat()
    return active_rules


def assembly_quality_dashboard(color: str) -> None:
    stored_rules = load_rules()
    if not st.session_state.get("assembly_auto_import_checked", False):
        auto_import_results = import_assembly_monitored_folder()
        st.session_state["assembly_auto_import_checked"] = True
    else:
        auto_import_results = []
    if any(result["status"] == "imported" for result in auto_import_results):
        st.session_state["assembly_last_import_results"] = auto_import_results
    store_status = assembly_store_status()
    st.markdown(f"<h1 class='section-title' style='color:{color};'>Assembly · SKD Quality Dashboard</h1>", unsafe_allow_html=True)

    rules = assembly_period_selector(stored_rules, color)

    dashboard_sections = [
        "Overview",
        "Upload Data",
        "ManDo Analysis",
        "Models",
        "Lines",
        "Defects / Pareto",
        "Rules",
        "Details",
        "Export",
        "About",
    ]
    active_section = st.radio(
        "Assembly dashboard section",
        dashboard_sections,
        horizontal=True,
        label_visibility="collapsed",
        key="assembly_dashboard_section",
    )
    use_local_store = store_status["ready"]
    uploaded_defects = None
    uploaded_inputs = []

    if active_section == "Upload Data":
        st.markdown("### Upload Data")
        st.caption("Use the same SKD file formats: one defects file and multiple monthly production/input files.")
        st.markdown(
            f"""
            <div class="card">
                <h3>Local data store</h3>
                <p class="small-muted">Stored source: {escape(str(QUALITY_DB_PATH))}</p>
                <p class="small-muted">Monitored folder: {escape(str(ASSEMBLY_MONITORED_DIR))}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            skd_metric_card("Stored defects files", fmt_int(store_status["defects"]), "Local history")
        with c2:
            skd_metric_card("Stored input files", fmt_int(store_status["input"]), "Local history")
        with c3:
            skd_metric_card("Stored size", f"{store_status['bytes'] / 1024 / 1024:.1f} MB", "Local files")
        with c4:
            skd_metric_card("Latest import", str(store_status["latest"]), "Local data store")

        use_local_store = st.checkbox(
            "Use stored local Assembly data when available",
            value=store_status["ready"],
            disabled=not store_status["ready"],
        )
        if "assembly_last_import_results" in st.session_state:
            st.markdown("#### Last import result")
            import_results_table(st.session_state["assembly_last_import_results"])

        if st.button("Refresh monitored folder now", use_container_width=True):
            results = import_assembly_monitored_folder()
            st.session_state["assembly_last_import_results"] = results
            st.success("Monitored folder import finished.")
            st.rerun()

        uploaded_defects = st.file_uploader("Defects file", type=["xlsx"], key="assembly_defects_upload")
        uploaded_inputs = st.file_uploader(
            "Monthly production/input files",
            type=["csv", "xls", "xlsx"],
            accept_multiple_files=True,
            key="assembly_inputs_upload",
        )
        if uploaded_defects and uploaded_inputs:
            if st.button("Save uploaded files to local data store", use_container_width=True):
                results = [persist_assembly_source(uploaded_defects, "defects", "manual upload")]
                results.extend(persist_assembly_source(uploaded, "input", "manual upload") for uploaded in uploaded_inputs)
                st.session_state["assembly_last_import_results"] = results
                st.success("Uploaded files were processed into the local data store.")
                st.rerun()

        st.info("If no stored or uploaded files are selected, the dashboard uses the Jan-Jun/2026 sample data stored in sample_data/assembly.")
        st.info(
            "Defect updates are consolidated by key. When a later upload brings the same defect with additional analysis fields, "
            "the dashboard keeps one defect record and fills/updates the non-blank fields."
        )
        st.info(
            "Production inputs are controlled by model and period. Newer uploads replace older fully covered periods; "
            "ambiguous partial overlaps are blocked and listed in the export audit."
        )
        if uploaded_inputs:
            st.caption("For legacy .xls uploads, keep `xlrd` installed from requirements.txt.")

    if active_section == "Upload Data":
        return

    stored_defects, stored_inputs = stored_assembly_sources()
    if use_local_store and stored_defects and stored_inputs:
        selected_defects, defect_source_note = select_defect_sources(stored_defects)
        defect_source = selected_defects
        input_sources = stored_inputs
        source_label = f"Local stored Assembly data · {defect_source_note}"
    elif uploaded_defects and uploaded_inputs:
        defect_source = BytesIO(uploaded_defects.getvalue())
        defect_source.name = uploaded_defects.name
        input_sources = []
        for uploaded in uploaded_inputs:
            data = BytesIO(uploaded.getvalue())
            data.name = uploaded.name
            input_sources.append(data)
        source_label = "Uploaded data"
    else:
        defect_source, input_sources = sample_sources()
        source_label = "Bundled sample data"

    try:
        analysis = analyze_skd_quality_cached(defect_source, input_sources, rules, source_label)
    except Exception as exc:
        st.error(f"Unable to calculate the SKD dashboard: {exc}")
        return

    totals = analysis["totals"]
    monthly = analysis["monthly"].copy()
    trend = analysis["trend"].copy()
    trend_settings = analysis["trend_settings"]
    model_summary = analysis["model_summary"].copy()
    merge_stats = analysis.get("defect_merge_stats", {})
    production_input_stats = analysis.get("production_input_stats", {})
    period_start = coerce_timestamp(rules.get("date_start", "2026-01-01"), "2026-01-01").strftime("%d/%m/%Y")
    period_end = coerce_timestamp(rules.get("date_end", "2026-12-31"), "2026-12-31").strftime("%d/%m/%Y")
    period_note = f"{period_start} to {period_end}"

    if trend_settings.get("summarized_input_rows", 0):
        resolution_note = (
            f"Input resolution protection: summarized {trend_settings['input_grain']} input was detected. "
            f"The software does not divide or estimate this input at a finer time scale. "
            f"Production, PPM and ManDo PPM trends are displayed {trend_settings['title']}."
        )
        if trend_settings.get("input_resolution_limited"):
            st.warning(resolution_note)
        else:
            st.caption(resolution_note)

    if active_section == "Overview":
        st.caption(f"Source: {totals['source']}")
        if merge_stats:
            st.caption(
                f"Defect consolidation: {fmt_int(merge_stats.get('merged_updates', 0))} update rows merged "
                f"using key {merge_stats.get('key_columns', '-')}."
            )
        selected_replaced_rows = production_input_stats.get(
            "selected_replaced_rows", production_input_stats.get("replaced_rows", 0)
        )
        selected_blocked_rows = production_input_stats.get(
            "selected_blocked_rows", production_input_stats.get("blocked_rows", 0)
        )
        if selected_replaced_rows:
            st.caption(
                f"Input period control: {fmt_int(selected_replaced_rows)} older covered input rows replaced by newer uploads."
            )
        if selected_blocked_rows:
            st.warning(
                f"Input period control blocked {fmt_int(selected_blocked_rows)} ambiguous overlapping input rows. "
                "Download the export and review the Input Period Audit sheet."
            )
        cols = st.columns(4)
        with cols[0]:
            skd_metric_card("Produced units", fmt_int(totals["produced"]), period_note)
        with cols[1]:
            skd_metric_card("Confirmed defects", fmt_int(totals["confirmed_defects"]), f"PPM {fmt_ppm(totals['confirmed_ppm'])}")
        with cols[2]:
            skd_metric_card("Rejudge OK / False NG", fmt_int(totals["rejudge_ok"]), fmt_pct(totals["rejudge_rate"]))
        with cols[3]:
            skd_metric_card("Straight Rate", fmt_pct(totals["straight_rate"]), f"Bad Machine {fmt_int(totals['bad_machine'])}")

        cols = st.columns(4)
        with cols[0]:
            skd_metric_card("Total records", fmt_int(totals["total_records"]), "Filtered by TestTime")
        with cols[1]:
            skd_metric_card("Worst PPM period", str(totals["worst_ppm_period"]), f"{trend_settings['label']} trend")
        with cols[2]:
            skd_metric_card("Worst volume period", str(totals["worst_volume_period"]), "Confirmed defects")
        with cols[3]:
            skd_metric_card("ManDo PPM", fmt_ppm(totals["mando_ppm"]), f"{fmt_pct(totals['mando_share'])} of confirmed")

        left, right = st.columns([1.35, 1])
        with left:
            chart_df = trend[["Period", "ConfirmedPPM", "ManDoPPM"]].fillna(0)
            show_chart(
                skd_line_chart(
                    chart_df,
                    "Period",
                    ["ConfirmedPPM", "ManDoPPM"],
                    f"Confirmed PPM vs ManDo PPM {trend_settings['title']}",
                    color,
                )
            )
        with right:
            show_chart(skd_rejudge_rate_chart(totals["rejudge_ok"], totals["confirmed_defects"]))

        monthly_view = monthly[
            ["Month", "Produced", "BadMachine", "TotalRecords", "RejudgeOK", "ConfirmedDefects", "ConfirmedPPM", "ManDoDefects", "ManDoPPM", "StraightRate"]
        ].copy()
        monthly_view[["ConfirmedPPM", "ManDoPPM"]] = monthly_view[["ConfirmedPPM", "ManDoPPM"]].round(0)
        monthly_view["StraightRate"] = (monthly_view["StraightRate"] * 100).round(2)
        styled_table(monthly_view)

    if active_section == "ManDo Analysis":
        st.caption(f"Source: {totals['source']}")
        cols = st.columns(4)
        with cols[0]:
            skd_metric_card("ManDo confirmed defects", fmt_int(totals["mando_defects"]), "Confirmed only")
        with cols[1]:
            skd_metric_card("ManDo share", fmt_pct(totals["mando_share"]), "Over confirmed defects")
        with cols[2]:
            skd_metric_card("ManDo PPM", fmt_ppm(totals["mando_ppm"]), "Per produced units")
        with cols[3]:
            skd_metric_card("Worst ManDo period", str(totals["worst_mando_period"]), "By ManDo PPM")

        left, right = st.columns(2)
        with left:
            show_chart(
                skd_line_chart(
                    trend[["Period", "ManDoPPM"]].fillna(0),
                    "Period",
                    ["ManDoPPM"],
                    f"ManDo PPM evolution {trend_settings['title']}",
                    color,
                )
            )
        with right:
            show_chart(
                skd_bar_chart(
                    trend[["Period", "ManDoDefects"]],
                    "Period",
                    "ManDoDefects",
                    f"Confirmed ManDo {trend_settings['title']}",
                    color,
                )
            )

        min_input = int(rules.get("minimum_model_input_for_priority", 100))
        eligible = model_summary[model_summary["Produced"] >= min_input].copy()
        ppm_rank = eligible.sort_values("ManDoPPM", ascending=False).head(10)
        impact_rank = eligible.sort_values(["ManDoDefects", "ManDoPPM"], ascending=[False, False]).head(10)
        left, right = st.columns(2)
        with left:
            ppm_display = ppm_rank[["Model", "Produced", "ManDoDefects", "ManDoPPM"]].copy()
            ppm_display["ManDoPPM"] = ppm_display["ManDoPPM"].round(0)
            st.markdown("#### Ranking by ManDo PPM")
            styled_table(ppm_display)
        with right:
            impact_display = impact_rank[["Model", "Produced", "ManDoDefects", "ManDoPPM", "ImpactScore"]].copy()
            impact_display[["ManDoPPM", "ImpactScore"]] = impact_display[["ManDoPPM", "ImpactScore"]].round(0)
            st.markdown("#### Ranking by real impact")
            styled_table(impact_display)

        show_chart(skd_bar_chart(analysis["mando_pareto"].head(12), "Phenomenon", "ManDoDefects", "ManDo defect phenomena Pareto", color, orientation="h"))

    if active_section == "Models":
        st.caption(f"Minimum model input for priority: {rules.get('minimum_model_input_for_priority', 100)}")
        model_view = model_summary[
            ["Model", "Produced", "TotalRecords", "RejudgeOK", "ConfirmedDefects", "ConfirmedPPM", "ManDoDefects", "ManDoPPM", "ImpactScore"]
        ].copy()
        model_view[["ConfirmedPPM", "ManDoPPM", "ImpactScore"]] = model_view[["ConfirmedPPM", "ManDoPPM", "ImpactScore"]].round(0)
        show_chart(skd_bar_chart(model_view.sort_values("ConfirmedPPM", ascending=False).head(12), "Model", "ConfirmedPPM", "Top models by confirmed PPM", color, orientation="h"))
        styled_table(model_view.sort_values(["ConfirmedDefects", "ConfirmedPPM"], ascending=[False, False]))

    if active_section == "Lines":
        st.info("Real PPM by line is not available because the production/input files do not include production by line. The view below shows defect share by line.")
        line_view = analysis["line_summary"].copy()
        line_view["Share"] = (line_view["Share"] * 100).round(2)
        show_chart(skd_bar_chart(line_view.head(15), "Line", "ConfirmedDefects", "Confirmed defects by line", color, orientation="h"))
        styled_table(line_view)

    if active_section == "Defects / Pareto":
        left, right = st.columns(2)
        with left:
            show_chart(skd_bar_chart(analysis["defect_pareto"].head(15), "Phenomenon", "ConfirmedDefects", "Confirmed defect Pareto", color, orientation="h"))
        with right:
            show_chart(skd_bar_chart(analysis["mando_pareto"].head(15), "Phenomenon", "ManDoDefects", "ManDo Pareto", color, orientation="h"))
        styled_table(analysis["defect_pareto"])

    if active_section == "Rules":
        st.markdown("### Rules")
        st.caption(f"Rules file: {RULES_PATH}")
        st.caption("The active analysis period is controlled by the calendar selector at the top of this dashboard.")
        with st.form("assembly_rules_form"):
            edited = stored_rules.copy()
            c1, c2, c3 = st.columns(3)
            with c1:
                edited["date_column"] = st.text_input("Date column", value=stored_rules["date_column"])
                edited["model_column"] = st.text_input("Model column", value=stored_rules["model_column"])
                edited["line_column"] = st.text_input("Line column", value=stored_rules["line_column"])
                edited["minimum_model_input_for_priority"] = st.number_input(
                    "Minimum model input for priority",
                    min_value=1,
                    value=int(stored_rules.get("minimum_model_input_for_priority", 100)),
                    step=10,
                )
            with c2:
                edited["phenomenon_column"] = st.text_input("Phenomenon column", value=stored_rules["phenomenon_column"])
                edited["rejudge_column"] = st.text_input("Rejudge column", value=stored_rules["rejudge_column"])
                edited["mando_column"] = st.text_input("ManDo column", value=stored_rules["mando_column"])
                edited["defect_sheet"] = st.text_input("Defect sheet", value=stored_rules["defect_sheet"])
            with c3:
                st.info("Use the calendar above to change the current analysis period.")
                edited["defect_merge_key_columns"] = [
                    item.strip()
                    for item in st.text_area(
                        "Defect merge key columns",
                        value="\n".join(stored_rules.get("defect_merge_key_columns", DEFAULT_RULES["defect_merge_key_columns"])),
                    ).splitlines()
                    if item.strip()
                ]
                edited["additional_rejudge_columns"] = [
                    item.strip()
                    for item in st.text_area("Additional rejudge columns", value="\n".join(stored_rules.get("additional_rejudge_columns", []))).splitlines()
                    if item.strip()
                ]
            edited["rejudge_ok_keywords"] = [
                item.strip()
                for item in st.text_area("Rejudge OK keywords", value="\n".join(stored_rules["rejudge_ok_keywords"])).splitlines()
                if item.strip()
            ]
            edited["mando_keywords"] = [
                item.strip()
                for item in st.text_area("ManDo keywords", value="\n".join(stored_rules["mando_keywords"])).splitlines()
                if item.strip()
            ]
            if st.form_submit_button("Save rules"):
                save_rules(edited)
                st.success("Rules saved. The dashboard will use the updated rules on rerun.")
                st.rerun()

    if active_section == "Details":
        raw = analysis["raw"].copy()
        selected_model = st.selectbox("Model", ["All", *sorted(raw["Model"].dropna().unique())])
        selected_line = st.selectbox("Line", ["All", *sorted(raw["Line"].dropna().unique())])
        selected_type = st.selectbox("Record type", ["All", "Confirmed defects", "Rejudge OK", "ManDo only"])
        view = raw
        if selected_model != "All":
            view = view[view["Model"] == selected_model]
        if selected_line != "All":
            view = view[view["Line"] == selected_line]
        if selected_type == "Confirmed defects":
            view = view[view["ConfirmedDefect"]]
        elif selected_type == "Rejudge OK":
            view = view[view["IsRejudgeOK"]]
        elif selected_type == "ManDo only":
            view = view[view["IsManDo"]]
        columns = [
            "Item",
            "PCB",
            "Barcode",
            "SingleCode",
            "TestTime",
            "TestOperation",
            "Month",
            "Model",
            "Line",
            "Phenomenon",
            "DutyType",
            "Maintenance",
            "Fault reason",
            "RepaireRemark",
            "IsRejudgeOK",
            "ConfirmedDefect",
            "IsManDo",
            "MergedUpdates",
            "SourceFile",
            "SourceFiles",
        ]
        visible_view = view[[col for col in columns if col in view.columns]].copy()
        st.info(
            f"{len(visible_view)} records match the selected filters. "
            "The detail table is not rendered on screen to keep the dashboard faster."
        )
        detail_signature = (
            rules.get("date_start"),
            rules.get("date_end"),
            selected_model,
            selected_line,
            selected_type,
            len(visible_view),
        )
        if st.session_state.get("assembly_detail_signature") != detail_signature:
            st.session_state.pop("assembly_detail_csv", None)
            st.session_state["assembly_detail_signature"] = detail_signature
        if st.button("Prepare filtered detail CSV", use_container_width=True):
            st.session_state["assembly_detail_csv"] = visible_view.to_csv(index=False).encode("utf-8-sig")
            st.success("Filtered detail CSV is ready to download.")
        if "assembly_detail_csv" in st.session_state:
            st.download_button(
                "Download filtered detail rows",
                data=st.session_state["assembly_detail_csv"],
                file_name="assembly_filtered_detail_rows.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if active_section == "Export":
        st.markdown("### Export Results")
        st.caption("Exports the calculated tables to Excel, with sheets for monthly summary, models, Pareto, Rejudge, ManDo, and filtered data.")
        export_signature = (
            rules.get("date_start"),
            rules.get("date_end"),
            totals["source"],
            int(totals["total_records"]),
            int(totals["produced"]),
        )
        if st.session_state.get("assembly_export_signature") != export_signature:
            st.session_state.pop("assembly_export_bytes", None)
            st.session_state["assembly_export_signature"] = export_signature
        if st.button("Prepare SKD analysis workbook", use_container_width=True):
            st.session_state["assembly_export_bytes"] = make_skd_export(analysis).getvalue()
            st.success("Workbook is ready to download.")
        if "assembly_export_bytes" in st.session_state:
            st.download_button(
                "Download SKD analysis workbook",
                data=st.session_state["assembly_export_bytes"],
                file_name="skd_quality_analysis.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    if active_section == "About":
        st.markdown(
            """
            <div class="card">
                <h3>SKD Quality Dashboard</h3>
                <p class="small-muted">Quality analysis dashboard for Assembly SKD data. The logic separates Rejudge OK / False NG from confirmed defects, calculates PPM by month/model, and includes a dedicated ManDo analysis.</p>
                <p><b>Default source:</b> Jan-Jun/2026 sample data in <span class="small-muted">sample_data/assembly</span>.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def home_page() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>JOVI QUALITY PORTAL</h1>
            <h3>One Portal. All Quality.</h3>
            <p>Knowledge, Processes and Performance in one place.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    data = [
        ("Learning Area", "Access knowledge, procedures, process maps and KPIs to empower your quality journey.", MODULES["Learning Area"]["color"], "▣", nav_href("Learning Area", "Overview")),
        ("SMT", "Surface Mount Technology process overview, KPI tracking, dashboard and BOM comparison.", MODULES["SMT"]["color"], "▦", nav_href("SMT", "Overview")),
        ("Assembly", "Assembly process overview, KPI tracking and quality dashboard.", MODULES["Assembly"]["color"], "◇", nav_href("Assembly", "Overview")),
        ("IQC", "Incoming Quality Control overview and inspection insights.", MODULES["IQC"]["color"], "○", nav_href("IQC", "Overview")),
    ]
    cards = "".join(module_card_html(*item) for item in data)
    st.markdown(f"<div class='home-module-grid'>{cards}</div>", unsafe_allow_html=True)


def overview_page(module: str, color: str) -> None:
    status = "Normal" if module != "Assembly" else "Attention"
    main_kpi = "852 PPM" if module == "SMT" else "1,248 PPM" if module == "Assembly" else "98.42%"
    st.markdown(f"<h1 class='section-title' style='color:{color};'>{module} Overview</h1>", unsafe_allow_html=True)
    c1, c2 = st.columns([2.3, 1])
    with c1:
        st.markdown(
            f"""
            <div class="card">
                <h3>Area overview</h3>
                <p class="small-muted">Operational landing page for the {module} module. Use this page to access key functions, check general status, and review important notices.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="card">
                <h3>Area Status</h3>
                <div class="metric-value" style="color:{color};">{status}</div>
                <div class="small-muted">Current module status</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")
    tabs = MODULES[module]["tabs"]
    quick = [t for t in tabs if t != "Overview"] or ["Overview"]
    cols = st.columns(len(quick))
    for col, tab in zip(cols, quick):
        with col:
            st.markdown(
                f"""
                <div class="card">
                    <h4>{tab}</h4>
                    <p class="small-muted">Quick access to {tab.lower()}.</p>
                    <div class="fake-btn" style="background:{color};">Open</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.write("")
    c1, c2, c3 = st.columns([1.4, 1, 1])
    with c1:
        st.markdown(f"<div class='card'><h3>Main Indicator</h3><div class='metric-value' style='color:{color};'>{main_kpi}</div><p class='small-muted'>Current month · demo data</p></div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='card'><h3>Last Update</h3><div class='metric-value'>08:30</div><p class='small-muted'>2026-06-01 · automatic update</p></div>", unsafe_allow_html=True)
    with c3:
        st.markdown("<div class='card'><h3>Notices</h3><p class='small-muted'>• Quality meeting<br>• Planned training<br>• New update available</p></div>", unsafe_allow_html=True)


def kpi_track_page(module: str, color: str) -> None:
    st.markdown(f"<h1 class='section-title' style='color:{color};'>{module} KPI Track</h1>", unsafe_allow_html=True)
    cols = st.columns(4)
    metrics = [("FPY", "98.65%"), ("OEE", "85.42%"), ("Defect Rate", "0.68%"), ("Rework Rate", "1.25%")]
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value' style='color:{color};'>{value}</div><div class='small-muted'>Demo target</div></div>", unsafe_allow_html=True)
    trend_chart(color)


def dashboard_page(module: str, color: str) -> None:
    if module == "Assembly":
        assembly_quality_dashboard(color)
        return

    if module == "SMT":
        import importlib
        from tools import smt_input_tool

        importlib.reload(smt_input_tool)
        smt_input_tool.render_smt_quality_dashboard(color)
        return

    st.markdown(f"<h1 class='section-title' style='color:{color};'>{module} Quality Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<div class='card'><h3>Quality Dashboard</h3><p class='small-muted'>Area reserved for detailed analysis of production, defects, PPM, trends, model, line, shift, and actions. In this version, the data is demonstrative.</p></div>", unsafe_allow_html=True)
    defect_chart(color)


SMT_KNOWLEDGE_TOPICS = [
    {
        "title": "SMT Fundamentals for Smartphone PCBAs",
        "desc": "Surface Mount Technology basics applied to Jovi mobile phone boards: PCB layers, pads, solder mask, SMD packages, fine pitch parts, RF areas, shields, cameras, connectors, and FPC/BTB interfaces.",
        "tags": ["PCB", "SMD", "Fine Pitch", "Smartphone"],
    },
    {
        "title": "Solder Paste & Stencil Printing",
        "desc": "Paste storage, thawing, mixing, stencil aperture control, printer parameters, paste volume, paste offset, bridge risk, and first-print approval for dense phone boards.",
        "tags": ["Paste", "Stencil", "SPI", "Print Offset"],
    },
    {
        "title": "Placement Control",
        "desc": "Feeder setup, nozzle selection, polarity, component orientation, tiny passive placement, IC alignment, connector positioning, camera module interface risk, and first article inspection.",
        "tags": ["Feeder", "Nozzle", "Polarity", "FAI"],
    },
    {
        "title": "Reflow Profile & Solder Joint Formation",
        "desc": "Thermal profile design for high-density smartphone PCBAs, peak temperature, soak time, cooling rate, warpage risk, component sensitivity, and solder joint reliability.",
        "tags": ["Profile", "Peak Temp", "Warpage", "Reliability"],
    },
    {
        "title": "Main SMT Defects",
        "desc": "Core defect modes: bridge, open solder, insufficient solder, tombstone, skew, missing component, wrong polarity, solder ball, lifted lead, non-wetting, head-in-pillow, and component damage.",
        "tags": ["Bridge", "Open", "Tombstone", "HIP"],
    },
    {
        "title": "Troubleshooting Method",
        "desc": "How to connect defect symptoms to process causes using 5M1E, defect position, recurrence pattern, SPI/AOI evidence, model comparison, line comparison, and before/after verification.",
        "tags": ["5M1E", "Pareto", "Root Cause", "Containment"],
    },
    {
        "title": "Inspection Strategy",
        "desc": "How SPI, AOI, visual inspection, X-Ray, and electrical testing work together to detect print issues, solder joint risks, polarity errors, hidden joints, and process escapes.",
        "tags": ["SPI", "AOI", "X-Ray", "ICT/FCT"],
    },
    {
        "title": "ESD, MSD & Handling Risks",
        "desc": "Control of electrostatic discharge, moisture-sensitive devices, board handling, tray management, connector protection, shield deformation, and cosmetic/functional risk during SMT.",
        "tags": ["ESD", "MSD", "Handling", "Traceability"],
    },
]

SMT_PROCEDURE_TOPICS = [
    ("Material Receiving & Storage", "Control PCB, IC, passive components, shields, connectors, camera-related parts, solder paste, MSD exposure, FIFO, shelf life, humidity, and storage status."),
    ("Solder Paste Management", "Define thawing time, mixing, open time, stencil life, paste lot traceability, disposal rules, and abnormal paste reaction."),
    ("Stencil Setup & Cleaning", "Standardize stencil verification, mounting, damage check, underside cleaning frequency, cleaning material, and aperture blockage response."),
    ("Printer Setup & SPI Reaction", "Control print speed, pressure, separation, support pins, first print approval, SPI limits, line stop criteria, and repeated print defect escalation."),
    ("Feeder, Nozzle & Program Setup", "Verify feeder position, nozzle condition, component orientation, program version, fine pitch alignment, and first article inspection."),
    ("Reflow Profile Validation", "Define product profile creation, thermocouple position, peak temperature, soak time, cooling rate, approval rule, and periodic profile confirmation."),
    ("AOI / X-Ray Program Control", "Manage golden board, inspection thresholds, false call review, hidden solder joint inspection, program change approval, and defect library update."),
    ("Defect Reaction & Troubleshooting", "Define containment, defect confirmation, board disposition, root cause method, owner, deadline, corrective action, and recurrence prevention."),
    ("ESD / MSD / Handling Control", "Document ESD check, grounding, gloves, tray rules, MSD baking, exposure tracking, connector protection, and board handling restrictions."),
    ("Changeover & First Article", "Define model changeover, material verification, program check, line clearance, first board approval, and mass production release criteria."),
]

SMT_PROCESS_STEPS = [
    ("01", "Material Preparation", "Confirm PCB, components, solder paste, stencil, feeder list, program revision, MSD/ESD status, and production order."),
    ("02", "Solder Paste Printing", "Apply solder paste through stencil and control paste position, volume, pressure, speed, support pins, and cleaning cycle."),
    ("03", "SPI Inspection", "Measure solder paste height, area, volume, offset, bridge risk, insufficient solder, and excess solder before placement."),
    ("04", "Component Placement", "Place passive parts, ICs, shields, connectors, and smartphone-specific components according to program, feeder map, nozzle condition, and polarity."),
    ("05", "Pre-Reflow Verification", "Check critical components, orientation, missing parts, skew, connector seating, and obvious abnormalities before oven entry."),
    ("06", "Reflow Soldering", "Use controlled thermal profile to form solder joints while managing warpage, component sensitivity, and solderability risk."),
    ("07", "AOI / X-Ray Inspection", "Detect bridge, open, polarity, missing, skew, lifted lead, insufficient solder, and hidden solder joint risks."),
    ("08", "Defect Confirmation", "Separate real defects from false calls, classify defect mode, record location, identify responsible step, and confirm containment scope."),
    ("09", "Rework & Re-Inspection", "Perform approved repair, protect components/connectors, re-inspect, update traceability, and escalate repeated or critical defects."),
    ("10", "Data Review & Improvement", "Review defect Pareto, model/line trend, SPI/AOI signals, repeat issues, and corrective action effectiveness."),
]

SMT_KPI_TOPICS = [
    ("FPY", "First Pass Yield", "Percentage of boards passing without repair or retest. Good for monitoring overall SMT process stability."),
    ("DPPM / PPM", "Defective Parts Per Million", "Normalizes defect quantity by production volume, helping compare smartphone models, lines, and periods."),
    ("SPI Defect Rate", "Printing defect rate", "Tracks paste abnormalities such as insufficient solder, excess solder, offset, and bridge risk."),
    ("AOI False Call Rate", "Inspection efficiency", "Measures AOI noise level. High false call rate reduces inspector efficiency and can hide real defect risk."),
    ("Escape Rate", "Downstream or customer escape", "Measures defects not detected in SMT and found later in Assembly, testing, OQC, or customer side."),
    ("Rework Rate", "Repair workload", "Tracks boards requiring repair, supporting cost, reliability risk, and process health analysis."),
    ("Repeat Defect Rate", "Recurrence control", "Highlights repeated defects by model, line, component, location, or process step."),
    ("Line Stop Time", "Operational impact", "Measures downtime caused by quality events, material issues, machine issues, or process instability."),
]


def learning_card_html(title: str, desc: str, tags: list[str] | None = None) -> str:
    tag_html = ""
    if tags:
        tag_html = "<div class='topic-pill-row'>" + "".join(f"<span class='topic-pill'>{escape(tag)}</span>" for tag in tags) + "</div>"
    return f"<div class='learning-card'><h4>{escape(title)}</h4><p>{escape(desc)}</p>{tag_html}</div>"


def learning_intro(title: str, desc: str, color: str = "#1D5FBF") -> None:
    st.markdown(
        f"""
        <div class="learning-hero" style="border-left:4px solid {color};">
            <h3>{escape(title)}</h3>
            <p class="small-muted">{escape(desc)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_smt_learning_overview() -> None:
    learning_intro(
        "Jovi Smartphone SMT Learning Path",
        "Initial knowledge base for the SMT process used in mobile phone production. The focus is practical: fundamentals, common defects, troubleshooting, process control, and quality indicators.",
        MODULES["SMT"]["color"],
    )
    cards = "".join(learning_card_html(item["title"], item["desc"], item["tags"]) for item in SMT_KNOWLEDGE_TOPICS)
    st.markdown(f"<div class='learning-grid'>{cards}</div>", unsafe_allow_html=True)


def render_smt_procedures() -> None:
    learning_intro(
        "SMT Procedure Topics",
        "Recommended procedure topics to document first for Jovi smartphone SMT. Each topic can later become a controlled procedure, work instruction, checklist, or training material.",
        MODULES["SMT"]["color"],
    )
    cards = "".join(learning_card_html(title, desc) for title, desc in SMT_PROCEDURE_TOPICS)
    st.markdown(f"<div class='learning-grid'>{cards}</div>", unsafe_allow_html=True)


def render_smt_process_map() -> None:
    learning_intro(
        "SMT Process Map for Smartphone PCBAs",
        "High-level flow from material preparation to improvement review. This can later be expanded with owners, records, quality gates, inspection criteria, and reaction rules.",
        MODULES["SMT"]["color"],
    )
    steps = "".join(
        f"""
        <div class="flow-step">
            <div class="step-no">Step {escape(no)}</div>
            <h4>{escape(title)}</h4>
            <p>{escape(desc)}</p>
        </div>
        """
        for no, title, desc in SMT_PROCESS_STEPS
    )
    st.markdown(f"<div class='process-flow'>{steps}</div>", unsafe_allow_html=True)


def render_smt_kpis() -> None:
    import pandas as pd

    learning_intro(
        "SMT KPI Learning",
        "Core indicators for SMT quality and process performance in smartphone production. These KPIs connect daily defects with process control and improvement priorities.",
        MODULES["SMT"]["color"],
    )
    kpi_df = pd.DataFrame(SMT_KPI_TOPICS, columns=["KPI", "Focus", "Purpose"])
    styled_table(kpi_df)


def learning_page(tab: str) -> None:
    color = MODULES["Learning Area"]["color"]
    st.markdown(f"<h1 class='section-title' style='color:{color};'>Learning Area · {tab}</h1>", unsafe_allow_html=True)
    if tab == "Overview":
        render_smt_learning_overview()
    elif tab == "Procedures":
        render_smt_procedures()
    elif tab == "Process Map":
        render_smt_process_map()
    elif tab == "KPI's":
        render_smt_kpis()


def bom_tool_smt_page() -> None:
    import importlib
    from tools import bom_comparison_tool

    importlib.reload(bom_comparison_tool)
    bom_comparison_tool.render_bom_comparison_tool(MODULES["SMT"]["color"])


def bom_tool_assy_page() -> None:
    import importlib
    from tools import bom_comparison_assy_tool

    importlib.reload(bom_comparison_assy_tool)
    bom_comparison_assy_tool.render_bom_comparison_assy_tool(MODULES["Assembly"]["color"])


def iqc_page() -> None:
    overview_page("IQC", MODULES["IQC"]["color"])


def about_page() -> None:
    st.markdown("<h1 class='section-title'>About</h1>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="card">
            <h3>Jovi Quality Portal</h3>
            <p><b>Current version:</b> {APP_VERSION}</p>
            <p><b>Developed by:</b> {DEVELOPER}<br><b>Role:</b> {ROLE}<br><b>Manager:</b> {MANAGER}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    st.markdown("<h3 class='section-title'>Version History</h3>", unsafe_allow_html=True)
    for version, desc in VERSION_HISTORY:
        st.markdown(f"<div class='card' style='min-height:auto;margin-bottom:0.6rem;'><b>{version}</b><br><span class='small-muted'>{desc}</span></div>", unsafe_allow_html=True)


def render_page() -> None:
    module = st.session_state.module
    tab = st.session_state.tab
    if module == "Home":
        home_page()
    elif module == "Learning Area":
        learning_page(tab)
    elif module in ["SMT", "Assembly"]:
        color = MODULES[module]["color"]
        if tab == "Overview":
            overview_page(module, color)
        elif tab == "KPI Track":
            kpi_track_page(module, color)
        elif tab == "Quality Dashboard":
            dashboard_page(module, color)
        elif tab == "BOM Comparison Tool - SMT":
            bom_tool_smt_page()
        elif tab == "BOM Comparison Tool - Assy":
            bom_tool_assy_page()
    elif module == "IQC":
        iqc_page()
    elif module == "About":
        about_page()


init_state()
sync_navigation_from_query()
apply_global_css()
sidebar()
topbar()
render_page()
footer()
