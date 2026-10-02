import base64
import json
import math
import os
import re
import hashlib
import importlib
import sqlite3
import streamlit as st
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO
from numbers import Number
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from tools.supabase_store import (
    DATABASE_OBJECT,
    DATA_VERSION_FILENAME,
    SYNC_MANIFEST_FILENAME,
    bump_cloud_data_version,
    cloud_store_is_active,
    cloud_store_status,
    delete_object,
    ensure_cloud_data_version,
    migrate_local_data_store,
    sync_file_from_cloud,
    sync_prefix_from_cloud,
    upload_bytes,
    upload_local_file,
)
from tools import trend_rules
if trend_rules.DAILY_TREND_LIMIT_DAYS != 31:
    # Streamlit can rerun app.py without re-importing modules already in memory.
    trend_rules = importlib.reload(trend_rules)
analysis_period_days = trend_rules.analysis_period_days
requested_trend_grain = trend_rules.requested_trend_grain
trend_grain_labels = trend_rules.trend_grain_labels
from tools import assembly_kpi_v2
from tools.kpi_slide import build_kpi_panel_chart
from tools.auth_session import COOKIE_NAME, SESSION_SECONDS, issue_token, revoke_token
from tools.access_control import (
    account_from_token,
    authenticate,
    configured_accounts,
    is_admin_session,
    require_admin_access,
)
from tools.historical_inspection_archive import apply_archive as apply_historical_inspection_archive
from tools.inspection_store import (
    create_inspection_tables,
    migrate_zero_sampling_schema,
    validate_inspection_counts,
)


APP_VERSION = "v0.5.93"
DEVELOPER = "Matheus Augusto de Lima Basilio"
ROLE = "Quality Specialist"
PORTAL_ACCOUNTS = configured_accounts()
LOGIN_USERNAME = PORTAL_ACCOUNTS[0].username
MANAGER = "曹毅"
BASE_DIR = Path(__file__).resolve().parent
RULES_PATH = BASE_DIR / "config" / "rules.json"
ASSEMBLY_SAMPLE_DIR = BASE_DIR / "sample_data" / "assembly"
DATA_STORE_DIR = BASE_DIR / "data_store"
QUALITY_DB_PATH = DATA_STORE_DIR / "jovi_quality.db"
ASSEMBLY_FILE_STORE_DIR = DATA_STORE_DIR / "assembly"
ASSEMBLY_MONITORED_DIR = BASE_DIR / "auto_import" / "assembly"
ASSEMBLY_SMT_DUTY_TYPES = ("SMT equipment", "SMT Mando", "SMT Process", "SMT Test")
ASSEMBLY_MES_EXCLUSION_KEYWORDS = (
    "Re-Judge Ok",
    "Rejudge OK",
    "Re-Judge OK",
    "rejudge ok",
    "Good machine rejudge ok",
    "Re-Download",
    "Re-Calibration",
)
ASSEMBLY_FUNCTIONAL_OPERATIONS = assembly_kpi_v2.FUNCTIONAL_OPERATIONS
ASSEMBLY_APPEARANCE_OPERATIONS = assembly_kpi_v2.APPEARANCE_OPERATIONS
HOME_ASSET_DIR = BASE_DIR / "assets" / "home"
HOME_MODULE_IMAGES = {
    "Learning Area": "learning_area.png",
    "SMT": "smt.png",
    "Assembly": "assembly.png",
    "IQC": "iqc.png",
}

st.set_page_config(
    page_title="Jovi Quality Center",
    page_icon="JOVI",
    layout="wide",
    initial_sidebar_state="collapsed",
)

MODULES = {
    "Home": {"color": "#1D5FBF", "tabs": []},
    "Learning Area": {"color": "#1D5FBF", "tabs": ["Overview", "Procedures", "Process Map", "KPI's"]},
    "SMT": {"color": "#0D7A45", "tabs": ["KPI Track", "Quality Dashboard", "BOM Comparison Tool - SMT", "Data Upload"]},
    "Assembly": {"color": "#6532C8", "tabs": ["KPI Track", "Quality Dashboard", "BOM Comparison Tool - Assembly", "Data Upload"]},
    "Model Comparison": {"color": "#1D5FBF", "tabs": []},
    "IQC": {"color": "#B45309", "tabs": ["Overview"]},
    "Smart Report": {"color": "#0F766E", "tabs": []},
    "Repair Info": {"color": "#1D5FBF", "tabs": []},
    "About": {"color": "#1D5FBF", "tabs": []},
}

VERSION_HISTORY = [
    ("v0.5.93", "Invalidate weekly SMT KPI cache when the selected period requires daily values."),
    ("v0.5.92", "Refresh cached KPI grouping rules after deployment and restore trend lines between recorded days."),
    ("v0.5.91", "Show every selected day on SMT and Assembly KPI Track charts for periods up to 31 days; keep OQC dates within the selected range."),
    ("v0.5.90", "Improved Repair Info daily chart with narrower bars, one date tick per day and visible PCB count labels."),
    ("v0.5.89", "Added read-only Repair Info with stored SMT and Assembly repair throughput, elapsed-time analysis and searchable PCB-level details."),
    ("v0.5.88", "Set Matheus as administrator and jovi as the standard read-only user; invalidated previous browser sessions after the role change."),
    ("v0.5.87", "Added administrator and read-only viewer accounts; data uploads, deletions and saved settings require administrator access."),
    ("v0.5.86", "Added Assembly PowerPoint KPI graphs below the SMT graphs in Weekly KPI Review, using the same weekly values, visible days and vector export."),
    ("v0.5.85", "Removed the excess gap above Assembly defect breakdown cards by rendering their styles in one block."),
    ("v0.5.84", "Reduced shared page, navigation and filter spacing across the portal while preserving the existing navigation button styling."),
    ("v0.5.83", "Aligned Assembly Quality Dashboard with SMT by keeping the defect breakdown and matching PCB details and removing the additional charts and analysis sections."),
    ("v0.5.82", "Standardized SMT and Assembly KPI Track to one chart per row and moved both data-detail sections below the charts."),
    ("v0.5.81", "Kept the portal's light colors consistent across browser and Streamlit theme preferences."),
    ("v0.5.80", "Rebuilt Home around selectable SMT and Assembly KPI trends, full-period details and quick date presets."),
    ("v0.5.79", "Added hover balloons to Home model trend points with defect PCB count, FPY input and daily PPM."),
    ("v0.5.78", "Added scrollable SMT Process NG and Assembly Function Mando daily model trends to Home, ordered by the latest FPY input."),
    ("v0.5.77", "Added Model, BadMachLocation and ItemCode cross-filter cards to SMT and Assembly Quality Dashboards."),
    ("v0.5.76", "Kept login through browser refresh, restored the last subtab and analysis selections, retained temporary comparison uploads, and opened Monthly KPI Review on the current month."),
    ("v0.5.75", "Accepted SMT FPY summaries with extra OrgDisplay line input from retests while preserving ModelData as the KPI denominator and auditing the difference."),
    ("v0.5.74", "Added a shared SMT and Assembly Model Comparison page with KPI, defect breakdown and formatted Excel reporting; expanded Assembly dashboard defect analysis."),
    ("v0.5.73", "Removed the unnecessary Assembly SMT duty defect breakdown table from SMT KPI Track."),
    ("v0.5.72", "Fixed a missing pandas import in the relocated OQC/FQC inspection history on Data Upload."),
    ("v0.5.71", "Moved SMT OQC and Assembly OQC/FQC manual entry and inspection history from KPI Track into each area's Data Upload page."),
    ("v0.5.54", "Classified Assembly Photosensor_calibration_Dark and Order-Linking defects as functional, aligning the MES functional-analysis scope."),
    ("v0.5.55", "Made refreshed Assembly FPY exports replace obsolete defects only on the MES dates covered by the upload, preserving all other historical data."),
    ("v0.5.56", "Extended MES date-level FPY reconciliation to SMT, so refreshed exports remove obsolete events only within their covered dates."),
    ("v0.5.57", "Invalidated the prepared Assembly KPI source cache when MES consolidation rules change, applying refreshed defect snapshots immediately."),
    ("v0.5.58", "Added a copy-ready four-panel SMT KPI slide with one selectable analysis period and presentation-standard styling."),
    ("v0.5.59", "Refined the SMT KPI slide with weekly rollups plus latest-week input days, and removed its non-chart header for a cleaner PowerPoint copy."),
    ("v0.5.60", "Moved the SMT KPI Slide into Smart Report's Weekly KPI Review, where it now mirrors the table's two weekly summaries and visible daily columns."),
    ("v0.5.70", "Reduced the on-screen presentation-chart preview while keeping its PNG and PowerPoint export dimensions unchanged."),
    ("v0.5.69", "Embedded the 16.17 cm × 8.17 cm physical dimensions in PowerPoint SVG exports so PowerPoint inserts them at the intended size."),
    ("v0.5.68", "Added a black outer frame to PowerPoint chart exports and simplified the inner axes to the bottom baseline only."),
    ("v0.5.67", "Kept the 100% ceiling while allowing presentation-chart labels, markers and lines to render into the top margin without clipping."),
    ("v0.5.66", "Prevented presentation pass-rate labels at 99.80% or above from clipping against the fixed 100% ceiling."),
    ("v0.5.65", "Made presentation pass-rate scales automatic with a fixed 100% ceiling and a compact lower bound based on the period minimum."),
    ("v0.5.64", "Expanded the presentation chart plot area, restored end-point labels with added headroom, and removed horizontal grid lines."),
    ("v0.5.63", "Sized the PowerPoint SVG export to a 16.17 cm × 8.17 cm chart slot, so it can be inserted without shrinking."),
    ("v0.5.62", "Added 4K PNG copy and vector SVG download for presentation charts, with larger labels and axes for slide readability."),
    ("v0.5.61", "Replaced the combined SMT KPI slide with four individual copy-ready charts, improving label spacing and keeping 100% values inside each plot."),
    ("v0.5.53", "Classified Assembly CCT_sensor_Calibration failures as functional, including their Mando records in the Function Mando KPI."),
    ("v0.5.52", "Restored the single Analysis period date field and constrained its Streamlit container to the visible control width."),
    ("v0.5.51", "Freed manual SMT and Assembly OQC/FQC inspection dates from the uploaded production period, defaulting to the latest available day."),
    ("v0.5.50", "Replaced the stretched Analysis period date trigger with a fixed-width popover button to prevent row-wide calendar activation."),
    ("v0.5.49", "Set explicit Streamlit widths for Analysis period widgets so their interactive area matches the visible controls."),
    ("v0.5.48", "Constrained Analysis period pointer events to the visible date field so adjacent whitespace cannot open the calendar."),
    ("v0.5.47", "Restricted Analysis period controls to their visible fields, removing the unused clickable row area."),
    ("v0.5.46", "Balanced Home heading and filter spacing while retaining the single-screen layout."),
    ("v0.5.45", "Compacted Home heading, filters and page spacing for a single-screen overview."),
    ("v0.5.44", "Aligned Home KPI card heights and added spacing above navigation shortcuts."),
    ("v0.5.43", "Fixed mismatched KPI status CSS classes and reserved space for status icons."),
    ("v0.5.42", "Applied target-status colors directly to KPI card markup so the Streamlit theme cannot override the alert backgrounds."),
    ("v0.5.41", "Fixed Home KPI card HTML rendering and increased the target-status background contrast."),
    ("v0.5.40", "Strengthened KPI target cards with clear status backgrounds and alert or confirmation icons."),
    ("v0.5.39", "Added target-status treatment to KPI cards, clearly identifying indicators below target and showing their configured threshold."),
    ("v0.5.38", "Added a print-only weekly day-column selector so low-volume days can be omitted from the copied KPI table without changing weekly calculations."),
    ("v0.5.37", "Grouped Smart Report and KPI Review top issues by the repair remark, with the original phenomenon retained only when no repair conclusion exists."),
    ("v0.5.36", "Made Weekly and Monthly major-problem narratives rank defects within each KPI's own functional, appearance, Mando or SMT-duty scope."),
    ("v0.5.35", "Fixed manual OQC/FQC history rendering for zero-sampling records."),
    ("v0.5.34", "Aligned Monthly KPI Review with KPI Track calculations, so September uses the uploaded source data instead of rejecting a month when its final input day has no defect-row timestamp."),
    ("v0.5.33", "Accepted explicit zero-sampling OQC/FQC records while keeping their pass rates unavailable rather than treating them as 100%."),
    ("v0.5.32", "Corrected Pareto cumulative lines when long defect labels share the same shortened axis text."),
    ("v0.5.31", "Kept Assembly SMT Process Duty NG Rate valid when its own SMT-duty defects reconcile with input, independent of unrelated Assembly defects."),
    ("v0.5.30", "Restored Assembly KPI Track after accommodating its Produced daily-input field in exception-marker tooltips."),
    ("v0.5.29", "Replaced invalid daily KPI points with true chart gaps and a red ×, while retaining the valid weekly and monthly aggregate results."),
    ("v0.5.28", "Extended red × input-versus-defect exception markers to the Assembly Quality Dashboard PPM trends."),
    ("v0.5.27", "Marked invalid daily input-versus-defect KPI results with a red × in trend charts and a × in Weekly and Monthly KPI Review tables, preventing misleading negative pass rates or PPM above one million."),
    ("v0.5.26", "Ranked Smart Report, Weekly KPI Review and Monthly KPI Review detractors solely by affected PCB count, without functional-versus-appearance preference."),
    ("v0.5.25", "Aligned the Monthly KPI Review Area selector vertically with Start date by removing Streamlit's negative button-group margins."),
    ("v0.5.24", "Removed the segmented Area control's internal padding so its lower border is fully visible."),
    ("v0.5.23", "Harmonized the Monthly KPI Review controls with matching widths, heights, centered labels and blue selected-area styling."),
    ("v0.5.22", "Brought the Monthly KPI Review Area selector next to Start date for a compact control row."),
    ("v0.5.21", "Moved the Monthly KPI Review Start date styling into the authenticated portal theme and targeted Streamlit's actual text-input root element."),
    ("v0.5.20", "Matched the Monthly KPI Review Start date control to the portal's blue period-selector styling through its dedicated layout container."),
    ("v0.5.19", "Styled the Monthly KPI Review Start date selector with the portal's blue period-control background and white text."),
    ("v0.5.18", "Replaced the Monthly KPI Review calendar picker with a compact Start date field using the YYYY-MM month format."),
    ("v0.5.17", "Cached the consolidated Assembly input, FPY and repair source data so Monthly KPI Review reuses it across the three monthly columns."),
    ("v0.5.16", "Made Assembly FPY and repair uploads incremental: partial files add new events and update only matching events, preserving earlier stored history."),
    ("v0.5.15", "Combined archived Assembly FPY defect snapshots by date, so August and earlier defects remain in KPI calculations after a newer September snapshot is uploaded."),
    ("v0.5.14", "Restored Weekly KPI Review parity with KPI Track: weekly SMT and Assembly KPI cells now use the validated calculator values without historical-source coverage gating."),
    ("v0.5.13", "Prevented Weekly and Monthly KPI Reviews from reporting false 100% pass rates or 0 PPM when the FPY defect source does not cover the selected input dates."),
    ("v0.5.12", "Imported the one-time July-to-September OQC/FQC historical archive into the existing SMT OQC and Assembly OQC/FQC records, preserving the daily manual workflow for future entries."),
    ("v0.5.11", "Refreshed the Assembly calculation revision after the current September repair snapshot was uploaded, ensuring Function Mando recomputes from the active FPY and repair files."),
    ("v0.5.10", "Added the Assembly MES rule revision to the calculation-cache key, so functional and appearance results recalculate immediately after a validated operation mapping changes."),
    ("v0.5.9", "Aligned the Assembly functional and appearance operation groups with the September MES FPY extracts: Camera-auxiliary-tester is functional, while Glue_dispensing and PCB-Assembly are appearance failures."),
    ("v0.5.8", "Clipped SMT weekly trend boundary labels to the selected analysis range, so partial weeks never display dates before or after the chosen period."),
    ("v0.5.7", "Added retry with fresh Supabase Storage connections when listing cloud folders after a paused project resumes."),
    ("v0.5.6", "Hardened Supabase Storage synchronization after project wake-up by ignoring internal empty-folder entries, extending Storage timeouts and retrying transient downloads."),
    ("v0.5.5", "Started a clean online data baseline in an isolated persistent-storage namespace. Previous production files are not loaded by this version."),

    ("v0.5.4", "Unified every Assembly view around the validated daily-input, FPY-detail and repair-detail rules; Quality Dashboard and Smart Report now use the same KPI calculation engine as KPI Track."),
    ("v0.5.3", "Aligned SMT Function Pass Rate and Process NG Rate with the authoritative FPY detail: defects are assigned by BadMachEntryTime and every FPY-listed PCB is counted without reapplying legacy repair or DutyType exclusions."),
    ("v0.5.2", "Moved SMT and Assembly source-file ingestion into a dedicated Data Upload page beside BOM Comparison, leaving KPI Track and Quality Dashboard focused on analysis."),
    ("v0.5.1", "Standardized data ingestion for both SMT and Assembly with three independent upload groups: daily FPY input, cumulative FPY defects and cumulative repair defects, including workbook validation and separate storage by area and source type."),
    ("v0.5.0", "Rebuilt Assembly KPI ingestion around validated MES sources: daily input, cumulative total defects and cumulative repair. Functional, appearance and Function Mando use unique PCBs in the selected scope, fixed operation groups and final repair responsibility, while OQC × FQC remains manual."),
    ("v0.4.6", "Applied MES-specific defect policies by area: SMT now excludes SMT Mando records from standard FPY, while Assembly retains only its validated rejudge dispositions. Assembly Functional and Appearance KPIs now count confirmed defect records rather than collapsing multiple valid occurrences into one PCB."),
    ("v0.4.5", "Aligned the SMT confirmed-defect rules with MES FPY validation: Retest OK remarks, AOI last-NG records and repeat repairs are now excluded with auditable reasons."),
    ("v0.4.4", "Added version-aware Supabase synchronization: the portal checks one compact data revision on each load and refreshes all affected files immediately when uploads or records change."),
    ("v0.4.3", "Added dashboard performance diagnostics and changed the initial analysis period to the latest available month, helping identify and reduce loading bottlenecks."),
    ("v0.4.2", "Refreshed the portal interface with Deep Navy navigation, standardized cobalt headings, persistent date selections, faster period presets, and a unified visual treatment for filter controls."),
    ("v0.4.1", "Added selective Supabase cache synchronization and a manual full cloud refresh, reducing repeated downloads while keeping a user-controlled complete refresh."),
    ("v0.4.0", "Added optional Supabase persistent storage for uploaded SMT and Assembly source files, OQC/FQC records and Smart Report actions, with a guided one-time migration."),
    ("v0.3.2", "Added Re-Download and Re-Calibration to the approved retest exclusion policy for SMT and Assembly, with visible exclusion reasons for audit."),
    ("v0.3.1", "Fixed SMT action-priority cards so missing or non-finite Impact PPM values display as N/A instead of causing a dashboard error."),
    ("v0.3.0", "Added stored-source management for SMT and Assembly: users can review and safely delete one uploaded source file at a time with explicit confirmation."),
    ("v0.2.9", "Made Assembly stored data portable across local and Streamlit deployments: sources resolve from the internal data_store directory and future imports save relative paths."),
    ("v0.2.8", "Added Smart Report with real SMT and Assembly top-defect suggestions, functional-failure priority, persistent action fields, and WhatsApp-ready reports without modifying source data files."),
    ("v0.2.7", "Centered Home module titles and descriptions and added clear vertical spacing between the hero panel and the Learning Area, SMT, Assembly and IQC cards."),
    ("v0.2.6", "Replaced full-page navigation links with session-preserving Streamlit navigation buttons in the sidebar and Home module cards, preventing authentication loss when switching modules or tabs."),
    ("v0.2.5", "Restored full chart height after the control-bar adjustment, kept chart actions inside the upper-right border, raised bottom legends, and expanded right margins for Pareto, model/input and heatmap charts to prevent axis-title clipping."),
    ("v0.2.4", "Centered KPI formula table content, added vertical separation before KPI trend charts, and moved chart copy/fullscreen controls into a reserved upper-right control band so they no longer overlap chart titles."),
    ("v0.2.3", "Reduced visual noise across SMT and Assembly KPI and Quality Dashboard pages by removing redundant rule captions, period notes and non-blocking audit messages; redesigned KPI formula tables with compact calculation bases, controlled column widths and clean text wrapping."),
    ("v0.2.2", "Added a branded login screen with authenticated session control, hashed-password validation, environment-configurable credentials and a functional sign-out action."),
    ("v0.2.1", "Audited SMT production and defect reconciliation; preserved accumulated defects through period-level model coverage, enabled proportional partial-period input selection, removed Failure Mix double counting with an exclusive Both-types category, corrected Pareto cumulative percentages, and added visible source-consistency warnings."),
    ("v0.2.0", "Redesigned SMT and Assembly Quality Dashboards as action-oriented analytical pages with global filters, executive KPIs, labeled trends, failure mix, Pareto, model/input rankings, process responsibility, SMT-origin analysis, priority tables and data-quality controls; removed redundant area Overview navigation."),
    ("v0.1.68", "Added SMT KPI daily data-consistency exceptions: Function Pass Rate remains independently available, while invalid Process NG PPM periods show a red marker, explanation and audit table; valid monthly or larger aggregates still include all defects."),
    ("v0.1.67", "Fixed SMT KPI defect-source consolidation: cumulative YTD defects and incremental daily files are combined with duplicate records resolved by the most recent source."),
    ("v0.1.66", "Centered manual OQC/FQC history tables and made the Assembly inspection history responsive without a horizontal scrollbar."),
    ("v0.1.65", "Added controlled deletion of manually entered SMT OQC and Assembly OQC/FQC inspection records from their KPI Track histories."),
    ("v0.1.64", "Fixed SMT KPI trend label refresh to use the SMT dashboard PeriodStart field, preventing the PeriodDate error."),
    ("v0.1.63", "Forced every chart to rebuild period labels at render time, ensuring dd/mm for daily and weekly trends and mm/yy for monthly trends even when cached calculations exist."),
    ("v0.1.62", "Made KPI target-label placement adaptive so it uses the opposite vertical side of the final data label, preventing overlap."),
    ("v0.1.61", "Changed all KPI target lines and their value labels to red."),
    ("v0.1.60", "Standardized trend dates as dd/mm for daily and weekly periods and mm/yy for monthly periods, and simplified target labels to an unboxed value in the target-line color."),
    ("v0.1.59", "Integrated all KPI target labels inside their charts, showing only the target value and preserving the chart plotting area."),
    ("v0.1.58", "Added visible target lines to all Assembly KPI trends: Function Pass Rate 99.05%, Appearance Total Pass Rate 99.04%, Function Mando 3,600 PPM and Assembly OQC × FQC Pass Rate 98.70%."),
    ("v0.1.57", "Standardized date labels across all date-based charts to dd/mm."),
    ("v0.1.56", "Completed Assembly KPI Track with Function Pass Rate, Appearance Total Pass Rate, Function Mando (PPM), persistent combined Assembly OQC × FQC Pass Rate input, and a reference-data station rule for Functional and Appearance failures."),
    ("v0.1.54", "Added visible target lines to every SMT KPI trend: Function Pass Rate 99.56%, SMT Process NG Rate 5,000 PPM, Assembly SMT Process Duty NG Rate 700 PPM and SMT OQC Pass Rate 98.50%."),
    ("v0.1.53", "Established the shared trend rule for current and future charts: analysis periods shorter than 30 calendar days use daily data, including Assembly SMT Process Duty NG Rate, with summarized totals distributed across calendar days while preserving the exact source-period total."),
    ("v0.1.52", "Capped percentage chart axes at 100%, aligned the SMT OQC Pass Rate trend with the shared daily, weekly and monthly period-granularity rules, and documented zero matching Assembly SMT-origin defects as 0 PPM."),
    ("v0.1.51", "Rebuilt SMT KPI Track with Function Pass Rate, SMT Process NG Rate, Assembly SMT Process Duty NG Rate and persistent manual SMT OQC Pass Rate input, including audited formulas and labeled trends."),
    ("v0.1.50", "Fixed the SMT FailureType cache migration so existing sessions rebuild the station classification instead of reusing legacy cached defect data."),
    ("v0.1.49", "Added SMT-only Functional Failure and Appearance Failure classification by station, with dedicated KPIs, PPM trend, Pareto views, model breakdown, detail filters and unclassified-station audit."),
    ("v0.1.48", "Standardized visible data labels across SMT and Assembly charts, with adaptive spacing, margins and axis headroom to prevent overlap and clipping."),
    ("v0.1.47", "Removed vertical scrolling inside dashboard tables, allowing normal page scrolling and adding pagination to the SMT detail view."),
    ("v0.1.46", "Added the June 2026 SMT production input, closing the monthly input coverage gap and recalculating the SMT Quality Dashboard indicators."),
    ("v0.1.45", "Added the real SMT Quality Dashboard v1.0.0 with stored summarized production input, cumulative defects, covered-period PPM, model analysis, Pareto, process views, Re-Judge/repeat audit, and data-quality controls."),
    ("v0.1.44", "Updated the project tagline to 'All Quality. One Center.' to align it with the Jovi Quality Center identity."),
    ("v0.1.43", "Renamed the project and all user-facing portal branding to Jovi Quality Center."),
    ("v0.1.42", "Validated and consolidated the Assembly BOM Comparison Tool v2.0.8 as a mandatory portal module, using the official Jovi BOM as reference, comparing Microsiga by code and quantity, applying Missing/Extra semantics and the HQHQ/G701/G999 exclusion rules, with auditable Excel export."),
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
            --navy: #061A3A;
            --navy-2: #0B2D61;
            --blue: #2563EB;
            --blue-2: #1D4ED8;
            --text: #071B38;
            --muted: #405775;
            --border: #C9D8EC;
            --card: #FFFFFF;
            --bg: #F1F5FB;
        }

        html, body, .stApp {
            color-scheme: light !important;
        }

        html, body, [class*="css"] {
            font-family: "Segoe UI", Arial, sans-serif !important;
        }

        .stApp {
            background: linear-gradient(180deg, #EAF1FA 0%, var(--bg) 28%, #F7F9FC 100%) !important;
            color: var(--text) !important;
        }

        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stStatusWidget"],
        #MainMenu {
            display: none !important;
        }

        [data-testid="stMainBlockContainer"] {
            max-width: none !important;
            padding: 0.2rem 1.35rem 0.8rem 1.35rem !important;
        }
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
            gap: 0.65rem !important;
        }

        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
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
            padding: 0.85rem 0.2rem 0.35rem 0.2rem;
            border-top: 1px solid rgba(255,255,255,0.16);
            font-size: 0.75rem;
            font-weight: 800;
            color: #EAF3FF !important;
        }
        .sidebar-user {
            margin-top: 0.35rem;
            color: #BFD5F1 !important;
            font-size: 0.7rem;
            font-weight: 700;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button {
            min-height: 34px;
            border: 1px solid rgba(255,255,255,0.24) !important;
            border-radius: 0.45rem !important;
            color: #FFFFFF !important;
            background: rgba(255,255,255,0.08) !important;
            font-size: 0.76rem !important;
            font-weight: 800 !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
            border-color: rgba(255,255,255,0.46) !important;
            background: rgba(255,255,255,0.15) !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"],
        section[data-testid="stSidebar"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] {
            border-color: rgba(147,197,253,0.70) !important;
            background: linear-gradient(135deg, var(--blue), var(--blue-2)) !important;
            box-shadow: 0 8px 18px rgba(29,95,191,0.28) !important;
        }
        section[data-testid="stSidebar"] [class*="st-key-nav_module_"] button {
            min-height: 42px;
            justify-content: flex-start;
            padding: 0.45rem 0.85rem;
            font-size: 0.86rem !important;
        }
        section[data-testid="stSidebar"] [class*="st-key-nav_tab_"] {
            margin-left: 0.72rem;
            padding-left: 0.55rem;
            border-left: 1px solid rgba(255,255,255,0.16);
        }
        section[data-testid="stSidebar"] [class*="st-key-nav_tab_"] button {
            min-height: 34px;
            justify-content: flex-start;
            padding: 0.34rem 0.62rem;
            color: #DDEBFF !important;
            font-size: 0.76rem !important;
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

        .st-key-top_navigation {
            position: sticky;
            top: 0.25rem;
            z-index: 100;
            background: linear-gradient(105deg, #061A3A 0%, #0B2D61 100%);
            border: 1px solid rgba(96, 165, 250, 0.34);
            border-radius: 0.9rem;
            padding: 0.42rem 0.55rem;
            margin-bottom: -0.5rem;
            box-shadow: 0 12px 28px rgba(4, 20, 48, 0.24);
            backdrop-filter: blur(10px);
        }
        .st-key-top_navigation [data-testid="stHorizontalBlock"] {
            align-items: center;
        }
        .st-key-top_navigation [data-testid="stColumn"]:first-child,
        .st-key-context_navigation [data-testid="stColumn"]:first-child {
            align-self: stretch;
            display: flex;
            align-items: center;
        }
        .st-key-top_navigation [data-testid="stColumn"]:first-child [data-testid="stElementContainer"],
        .st-key-context_navigation [data-testid="stColumn"]:first-child [data-testid="stElementContainer"],
        .st-key-top_navigation [data-testid="stColumn"]:first-child [data-testid="stMarkdown"],
        .st-key-context_navigation [data-testid="stColumn"]:first-child [data-testid="stMarkdown"] {
            width: 100%;
            margin: 0 !important;
        }
        .topnav-brand {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.03rem;
            min-height: 36px;
            padding: 0.08rem 0.38rem;
            box-sizing: border-box;
            white-space: nowrap;
        }
        .topnav-brand strong {
            color: #FFFFFF;
            font-size: 0.94rem;
            line-height: 1;
            letter-spacing: 0.035em;
        }
        .topnav-brand strong span { color: #72AEFF; }
        .topnav-brand small {
            color: #C4D7F4;
            font-size: 0.58rem;
            font-weight: 900;
            letter-spacing: 0.10em;
        }
        div[class*="st-key-top_nav_module_"] button {
            min-height: 36px;
            width: 100%;
            padding: 0.34rem 0.45rem;
            border-radius: 0.55rem;
            border: 1px solid transparent;
            background: transparent;
            color: #D9E7FB;
            font-size: 0.76rem;
            font-weight: 800;
            white-space: nowrap;
        }
        div[class*="st-key-top_nav_module_"] button:hover {
            background: rgba(96, 165, 250, 0.15);
            border-color: rgba(147, 197, 253, 0.38);
            color: #FFFFFF;
        }
        div[class*="st-key-top_nav_module_"] button[kind="primary"],
        div[class*="st-key-top_nav_module_"] button[data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #3B82F6, #2563EB);
            border-color: rgba(191, 219, 254, 0.60);
            box-shadow: 0 6px 14px rgba(3, 35, 91, 0.34);
            color: #FFFFFF;
        }
        .st-key-context_navigation {
            display: flex;
            align-items: center;
            gap: 0.7rem;
            min-height: 48px;
            padding: 0.38rem 0.55rem;
            margin: 0 0 0.12rem 0;
            background: rgba(255, 255, 255, 0.93);
            border: 1px solid var(--border);
            border-radius: 0.72rem;
            box-shadow: 0 5px 16px rgba(18, 48, 89, 0.07);
        }
        .st-key-context_navigation [data-testid="stHorizontalBlock"] {
            align-items: center;
        }
        .context-label {
            display: flex;
            align-items: center;
            color: #5C7190;
            font-size: 0.67rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            min-height: 34px;
            white-space: nowrap;
        }
        .context-label b { color: #08234A; }
        div[class*="st-key-top_nav_tab_"] button {
            min-height: 34px;
            width: 100%;
            padding: 0.3rem 0.58rem;
            border-radius: 0.48rem;
            border: 1px solid #DCE5F1;
            background: #FFFFFF;
            color: #42556F;
            font-size: 0.73rem;
            font-weight: 800;
            white-space: nowrap;
        }
        div[class*="st-key-top_nav_tab_"] button:hover {
            background: #F0F6FF;
            border-color: #A8C8EE;
        }
        div[class*="st-key-top_nav_tab_"] button[kind="primary"],
        div[class*="st-key-top_nav_tab_"] button[data-testid="stBaseButton-primary"] {
            border-color: #8EB9F3;
            background: #E2EEFF;
            color: #164D9B;
        }
        .st-key-top_navigation [data-testid="stPopover"] button {
            min-height: 36px;
            border-radius: 0.55rem;
            border-color: rgba(191, 219, 254, 0.45);
            background: rgba(255, 255, 255, 0.08);
            color: #E4EFFF;
            font-size: 0.73rem;
            font-weight: 800;
        }
        div[class*="st-key-smt_quality_v2_filter_panel"],
        div[class*="st-key-assembly_quality_v2_filter_panel"] {
            background: transparent;
            border: 0;
            padding: 0;
            margin: 0.1rem 0 0.55rem 0;
            box-shadow: none;
        }
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] label,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] label,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stDateInput"] label,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stDateInput"] label {
            color: #082957 !important;
            font-size: 0.84rem !important;
            font-weight: 900 !important;
            letter-spacing: 0.01em;
        }
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stDateInput"] > div > div,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stDateInput"] > div > div {
            background: linear-gradient(135deg, #2F80ED 0%, #1D5FBF 100%) !important;
            border-color: #4B8DEF !important;
            box-shadow: 0 4px 12px rgba(8, 45, 97, 0.18);
        }
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] [data-baseweb="select"] *,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] [data-baseweb="select"] *,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div *,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div *,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stDateInput"] input,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stDateInput"] input {
            color: #F8FBFF !important;
        }
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] svg,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] svg,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stDateInput"] svg,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stDateInput"] svg {
            fill: #BFD8FF !important;
            color: #BFD8FF !important;
        }
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div:hover,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stSelectbox"] > div > div:hover,
        div[class*="st-key-smt_quality_v2_filter_panel"] [data-testid="stDateInput"] > div > div:hover,
        div[class*="st-key-assembly_quality_v2_filter_panel"] [data-testid="stDateInput"] > div > div:hover {
            border-color: #93C5FD !important;
            box-shadow: 0 5px 14px rgba(37, 99, 235, 0.28);
        }
        div[class*="st-key-analysis_period_"] {
            max-width: 455px;
            margin: 0 0 0.2rem 0;
            width: 100%;
        }
        div[class*="st-key-analysis_period_"] [data-testid="stHorizontalBlock"] {
            align-items: end;
        }
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] label,
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] label {
            color: #52657F;
            font-size: 0.72rem;
            font-weight: 800;
            display: block;
            text-align: center;
        }
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] input,
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"],
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"],
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] input {
            text-align: center !important;
        }
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"] {
            justify-content: center !important;
            padding-left: 0 !important;
        }
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] > div > div:first-child,
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"] > div:first-child,
        div[class*="st-key-analysis_period_"] [data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"] > div:first-child > div {
            flex: 1 1 auto;
            width: 100%;
            text-align: center !important;
        }
        [data-testid="stSelectbox"] label,
        [data-testid="stMultiSelect"] label,
        [data-testid="stDateInput"] label {
            color: #082957 !important;
            font-size: 0.84rem !important;
            font-weight: 900 !important;
            letter-spacing: 0.01em;
        }
        [data-testid="stSelectbox"] > div > div,
        [data-testid="stMultiSelect"] > div > div,
        [data-testid="stDateInput"] > div > div {
            background: linear-gradient(135deg, #2F80ED 0%, #1D5FBF 100%) !important;
            border-color: #4B8DEF !important;
            box-shadow: 0 4px 12px rgba(8, 45, 97, 0.18);
        }
        [data-testid="stSelectbox"] > div > div *,
        [data-testid="stMultiSelect"] > div > div *,
        [data-testid="stDateInput"] input {
            color: #F8FBFF !important;
        }
        [data-testid="stSelectbox"] svg,
        [data-testid="stMultiSelect"] svg,
        [data-testid="stDateInput"] svg {
            fill: #BFD8FF !important;
            color: #BFD8FF !important;
        }
        [data-testid="stSelectbox"] > div > div:hover,
        [data-testid="stMultiSelect"] > div > div:hover,
        [data-testid="stDateInput"] > div > div:hover {
            border-color: #93C5FD !important;
            box-shadow: 0 5px 14px rgba(37, 99, 235, 0.28);
        }
        div[class*="st-key-monthly_kpi_start_month_control"] {
            max-width: 245px;
        }
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInput"] {
            max-width: 245px;
        }
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInput"] label {
            color: #52657F !important;
            display: block;
            font-size: 0.72rem !important;
            font-weight: 800 !important;
            text-align: center;
        }
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInputRootElement"] {
            background: linear-gradient(135deg, #2F80ED 0%, #1D5FBF 100%) !important;
            border: 1px solid #4B8DEF !important;
            border-radius: 0.55rem !important;
            box-shadow: 0 4px 12px rgba(8, 45, 97, 0.18);
        }
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInputField"] {
            background: transparent !important;
            color: #F8FBFF !important;
            -webkit-text-fill-color: #F8FBFF !important;
            font-weight: 750 !important;
            text-align: center !important;
        }
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInputRootElement"]:hover,
        div[class*="st-key-monthly_kpi_start_month_control"] [data-testid="stTextInputRootElement"]:focus-within {
            border-color: #93C5FD !important;
            box-shadow: 0 5px 14px rgba(37, 99, 235, 0.28);
        }
        div[class*="st-key-monthly_kpi_area"] {
            max-width: 245px;
            width: 245px;
        }
        div[class*="st-key-monthly_kpi_area"] [data-testid="stButtonGroup"] {
            max-width: 245px;
            width: 245px;
        }
        div[class*="st-key-monthly_kpi_area"] [data-testid="stWidgetLabel"] {
            display: flex;
            justify-content: center;
        }
        div[class*="st-key-monthly_kpi_area"] [data-testid="stWidgetLabel"] p {
            color: #52657F !important;
            font-size: 0.72rem !important;
            font-weight: 800 !important;
        }
        div[class*="st-key-monthly_kpi_area"] [role="radiogroup"] {
            height: 40px;
            margin: 0 !important;
            overflow: hidden;
            padding: 0 !important;
            width: 245px;
        }
        div[class*="st-key-monthly_kpi_area"] [role="radio"] {
            background: #F8FBFF !important;
            border-color: #B8CBE3 !important;
            color: #274463 !important;
            flex: 1 1 50%;
            height: 40px;
            justify-content: center;
        }
        div[class*="st-key-monthly_kpi_area"] [role="radio"] p {
            color: inherit !important;
            font-weight: 750 !important;
        }
        div[class*="st-key-monthly_kpi_area"] [role="radio"][data-selected="true"] {
            background: linear-gradient(135deg, #2F80ED 0%, #1D5FBF 100%) !important;
            border-color: #4B8DEF !important;
            color: #F8FBFF !important;
            box-shadow: 0 4px 12px rgba(8, 45, 97, 0.18);
        }
        div[class*="st-key-monthly_kpi_area"] [role="radio"]:hover {
            border-color: #93C5FD !important;
        }
        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] { padding-left: 0.7rem !important; padding-right: 0.7rem !important; }
            .topnav-brand small { display: none; }
            div[class*="st-key-top_nav_module_"] button { font-size: 0.66rem; padding-left: 0.22rem; padding-right: 0.22rem; }
            div[class*="st-key-top_nav_tab_"] button { font-size: 0.66rem; padding-left: 0.28rem; padding-right: 0.28rem; }
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
            text-align: center;
        }
        .module-title {
            text-align: center;
        }
        .home-module-gap {
            height: 1.15rem;
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
        [class*="st-key-home_card_"] [data-testid="stVerticalBlockBorderWrapper"] {
            min-height: 246px;
            border: 1px solid var(--border) !important;
            border-radius: 0.75rem !important;
            background: #FFFFFF !important;
            box-shadow: 0 4px 18px rgba(16, 24, 40, 0.06);
        }
        [class*="st-key-home_card_"] [data-testid="stVerticalBlock"] {
            gap: 0.35rem;
            text-align: center;
        }
        [class*="st-key-home_card_"] div[data-testid="stButton"] {
            margin-top: auto;
        }
        [class*="st-key-home_card_"] div[data-testid="stButton"] button {
            min-height: 36px;
            border: 0 !important;
            border-radius: 0.45rem !important;
            color: #FFFFFF !important;
            background: linear-gradient(135deg, #1D5FBF, #071F41) !important;
            box-shadow: 0 8px 16px rgba(16, 24, 40, 0.12);
            font-size: 0.84rem !important;
            font-weight: 800 !important;
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
            color: #2563EB !important;
            font-weight: 900;
            margin: 0.15rem 0 0.4rem 0;
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
            min-height: 7.9rem;
            box-sizing: border-box;
            text-align: center;
        }
        .metric-card.kpi-target-on { background:#E8FAEF !important; border:1px solid #86D5A6; border-left:6px solid #0D7A45; position:relative; }
        .metric-card.kpi-target-below { background:#FFE8E8 !important; border:1px solid #F39A9A; border-left:6px solid #DC2626; box-shadow:0 8px 22px rgba(220,38,38,.16); position:relative; }
        .metric-card.kpi-target-on .metric-value { color:#08703B !important; }
        .metric-card.kpi-target-below .metric-value { color:#B91C1C !important; }
        .metric-label { color: #0B1F3A; font-size: 0.78rem; font-weight: 900; text-transform: uppercase; }
        .metric-value { color: #061B36; font-size: 1.65rem; font-weight: 900; margin-top: 0.15rem; }
        .kpi-target-status { margin-top: 0.32rem; font-size: 0.71rem; font-weight: 900; letter-spacing: 0.01em; }
        .kpi-target-status.on-target { color: #08703B; }
        .kpi-target-status.below-target { color: #B91C1C; }
        .metric-card.kpi-target-on .metric-label, .metric-card.kpi-target-below .metric-label { padding-right:1.8rem; text-align:left; }
        .metric-card.kpi-target-on, .metric-card.kpi-target-below { text-align:left; }
        .home-overview-kpi.kpi-target-on .label, .home-overview-kpi.kpi-target-below .label { padding-right:1.25rem; }
        .kpi-target-icon { align-items:center; border-radius:50%; color:#fff; display:flex; font-size:.92rem; font-weight:950; height:1.48rem; justify-content:center; line-height:1; position:absolute; right:.72rem; top:.7rem; width:1.48rem; }
        .kpi-target-icon.on-target { background:#0D7A45; }
        .kpi-target-icon.below-target { background:#DC2626; box-shadow:0 3px 8px rgba(185,28,28,.28); }
        .dashboard-kpi-chart-gap { height: 0.9rem; }
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
        div[data-testid="stPlotlyChart"] .js-plotly-plot,
        div[data-testid="stPlotlyChart"] .plot-container {
            overflow: visible !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-container {
            top: 0.18rem !important;
            right: 0.18rem !important;
            max-width: calc(100% - 1rem) !important;
            overflow: visible !important;
            z-index: 15 !important;
        }
        div[data-testid="stPlotlyChart"] .modebar {
            align-items: center !important;
            background: rgba(255,255,255,0.96) !important;
            border: 1px solid #D6DFEB !important;
            border-radius: 0.48rem !important;
            box-shadow: 0 5px 14px rgba(15,35,65,0.10) !important;
            display: flex !important;
            gap: 0.08rem !important;
            max-width: 100% !important;
            overflow: visible !important;
            padding: 0.08rem 0.18rem !important;
        }
        div[data-testid="stElementContainer"]:has(div[data-testid="stPlotlyChart"])
        div[data-testid="stElementToolbar"] {
            right: 0.35rem !important;
            top: 0.35rem !important;
            z-index: 20 !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-btn[data-title*="Download plot as" i] {
            display: none !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-btn.jovi-copy-chart-button {
            align-items: center !important;
            color: #52647A !important;
            cursor: pointer !important;
            display: inline-flex !important;
            font-size: 1rem !important;
            font-weight: 900 !important;
            height: 1.65rem !important;
            justify-content: center !important;
            line-height: 1 !important;
            width: 1.65rem !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-btn.jovi-copy-chart-button:hover {
            color: #0B1F3A !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-btn.jovi-download-svg-button {
            align-items: center !important;
            color: #52647A !important;
            cursor: pointer !important;
            display: inline-flex !important;
            font-family: Arial, sans-serif !important;
            font-size: 0.63rem !important;
            font-weight: 900 !important;
            height: 1.65rem !important;
            justify-content: center !important;
            letter-spacing: 0.02em !important;
            line-height: 1 !important;
            width: 2rem !important;
        }
        div[data-testid="stPlotlyChart"] .modebar-btn.jovi-download-svg-button:hover {
            color: #0B1F3A !important;
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
            overflow: hidden;
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
            overflow-x: auto;
            overflow-y: visible;
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
        .data-table.inspection-history-table th,
        .data-table.inspection-history-table td {
            text-align: center;
            vertical-align: middle;
        }
        .data-table-wrap.assembly-inspection-history-table {
            overflow-x: visible;
        }
        .data-table.assembly-inspection-history-table {
            min-width: 0;
            table-layout: fixed;
            font-size: 0.68rem;
        }
        .data-table.assembly-inspection-history-table th,
        .data-table.assembly-inspection-history-table td {
            padding: 0.45rem 0.24rem;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .data-table.assembly-inspection-history-table th:nth-child(1) { width: 3%; }
        .data-table.assembly-inspection-history-table th:nth-child(2) { width: 7%; }
        .data-table.assembly-inspection-history-table th:nth-child(3) { width: 7%; }
        .data-table.assembly-inspection-history-table th:nth-child(4),
        .data-table.assembly-inspection-history-table th:nth-child(5),
        .data-table.assembly-inspection-history-table th:nth-child(6),
        .data-table.assembly-inspection-history-table th:nth-child(8),
        .data-table.assembly-inspection-history-table th:nth-child(9),
        .data-table.assembly-inspection-history-table th:nth-child(10) { width: 6%; }
        .data-table.assembly-inspection-history-table th:nth-child(7),
        .data-table.assembly-inspection-history-table th:nth-child(11),
        .data-table.assembly-inspection-history-table th:nth-child(12) { width: 7%; }
        .data-table.assembly-inspection-history-table th:nth-child(13) { width: 10%; }
        .data-table.assembly-inspection-history-table th:nth-child(14) { width: 8%; }
        .data-table-wrap.compact-dashboard-table {
            overflow-x: visible;
        }
        .data-table.compact-dashboard-table {
            min-width: 0;
            table-layout: fixed;
            font-size: 0.70rem;
        }
        .data-table.compact-dashboard-table th,
        .data-table.compact-dashboard-table td {
            padding: 0.46rem 0.36rem;
            overflow-wrap: anywhere;
            word-break: break-word;
            line-height: 1.25;
        }
        .data-table-wrap.kpi-formula-table {
            margin-bottom: 2rem;
            overflow-x: visible;
        }
        .data-table.kpi-formula-table {
            min-width: 0;
            table-layout: fixed;
            font-size: 0.78rem;
        }
        .data-table.kpi-formula-table th,
        .data-table.kpi-formula-table td {
            padding: 0.62rem 0.58rem;
            text-align: center;
            vertical-align: middle;
            overflow-wrap: normal;
            word-break: normal;
            line-height: 1.35;
        }
        .data-table.kpi-formula-table th:nth-child(1) { width: 23%; }
        .data-table.kpi-formula-table th:nth-child(2) { width: 31%; }
        .data-table.kpi-formula-table th:nth-child(3) { width: 29%; }
        .data-table.kpi-formula-table th:nth-child(4) { width: 17%; }
        .data-table.kpi-formula-table td:nth-child(1) {
            font-weight: 800;
        }
        .data-table.kpi-formula-table td:nth-child(3) {
            color: #29415F;
        }
        .data-table.kpi-formula-table td:nth-child(4) {
            white-space: nowrap;
            font-weight: 900;
            color: #0D7A45;
        }
        .action-priority-list {
            display: grid;
            gap: 0.4rem;
            margin-top: 0.4rem;
        }
        .action-priority-card {
            background: #FFFFFF;
            border: 1px solid #D6DFEB;
            border-left: 4px solid var(--priority-color, #64748B);
            border-radius: 0.75rem;
            box-shadow: 0 5px 16px rgba(15, 35, 65, 0.07);
            padding: 0.55rem 0.65rem;
        }
        .action-priority-card.critical { --priority-color: #DC2626; }
        .action-priority-card.high { --priority-color: #EA580C; }
        .action-priority-card.medium { --priority-color: #D97706; }
        .action-priority-card.monitor { --priority-color: #2563EB; }
        .action-priority-header {
            align-items: flex-start;
            display: grid;
            gap: 0.45rem;
            grid-template-columns: auto minmax(0, 1fr) auto;
        }
        .action-priority-rank {
            align-items: center;
            background: var(--priority-color, #64748B);
            border-radius: 999px;
            color: #FFFFFF;
            display: inline-flex;
            font-size: 0.64rem;
            font-weight: 900;
            height: 1.55rem;
            justify-content: center;
            width: 1.55rem;
        }
        .action-priority-name {
            color: #0B1F3A;
            font-size: 0.76rem;
            font-weight: 900;
            line-height: 1.25;
            overflow-wrap: anywhere;
        }
        .action-priority-badge {
            background: color-mix(in srgb, var(--priority-color, #64748B) 10%, white);
            border: 1px solid color-mix(in srgb, var(--priority-color, #64748B) 28%, white);
            border-radius: 999px;
            color: var(--priority-color, #64748B);
            font-size: 0.63rem;
            font-weight: 900;
            padding: 0.18rem 0.45rem;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .action-priority-body {
            align-items: end;
            display: grid;
            gap: 0.5rem;
            grid-template-columns: minmax(0, 1fr) auto;
            margin-left: 2rem;
            margin-top: 0.25rem;
        }
        .action-priority-context {
            color: #52647A;
            font-size: 0.62rem;
            line-height: 1.35;
            min-width: 0;
            overflow-wrap: anywhere;
        }
        .action-priority-context b {
            color: #0B1F3A;
            font-weight: 850;
        }
        .action-priority-metrics {
            display: flex;
            gap: 0.55rem;
            text-align: right;
        }
        .action-priority-metric strong {
            color: #0B1F3A;
            display: block;
            font-size: 0.72rem;
            font-variant-numeric: tabular-nums;
            font-weight: 900;
            line-height: 1.1;
        }
        .action-priority-metric small {
            color: #6B7C90;
            display: block;
            font-size: 0.58rem;
            font-weight: 800;
            margin-top: 0.15rem;
            text-transform: uppercase;
        }
        @media (max-width: 900px) {
            .action-priority-body {
                align-items: start;
                grid-template-columns: 1fr;
            }
            .action-priority-metrics {
                justify-content: flex-start;
                text-align: left;
            }
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
            margin-top: 0.25rem;
            border-radius: 0.55rem;
            font-size: 0.72rem;
            line-height: 1.25;
        }
        .small-muted { color: #17243A; font-size: 0.85rem; font-weight: 650; }
        .smart-report-title { color:#0B1F3A; font-size:2.05rem; font-weight:900; letter-spacing:-.03em; margin:.1rem 0 .2rem; }
        .smart-report-subtitle { color:#53657D; font-size:.93rem; font-weight:650; margin:0 0 1.1rem; }
        .smart-control-label { color:#50627B; font-size:.78rem; font-weight:850; letter-spacing:.02em; margin:0 0 .35rem; text-transform:uppercase; }
        .smart-kpi { background:#FFF; border:1px solid #E1E8F2; border-radius:.75rem; min-height:104px; padding:1rem 1.05rem; box-shadow:0 6px 17px rgba(15,35,65,.06); box-sizing:border-box; }
        .smart-kpi-label { color:#5C6B80; font-size:.82rem; font-weight:800; margin-bottom:.32rem; }
        .smart-kpi-value { color:#102440; font-size:1.65rem; font-weight:900; letter-spacing:-.04em; line-height:1.05; }
        .smart-kpi-note { color:#0D8A50; font-size:.73rem; font-weight:800; margin-top:.36rem; }
        .smart-kpi-note.attention { color:#C2410C; }
        .smart-area-panel,.smart-whatsapp-panel { background:#FFF; border:1px solid #DCE5F0; border-radius:.8rem; padding:1rem; box-shadow:0 6px 18px rgba(15,35,65,.055); box-sizing:border-box; min-height:400px; }
        .smart-area-head { display:flex; align-items:center; gap:.6rem; margin-bottom:.25rem; }
        .smart-area-icon { display:inline-flex; align-items:center; justify-content:center; width:29px; height:29px; border-radius:.45rem; color:#FFF; font-size:.85rem; font-weight:900; }
        .smart-area-title { font-size:1.22rem; font-weight:900; }
        .smart-area-caption { color:#5C6B80; font-size:.76rem; font-weight:750; margin:0 0 .85rem; }
        .smart-defect-list { border:1px solid #DDE6F0; border-radius:.6rem; overflow:hidden; margin:.4rem 0 .85rem; }
        .smart-defect-item { display:grid; grid-template-columns:26px minmax(0,1fr) auto; align-items:center; gap:.55rem; min-height:45px; padding:.52rem .6rem; border-bottom:1px solid #E7EDF5; color:#152941; font-size:.8rem; font-weight:800; box-sizing:border-box; }
        .smart-defect-item:last-child { border-bottom:0; }
        .smart-defect-item.selected { background:#F1FBF6; }
        .smart-defect-rank { align-items:center; border-radius:.35rem; color:#FFF; display:inline-flex; font-size:.75rem; font-weight:900; height:24px; justify-content:center; width:24px; }
        .smart-defect-meta { color:#54667D; font-size:.75rem; font-weight:800; text-align:right; white-space:nowrap; }
        .smart-action-summary { background:#F8FBFD; border:1px solid #D8E6DD; border-radius:.58rem; overflow:hidden; }
        .smart-action-row { display:grid; grid-template-columns:100px minmax(0,1fr); gap:.5rem; padding:.6rem .7rem; border-bottom:1px solid #E3EBE7; color:#32445B; font-size:.75rem; line-height:1.34; }
        .smart-action-row:last-child { border-bottom:0; }
        .smart-action-label { color:#13273F; font-weight:900; }
        .smart-preview-copy { background:#F7FCF9; border:1px solid #B9DEC7; border-radius:.58rem; color:#173421; font-family:Consolas,"Courier New",monospace; font-size:.75rem; font-weight:650; line-height:1.55; min-height:248px; padding:.85rem; white-space:pre-wrap; }
        .smart-preview-footnote { color:#63728A; font-size:.73rem; font-weight:700; margin:.72rem 0 .2rem; }
        /* Home overview: independent operational summary for SMT and Assembly. */
        .home-overview-head { margin:.75rem 0 .6rem; }
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) { padding-top:.5rem !important; padding-bottom:.5rem !important; }
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) > [data-testid="stVerticalBlock"] { gap:.75rem !important; }
        .home-overview-head h1 { color:#081f45; font-size:1.72rem; letter-spacing:-.045em; line-height:1.05; margin:0; padding:0 !important; }
        .home-trend-heading {border-left:4px solid var(--home-area);padding:.1rem 0 .2rem .75rem;margin:.4rem 0 .15rem;min-height:2.7rem;}
        .home-trend-heading strong {display:block;color:#102d5b;font-size:1rem;line-height:1.25;}
        .home-trend-heading small {display:block;color:#7187a1;font-size:.7rem;margin-top:.12rem;}
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) .rangeslider-slidebox {fill:#AFCFFF !important;fill-opacity:.72 !important;}
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) .rangeslider-mask-min,
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) .rangeslider-mask-max {fill:#D7E0ED !important;fill-opacity:.82 !important;}
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) .rangeslider-handle-min,
        [data-testid="stMainBlockContainer"]:has(.home-overview-head) .rangeslider-handle-max {fill:#FFFFFF !important;stroke:#3469B3 !important;stroke-width:1.5px !important;}
        .home-detail-scroll {max-width:100%;overflow-x:auto;overflow-y:auto;border:1px solid #d5e2f0;border-radius:.5rem;background:#fff;max-height:460px;}
        .home-detail-table {border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;font-size:.72rem;color:#17375f;}
        .home-detail-table th,.home-detail-table td {box-sizing:border-box;border-bottom:1px solid #e5edf6;padding:.48rem .55rem;text-align:left;white-space:nowrap;min-width:148px;}
        .home-detail-table thead th {background:#123f81;color:#fff;font-weight:800;position:sticky;top:0;z-index:2;min-width:150px;}
        .home-detail-table .sticky-model {position:sticky;left:0;z-index:3;min-width:175px;width:175px;background:#f8fbff;font-weight:800;}
        .home-detail-table .sticky-kpi {position:sticky;left:175px;z-index:3;min-width:210px;width:210px;background:#f8fbff;box-shadow:4px 0 8px rgba(17,56,103,.12);}
        .home-detail-table thead .sticky-model,.home-detail-table thead .sticky-kpi {background:#123f81;z-index:4;color:#fff;}
        .home-detail-table tbody tr:nth-child(even) td {background:#f8fbff;}
        .home-detail-table td strong {display:block;color:#0c724a;}
        .home-detail-table td small {display:block;color:#6b819d;font-size:.66rem;}
        .home-detail-table td.on-target {background:#eaf8f0 !important;}
        .home-detail-table td.below-target {background:#fff0ef !important;}
        .home-detail-table td.below-target strong {color:#bc2a2a;}
        .home-detail-table td.empty {color:#8294aa;}
        .home-area-shell { background:#fff; border:1px solid #dbe6f2; border-top:5px solid var(--area-color); border-radius:.85rem; box-shadow:0 7px 19px rgba(16,42,78,.07); margin:.15rem 0 .7rem; overflow:hidden; padding:1rem; }
        .home-area-heading { align-items:center; display:flex; gap:.65rem; justify-content:space-between; margin:0 0 .55rem; }
        .home-area-heading h2 { color:#102747; font-size:1.2rem; letter-spacing:-.025em; margin:0; }
        .home-area-heading small { color:#65758e; display:block; font-size:.76rem; font-weight:700; margin-top:.1rem; }
        .home-area-status { background:var(--area-soft); border-radius:99px; color:var(--area-color); font-size:.72rem; font-weight:900; padding:.36rem .62rem; white-space:nowrap; }
        .home-area-status.attention { background:#fff3df; color:#b76200; }
        .home-overview-kpi { background:#fbfdff; border:1px solid #e0e9f3; border-radius:.58rem; height:9.5rem; box-sizing:border-box; display:flex; flex-direction:column; margin-bottom:.75rem; padding:.62rem .68rem; position:relative; }
        .home-overview-kpi.kpi-target-on { background:#E8FAEF !important; border:1px solid #86D5A6; border-left:4px solid #0D7A45; }
        .home-overview-kpi.kpi-target-below { background:#FFE8E8 !important; border:1px solid #F39A9A; border-left:4px solid #DC2626; }
        .home-overview-kpi.kpi-target-on .value { color:#08703B !important; }
        .home-overview-kpi.kpi-target-below .value { color:#B91C1C !important; }
        .home-overview-kpi .label { color:#526781; font-size:.7rem; font-weight:850; line-height:1.2; min-height:30px; }
        .home-overview-kpi .value { color:var(--kpi-color); font-size:1.34rem; font-weight:900; letter-spacing:-.045em; line-height:1.06; margin:.22rem 0; }
        .home-overview-kpi .note { color:#77869a; font-size:.61rem; font-weight:700; line-height:1.2; min-height:25px; }
        .home-overview-kpi .target-state { font-size:.58rem; font-weight:900; line-height:1.1; min-height:11px; }
        .home-overview-kpi .target-state.on-target { color:#08703B; }
        .home-overview-kpi .target-state.below-target { color:#B91C1C; }
        .home-overview-kpi .kpi-target-icon { font-size:.65rem; height:1.15rem; right:.45rem; top:.42rem; width:1.15rem; }
        .home-overview-kpi .spark { border-radius:99px; height:3px; flex-shrink:0; margin-top:auto; opacity:.8; background:linear-gradient(90deg,var(--kpi-color) 0 26%,transparent 26% 34%,var(--kpi-color) 34% 57%,transparent 57% 65%,var(--kpi-color) 65% 100%); }
        .home-overview-actions { margin-top:.1rem; }
        div[class*="st-key-analysis_period_home_overview"] { margin-top:0 !important; margin-bottom:.35rem; padding-top:.25rem !important; padding-bottom:.15rem; }
        /* Streamlit applies a text-fill color to date inputs; override it so the
           selected range has the same white contrast as the quick selector. */
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] input,
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInput"] input,
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] input::placeholder,
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInput"] input::placeholder,
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] [contenteditable="true"],
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInput"] [contenteditable="true"],
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] [data-type="literal"],
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInput"] [data-type="literal"],
        div[class*="st-key-analysis_period_"] [data-testid="stDateInput"] > div > span,
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInput"] > div > span,
        div[class*="st-key-analysis_period_"] [data-testid="stDateInputField"] > span,
        div[class*="st-key-weekly_kpi_week_end"] [data-testid="stDateInputField"] > span {
            color:#F8FBFF !important;
            -webkit-text-fill-color:#F8FBFF !important;
            opacity:1 !important;
        }
        div[class*="st-key-home_overview_smt"] { border-top:4px solid #0D7A45 !important; }
        div[class*="st-key-home_overview_assembly"] { border-top:4px solid #6532C8 !important; }
        div[class*="st-key-home_open_smt_kpi"] button { background:#0D7A45 !important; border-color:#0D7A45 !important; }
        div[class*="st-key-home_open_assembly_kpi"] button { background:#6532C8 !important; border-color:#6532C8 !important; }
        .home-model-heading { display:flex;align-items:end;justify-content:space-between;gap:1rem;margin:.65rem 0 .55rem; }
        .home-model-heading h2 { color:#102D5B;font-size:1.3rem;line-height:1.1;margin:0 0 .2rem; }
        .home-model-heading p,.home-model-count { color:#607895;font-size:.76rem;margin:0; }
        .home-model-count { font-weight:800;white-space:nowrap; }
        .home-model-row { display:grid;grid-template-columns:minmax(145px,18%) minmax(0,1fr) minmax(0,1fr);gap:0;background:#fff;border:1px solid #D3DDED;border-left:5px solid var(--row-color);border-radius:.72rem;margin:0 0 .5rem;min-height:148px;box-sizing:border-box; }
        .home-model-row:hover,.home-model-row:focus-within { position:relative;z-index:2; }
        .home-model-id { padding:.85rem .9rem;min-width:0; }
        .home-model-id strong { color:#102D5B;display:block;font-size:1.08rem;overflow-wrap:anywhere; }
        .home-model-id small { color:#7085A0;display:block;font-size:.68rem;margin:.24rem 0 .55rem; }
        .home-model-badge { background:var(--badge-bg);border-radius:99px;color:var(--badge-color);display:inline-block;font-size:.67rem;font-weight:850;padding:.35rem .55rem; }
        .home-model-chart { border-left:1px solid #E0E7F2;min-width:0;padding:.75rem .8rem .45rem; }
        .home-model-chart-head { align-items:baseline;display:flex;gap:.5rem;justify-content:space-between;min-height:1.55rem; }
        .home-model-chart-head b { color:#18365E;font-size:.78rem; }
        .home-model-chart-head strong { color:var(--value-color);font-size:1.02rem;white-space:nowrap; }
        .home-model-chart-note { color:#7789A0;font-size:.64rem;margin-top:-.1rem; }
        .home-model-svg { display:block;height:96px;width:100%;overflow:visible; }
        .home-model-point { cursor:help;outline:none; }
        .home-model-point .home-model-tooltip { opacity:0;pointer-events:none;transition:opacity .12s ease; }
        .home-model-point:hover .home-model-tooltip,
        .home-model-point:focus .home-model-tooltip { opacity:1; }
        .home-model-point:focus .home-model-dot { stroke:#0B2D5A;stroke-width:2.5; }
        .home-model-empty { color:#8393A8;display:flex;align-items:center;font-size:.72rem;height:82px; }
        @media (max-width:900px) {
            .home-model-row { grid-template-columns:1fr 1fr; }
            .home-model-id { grid-column:1 / -1;padding:.7rem .8rem; }
            .home-model-chart:nth-child(2) { border-left:0; }
        }
        @media (max-width:600px) {
            .home-model-row { grid-template-columns:1fr; }
            .home-model-chart { border-left:0;border-top:1px solid #E0E7F2; }
        }
        .weekly-review-period { color:#526781; font-size:.82rem; font-weight:850; margin:.15rem 0 .55rem; }
        .jovi-copy-kpi-table { align-items:center; background:#FFF; border:1px solid #C9D7E7; border-radius:.45rem; box-shadow:0 2px 6px rgba(20,48,86,.10); color:#173A67; cursor:pointer; display:flex; font-size:.76rem; font-weight:850; gap:.35rem; margin:0 0 .38rem auto; padding:.38rem .62rem; }
        .jovi-copy-kpi-table:hover { background:#F2F7FD; border-color:#2F80ED; }
        .weekly-review-wrap { border:1px solid #B9C8DB; border-radius:.65rem; margin:.15rem 0 1rem; max-width:100%; overflow:visible; width:fit-content; }
        .weekly-review-wrap.weekly-layout { width:100%; }
        .weekly-review-table { border-collapse:collapse; font-size:.76rem; min-width:0; table-layout:fixed; width:max-content; }
        .weekly-review-table.weekly-layout { width:100%; }
        .weekly-review-table th { background:#072964; border:1px solid #244776; color:#FFF; font-weight:850; padding:.48rem .5rem; text-align:center; white-space:nowrap; }
        .weekly-review-table td { border:1px solid #C8D4E3; color:#152941; padding:.34rem .48rem; text-align:center; white-space:nowrap; }
        .weekly-review-table col.weekly-col-area { width:72px; }
        .weekly-review-table col.weekly-col-kpi { width:260px; }
        .weekly-review-table col.weekly-col-meta { width:92px; }
        .weekly-review-table col.weekly-col-summary,
        .weekly-review-table col.weekly-col-day { width:68px; }
        .weekly-review-table.weekly-layout col.weekly-col-area { width:6%; }
        .weekly-review-table.weekly-layout col.weekly-col-kpi { width:16%; }
        .weekly-review-table.weekly-layout col.weekly-col-meta { width:8%; }
        .weekly-review-table.weekly-layout col.weekly-col-summary,
        .weekly-review-table.weekly-layout col.weekly-col-day { width:6%; }
        .weekly-review-table.weekly-layout .weekly-kpi-name { white-space:normal; }
        .weekly-review-table .weekly-area { font-weight:900; vertical-align:middle; }
        .weekly-review-table .weekly-kpi-name { text-align:left; font-weight:800; }
        .weekly-review-table .weekly-value { font-weight:900; }
        .weekly-review-table .weekly-value.on-target { background:#9DDD64; color:#123A22; }
        .weekly-review-table .weekly-value.below { background:#FF9B9B; color:#7A1010; }
        .weekly-review-table .weekly-value.unavailable { background:#F4F7FB; color:#8795A8; }
        .weekly-review-table .weekly-value.exception { background:#FEF2F2; color:#DC2626; font-size:1rem; }
        hr { border-color: var(--border) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def apply_login_css() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        [data-testid="stHeader"] {
            display: none !important;
        }

        html, body, [class*="css"] {
            font-family: "Segoe UI", Arial, sans-serif !important;
        }

        .stApp {
            color: #0B1F3A !important;
            background:
                radial-gradient(circle at 12% 18%, rgba(29, 95, 191, 0.16), transparent 30rem),
                radial-gradient(circle at 88% 84%, rgba(13, 122, 69, 0.12), transparent 28rem),
                #F4F7FB !important;
        }

        [data-testid="stMain"] {
            min-height: 100vh;
        }

        [data-testid="stMainBlockContainer"] {
            max-width: 1180px !important;
            min-height: 100vh;
            padding: 8vh 2rem 4rem !important;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        [data-testid="stHorizontalBlock"] {
            align-items: center;
            gap: 4rem;
        }

        .login-brand {
            display: inline-flex;
            align-items: center;
            gap: 0.65rem;
            color: #0B1F3A;
            font-size: 0.78rem;
            font-weight: 900;
            letter-spacing: 0.13em;
            text-transform: uppercase;
        }

        .login-brand-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 3.4rem;
            height: 3.4rem;
            border-radius: 1rem;
            color: #FFFFFF;
            background: linear-gradient(145deg, #0B1F3A 0%, #1D5FBF 100%);
            box-shadow: 0 14px 32px rgba(11, 31, 58, 0.20);
            font-size: 0.82rem;
            letter-spacing: 0.05em;
        }

        .login-eyebrow {
            margin-top: 4rem;
            color: #0D7A45;
            font-size: 0.78rem;
            font-weight: 900;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .login-hero h1 {
            max-width: 610px;
            margin: 0.85rem 0 1.1rem;
            color: #071B33;
            font-size: clamp(2.7rem, 5vw, 4.8rem);
            line-height: 0.98;
            letter-spacing: -0.045em;
        }

        .login-hero p {
            max-width: 560px;
            margin: 0;
            color: #536174;
            font-size: 1.02rem;
            line-height: 1.65;
        }

        .login-pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.65rem;
            margin-top: 2rem;
        }

        .login-pill {
            padding: 0.55rem 0.8rem;
            border: 1px solid #D5DFEC;
            border-radius: 999px;
            color: #29415F;
            background: rgba(255,255,255,0.68);
            font-size: 0.78rem;
            font-weight: 800;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid rgba(191, 203, 219, 0.86) !important;
            border-radius: 1.3rem !important;
            background: rgba(255,255,255,0.94) !important;
            box-shadow: 0 26px 70px rgba(11, 31, 58, 0.14);
        }

        [data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 0.65rem 0.7rem !important;
        }

        .login-card-kicker {
            color: #1D5FBF;
            font-size: 0.76rem;
            font-weight: 900;
            letter-spacing: 0.10em;
            text-transform: uppercase;
        }

        .login-card-title {
            margin: 0.45rem 0 0.25rem;
            color: #071B33;
            font-size: 2rem;
            font-weight: 900;
            letter-spacing: -0.03em;
        }

        .login-card-copy {
            margin: 0 0 1rem;
            color: #657286;
            font-size: 0.92rem;
        }

        div[data-testid="stForm"] {
            border: 0 !important;
            padding: 0 !important;
        }

        div[data-testid="stTextInput"] label {
            color: #243B5A !important;
            font-size: 0.83rem !important;
            font-weight: 800 !important;
        }

        div[data-testid="stTextInput"] input {
            min-height: 3rem;
            border-color: #CBD7E6;
            border-radius: 0.72rem;
            color: #071B33;
            background: #F9FBFD;
        }

        div[data-testid="stTextInput"] input:focus {
            border-color: #1D5FBF;
            box-shadow: 0 0 0 3px rgba(29, 95, 191, 0.13);
        }

        div[data-testid="stFormSubmitButton"] button {
            min-height: 3.05rem;
            margin-top: 0.35rem;
            border: 0 !important;
            border-radius: 0.72rem !important;
            color: #FFFFFF !important;
            background: linear-gradient(135deg, #0B4F9C, #1D6FD1) !important;
            box-shadow: 0 10px 24px rgba(29, 95, 191, 0.24);
            font-weight: 900 !important;
        }

        .login-security-note {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.8rem;
            color: #68778B;
            font-size: 0.76rem;
            font-weight: 700;
        }

        .login-security-dot {
            width: 0.52rem;
            height: 0.52rem;
            border-radius: 50%;
            background: #0D7A45;
            box-shadow: 0 0 0 4px rgba(13,122,69,0.12);
        }

        .smart-report-title {
            color: #0B1F3A;
            font-size: 2.05rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            margin: 0.1rem 0 0.2rem 0;
        }
        .smart-report-subtitle { color: #53657D; font-size: 0.93rem; font-weight: 650; margin: 0 0 1.1rem 0; }
        .smart-control-label { color: #50627B; font-size: 0.78rem; font-weight: 850; letter-spacing: 0.02em; margin: 0 0 0.35rem 0; text-transform: uppercase; }
        .smart-kpi { background:#FFF; border:1px solid #E1E8F2; border-radius:.75rem; min-height:104px; padding:1rem 1.05rem; box-shadow:0 6px 17px rgba(15,35,65,.06); box-sizing:border-box; }
        .smart-kpi-label { color:#5C6B80; font-size:.82rem; font-weight:800; margin-bottom:.32rem; }
        .smart-kpi-value { color:#102440; font-size:1.65rem; font-weight:900; letter-spacing:-.04em; line-height:1.05; }
        .smart-kpi-note { color:#0D8A50; font-size:.73rem; font-weight:800; margin-top:.36rem; }
        .smart-kpi-note.attention { color:#C2410C; }
        .smart-area-panel,.smart-whatsapp-panel { background:#FFF; border:1px solid #DCE5F0; border-radius:.8rem; padding:1rem; box-shadow:0 6px 18px rgba(15,35,65,.055); box-sizing:border-box; min-height:400px; }
        .smart-area-head { display:flex; align-items:center; gap:.6rem; margin-bottom:.25rem; }
        .smart-area-icon { display:inline-flex; align-items:center; justify-content:center; width:29px; height:29px; border-radius:.45rem; color:#FFF; font-size:.85rem; font-weight:900; }
        .smart-area-title { font-size:1.22rem; font-weight:900; }
        .smart-area-caption { color:#5C6B80; font-size:.76rem; font-weight:750; margin:0 0 .85rem 0; }
        .smart-defect-list { border:1px solid #DDE6F0; border-radius:.6rem; overflow:hidden; margin:.4rem 0 .85rem 0; }
        .smart-defect-item { display:grid; grid-template-columns:26px minmax(0,1fr) auto; align-items:center; gap:.55rem; min-height:45px; padding:.52rem .6rem; border-bottom:1px solid #E7EDF5; color:#152941; font-size:.8rem; font-weight:800; box-sizing:border-box; }
        .smart-defect-item:last-child { border-bottom:0; }
        .smart-defect-item.selected { background:#F1FBF6; }
        .smart-defect-rank { align-items:center; border-radius:.35rem; color:#FFF; display:inline-flex; font-size:.75rem; font-weight:900; height:24px; justify-content:center; width:24px; }
        .smart-defect-meta { color:#54667D; font-size:.75rem; font-weight:800; text-align:right; white-space:nowrap; }
        .smart-action-summary { background:#F8FBFD; border:1px solid #D8E6DD; border-radius:.58rem; overflow:hidden; }
        .smart-action-row { display:grid; grid-template-columns:100px minmax(0,1fr); gap:.5rem; padding:.6rem .7rem; border-bottom:1px solid #E3EBE7; color:#32445B; font-size:.75rem; line-height:1.34; }
        .smart-action-row:last-child { border-bottom:0; }
        .smart-action-label { color:#13273F; font-weight:900; }
        .smart-preview-copy { background:#F7FCF9; border:1px solid #B9DEC7; border-radius:.58rem; color:#173421; font-family:Consolas,"Courier New",monospace; font-size:.75rem; font-weight:650; line-height:1.55; min-height:248px; padding:.85rem; white-space:pre-wrap; }
        .smart-preview-footnote { color:#63728A; font-size:.73rem; font-weight:700; margin:.72rem 0 .2rem 0; }

        @media (max-width: 820px) {
            [data-testid="stMainBlockContainer"] {
                padding: 2.5rem 1.1rem 3rem !important;
            }

            [data-testid="stHorizontalBlock"] {
                gap: 1.6rem;
            }

            .login-eyebrow {
                margin-top: 2.4rem;
            }

            .login-hero h1 {
                font-size: 2.65rem;
            }

            .login-pill-row {
                margin-bottom: 1rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def credentials_are_valid(username: str, password: str) -> bool:
    return authenticate(username, password, PORTAL_ACCOUNTS) is not None


def is_admin() -> bool:
    return is_admin_session(st.session_state)


def render_auth_cookie(token: str = "") -> None:
    """Write the signed browser cookie without exposing the password to JavaScript."""
    value = f"{COOKIE_NAME}={token}; Path=/; SameSite=Lax"
    value += f"; Max-Age={SESSION_SECONDS if token else 0}"
    st.html(
        "<script>document.cookie = " + json.dumps(value)
        + " + (location.protocol === 'https:' ? '; Secure' : '');"
        + "document.cookie = 'jovi_quality_auth_v1=; Path=/; SameSite=Lax; Max-Age=0';</script>",
        unsafe_allow_javascript=True,
    )


def restore_authentication() -> None:
    if st.session_state.get("authenticated"):
        current_user = st.session_state.get("authenticated_user")
        current_role = st.session_state.get("auth_role")
        if any(account.username == current_user and account.role == current_role for account in PORTAL_ACCOUNTS):
            return
        # Preserve existing administrator sessions across this deployment.
        if current_user == LOGIN_USERNAME and not current_role:
            st.session_state["auth_role"] = "admin"
            return
        st.session_state["authenticated"] = False
    token = st.context.cookies.get(COOKIE_NAME)
    account = account_from_token(token, PORTAL_ACCOUNTS)
    if account:
        st.session_state["authenticated"] = True
        st.session_state["authenticated_user"] = account.username
        st.session_state["auth_role"] = account.role
        st.session_state["auth_cookie_token"] = token


def login_page() -> None:
    apply_login_css()
    hero_column, form_column = st.columns([1.15, 0.85], gap="large")

    with hero_column:
        st.markdown(
            """
            <div class="login-hero">
                <div class="login-brand">
                    <span class="login-brand-mark">JOVI</span>
                    <span>Quality Center</span>
                </div>
                <div class="login-eyebrow">Quality intelligence portal</div>
                <h1>All Quality.<br>One Center.</h1>
                <p>
                    Process performance, critical failures and quality priorities
                    brought together in one reliable workspace.
                </p>
                <div class="login-pill-row">
                    <span class="login-pill">SMT performance</span>
                    <span class="login-pill">Assembly quality</span>
                    <span class="login-pill">Action-oriented analysis</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with form_column:
        with st.container(border=True):
            st.markdown(
                """
                <div class="login-card-kicker">Restricted access</div>
                <div class="login-card-title">Welcome back</div>
                <div class="login-card-copy">Enter your credentials to access the portal.</div>
                """,
                unsafe_allow_html=True,
            )
            with st.form("portal_login", clear_on_submit=False):
                username = st.text_input(
                    "Username",
                    placeholder="Enter your username",
                    autocomplete="username",
                )
                password = st.text_input(
                    "Password",
                    type="password",
                    placeholder="Enter your password",
                    autocomplete="current-password",
                )
                submitted = st.form_submit_button("Sign in", use_container_width=True)

            if submitted:
                account = authenticate(username, password, PORTAL_ACCOUNTS)
                if account:
                    st.session_state["authenticated"] = True
                    st.session_state["authenticated_user"] = account.username
                    st.session_state["auth_role"] = account.role
                    st.session_state["auth_cookie_token"] = issue_token(account.username, account.password_hash)
                    st.session_state.pop("auth_logout_pending", None)
                    st.session_state.pop("login_error", None)
                    st.rerun()
                else:
                    st.session_state["login_error"] = "Incorrect username or password."

            if st.session_state.get("login_error"):
                st.error(st.session_state["login_error"])

            st.markdown(
                """
                <div class="login-security-note">
                    <span class="login-security-dot"></span>
                    <span>Internal access &middot; authenticated session</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def logout() -> None:
    revoke_token(st.session_state.get("auth_cookie_token") or st.context.cookies.get(COOKIE_NAME))
    st.session_state.clear()
    st.session_state["auth_logout_pending"] = True
    st.query_params.clear()
    st.rerun()


def init_state() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "module" not in st.session_state:
        st.session_state.module = "Home"
    if "tab" not in st.session_state:
        st.session_state.tab = ""


def get_query_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def accessible_tabs(module: str) -> list[str]:
    tabs = MODULES[module]["tabs"]
    return tabs if is_admin() else [tab for tab in tabs if tab != "Data Upload"]


def sync_navigation_from_query() -> None:
    module = get_query_value("module", st.session_state.module)
    if module not in MODULES:
        module = "Home"

    if module in {"SMT", "Assembly"} and get_query_value("tab") == "Model Comparison":
        module = "Model Comparison"

    tabs = accessible_tabs(module)
    tab = get_query_value("tab", st.session_state.tab)
    if tabs and tab not in tabs:
        tab = tabs[0]
    if not tabs:
        tab = ""

    st.session_state.module = module
    st.session_state.tab = tab
    if tab:
        st.session_state[f"last_tab_{navigation_key(module)}"] = tab


def navigation_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def set_navigation(module: str, tab: str = "") -> None:
    if module in {"SMT", "Assembly"} and tab == "Model Comparison":
        module = "Model Comparison"
    if module not in MODULES:
        module = "Home"
    available_tabs = accessible_tabs(module)
    if available_tabs:
        remembered_tab = st.session_state.get(f"last_tab_{navigation_key(module)}")
        if tab not in available_tabs:
            tab = remembered_tab if remembered_tab in available_tabs else available_tabs[0]
    else:
        tab = ""

    st.session_state.module = module
    st.session_state.tab = tab
    if tab:
        st.session_state[f"last_tab_{navigation_key(module)}"] = tab
    query_values = {"module": module}
    if tab:
        query_values["tab"] = tab
    st.query_params.from_dict(query_values)


def top_navigation() -> None:
    """Render the full-width primary navigation without using Streamlit's sidebar."""
    nav_items = [
        ("Home", "Home", 0.58),
        ("SMT", "SMT", 0.48),
        ("Assembly", "Assembly", 0.74),
        ("Model Comparison", "Compare Models", 1.06),
        ("IQC", "IQC", 0.46),
        ("Smart Report", "Smart Report", 0.98),
        ("Repair Info", "Repair Info", 0.83),
        ("Learning Area", "Learning", 0.84),
    ]
    with st.container(key="top_navigation"):
        columns = st.columns([1.42] + [item[2] for item in nav_items] + [0.56], gap="small")
        with columns[0]:
            st.markdown(
                "<div class='topnav-brand'><strong><span>JOVI</span> QUALITY CENTER</strong><small>QUALITY INTELLIGENCE PORTAL</small></div>",
                unsafe_allow_html=True,
            )
        for column, (module, label, _) in zip(columns[1:-1], nav_items):
            with column:
                cfg = MODULES[module]
                st.button(
                    label,
                    key=f"top_nav_module_{navigation_key(module)}",
                    type="primary" if st.session_state.module == module else "secondary",
                    use_container_width=True,
                    on_click=set_navigation,
                    args=(module, ""),
                )
        with columns[-1]:
            with st.popover("More", use_container_width=True):
                role_label = "Administrator" if is_admin() else "Viewer"
                st.caption(f"{APP_VERSION} · {role_label} · Signed in as {st.session_state.get('authenticated_user', LOGIN_USERNAME)}")
                st.button("About", key="top_nav_about", use_container_width=True, on_click=set_navigation, args=("About", ""))
                if st.button("Sign out", key="top_nav_logout", use_container_width=True):
                    logout()


def context_navigation() -> None:
    """Show the pages available in the active workspace directly below the primary navigation."""
    module = st.session_state.module
    tabs = accessible_tabs(module)
    if not tabs:
        return
    tab_labels = {
        "BOM Comparison Tool - SMT": "BOM Comparison",
        "BOM Comparison Tool - Assembly": "BOM Comparison",
    }
    with st.container(key="context_navigation"):
        columns = st.columns([1.15] + [1] * len(tabs), gap="small")
        with columns[0]:
            st.markdown(f"<div class='context-label'><b>{escape(module)}</b> WORKSPACE</div>", unsafe_allow_html=True)
        for column, tab in zip(columns[1:], tabs):
            with column:
                st.button(
                    tab_labels.get(tab, tab),
                    key=f"top_nav_tab_{navigation_key(module)}_{navigation_key(tab)}",
                    type="primary" if st.session_state.tab == tab else "secondary",
                    use_container_width=True,
                    on_click=set_navigation,
                    args=(module, tab),
                )


def footer() -> None:
    footer_class = "footer home-footer" if st.session_state.get("module") == "Home" else "footer"
    st.markdown(
        f"""
        <div class="{footer_class}">
            <b>Jovi Quality Center {APP_VERSION}</b><br>
            Developed by: {DEVELOPER} &nbsp; | &nbsp; Role: {ROLE} &nbsp; | &nbsp; Manager: {MANAGER}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def asset_data_uri(path_text: str) -> str:
    path = Path(path_text)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def module_card_html(title: str, desc: str, color: str, icon: str) -> str:
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
        f'{media}'
        f'<div class="module-title">{escape(title)}</div>'
        f'<div class="module-desc">{escape(desc)}</div>'
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
    "rejudge_ok_keywords": ["Re-Judge Ok", "Rejudge OK", "Re-Judge OK", "rejudge ok", "Good machine rejudge ok", "Re-Download", "Re-Calibration"],
    "mando_column": "DutyType",
    "mando_keywords": ["ManDo", "Mando", "Man Do", "Man-do", "Man_Do"],
    "assembly_functional_operations": list(ASSEMBLY_FUNCTIONAL_OPERATIONS),
    "assembly_appearance_operations": list(ASSEMBLY_APPEARANCE_OPERATIONS),
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
    require_admin_access(st.session_state)
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


ANALYSIS_PERIOD_OPTIONS = ("Today", "Last 7 days", "This month", "Previous month", "YTD")


def _as_date(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def _preset_period_range(preset: str, minimum_date: date, maximum_date: date) -> tuple[date, date]:
    anchor = min(date.today(), maximum_date)
    if preset == "Today":
        start = end = anchor
    elif preset == "Last 7 days":
        start, end = anchor - timedelta(days=6), anchor
    elif preset == "Last 30 days":
        start, end = anchor - timedelta(days=29), anchor
    elif preset == "This month":
        start, end = anchor.replace(day=1), anchor
    elif preset == "Previous month":
        current_month_start = anchor.replace(day=1)
        end = current_month_start - timedelta(days=1)
        start = end.replace(day=1)
    else:  # YTD uses the complete available data range.
        start, end = minimum_date, maximum_date
    return max(start, minimum_date), min(end, maximum_date)


def _apply_period_preset(
    preset_key: str,
    range_key: str,
    remembered_range_key: str,
    minimum_date: date,
    maximum_date: date,
) -> None:
    preset = st.session_state.get(preset_key, "YTD")
    selected_range = _preset_period_range(preset, minimum_date, maximum_date)
    st.session_state[range_key] = selected_range
    st.session_state[remembered_range_key] = selected_range


def _remember_period_range(range_key: str, remembered_range_key: str) -> None:
    selected_range = st.session_state.get(range_key)
    if isinstance(selected_range, (tuple, list)) and len(selected_range) >= 2:
        start_date, end_date = _as_date(selected_range[0]), _as_date(selected_range[1])
        st.session_state[remembered_range_key] = (
            min(start_date, end_date),
            max(start_date, end_date),
        )


def analysis_period_control(
    key: str,
    minimum_value,
    maximum_value,
    *,
    default_start=None,
    default_end=None,
    show_presets: bool = True,
) -> tuple[date, date]:
    """Render the shared compact period menu used by KPI and quality dashboards."""
    minimum_date = _as_date(minimum_value)
    maximum_date = _as_date(maximum_value)
    if maximum_date < minimum_date:
        minimum_date, maximum_date = maximum_date, minimum_date
    default_start = _as_date(default_start) if default_start is not None else minimum_date
    default_end = _as_date(default_end) if default_end is not None else maximum_date
    default_start = min(max(default_start, minimum_date), maximum_date)
    default_end = min(max(default_end, minimum_date), maximum_date)
    if default_end < default_start:
        default_start, default_end = default_end, default_start
    full_data_range_requested = (default_start, default_end) == (minimum_date, maximum_date)
    if full_data_range_requested:
        default_start, default_end = _preset_period_range(
            "This month", minimum_date, maximum_date
        )

    preset_key = f"{key}_preset"
    range_key = f"{key}_range"
    remembered_range_key = f"{key}_remembered_range"
    if st.session_state.get(preset_key) not in ANALYSIS_PERIOD_OPTIONS:
        st.session_state[preset_key] = "This month" if full_data_range_requested else "YTD"
    remembered_range = st.session_state.get(remembered_range_key)
    if not isinstance(remembered_range, (tuple, list)) or len(remembered_range) < 2:
        remembered_range = st.session_state.get(range_key)
    if isinstance(remembered_range, (tuple, list)) and len(remembered_range) >= 2:
        remembered_start = min(max(_as_date(remembered_range[0]), minimum_date), maximum_date)
        remembered_end = min(max(_as_date(remembered_range[1]), minimum_date), maximum_date)
        initial_range = (min(remembered_start, remembered_end), max(remembered_start, remembered_end))
    else:
        initial_range = (default_start, default_end)
    st.session_state[remembered_range_key] = initial_range
    if range_key not in st.session_state:
        st.session_state[range_key] = initial_range

    with st.container(key=f"analysis_period_{navigation_key(key)}", width=455 if show_presets else 270):
        if show_presets:
            preset_col, range_col = st.columns([0.48, 0.82], gap="small", width=455)
            with preset_col:
                st.selectbox(
                    "Quick selection",
                    ANALYSIS_PERIOD_OPTIONS,
                    key=preset_key,
                    persist_state="session",
                    on_change=_apply_period_preset,
                    args=(preset_key, range_key, remembered_range_key, minimum_date, maximum_date),
                    width=160,
                )
            with range_col:
                selected_period = st.date_input(
                    "Analysis period", min_value=minimum_date, max_value=maximum_date,
                    format="DD/MM/YYYY", key=range_key,
                    persist_state="session",
                    on_change=_remember_period_range, args=(range_key, remembered_range_key), width=270,
                )
        else:
            selected_period = st.date_input(
                "Analysis period", min_value=minimum_date, max_value=maximum_date,
                format="DD/MM/YYYY", key=range_key,
                persist_state="session",
                on_change=_remember_period_range, args=(range_key, remembered_range_key),
                width=270,
            )

    if isinstance(selected_period, (tuple, list)) and len(selected_period) >= 2:
        start_date, end_date = selected_period[0], selected_period[1]
    elif isinstance(selected_period, (tuple, list)) and len(selected_period) == 1:
        start_date = end_date = selected_period[0]
    else:
        start_date = end_date = selected_period
    start_date, end_date = _as_date(start_date), _as_date(end_date)
    return (end_date, start_date) if end_date < start_date else (start_date, end_date)


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
    days = analysis_period_days(start, end)
    requested_grain = requested_trend_grain(start, end)

    input_resolution = production_input_granularity(production)
    grain_order = {"day": 0, "week": 1, "month": 2}
    grain = requested_grain
    input_distributed = grain_order[input_resolution["grain"]] > grain_order[requested_grain]
    label, title = trend_grain_labels(grain)
    return {
        "grain": grain,
        "label": label,
        "title": title,
        "period_days": days,
        "requested_grain": requested_grain,
        "input_grain": input_resolution["grain"],
        "input_max_span_days": input_resolution["max_span_days"],
        "summarized_input_rows": input_resolution["summarized_rows"],
        "input_distributed": input_distributed,
        "input_resolution_limited": False,
    }


def distribute_production_to_days(production):
    import pandas as pd

    if production is None or production.empty:
        return production.copy()

    daily_rows = []
    for _, row in production.iterrows():
        start = pd.Timestamp(row["ProductionStart"]).normalize()
        end = pd.Timestamp(row["ProductionEnd"]).normalize()
        dates = pd.date_range(start, end, freq="D")
        if dates.empty:
            dates = pd.DatetimeIndex([start])

        def allocate(total_value):
            total = max(int(round(float(total_value))), 0)
            base, remainder = divmod(total, len(dates))
            return [base + (1 if index < remainder else 0) for index in range(len(dates))]

        produced_by_day = allocate(row.get("Produced", 0))
        bad_machine_by_day = allocate(row.get("BadMachine", 0))
        for index, production_date in enumerate(dates):
            daily_row = row.to_dict()
            daily_row["ProductionStart"] = production_date
            daily_row["ProductionEnd"] = production_date
            daily_row["Produced"] = produced_by_day[index]
            daily_row["BadMachine"] = bad_machine_by_day[index]
            daily_rows.append(daily_row)
    return pd.DataFrame(daily_rows)


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
    return ts.strftime("%m/%y") if grain == "month" else ts.strftime("%d/%m")


def build_skd_trend(production, filtered, start, end) -> tuple:
    import pandas as pd

    settings = trend_granularity(start, end, production)
    grain = settings["grain"]
    production_for_trend = (
        distribute_production_to_days(production)
        if settings.get("input_distributed")
        else production
    )
    production_period = add_trend_period(production_for_trend, "ProductionStart", settings)
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


def init_quality_store() -> tuple[bool, str]:
    DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
    cloud_status = cloud_store_status()
    cloud_active = bool(cloud_status["active"])
    initialize_clean_cloud = (
        is_admin()
        and bool(cloud_status["configured"])
        and not cloud_active
        and str(cloud_status["mode"]) == "Supabase awaiting migration"
    )
    if initialize_clean_cloud and QUALITY_DB_PATH.is_file():
        QUALITY_DB_PATH.unlink()
    data_version = ensure_cloud_data_version() if cloud_active else ""
    sync_file_from_cloud(
        DATABASE_OBJECT,
        QUALITY_DB_PATH,
        data_version=data_version,
        cloud_active=cloud_active,
    )
    historical_archive_applied = False
    inspection_schema_migrated = False
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
        create_inspection_tables(conn)
        inspection_schema_migrated = migrate_zero_sampling_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_report_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area TEXT NOT NULL,
                period_key TEXT NOT NULL,
                defect_name TEXT NOT NULL,
                failure_type TEXT NOT NULL,
                root_cause TEXT,
                cause_status TEXT NOT NULL DEFAULT 'Under investigation',
                containment TEXT,
                countermeasure TEXT,
                owner TEXT,
                due_date TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (area, period_key, defect_name, failure_type)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_kpi_owners (
                kpi_key TEXT PRIMARY KEY,
                gbr_owner TEXT NOT NULL DEFAULT '',
                jovi_owner TEXT NOT NULL DEFAULT '',
                target_value REAL,
                updated_at TEXT NOT NULL
            )
            """
        )
        weekly_owner_columns = {row[1] for row in conn.execute("PRAGMA table_info(weekly_kpi_owners)")}
        if "target_value" not in weekly_owner_columns:
            conn.execute("ALTER TABLE weekly_kpi_owners ADD COLUMN target_value REAL")
        if is_admin():
            historical_archive_applied = apply_historical_inspection_archive(conn)
    if initialize_clean_cloud:
        upload_local_file(DATABASE_OBJECT, QUALITY_DB_PATH, upsert=True)
        data_version = bump_cloud_data_version("initialize clean Quality Center 2.0 baseline")
        cloud_active = True
    elif (historical_archive_applied or inspection_schema_migrated) and cloud_active and is_admin():
        upload_local_file(DATABASE_OBJECT, QUALITY_DB_PATH, upsert=True)
        reason = (
            "allow zero-sampling OQC/FQC records"
            if inspection_schema_migrated
            else "import OQC/FQC historical archive"
        )
        data_version = bump_cloud_data_version(reason)
    return cloud_active, data_version


def require_persistent_store_for_writes() -> None:
    """Prevent writes to the temporary Streamlit disk after Supabase setup starts."""
    require_admin_access(st.session_state)
    status = cloud_store_status()
    if bool(status["configured"]) and not bool(status["active"]):
        raise RuntimeError(
            "Supabase is configured but the portal data has not been migrated yet. "
            "Open About > Cloud data storage and complete the migration before adding or deleting data."
        )


def sync_quality_database_to_cloud(*, bump_version: bool = True) -> None:
    if cloud_store_is_active():
        upload_local_file(DATABASE_OBJECT, QUALITY_DB_PATH, upsert=True)
        if bump_version:
            bump_cloud_data_version("portal database update")


def sync_assembly_source_cache(cloud_active: bool | None = None, data_version: str = "") -> None:
    if cloud_active is None:
        cloud_active = cloud_store_is_active()
    if not cloud_active:
        return
    data_version = data_version or ensure_cloud_data_version()
    sync_prefix_from_cloud(
        "assembly/defects",
        ASSEMBLY_FILE_STORE_DIR / "defects",
        data_version=data_version,
        cloud_active=True,
    )
    sync_prefix_from_cloud(
        "assembly/input",
        ASSEMBLY_FILE_STORE_DIR / "input",
        data_version=data_version,
        cloud_active=True,
    )
    sync_prefix_from_cloud(
        "assembly/repair",
        ASSEMBLY_FILE_STORE_DIR / "repair",
        data_version=data_version,
        cloud_active=True,
    )


def full_cloud_refresh() -> dict[str, int]:
    """Rebuild the temporary portal cache from every current Supabase object."""
    require_admin_access(st.session_state)
    if not cloud_store_is_active():
        raise RuntimeError("Supabase persistent storage is not active.")

    from tools import smt_quality_dashboard

    data_version = ensure_cloud_data_version()
    refreshed = []
    if sync_file_from_cloud(
        DATABASE_OBJECT,
        QUALITY_DB_PATH,
        force=True,
        data_version=data_version,
        cloud_active=True,
    ):
        refreshed.append(QUALITY_DB_PATH)
    init_quality_store()
    refreshed.extend(sync_prefix_from_cloud("smt/fpy/input", smt_quality_dashboard.SMT_INPUT_DIR, force=True, data_version=data_version, cloud_active=True))
    refreshed.extend(sync_prefix_from_cloud("smt/fpy/detail", smt_quality_dashboard.SMT_DEFECT_DIR, force=True, data_version=data_version, cloud_active=True))
    refreshed.extend(sync_prefix_from_cloud("smt/repair", smt_quality_dashboard.SMT_REPAIR_DIR, force=True, data_version=data_version, cloud_active=True))
    refreshed.extend(sync_prefix_from_cloud("assembly/input", ASSEMBLY_FILE_STORE_DIR / "input", force=True, data_version=data_version, cloud_active=True))
    refreshed.extend(sync_prefix_from_cloud("assembly/defects", ASSEMBLY_FILE_STORE_DIR / "defects", force=True, data_version=data_version, cloud_active=True))
    refreshed.extend(sync_prefix_from_cloud("assembly/repair", ASSEMBLY_FILE_STORE_DIR / "repair", force=True, data_version=data_version, cloud_active=True))
    st.cache_data.clear()
    return {"files": len(refreshed), "bytes": sum(path.stat().st_size for path in refreshed if path.is_file())}


PERFORMANCE_DIAGNOSTICS_KEY = "portal_dashboard_performance"


def record_dashboard_performance(
    dashboard: str,
    start_date: date,
    end_date: date,
    source_seconds: float,
    analysis_seconds: float,
    total_seconds: float,
    source_files: int,
) -> None:
    """Keep the latest real dashboard timings in the current administrator session."""
    total_seconds = max(float(total_seconds), 0.0)
    source_seconds = max(float(source_seconds), 0.0)
    analysis_seconds = max(float(analysis_seconds), 0.0)
    st.session_state[PERFORMANCE_DIAGNOSTICS_KEY] = {
        **st.session_state.get(PERFORMANCE_DIAGNOSTICS_KEY, {}),
        dashboard: {
            "period": f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}",
            "source_seconds": source_seconds,
            "analysis_seconds": analysis_seconds,
            "composition_seconds": max(total_seconds - source_seconds - analysis_seconds, 0.0),
            "total_seconds": total_seconds,
            "source_files": int(source_files),
            "measured_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        },
    }


def render_performance_diagnostics_panel() -> None:
    """Show timing from real dashboard loads without storing operational data."""
    import pandas as pd

    measurements = st.session_state.get(PERFORMANCE_DIAGNOSTICS_KEY, {})
    st.markdown("<h3 class='section-title'>Performance diagnostics</h3>", unsafe_allow_html=True)
    with st.expander("Latest dashboard load measurements", expanded=bool(measurements)):
        st.caption(
            "Measurements are captured from real dashboard openings in this browser session. "
            "They do not alter cloud files, cached sources, or production data."
        )
        if not measurements:
            st.info("Open the SMT or Assembly Quality Dashboard once, then return here to review its loading breakdown.")
            return

        rows = []
        for dashboard in ("SMT Quality Dashboard", "Assembly Quality Dashboard"):
            result = measurements.get(dashboard)
            if not result:
                continue
            rows.append(
                {
                    "Dashboard": dashboard,
                    "Analysis period": result["period"],
                    "Sources": f"{result['source_files']:,} file(s)",
                    "Cloud sync & source discovery": f"{result['source_seconds']:.2f} s",
                    "Data reading & analysis": f"{result['analysis_seconds']:.2f} s",
                    "Dashboard composition": f"{result['composition_seconds']:.2f} s",
                    "Total server processing": f"{result['total_seconds']:.2f} s",
                    "Measured at": result["measured_at"],
                }
            )
        if rows:
            styled_table(pd.DataFrame(rows), max_rows=4, table_class="compact-dashboard-table")
        st.caption(
            "Cloud sync includes checking Supabase for new or changed files. Dashboard composition covers filters, KPI cards and chart preparation; browser/network rendering time is not included."
        )
        if st.button("Clear performance measurements", key="clear_performance_diagnostics"):
            st.session_state.pop(PERFORMANCE_DIAGNOSTICS_KEY, None)
            st.rerun()


def assembly_portable_stored_path(data_type: str, stored_name: str) -> str:
    """Return the repository-relative location recorded for new Assembly imports."""
    return (Path("data_store") / "assembly" / data_type / stored_name).as_posix()


def resolve_assembly_stored_path(data_type: str, stored_name: str, stored_path: str | None) -> Path | None:
    """Resolve imported Assembly files without relying on a machine-specific database path."""
    candidates = [ASSEMBLY_FILE_STORE_DIR / data_type / stored_name]
    if stored_path:
        legacy_path = Path(stored_path)
        candidates.append(legacy_path)
        if not legacy_path.is_absolute():
            candidates.append(BASE_DIR / legacy_path)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_smart_report_actions(area: str, period_key: str) -> dict[str, dict]:
    import pandas as pd

    init_quality_store()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        frame = pd.read_sql_query(
            """
            SELECT defect_name, failure_type, root_cause, cause_status, containment,
                   countermeasure, owner, due_date, updated_at
            FROM smart_report_actions
            WHERE area = ? AND period_key = ?
            """,
            conn,
            params=(area, period_key),
        )
    return {
        f"{row.failure_type}|{row.defect_name}": {
            "root_cause": row.root_cause or "",
            "cause_status": row.cause_status or "Under investigation",
            "containment": row.containment or "",
            "countermeasure": row.countermeasure or "",
            "owner": row.owner or "",
            "due_date": row.due_date or "",
            "updated_at": row.updated_at or "",
        }
        for row in frame.itertuples(index=False)
    }


def save_smart_report_action(area: str, period_key: str, item: dict, action: dict) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO smart_report_actions (
                area, period_key, defect_name, failure_type, root_cause, cause_status,
                containment, countermeasure, owner, due_date, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(area, period_key, defect_name, failure_type) DO UPDATE SET
                root_cause = excluded.root_cause,
                cause_status = excluded.cause_status,
                containment = excluded.containment,
                countermeasure = excluded.countermeasure,
                owner = excluded.owner,
                due_date = excluded.due_date,
                updated_at = excluded.updated_at
            """,
            (
                area,
                period_key,
                item["defect"],
                item["failure_type"],
                action["root_cause"].strip(),
                action["cause_status"],
                action["containment"].strip(),
                action["countermeasure"].strip(),
                action["owner"].strip(),
                action["due_date"].strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    sync_quality_database_to_cloud()


def load_weekly_kpi_owners() -> dict[str, dict[str, str]]:
    import pandas as pd

    init_quality_store()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        frame = pd.read_sql_query("SELECT kpi_key, gbr_owner, jovi_owner, target_value FROM weekly_kpi_owners", conn)
    return {
        str(row.kpi_key): {
            "gbr": str(row.gbr_owner or ""),
            "jovi": str(row.jovi_owner or ""),
            "target": float(row.target_value) if pd.notna(row.target_value) else None,
        }
        for row in frame.itertuples(index=False)
    }


def save_weekly_kpi_owners(rows: list[dict]) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    updated_at = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO weekly_kpi_owners (kpi_key, gbr_owner, jovi_owner, target_value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kpi_key) DO UPDATE SET
                    gbr_owner = excluded.gbr_owner,
                    jovi_owner = excluded.jovi_owner,
                    target_value = excluded.target_value,
                    updated_at = excluded.updated_at
                """,
                (
                    str(row["source"]),
                    str(row.get("gbr", "")).strip(),
                    str(row.get("jovi", "")).strip(),
                    float(row["target"]),
                    updated_at,
                ),
            )
    sync_quality_database_to_cloud()


def save_smt_oqc_inspection(
    inspection_date: date,
    model: str,
    inspected_qty: int,
    ok_qty: int,
    ng_qty: int,
    notes: str,
) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    validate_inspection_counts("SMT OQC", inspected_qty, ok_qty, ng_qty)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO smt_oqc_inspections (
                inspection_date, model, inspected_qty, ok_qty, ng_qty, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inspection_date.isoformat(),
                model.strip(),
                int(inspected_qty),
                int(ok_qty),
                int(ng_qty),
                notes.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    sync_quality_database_to_cloud()


def load_smt_oqc_inspections(start_date: date | None = None, end_date: date | None = None):
    import pandas as pd

    init_quality_store()
    start_date = start_date or date.min
    end_date = end_date or date.max
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                id AS ID,
                inspection_date AS InspectionDate,
                model AS Model,
                inspected_qty AS Inspected,
                ok_qty AS OK,
                ng_qty AS NG,
                notes AS Notes,
                created_at AS CreatedAt
            FROM smt_oqc_inspections
            WHERE inspection_date BETWEEN ? AND ?
            ORDER BY inspection_date, id
            """,
            conn,
            params=(start_date.isoformat(), end_date.isoformat()),
        )
    if not frame.empty:
        frame["InspectionDate"] = pd.to_datetime(frame["InspectionDate"], errors="coerce")
        frame["PassRate"] = frame["OK"] / frame["Inspected"].replace(0, pd.NA)
    else:
        frame["InspectionDate"] = pd.to_datetime(frame.get("InspectionDate"))
        frame["PassRate"] = pd.Series(dtype="float64")
    return frame


def delete_smt_oqc_inspection(record_id: int) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM smt_oqc_inspections WHERE id = ?", (int(record_id),))
    if cursor.rowcount != 1:
        raise ValueError("The selected SMT OQC inspection record was not found.")
    sync_quality_database_to_cloud()


def save_assembly_oqc_fqc_inspection(
    inspection_date: date,
    model: str,
    oqc_inspected_qty: int,
    oqc_ok_qty: int,
    oqc_ng_qty: int,
    fqc_inspected_qty: int,
    fqc_ok_qty: int,
    fqc_ng_qty: int,
    notes: str,
) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    checks = [
        ("OQC", oqc_inspected_qty, oqc_ok_qty, oqc_ng_qty),
        ("FQC", fqc_inspected_qty, fqc_ok_qty, fqc_ng_qty),
    ]
    for stage, inspected_qty, ok_qty, ng_qty in checks:
        validate_inspection_counts(stage, inspected_qty, ok_qty, ng_qty)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO assembly_oqc_fqc_inspections (
                inspection_date, model,
                oqc_inspected_qty, oqc_ok_qty, oqc_ng_qty,
                fqc_inspected_qty, fqc_ok_qty, fqc_ng_qty,
                notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inspection_date.isoformat(),
                model.strip(),
                int(oqc_inspected_qty),
                int(oqc_ok_qty),
                int(oqc_ng_qty),
                int(fqc_inspected_qty),
                int(fqc_ok_qty),
                int(fqc_ng_qty),
                notes.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    sync_quality_database_to_cloud()


def load_assembly_oqc_fqc_inspections(start_date: date | None = None, end_date: date | None = None):
    import pandas as pd

    init_quality_store()
    start_date = start_date or date.min
    end_date = end_date or date.max
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                id AS ID,
                inspection_date AS InspectionDate,
                model AS Model,
                oqc_inspected_qty AS OQCInspected,
                oqc_ok_qty AS OQCOK,
                oqc_ng_qty AS OQCNG,
                fqc_inspected_qty AS FQCInspected,
                fqc_ok_qty AS FQCOK,
                fqc_ng_qty AS FQCNG,
                notes AS Notes,
                created_at AS CreatedAt
            FROM assembly_oqc_fqc_inspections
            WHERE inspection_date BETWEEN ? AND ?
            ORDER BY inspection_date, id
            """,
            conn,
            params=(start_date.isoformat(), end_date.isoformat()),
        )
    if not frame.empty:
        frame["InspectionDate"] = pd.to_datetime(frame["InspectionDate"], errors="coerce")
        frame["OQCPassRate"] = frame["OQCOK"] / frame["OQCInspected"].replace(0, pd.NA)
        frame["FQCPassRate"] = frame["FQCOK"] / frame["FQCInspected"].replace(0, pd.NA)
        frame["CombinedPassRate"] = frame["OQCPassRate"] * frame["FQCPassRate"]
    else:
        frame["InspectionDate"] = pd.to_datetime(frame.get("InspectionDate"))
        for column in ["OQCPassRate", "FQCPassRate", "CombinedPassRate"]:
            frame[column] = pd.Series(dtype="float64")
    return frame


def delete_assembly_oqc_fqc_inspection(record_id: int) -> None:
    init_quality_store()
    require_persistent_store_for_writes()
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM assembly_oqc_fqc_inspections WHERE id = ?", (int(record_id),))
    if cursor.rowcount != 1:
        raise ValueError("The selected Assembly OQC/FQC inspection record was not found.")
    sync_quality_database_to_cloud()


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
    if "repair" in name or "reparo" in name:
        return "repair" if suffix in {".xlsx", ".xls"} else None
    if "defect" in name and suffix in {".xlsx", ".xls"}:
        return "defects"
    if any(keyword in name for keyword in ("input", "production", "produced")) and suffix in {".csv", ".xls", ".xlsx"}:
        return "input"
    return None


def persist_assembly_source(source, data_type: str, source_method: str) -> dict:
    init_quality_store()
    require_persistent_store_for_writes()
    if data_type not in {"defects", "input", "repair"}:
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

        if cloud_store_is_active():
            upload_bytes(f"assembly/{data_type}/{stored_name}", data, upsert=True)
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
                assembly_portable_stored_path(data_type, stored_name),
                file_hash,
                len(data),
                modified_at,
                imported_at,
                source_method,
            ),
        )
    sync_quality_database_to_cloud()

    return {
        "status": "imported",
        "data_type": data_type,
        "name": original_name,
        "message": "Imported to Supabase persistent storage." if cloud_store_is_active() else "Imported to the local data store.",
    }


def import_assembly_monitored_folder() -> list[dict]:
    require_admin_access(st.session_state)
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
    cloud_active, data_version = init_quality_store()
    sync_assembly_source_cache(cloud_active, data_version)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT data_type, stored_name, stored_path
            FROM assembly_files
            WHERE status = 'imported'
            ORDER BY imported_at, id
            """
        ).fetchall()

    defects = []
    inputs = []
    for data_type, stored_name, stored_path in rows:
        path = resolve_assembly_stored_path(data_type, stored_name, stored_path)
        if path is None:
            continue
        if data_type == "defects":
            defects.append(path)
        elif data_type == "input":
            inputs.append(path)
    return defects, inputs


def stored_assembly_sources_v2() -> dict[str, list[Path]]:
    """Return Assembly sources grouped by the validated v2 source contract."""
    cloud_active, data_version = init_quality_store()
    sync_assembly_source_cache(cloud_active, data_version)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT data_type, stored_name, stored_path
            FROM assembly_files
            WHERE status = 'imported'
            ORDER BY imported_at, id
            """
        ).fetchall()
    grouped = {"defects": [], "input": [], "repair": []}
    for data_type, stored_name, stored_path in rows:
        if data_type not in grouped:
            continue
        path = resolve_assembly_stored_path(data_type, stored_name, stored_path)
        if path is not None:
            grouped[data_type].append(path)
    return grouped


def stored_assembly_file_records() -> list[dict]:
    """Return stored Assembly source metadata for the managed deletion interface."""
    cloud_active, data_version = init_quality_store()
    sync_assembly_source_cache(cloud_active, data_version)
    with sqlite3.connect(QUALITY_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, data_type, original_name, stored_name, file_size,
                   modified_at, imported_at, source_method
            FROM assembly_files
            WHERE status = 'imported'
            ORDER BY imported_at DESC, id DESC
            """
        ).fetchall()

    records = []
    for record_id, data_type, original_name, stored_name, file_size, modified_at, imported_at, source_method in rows:
        canonical_path = ASSEMBLY_FILE_STORE_DIR / data_type / stored_name
        records.append(
            {
                "id": int(record_id),
                "data_type": data_type,
                "original_name": original_name,
                "stored_name": stored_name,
                "file_size": int(file_size),
                "modified_at": modified_at or "-",
                "imported_at": imported_at,
                "source_method": source_method,
                "available": canonical_path.is_file(),
            }
        )
    return records


def delete_assembly_source(record_id: int) -> dict:
    """Remove one Assembly source record and only its portal-managed physical file."""
    init_quality_store()
    require_persistent_store_for_writes()
    conn = sqlite3.connect(QUALITY_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT data_type, original_name, stored_name
            FROM assembly_files
            WHERE id = ? AND status = 'imported'
            """,
            (int(record_id),),
        ).fetchone()
        if not row:
            raise ValueError("The selected Assembly source file was not found.")
        data_type, original_name, stored_name = row
        if data_type not in {"defects", "input", "repair"} or Path(stored_name).name != stored_name:
            raise ValueError("The selected Assembly source file is invalid.")
        conn.execute("DELETE FROM assembly_files WHERE id = ?", (int(record_id),))
        conn.commit()
    finally:
        conn.close()
    sync_quality_database_to_cloud(bump_version=False)

    # Never follow a legacy absolute path here. Deletion is limited to the portal-managed store.
    managed_file = ASSEMBLY_FILE_STORE_DIR / data_type / stored_name
    cleanup_note = ""
    cloud_active = cloud_store_is_active()
    if cloud_active:
        try:
            delete_object(f"assembly/{data_type}/{stored_name}")
        except RuntimeError as exc:
            cleanup_note = f" The source record was removed, but Supabase could not clean up the stored file: {exc}"
    if managed_file.exists():
        try:
            managed_file.unlink()
        except OSError as exc:
            cleanup_note = f" The source record was removed, but the stored file could not be cleaned up: {exc}"
    if cloud_active:
        bump_cloud_data_version("Assembly source deletion")
    st.cache_data.clear()
    return {
        "data_type": data_type,
        "original_name": original_name,
        "cleanup_note": cleanup_note,
    }


def render_assembly_source_manager() -> None:
    """Render the confirmed, individual Assembly source-file deletion workflow."""
    import pandas as pd

    records = stored_assembly_file_records()
    with st.expander("Manage stored files"):
        st.caption(
            "Review the portal's stored Assembly source files before deleting one. "
            "Deletion changes the data used by dashboards and Smart Report and cannot be undone."
        )
        if not records:
            st.info("No Assembly source files are currently stored.")
            return

        file_types = {"input": "Input diário", "defects": "Defeitos gerais", "repair": "Reparo cumulativo"}
        table = pd.DataFrame(
            [
                {
                    "Type": file_types.get(record["data_type"], record["data_type"]),
                    "Source file": record["original_name"],
                    "Imported at": record["imported_at"],
                    "Import method": record["source_method"],
                    "Size": f"{record['file_size'] / 1024 / 1024:.2f} MB",
                    "Available": "Yes" if record["available"] else "Missing",
                }
                for record in records
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True, height="content")

        record_by_id = {record["id"]: record for record in records}
        selected_id = st.selectbox(
            "Source file to delete",
            options=list(record_by_id),
            format_func=lambda record_id: (
                f"{file_types.get(record_by_id[record_id]['data_type'], record_by_id[record_id]['data_type'])} · "
                f"{record_by_id[record_id]['original_name']} · imported {record_by_id[record_id]['imported_at']}"
            ),
            key="assembly_source_delete_selection",
        )
        selected = record_by_id[selected_id]
        if not selected["available"]:
            st.warning("The file bytes are already missing, but deleting this record will remove it from the portal data store.")
        confirmed = st.checkbox(
            "I understand that this permanently removes the selected Assembly source file from this portal.",
            key=f"assembly_source_delete_confirm_{selected_id}",
        )
        if st.button(
            "Delete selected source file",
            type="secondary",
            disabled=not confirmed,
            use_container_width=True,
            key="assembly_source_delete_button",
        ):
            try:
                deleted = delete_assembly_source(selected_id)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("assembly_last_import_results", None)
                st.success(
                    f"Deleted Assembly {file_types.get(deleted['data_type'], deleted['data_type']).lower()} "
                    f"source: {deleted['original_name']}.{deleted['cleanup_note']}"
                )
                st.rerun()


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


def assembly_store_status(*, sync: bool = True) -> dict:
    if sync:
        cloud_active, data_version = init_quality_store()
        sync_assembly_source_cache(cloud_active, data_version)
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
        "repair": 0,
        "bytes": 0,
        "latest": latest[0] if latest else "-",
        "ready": False,
    }
    for data_type, count, file_size in rows:
        status[data_type] = count
        status["bytes"] += file_size
    status["ready"] = status["defects"] > 0 and status["input"] > 0 and status["repair"] > 0
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

    # Assembly FPY has a distinct judgment policy. It excludes approved rejudge
    # dispositions only; unlike SMT, it retains Retest OK remarks and repeat repairs.
    rejudge_columns = [rules["rejudge_column"], *rules.get("additional_rejudge_columns", [])]
    rejudge_text = pd.Series("", index=filtered.index, dtype="object")
    for col in rejudge_columns:
        if col in filtered.columns:
            rejudge_text = rejudge_text + " " + filtered[col].fillna("").astype(str)
    rejudge_mask = keyword_mask(
        rejudge_text,
        ["Re-Judge Ok", "Rejudge OK", "Re-Judge OK", "rejudge ok", "Good machine rejudge ok"],
    )
    redownload_mask = keyword_mask(rejudge_text, ["Re-Download"])
    recalibration_mask = keyword_mask(rejudge_text, ["Re-Calibration"])
    filtered["ExclusionReason"] = ""
    filtered.loc[rejudge_mask, "ExclusionReason"] = "Re-Judge OK"
    filtered.loc[redownload_mask, "ExclusionReason"] = "Re-Download"
    filtered.loc[recalibration_mask, "ExclusionReason"] = "Re-Calibration"
    # The existing field name is retained for compatibility; it represents all approved retest exclusions.
    filtered["IsRejudgeOK"] = keyword_mask(rejudge_text, list(ASSEMBLY_MES_EXCLUSION_KEYWORDS))
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
        "production_detail": production_detail,
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


SKD_ANALYSIS_SCHEMA_VERSION = "production-detail-v1"


@st.cache_data(show_spinner=False)
def analyze_skd_quality_paths_cached(
    defect_paths: tuple[str, ...],
    input_paths: tuple[str, ...],
    path_signatures: tuple,
    rules_text: str,
    source_label: str,
    schema_version: str,
) -> dict:
    _ = schema_version
    rules = json.loads(rules_text)
    return analyze_skd_quality([Path(path) for path in defect_paths], [Path(path) for path in input_paths], rules, source_label)


def analyze_skd_quality_cached(defect_source, input_sources: list, rules: dict, source_label: str) -> dict:
    defect_sources = defect_source if isinstance(defect_source, (list, tuple)) else [defect_source]
    if all(isinstance(source, Path) for source in defect_sources) and all(isinstance(source, Path) for source in input_sources):
        defect_paths = tuple(str(source) for source in defect_sources)
        input_paths = tuple(str(source) for source in input_sources)
        signatures = tuple(path_signature(source) for source in [*defect_sources, *input_sources])
        rules_text = json.dumps(rules, sort_keys=True, ensure_ascii=False)
        analysis = analyze_skd_quality_paths_cached(
            defect_paths,
            input_paths,
            signatures,
            rules_text,
            source_label,
            SKD_ANALYSIS_SCHEMA_VERSION,
        )
        if "production_detail" not in analysis:
            analysis = analyze_skd_quality(
                [Path(path) for path in defect_paths],
                [Path(path) for path in input_paths],
                rules,
                source_label,
            )
        return analysis
    return analyze_skd_quality(defect_source, input_sources, rules, source_label)


def fmt_int(value: float) -> str:
    return f"{float(value):,.0f}"


def fmt_ppm(value: float) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{numeric_value:,.0f}" if math.isfinite(numeric_value) else "N/A"


def fmt_pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def fmt_compact(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 1000:
        return f"{value / 1000:.0f}k"
    return f"{value:.0f}"


def styled_table(df, max_rows: int | None = None, table_class: str = "") -> None:
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

    class_names = " ".join(part for part in table_class.split() if part)
    class_suffix = f" {class_names}" if class_names else ""
    st.markdown(
        f"""
        <div class="data-table-wrap{class_suffix}">
            <table class="data-table{class_suffix}">
                <thead><tr>{headers}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def action_priority_cards(
    frame,
    defect_column: str,
    station_column: str,
    model_column: str,
    max_items: int = 5,
) -> None:
    view = frame.head(max_items).copy()
    cards = []
    for rank, (_, row) in enumerate(view.iterrows(), start=1):
        defect = str(row.get(defect_column, "Unknown") or "Unknown").strip()
        station = str(row.get(station_column, "Unknown") or "Unknown").strip()
        model = str(row.get(model_column, "Unknown") or "Unknown").strip()
        priority = str(row.get("Priority", "Monitor") or "Monitor").strip()
        priority_text = compact_text(priority)
        if "critical" in priority_text:
            priority_class = "critical"
        elif "high" in priority_text:
            priority_class = "high"
        elif "medium" in priority_text:
            priority_class = "medium"
        else:
            priority_class = "monitor"
        ng_value = fmt_int(row.get("NGPCBs", 0))
        ppm_value = fmt_ppm(row.get("ImpactPPM", 0))
        cards.append(
            f'<div class="action-priority-card {priority_class}">'
            f'<div class="action-priority-header">'
            f'<span class="action-priority-rank">{rank:02d}</span>'
            f'<div class="action-priority-name" title="{escape(defect, quote=True)}">{escape(defect)}</div>'
            f'<span class="action-priority-badge">{escape(priority)}</span>'
            f'</div>'
            f'<div class="action-priority-body">'
            f'<div class="action-priority-context">'
            f'<b>Station:</b> {escape(station)}<br>'
            f'<b>Model:</b> {escape(model)}'
            f'</div>'
            f'<div class="action-priority-metrics">'
            f'<div class="action-priority-metric"><strong>{escape(ng_value)}</strong><small>NG PCBs</small></div>'
            f'<div class="action-priority-metric"><strong>{escape(ppm_value)}</strong><small>Impact PPM</small></div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="action-priority-list">{"".join(cards)}</div>',
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
        "ExclusionReason",
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
    "modeBarButtonsToRemove": [
        "zoom2d",
        "pan2d",
        "select2d",
        "lasso2d",
        "zoomIn2d",
        "zoomOut2d",
        "autoScale2d",
        "resetScale2d",
        "toggleSpikelines",
    ],
    "toImageButtonOptions": {
        "format": "png",
        "filename": "jovi-quality-chart",
        # The clipboard action uses Plotly's native PNG export. Fixing the
        # output dimensions makes every copied chart 4K, independent of the
        # browser window or the Streamlit column where it is displayed.
        "width": 1920,
        "height": 1080,
        "scale": 2,
    },
}


def show_chart(fig, image_filename: str | None = None) -> None:
    config = dict(PLOTLY_CONFIG)
    config["toImageButtonOptions"] = dict(PLOTLY_CONFIG["toImageButtonOptions"])
    if image_filename:
        config["toImageButtonOptions"]["filename"] = image_filename
    st.plotly_chart(fig, use_container_width=True, config=config)


def install_chart_copy_controls() -> None:
    import streamlit.components.v1 as components

    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const buttonClass = "jovi-copy-chart-button";
            const svgButtonClass = "jovi-download-svg-button";
            const nativeSelector = '.modebar-btn[data-title*="Download plot as" i]';

            parentDocument.querySelectorAll(`.${buttonClass}, .${svgButtonClass}`).forEach((button) => button.remove());

            const setButtonState = (button, symbol, title, delay = 1800) => {
                const originalSymbol = button.dataset.originalSymbol || "⧉";
                const originalTitle = button.dataset.originalTitle || "Copy chart image";
                button.textContent = symbol;
                button.setAttribute("data-title", title);
                button.setAttribute("aria-label", title);
                if (delay > 0) {
                    parentWindow.setTimeout(() => {
                        button.textContent = originalSymbol;
                        button.setAttribute("data-title", originalTitle);
                        button.setAttribute("aria-label", originalTitle);
                    }, delay);
                }
            };

            const copyImage = async (href) => {
                const response = await parentWindow.fetch(href);
                const sourceBlob = await response.blob();
                const pngBlob = sourceBlob.type === "image/png"
                    ? sourceBlob
                    : new parentWindow.Blob([await sourceBlob.arrayBuffer()], {type: "image/png"});
                await parentWindow.navigator.clipboard.write([
                    new parentWindow.ClipboardItem({"image/png": pngBlob})
                ]);
            };

            const addPowerPointFrame = async (href, width, height) => {
                const response = await parentWindow.fetch(href);
                const svg = await response.text();
                const svgDocument = new parentWindow.DOMParser().parseFromString(svg, "image/svg+xml");
                const svgElement = svgDocument.documentElement;
                if (!svgElement || svgElement.localName !== "svg") {
                    throw new Error("Invalid SVG export");
                }
                // PowerPoint respects physical SVG units. Keep the larger
                // viewBox for sharp vector content, while making the inserted
                // object exactly 16.17 cm × 8.17 cm, including its frame.
                svgElement.setAttribute("width", "16.17cm");
                svgElement.setAttribute("height", "8.17cm");
                // The half-pixel inset keeps the full one-pixel stroke within
                // the SVG canvas, so the physical dimensions above include
                // the complete external frame in PowerPoint.
                const frame = svgDocument.createElementNS("http://www.w3.org/2000/svg", "rect");
                frame.setAttribute("x", "0.5");
                frame.setAttribute("y", "0.5");
                frame.setAttribute("width", String(width - 1));
                frame.setAttribute("height", String(height - 1));
                frame.setAttribute("fill", "none");
                frame.setAttribute("stroke", "#000000");
                frame.setAttribute("stroke-width", "1");
                frame.setAttribute("vector-effect", "non-scaling-stroke");
                svgElement.appendChild(frame);
                const framedSvg = new parentWindow.XMLSerializer().serializeToString(svgDocument);
                return parentWindow.URL.createObjectURL(
                    new parentWindow.Blob([framedSvg], {type: "image/svg+xml;charset=utf-8"})
                );
            };

            const addCopyButton = (chartContainer) => {
                if (chartContainer.querySelector(`.${buttonClass}`)) return;
                const nativeButton = chartContainer.querySelector(nativeSelector);
                if (!nativeButton) return;

                const copyButton = parentDocument.createElement("a");
                copyButton.className = `modebar-btn ${buttonClass}`;
                copyButton.dataset.originalSymbol = "⧉";
                copyButton.dataset.originalTitle = "Copy chart image";
                copyButton.textContent = "⧉";
                copyButton.setAttribute("data-title", "Copy chart image");
                copyButton.setAttribute("aria-label", "Copy chart image");
                copyButton.setAttribute("role", "button");
                copyButton.setAttribute("tabindex", "0");

                const capture = () => {
                    if (!parentWindow.navigator?.clipboard || !parentWindow.ClipboardItem) {
                        nativeButton.click();
                        setButtonState(copyButton, "↓", "Clipboard unavailable; PNG downloaded");
                        return;
                    }

                    let handled = false;
                    const interceptDownload = async (event) => {
                        const anchor = event.target?.closest?.("a[download]");
                        if (!anchor) return;
                        const href = anchor.href || "";
                        if (!href.startsWith("data:image/") && !href.startsWith("blob:")) return;

                        handled = true;
                        event.preventDefault();
                        event.stopImmediatePropagation();
                        parentDocument.removeEventListener("click", interceptDownload, true);
                        try {
                            await copyImage(href);
                            setButtonState(copyButton, "✓", "Chart image copied");
                        } catch (_error) {
                            parentDocument.removeEventListener("click", interceptDownload, true);
                            anchor.click();
                            setButtonState(copyButton, "↓", "Copy failed; PNG downloaded");
                        }
                    };

                    parentDocument.addEventListener("click", interceptDownload, true);
                    nativeButton.click();
                    parentWindow.setTimeout(() => {
                        parentDocument.removeEventListener("click", interceptDownload, true);
                        if (!handled) {
                            setButtonState(copyButton, "!", "Unable to capture chart");
                        }
                    }, 7000);
                };

                copyButton.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    capture();
                });
                copyButton.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        capture();
                    }
                });

                const svgButton = parentDocument.createElement("a");
                svgButton.className = `modebar-btn ${svgButtonClass}`;
                svgButton.textContent = "PPT";
                svgButton.dataset.originalSymbol = "PPT";
                svgButton.dataset.originalTitle = "Download vector SVG sized 16.17 cm × 8.17 cm for PowerPoint";
                svgButton.setAttribute("data-title", svgButton.dataset.originalTitle);
                svgButton.setAttribute("aria-label", svgButton.dataset.originalTitle);
                svgButton.setAttribute("role", "button");
                svgButton.setAttribute("tabindex", "0");
                const downloadSvg = async () => {
                    const graphDiv = chartContainer.querySelector(".js-plotly-plot");
                    if (!graphDiv || !parentWindow.Plotly?.toImage) {
                        setButtonState(svgButton, "!", "SVG export is unavailable");
                        return;
                    }
                    try {
                        const svgWidth = 916;
                        const svgHeight = 463;
                        const href = await parentWindow.Plotly.toImage(graphDiv, {
                            format: "svg",
                            // These canvas values provide enough drawing room;
                            // addPowerPointFrame writes the final physical size.
                            width: svgWidth,
                            height: svgHeight,
                            scale: 1,
                        });
                        const framedHref = await addPowerPointFrame(href, svgWidth, svgHeight);
                        const link = parentDocument.createElement("a");
                        link.href = framedHref;
                        link.download = "jovi-quality-chart-powerpoint.svg";
                        parentDocument.body.appendChild(link);
                        link.click();
                        link.remove();
                        parentWindow.setTimeout(() => parentWindow.URL.revokeObjectURL(framedHref), 1000);
                        setButtonState(svgButton, "✓", "PowerPoint SVG downloaded");
                    } catch (_error) {
                        setButtonState(svgButton, "!", "Unable to export SVG");
                    }
                };
                svgButton.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    downloadSvg();
                });
                svgButton.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        downloadSvg();
                    }
                });
                nativeButton.insertAdjacentElement("afterend", copyButton);
                copyButton.insertAdjacentElement("afterend", svgButton);
            };

            const scan = () => {
                parentDocument.querySelectorAll('[data-testid="stPlotlyChart"]').forEach(addCopyButton);
            };
            const observer = new parentWindow.MutationObserver(scan);
            observer.observe(parentDocument.body, {childList: true, subtree: true});
            scan();
            window.addEventListener("unload", () => observer.disconnect(), {once: true});
        })();
        </script>
        """,
        height=0,
        scrolling=False,
    )


def install_kpi_table_copy_controls() -> None:
    """Add a user-initiated clipboard button to each KPI review table."""
    import streamlit.components.v1 as components

    components.html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const buttonClass = "jovi-copy-kpi-table";
            parentDocument.querySelectorAll(`.${buttonClass}`).forEach((button) => button.remove());

            const tableImage = async (table) => {
                const rect = table.getBoundingClientRect();
                const scale = 2;
                const canvas = parentDocument.createElement("canvas");
                canvas.width = Math.ceil(rect.width * scale);
                canvas.height = Math.ceil(rect.height * scale);
                const context = canvas.getContext("2d");
                context.scale(scale, scale);
                context.fillStyle = "#FFFFFF";
                context.fillRect(0, 0, rect.width, rect.height);
                const drawCell = (cell) => {
                    const cellRect = cell.getBoundingClientRect();
                    const x = cellRect.left - rect.left;
                    const y = cellRect.top - rect.top;
                    const style = parentWindow.getComputedStyle(cell);
                    context.fillStyle = style.backgroundColor && style.backgroundColor !== "rgba(0, 0, 0, 0)" ? style.backgroundColor : "#FFFFFF";
                    context.fillRect(x, y, cellRect.width, cellRect.height);
                    context.strokeStyle = style.borderColor || "#C8D4E3";
                    context.lineWidth = 1;
                    context.strokeRect(x, y, cellRect.width, cellRect.height);
                    context.fillStyle = style.color || "#152941";
                    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
                    context.textBaseline = "middle";
                    context.textAlign = cell.classList.contains("weekly-kpi-name") ? "left" : "center";
                    const lines = cell.innerText.split("\\n");
                    const lineHeight = parseFloat(style.fontSize) * 1.25;
                    const textY = y + cellRect.height / 2 - ((lines.length - 1) * lineHeight) / 2;
                    lines.forEach((line, index) => context.fillText(line, context.textAlign === "left" ? x + 8 : x + cellRect.width / 2, textY + index * lineHeight, cellRect.width - 12));
                };
                Array.from(table.querySelectorAll("th, td")).forEach(drawCell);
                const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
                if (!png || !parentWindow.ClipboardItem || !parentWindow.navigator?.clipboard?.write) throw new Error("Clipboard image unavailable");
                await parentWindow.navigator.clipboard.write([new parentWindow.ClipboardItem({"image/png": png})]);
            };

            parentDocument.querySelectorAll(".weekly-review-wrap").forEach((wrapper) => {
                const table = wrapper.querySelector("table");
                if (!table) return;
                const button = parentDocument.createElement("button");
                button.type = "button";
                button.className = buttonClass;
                button.textContent = "⧉ Copy as image";
                button.title = "Copy table as image";
                button.setAttribute("aria-label", "Copy table as image to clipboard");
                button.addEventListener("click", async () => {
                    try {
                        await tableImage(table);
                        button.textContent = "✓ Image copied";
                        parentWindow.setTimeout(() => { button.textContent = "⧉ Copy as image"; }, 1600);
                    } catch (_error) {
                        button.textContent = "Copy unavailable";
                        parentWindow.setTimeout(() => { button.textContent = "⧉ Copy as image"; }, 1800);
                    }
                });
                wrapper.parentNode.insertBefore(button, wrapper);
            });
        })();
        </script>
        """,
        height=0,
        scrolling=False,
    )


def skd_line_chart(df, x_col: str, y_cols: list[str], title: str, color: str):
    import pandas as pd
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
                textposition=[
                    "top center" if idx == 0 or float(value or 0) <= 0 else "bottom center"
                    for value in df[y_col]
                ],
                textfont=dict(size=11, color=palette[idx % len(palette)]),
                marker=dict(size=8, color=palette[idx % len(palette)]),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{y_col}: %{{y:,.0f}}<extra></extra>",
            )
        )
    numeric_values = [
        float(value)
        for y_col in y_cols
        for value in df[y_col]
        if value is not None and not pd.isna(value)
    ]
    maximum_value = max(numeric_values, default=0)
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left"),
        template="plotly_white",
        height=410,
        autosize=True,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=dict(l=50, r=35, t=80, b=90),
        legend=dict(orientation="h", yanchor="top", y=-0.19, xanchor="center", x=0.5),
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor="#C8D3E3",
        tickfont=dict(color="#17243A"),
        tickangle=-35 if len(df) > 10 else 0,
        automargin=True,
    )
    fig.update_yaxes(
        range=[0, maximum_value * 1.2] if maximum_value > 0 else None,
        gridcolor="#DDE5F0",
        linecolor="#C8D3E3",
        tickfont=dict(color="#17243A"),
        automargin=True,
    )
    return fig


def skd_bar_chart(df, x_col: str, y_col: str, title: str, color: str, orientation: str = "v"):
    import pandas as pd
    import plotly.express as px

    maximum_value = pd.to_numeric(df[y_col], errors="coerce").max()
    if orientation == "h":
        fig = px.bar(df, x=y_col, y=x_col, orientation="h", title=title, color_discrete_sequence=[color])
        fig.update_layout(yaxis=dict(autorange="reversed"))
        fig.update_traces(
            text=[fmt_compact(value) for value in df[y_col]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11, color="#0B1F3A"),
        )
        chart_height = max(390, len(df) * 34 + 120)
        chart_margin = dict(l=35, r=90, t=75, b=45)
    else:
        fig = px.bar(df, x=x_col, y=y_col, title=title, color_discrete_sequence=[color])
        fig.update_traces(
            text=[fmt_compact(value) for value in df[y_col]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11, color="#0B1F3A"),
        )
        chart_height = 400
        chart_margin = dict(l=50, r=35, t=80, b=75)
    fig.update_layout(
        template="plotly_white",
        height=chart_height,
        autosize=True,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=chart_margin,
        showlegend=False,
        uniformtext_minsize=9,
        uniformtext_mode="show",
    )
    if orientation == "h":
        fig.update_xaxes(
            range=[0, float(maximum_value) * 1.24] if pd.notna(maximum_value) and maximum_value > 0 else None,
            gridcolor="#DDE5F0",
            linecolor="#C8D3E3",
            tickfont=dict(color="#17243A"),
            automargin=True,
        )
        fig.update_yaxes(gridcolor="#DDE5F0", linecolor="#C8D3E3", tickfont=dict(color="#17243A"), automargin=True)
    else:
        fig.update_xaxes(
            gridcolor="#DDE5F0",
            linecolor="#C8D3E3",
            tickfont=dict(color="#17243A"),
            tickangle=-35 if len(df) > 8 else 0,
            automargin=True,
        )
        fig.update_yaxes(
            range=[0, float(maximum_value) * 1.2] if pd.notna(maximum_value) and maximum_value > 0 else None,
            gridcolor="#DDE5F0",
            linecolor="#C8D3E3",
            tickfont=dict(color="#17243A"),
            automargin=True,
        )
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
                textposition="outside",
                textfont=dict(color="#0B1F3A", size=12),
                cliponaxis=False,
                hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        template="plotly_white",
        height=380,
        autosize=True,
        title="Rejudge OK Rate",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFD",
        font=dict(color="#0B1F3A"),
        margin=dict(l=45, r=25, t=85, b=60),
        showlegend=False,
        xaxis_title="",
        yaxis_title="% of total records",
    )
    fig.update_xaxes(showgrid=False, linecolor="#C8D3E3", tickfont=dict(color="#0B1F3A"))
    fig.update_yaxes(range=[0, 115], gridcolor="#DDE5F0", linecolor="#C8D3E3", ticksuffix="%", tickfont=dict(color="#17243A"))
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
    start_date, end_date = analysis_period_control(
        "assembly_analysis_period",
        start_default,
        end_default,
        default_start=start_default,
        default_end=end_default,
    )
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
    if is_admin() and not st.session_state.get("assembly_auto_import_checked", False):
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
        persist_state="session",
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
    if "PeriodDate" in trend.columns:
        trend["Period"] = trend["PeriodDate"].map(
            lambda value: format_trend_period(value, trend_settings["grain"])
        )
    model_summary = analysis["model_summary"].copy()
    merge_stats = analysis.get("defect_merge_stats", {})
    production_input_stats = analysis.get("production_input_stats", {})
    period_start = coerce_timestamp(rules.get("date_start", "2026-01-01"), "2026-01-01").strftime("%d/%m/%Y")
    period_end = coerce_timestamp(rules.get("date_end", "2026-12-31"), "2026-12-31").strftime("%d/%m/%Y")
    period_note = f"{period_start} to {period_end}"

    if trend_settings.get("summarized_input_rows", 0):
        if trend_settings.get("input_distributed"):
            st.info(
                f"Trend standard: summarized {trend_settings['input_grain']} input was distributed across its "
                f"calendar days. The exact source-period production total is preserved."
            )
        elif trend_settings.get("input_resolution_limited"):
            st.warning(f"Input resolution limited the trend to {trend_settings['title']}.")
        else:
            st.caption(
                f"Summarized {trend_settings['input_grain']} input was detected. "
                f"Production, PPM and ManDo PPM trends are displayed {trend_settings['title']}."
            )

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
            skd_metric_card("Excluded retest / False NG", fmt_int(totals["rejudge_ok"]), fmt_pct(totals["rejudge_rate"]))
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
                for item in st.text_area("Exclusion keywords (Re-Judge / retest)", value="\n".join(stored_rules["rejudge_ok_keywords"])).splitlines()
                if item.strip()
            ]
            edited["mando_keywords"] = [
                item.strip()
                for item in st.text_area("ManDo keywords", value="\n".join(stored_rules["mando_keywords"])).splitlines()
                if item.strip()
            ]
            if st.form_submit_button("Save rules", disabled=not is_admin()):
                save_rules(edited)
                st.success("Rules saved. The dashboard will use the updated rules on rerun.")
                st.rerun()

    if active_section == "Details":
        raw = analysis["raw"].copy()
        selected_model = st.selectbox("Model", ["All", *sorted(raw["Model"].dropna().unique())], key="assembly_detail_model", persist_state="session")
        selected_line = st.selectbox("Line", ["All", *sorted(raw["Line"].dropna().unique())], key="assembly_detail_line", persist_state="session")
        selected_type = st.selectbox("Record type", ["All", "Confirmed defects", "Excluded retest", "ManDo only"], key="assembly_detail_type", persist_state="session")
        view = raw
        if selected_model != "All":
            view = view[view["Model"] == selected_model]
        if selected_line != "All":
            view = view[view["Line"] == selected_line]
        if selected_type == "Confirmed defects":
            view = view[view["ConfirmedDefect"]]
        elif selected_type == "Excluded retest":
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
            "ExclusionReason",
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
                <p class="small-muted">Quality analysis dashboard for Assembly SKD data. The logic separates approved retest / False NG records from confirmed defects, calculates PPM by month/model, and includes a dedicated ManDo analysis.</p>
                <p><b>Default source:</b> Jan-Jun/2026 sample data in <span class="small-muted">sample_data/assembly</span>.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def smart_report_reference_date() -> date:
    from tools import smt_quality_dashboard

    latest_dates = []
    try:
        smt_inputs, _ = smt_quality_dashboard.stored_smt_sources()
        if smt_inputs:
            signatures = tuple(smt_quality_dashboard.path_signature(path) for path in smt_inputs)
            _, end = smt_quality_dashboard.input_bounds(signatures)
            latest_dates.append(end.date())
    except Exception:
        pass
    try:
        assembly_inputs = stored_assembly_sources_v2()["input"]
        if assembly_inputs:
            _, end = assembly_input_bounds(assembly_inputs)
            latest_dates.append(end)
    except Exception:
        pass
    return min(latest_dates) if latest_dates else date.today()


def smart_report_period_selector(reference_date: date) -> tuple[str, date, date, str, str]:
    report_type = st.segmented_control(
        "Report type",
        ["Daily", "Weekly", "Monthly"],
        default="Daily",
        selection_mode="single",
        key="smart_report_type",
        persist_state="session",
        label_visibility="collapsed",
    ) or "Daily"
    selected = st.date_input(
        "Reference date",
        value=reference_date,
        key="smart_report_reference_date",
        persist_state="session",
        label_visibility="collapsed",
    )
    if report_type == "Daily":
        start = end = selected
        label = selected.strftime("%m/%d/%Y")
    elif report_type == "Weekly":
        start = selected - timedelta(days=selected.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%m/%d/%Y')} – {end.strftime('%m/%d/%Y')}"
    else:
        start = selected.replace(day=1)
        following_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = following_month - timedelta(days=1)
        label = start.strftime("%b %Y")
    period_key = f"{report_type}|{start.isoformat()}|{end.isoformat()}"
    return report_type, start, end, label, period_key


def smart_report_defect_key(frame):
    import pandas as pd

    if frame.empty:
        return pd.Series(dtype="object", index=frame.index)
    if "PCB" in frame.columns:
        pcb = frame["PCB"].fillna("").astype(str).str.strip()
        return pcb.where(pcb.ne(""), "ROW-" + frame.index.astype(str))
    return "ROW-" + frame.index.astype(str)


def smart_report_candidates(frame, produced: int) -> list[dict]:
    import pandas as pd
    from tools.smart_report_rules import top_issue_reasons

    if frame.empty:
        return []
    data = frame.copy()
    data["FailureType"] = data.get("FailureType", "Unclassified").fillna("Unclassified").astype(str)
    data["TopIssue"] = top_issue_reasons(data)
    data["_SmartDefectKey"] = smart_report_defect_key(data)
    grouped = (
        data.groupby(["FailureType", "TopIssue"], as_index=False)
        .agg(Cases=("_SmartDefectKey", "nunique"))
    )
    grouped = grouped.sort_values(
        ["Cases", "TopIssue", "FailureType"],
        ascending=[False, True, True],
    ).head(8)
    candidates = []
    for row in grouped.itertuples(index=False):
        cases = int(row.Cases)
        rate = cases / produced * 100 if produced else None
        candidates.append(
            {
                "defect": str(row.TopIssue),
                "failure_type": str(row.FailureType),
                "cases": cases,
                "rate": rate,
                "key": f"{row.FailureType}|{row.TopIssue}",
            }
        )
    return candidates


def smart_report_smt_data(start_date: date, end_date: date) -> tuple[list[dict], int, int, str]:
    from tools import smt_quality_dashboard

    input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
    if not input_paths or not defect_paths:
        return [], 0, 0, "SMT input and defect files are required."
    signatures_input = tuple(smt_quality_dashboard.path_signature(path) for path in input_paths)
    signatures_defect = tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths)
    analysis = smt_quality_dashboard.analyze_smt_quality_paths(
        signatures_input,
        signatures_defect,
        start_date.isoformat(),
        end_date.isoformat(),
    )
    raw = analysis["raw"].copy()
    confirmed = raw[~raw["IsRejudgeOK"].fillna(False).astype(bool)].copy()
    produced = int(analysis["selected_input"]["Input"].sum())
    repeated = int(analysis["totals"].get("RepeatedPCBs", 0))
    return smart_report_candidates(confirmed, produced), produced, repeated, ""


def smart_report_assembly_data(start_date: date, end_date: date) -> tuple[list[dict], int, int, str]:
    try:
        metrics = calculate_assembly_kpi_metrics(start_date, end_date)
    except Exception as exc:
        return [], 0, 0, str(exc)
    confirmed = metrics["defects"].copy()
    confirmed["FailureType"] = confirmed["FailureType"].map(
        {
            "Funcional": "Functional Failure",
            "Aparência": "Appearance Failure",
            "Fora do escopo": "Unclassified",
        }
    ).fillna("Unclassified")
    produced = int(metrics["produced"])
    frequency = smart_report_defect_key(confirmed).value_counts()
    repeated = int((frequency > 1).sum())
    return smart_report_candidates(confirmed, produced), produced, repeated, ""


def smart_report_kpi_candidates(start_date: date, end_date: date) -> dict[str, list[dict]]:
    """Rank defect phenomena within each KPI's actual calculation scope."""
    import pandas as pd
    from tools import smt_quality_dashboard
    from tools.smart_report_rules import kpi_defect_scopes

    candidates = {item["source"]: [] for item in WEEKLY_KPI_DIRECTORY}
    smt_confirmed = pd.DataFrame()
    assembly_confirmed = pd.DataFrame()
    smt_produced = 0
    assembly_produced = 0
    try:
        input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
        if input_paths and defect_paths:
            analysis = smt_quality_dashboard.analyze_smt_quality_paths(
                tuple(smt_quality_dashboard.path_signature(path) for path in input_paths),
                tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths),
                start_date.isoformat(),
                end_date.isoformat(),
                smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
            )
            smt_confirmed = analysis["covered_raw"].copy()
            smt_confirmed = smt_confirmed[~smt_confirmed["IsRejudgeOK"].fillna(False).astype(bool)]
            smt_produced = int(analysis["selected_input"]["Input"].sum())
    except Exception:
        pass
    try:
        assembly_metrics = calculate_assembly_kpi_metrics(start_date, end_date)
        assembly_confirmed = assembly_metrics["defects"].copy()
        assembly_produced = int(assembly_metrics["produced"])
    except Exception:
        pass

    for source, frame in kpi_defect_scopes(smt_confirmed, assembly_confirmed).items():
        produced = assembly_produced if source.startswith("assembly_") or source == "smt_assembly_duty" else smt_produced
        candidates[source] = smart_report_candidates(frame, produced)
    return candidates


def smart_report_action_defaults(actions: dict[str, dict], item: dict) -> dict:
    return actions.get(
        item["key"],
        {
            "root_cause": "",
            "cause_status": "Under investigation",
            "containment": "",
            "countermeasure": "",
            "owner": "",
            "due_date": "",
        },
    )


def smart_report_selected_items(area: str, candidates: list[dict], period_key: str) -> list[dict]:
    labels = [f"{item['failure_type']} · {item['defect']} ({item['cases']} cases)" for item in candidates]
    selected_labels = st.session_state.get(f"smart_report_selection_{area}_{period_key}", labels[:3])
    selected_set = set(selected_labels)
    return [item for label, item in zip(labels, candidates) if label in selected_set]


def smart_report_rate(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "N/A"


def smart_report_area_html(area: str, color: str, items: list[dict], actions: dict[str, dict]) -> str:
    icon = "▦" if area == "SMT" else "⚙"
    if not items:
        return (
            f"<div class='smart-area-panel'><div class='smart-area-head'><span class='smart-area-icon' style='background:{color};'>{icon}</span>"
            f"<span class='smart-area-title' style='color:{color};'>{area}</span></div>"
            "<div class='smart-area-caption'>No reportable defects in the selected period.</div></div>"
        )
    rows = []
    for index, item in enumerate(items):
        selected_class = " selected" if index == 0 else ""
        rows.append(
            f"<div class='smart-defect-item{selected_class}'>"
            f"<span class='smart-defect-rank' style='background:{color};'>{index + 1}</span>"
            f"<span>{escape(item['defect'])}</span>"
            f"<span class='smart-defect-meta'>{item['cases']} cases | {smart_report_rate(item['rate'])}</span></div>"
        )
    focus = items[0]
    action = smart_report_action_defaults(actions, focus)
    owner_due = " · ".join(part for part in [action["owner"], action["due_date"]] if part) or "to be defined"
    return (
        f"<div class='smart-area-panel'><div class='smart-area-head'><span class='smart-area-icon' style='background:{color};'>{icon}</span>"
        f"<span class='smart-area-title' style='color:{color};'>{area}</span></div>"
        "<div class='smart-area-caption'>Top 3 issues · functional failures first</div>"
        f"<div class='smart-defect-list'>{''.join(rows)}</div><div class='smart-action-summary'>"
        f"<div class='smart-action-row'><span class='smart-action-label'>Cause</span><span>{escape(action['root_cause'] or 'under investigation')} — {escape(action['cause_status'].lower())}</span></div>"
        f"<div class='smart-action-row'><span class='smart-action-label'>Containment</span><span>{escape(action['containment'] or 'not informed')}</span></div>"
        f"<div class='smart-action-row'><span class='smart-action-label'>Countermeasure</span><span>{escape(action['countermeasure'] or 'not informed')} — {escape(owner_due)}</span></div>"
        "</div></div>"
    )


def smart_report_area_panel(area: str, color: str, candidates: list[dict], period_key: str) -> tuple[list[dict], dict[str, dict]]:
    actions = load_smart_report_actions(area, period_key)
    labels = [f"{item['failure_type']} · {item['defect']} ({item['cases']} cases)" for item in candidates]
    by_label = dict(zip(labels, candidates))
    default_labels = labels[:3]
    with st.expander("Select up to three defects for the report"):
        selected_labels = st.multiselect(
            "Reported defects",
            labels,
            default=default_labels,
            max_selections=3,
            key=f"smart_report_selection_{area}_{period_key}",
            persist_state="session",
        )
        st.caption("Suggestions are ranked by affected PCB count. Select the defects that are operationally relevant.")
    selected = [by_label[label] for label in labels if label in selected_labels]
    st.markdown(smart_report_area_html(area, color, selected, actions), unsafe_allow_html=True)
    if candidates and is_admin():
        with st.expander("Edit cause, containment, and countermeasure"):
            selected_label = st.selectbox(
                "Defect being edited",
                labels,
                key=f"smart_report_edit_{area}_{period_key}",
                persist_state="session",
            )
            item = by_label[selected_label]
            action = smart_report_action_defaults(actions, item)
            with st.form(f"smart_report_action_form_{area}_{period_key}_{item['key']}"):
                include = st.checkbox("Include in report", value=item in selected)
                status_options = ["Confirmed", "Under investigation", "Undefined"]
                status = action["cause_status"] if action["cause_status"] in status_options else "Under investigation"
                c1, c2 = st.columns([1, 2])
                with c1:
                    cause_status = st.selectbox("Cause status", status_options, index=status_options.index(status))
                with c2:
                    root_cause = st.text_input("Root cause", value=action["root_cause"])
                containment = st.text_input("Containment", value=action["containment"])
                countermeasure = st.text_input("Countermeasure", value=action["countermeasure"])
                c3, c4 = st.columns(2)
                with c3:
                    owner = st.text_input("Owner", value=action["owner"])
                with c4:
                    due_date = st.text_input("Due date", value=action["due_date"], placeholder="MM/DD/YYYY")
                if st.form_submit_button("Save information", use_container_width=True):
                    save_smart_report_action(
                        area,
                        period_key,
                        item,
                        {
                            "root_cause": root_cause,
                            "cause_status": cause_status,
                            "containment": containment,
                            "countermeasure": countermeasure,
                            "owner": owner,
                            "due_date": due_date,
                        },
                    )
                    if not include:
                        current_key = f"smart_report_selection_{area}_{period_key}"
                        current_labels = [value for value in st.session_state.get(current_key, default_labels) if value != selected_label]
                        st.session_state[current_key] = current_labels
                    st.success("Information saved without changing the source files.")
                    st.rerun()
    return selected, actions


def smart_report_message(report_type: str, period_label: str, selected_by_area: dict[str, list[dict]], actions_by_area: dict[str, dict]) -> str:
    lines = [f"📊 QUALITY {report_type.upper()} — {period_label}", ""]
    for area, items in selected_by_area.items():
        lines.append(f"{'🔧' if area == 'SMT' else '⚙️'} {area}")
        if not items:
            lines.append("No defects selected.")
        for rank, item in enumerate(items, start=1):
            action = smart_report_action_defaults(actions_by_area[area], item)
            owner_due = ""
            if action["owner"] or action["due_date"]:
                owner_due = f" — {action['owner']}, {action['due_date']}".rstrip(" ,")
            lines.extend(
                [
                    f"{rank}. {item['defect']} — {item['cases']} cases | {smart_report_rate(item['rate'])}",
                    f"   Cause: {action['root_cause'] or 'under investigation'} — {action['cause_status'].lower()}",
                    f"   Containment: {action['containment'] or 'not informed'}",
                    f"   Countermeasure: {action['countermeasure'] or 'not informed'}{owner_due}",
                    "",
                ]
            )
    return "\n".join(lines).strip()


def smart_report_kpi_cards(selected_by_area: dict[str, list[dict]], inputs: dict[str, int], repeats: dict[str, int], actions: dict[str, dict]) -> None:
    selected = [item for area_items in selected_by_area.values() for item in area_items]
    total_cases = sum(item["cases"] for item in selected)
    total_input = sum(inputs.values())
    defect_rate = total_cases / total_input * 100 if total_input else None
    open_actions = sum(
        not smart_report_action_defaults(actions[area], item)["root_cause"]
        or smart_report_action_defaults(actions[area], item)["cause_status"] != "Confirmed"
        for area, area_items in selected_by_area.items()
        for item in area_items
    )
    recurrence = sum(repeats.values()) / total_cases * 100 if total_cases else 0
    cards = [
        ("Total defects", f"{total_cases:,}", "Selected report items", False),
        ("Defect rate", smart_report_rate(defect_rate), "Selected scope", False),
        ("Open actions", str(open_actions), "Cause not yet confirmed", True),
        ("Recurrence", smart_report_rate(recurrence), "Repeated boards in selected scope", False),
    ]
    columns = st.columns(4)
    for column, (label, value, note, attention) in zip(columns, cards):
        with column:
            note_class = " attention" if attention else ""
            st.markdown(
                f"<div class='smart-kpi'><div class='smart-kpi-label'>{label}</div><div class='smart-kpi-value'>{value}</div><div class='smart-kpi-note{note_class}'>{note}</div></div>",
                unsafe_allow_html=True,
            )


def defect_action_report_page() -> None:
    st.markdown("<div class='smart-report-title'>Smart Report</div><div class='smart-report-subtitle'>Fast, actionable reports generated from the stored SMT and Assembly inputs.</div>", unsafe_allow_html=True)
    control_column, area_column, action_column = st.columns([1.8, 1.55, 0.85])
    with control_column:
        st.markdown("<div class='smart-control-label'>Report period</div>", unsafe_allow_html=True)
        report_type, start_date, end_date, period_label, period_key = smart_report_period_selector(smart_report_reference_date())
    with area_column:
        st.markdown("<div class='smart-control-label'>Area</div>", unsafe_allow_html=True)
        area_filter = st.segmented_control(
            "Area",
            ["All", "SMT", "Assembly"],
            default="All",
            selection_mode="single",
            key="smart_report_area_filter",
            persist_state="session",
            label_visibility="collapsed",
        ) or "All"
    with action_column:
        st.markdown("<div class='smart-control-label'>&nbsp;</div>", unsafe_allow_html=True)
        if st.button("Generate report", use_container_width=True, type="primary"):
            st.toast("Report suggestions refreshed from the stored input data.")

    area_results = {}
    for area, loader in [("SMT", smart_report_smt_data), ("Assembly", smart_report_assembly_data)]:
        try:
            area_results[area] = loader(start_date, end_date)
        except Exception as exc:
            area_results[area] = ([], 0, 0, str(exc))
    areas = ["SMT", "Assembly"] if area_filter == "All" else [area_filter]
    for area in areas:
        error = area_results[area][3]
        if error:
            st.warning(f"{area} data could not be calculated for this period: {error}")

    selected_by_area: dict[str, list[dict]] = {}
    actions_by_area: dict[str, dict] = {}
    inputs = {area: area_results[area][1] for area in areas}
    repeats = {area: area_results[area][2] for area in areas}
    for area in areas:
        selected_by_area[area] = smart_report_selected_items(area, area_results[area][0], period_key)
        actions_by_area[area] = load_smart_report_actions(area, period_key)
    smart_report_kpi_cards(selected_by_area, inputs, repeats, actions_by_area)
    st.write("")
    message = smart_report_message(report_type, period_label, selected_by_area, actions_by_area)
    if len(areas) == 2:
        smt_column, assembly_column, preview_column = st.columns([1.05, 1.05, 1.0])
        with smt_column:
            smart_report_area_panel("SMT", MODULES["SMT"]["color"], area_results["SMT"][0], period_key)
        with assembly_column:
            smart_report_area_panel("Assembly", MODULES["Assembly"]["color"], area_results["Assembly"][0], period_key)
        with preview_column:
            st.markdown("<div class='smart-whatsapp-panel'><div class='smart-area-head'><span class='smart-area-icon' style='background:#16A05D;'>◔</span><span class='smart-area-title'>WhatsApp Preview</span></div><div class='smart-preview-copy'>" + escape(message) + "</div><div class='smart-preview-footnote'>Preview based on selected real-data defects.</div></div>", unsafe_allow_html=True)
            if st.button("Copy for WhatsApp", key="smart_report_copy_all", use_container_width=True):
                st.toast("Select the preview text and copy it to WhatsApp.")
    else:
        report_column, preview_column = st.columns([1.3, 1.0])
        area = areas[0]
        with report_column:
            smart_report_area_panel(area, MODULES[area]["color"], area_results[area][0], period_key)
        with preview_column:
            st.markdown("<div class='smart-whatsapp-panel'><div class='smart-area-head'><span class='smart-area-icon' style='background:#16A05D;'>◔</span><span class='smart-area-title'>WhatsApp Preview</span></div><div class='smart-preview-copy'>" + escape(message) + "</div><div class='smart-preview-footnote'>Preview based on selected real-data defects.</div></div>", unsafe_allow_html=True)
            if st.button("Copy for WhatsApp", key="smart_report_copy_single", use_container_width=True):
                st.toast("Select the preview text and copy it to WhatsApp.")
    with st.expander("Copyable report text"):
        st.code(message, language=None)
    st.caption("The report reads the existing stored data. Only action details are saved separately in the local quality database.")


WEEKLY_KPI_DIRECTORY = (
    {"area": "Assembly", "kpi": "Functional Pass Rate", "target": 0.9905, "direction": "min", "gbr": "Ewerton", "jovi": "Jeffry", "source": "assembly_function"},
    {"area": "Assembly", "kpi": "Appearance Pass Rate", "target": 0.9904, "direction": "min", "gbr": "Joao", "jovi": "Key", "source": "assembly_appearance"},
    {"area": "Assembly", "kpi": "Function Mando (PPM)", "target": 3600.0, "direction": "max", "gbr": "Lene", "jovi": "Jason", "source": "assembly_mando"},
    {"area": "Assembly", "kpi": "Assembly OQC*FQC Pass Rate", "target": 0.9870, "direction": "min", "gbr": "Douglas", "jovi": "Jason", "source": "assembly_oqc_fqc"},
    {"area": "SMT", "kpi": "Functional Pass Rate", "target": 0.9966, "direction": "min", "gbr": "Afranio", "jovi": "Jeffry", "source": "smt_function"},
    {"area": "SMT", "kpi": "SMT Process NG Rate (PPM)", "target": 5000.0, "direction": "max", "gbr": "Felipe - SMT", "jovi": "Hanlin", "source": "smt_process"},
    {"area": "SMT", "kpi": "Assembly SMT Process Duty NG Rate (PPM)", "target": 700.0, "direction": "max", "gbr": "Alan", "jovi": "Blanc", "source": "smt_assembly_duty"},
    {"area": "SMT", "kpi": "SMT OQC Pass Rate", "target": 0.9850, "direction": "min", "gbr": "Douglas", "jovi": "Hanlin", "source": "smt_oqc"},
)


def configured_kpi_directory() -> tuple[dict, ...]:
    overrides = load_weekly_kpi_owners()
    return tuple(
        {
            **item,
            "gbr": overrides.get(item["source"], {}).get("gbr") or item["gbr"],
            "jovi": overrides.get(item["source"], {}).get("jovi") or item["jovi"],
            "target": overrides.get(item["source"], {}).get("target") if overrides.get(item["source"], {}).get("target") is not None else item["target"],
        }
        for item in WEEKLY_KPI_DIRECTORY
    )


def weekly_kpi_value_label(value: float | None, direction: str) -> str:
    if value is None:
        return "—"
    return fmt_ppm(value) if direction == "max" else fmt_kpi_pct(value)


def weekly_kpi_is_below_target(value: float | None, target: float, direction: str) -> bool:
    if value is None:
        return False
    return float(value) > target if direction == "max" else float(value) < target


def weekly_kpi_review_data(
    start_date: date,
    end_date: date,
    *,
    require_defect_coverage: bool = False,
) -> tuple[
    dict[str, float | None],
    dict[str, dict[date, float | None]],
    dict[str, str],
    dict[str, str],
    dict[str, dict[date, str]],
]:
    """Use the same validated KPI engines to prepare weekly or monthly review tables."""
    import pandas as pd
    from tools import smt_quality_dashboard

    totals: dict[str, float | None] = {item["source"]: None for item in WEEKLY_KPI_DIRECTORY}
    daily: dict[str, dict[date, float | None]] = {item["source"]: {} for item in WEEKLY_KPI_DIRECTORY}
    errors: dict[str, str] = {}
    total_exceptions: dict[str, str] = {}
    daily_exceptions: dict[str, dict[date, str]] = {item["source"]: {} for item in WEEKLY_KPI_DIRECTORY}

    def add_daily(frame, source: str, value_column: str, status_column: str | None = None) -> None:
        if frame is None or frame.empty or value_column not in frame.columns:
            return
        date_column = next(
            (column for column in ("PeriodDate", "PeriodStart", "Date") if column in frame.columns),
            None,
        )
        if date_column is None:
            return
        selected_columns = [date_column, value_column]
        if status_column and status_column in frame.columns:
            selected_columns.append(status_column)
        values = frame[selected_columns].copy()
        values[date_column] = pd.to_datetime(values[date_column], errors="coerce").dt.date
        for _, row in values.dropna(subset=[date_column]).iterrows():
            day = row[date_column]
            status = str(row.get(status_column, "Valid")) if status_column else "Valid"
            if status != "Valid":
                daily[source][day] = None
                daily_exceptions[source][day] = status
            else:
                raw_value = row[value_column]
                daily[source][day] = None if pd.isna(raw_value) else float(raw_value)

    def source_dates_cover_inputs(inputs, input_date_column: str, defect_start, defect_end) -> tuple[bool, date | None, date | None]:
        if inputs is None or inputs.empty or input_date_column not in inputs.columns:
            return False, None, None
        input_dates = pd.to_datetime(inputs[input_date_column], errors="coerce").dropna()
        if input_dates.empty or defect_start is None or defect_end is None or pd.isna(defect_start) or pd.isna(defect_end):
            return False, None, None
        input_start = input_dates.min().date()
        input_end = input_dates.max().date()
        defect_start_date = pd.Timestamp(defect_start).date()
        defect_end_date = pd.Timestamp(defect_end).date()
        return defect_start_date <= input_start and defect_end_date >= input_end, defect_start_date, defect_end_date

    def restrict_daily_to_defect_coverage(source: str, defect_start: date | None, defect_end: date | None) -> None:
        if defect_start is None or defect_end is None:
            daily[source] = {day: None for day in daily[source]}
            daily_exceptions[source] = {}
            return
        daily[source] = {
            day: value if defect_start <= day <= defect_end else None
            for day, value in daily[source].items()
        }
        daily_exceptions[source] = {
            day: reason for day, reason in daily_exceptions[source].items()
            if defect_start <= day <= defect_end
        }

    try:
        input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
        if not input_paths or not defect_paths:
            raise RuntimeError("SMT FPY input and defect files are required.")
        analysis = smt_quality_dashboard.analyze_smt_quality_paths(
            tuple(smt_quality_dashboard.path_signature(path) for path in input_paths),
            tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths),
            start_date.isoformat(),
            end_date.isoformat(),
            smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
        )
        smt_totals = analysis["totals"]
        smt_covered, smt_defect_start, smt_defect_end = source_dates_cover_inputs(
            analysis.get("selected_input"),
            "BeginDate",
            analysis.get("source_defect_start"),
            analysis.get("source_defect_end"),
        )
        totals["smt_function"] = smt_totals.get("FunctionPassRate") if (smt_covered or not require_defect_coverage) and smt_totals.get("FunctionPassStatus") == "Valid" else None
        totals["smt_process"] = smt_totals.get("SMTProcessNGRatePPM") if (smt_covered or not require_defect_coverage) and smt_totals.get("SMTProcessStatus") == "Valid" else None
        add_daily(analysis.get("trend"), "smt_function", "FunctionPassRate", "FunctionPassStatus")
        add_daily(analysis.get("trend"), "smt_process", "SMTProcessNGRatePPM", "SMTProcessStatus")
        if require_defect_coverage:
            restrict_daily_to_defect_coverage("smt_function", smt_defect_start, smt_defect_end)
            restrict_daily_to_defect_coverage("smt_process", smt_defect_start, smt_defect_end)
        if require_defect_coverage and not smt_covered:
            errors["SMT"] = "Functional and Process KPIs require an FPY defect file whose dates cover every selected SMT input day."
        oqc = load_smt_oqc_inspections(start_date, end_date)
        if not oqc.empty:
            inspected = int(oqc["Inspected"].sum())
            totals["smt_oqc"] = int(oqc["OK"].sum()) / inspected if inspected else None
            oqc_trend, _ = build_smt_oqc_trend(oqc, start_date, end_date)
            add_daily(oqc_trend, "smt_oqc", "PassRate")
    except Exception as exc:
        errors["SMT"] = str(exc)

    try:
        assembly = calculate_assembly_kpi_metrics(start_date, end_date)
        assembly_covered, assembly_defect_start, assembly_defect_end = source_dates_cover_inputs(
            assembly.get("inputs"),
            "Date",
            assembly.get("source_defect_start"),
            assembly.get("source_defect_end"),
        )
        totals["assembly_function"] = assembly.get("function_pass_rate") if assembly_covered or not require_defect_coverage else None
        totals["assembly_appearance"] = assembly.get("appearance_pass_rate") if assembly_covered or not require_defect_coverage else None
        totals["assembly_mando"] = assembly.get("function_mando_ppm") if assembly_covered or not require_defect_coverage else None
        add_daily(assembly.get("trend"), "assembly_function", "FunctionPassRate", "FunctionPassStatus")
        add_daily(assembly.get("trend"), "assembly_appearance", "AppearanceTotalPassRate", "AppearancePassStatus")
        add_daily(assembly.get("trend"), "assembly_mando", "FunctionMandoPPM", "FunctionMandoStatus")
        if require_defect_coverage:
            restrict_daily_to_defect_coverage("assembly_function", assembly_defect_start, assembly_defect_end)
            restrict_daily_to_defect_coverage("assembly_appearance", assembly_defect_start, assembly_defect_end)
            restrict_daily_to_defect_coverage("assembly_mando", assembly_defect_start, assembly_defect_end)
        if require_defect_coverage and not assembly_covered:
            errors["Assembly"] = "Functional, Appearance and Mando KPIs require an FPY defect file whose dates cover every selected Assembly input day."
        duty = calculate_assembly_smt_duty_kpi(start_date, end_date)
        totals["smt_assembly_duty"] = duty.get("duty_ppm")
        add_daily(duty.get("trend"), "smt_assembly_duty", "DutyPPM", "SMTDutyStatus")
        oqc_fqc = load_assembly_oqc_fqc_inspections(start_date, end_date)
        if not oqc_fqc.empty:
            oqc_inspected = int(oqc_fqc["OQCInspected"].sum())
            fqc_inspected = int(oqc_fqc["FQCInspected"].sum())
            if oqc_inspected and fqc_inspected:
                totals["assembly_oqc_fqc"] = (int(oqc_fqc["OQCOK"].sum()) / oqc_inspected) * (int(oqc_fqc["FQCOK"].sum()) / fqc_inspected)
            oqc_fqc_trend, _ = build_assembly_oqc_fqc_trend(oqc_fqc, start_date, end_date)
            add_daily(oqc_fqc_trend, "assembly_oqc_fqc", "CombinedPassRate")
    except Exception as exc:
        errors["Assembly"] = str(exc)

    return totals, daily, errors, total_exceptions, daily_exceptions


def kpi_review_table(
    directory: tuple[dict, ...],
    summary_columns: list[tuple[str, dict[str, float | None], dict[str, str]]],
    daily: dict[str, dict[date, float | None]],
    days: list[date],
    daily_exceptions: dict[str, dict[date, str]] | None = None,
) -> None:
    headers = ["Area", "KPI", "Brazil<br>Goal", "GBR", "Jovi"] + [column[0] for column in summary_columns] + [f"{day.day}-{day.strftime('%b')}" for day in days]
    colgroup = (
        "<colgroup><col class='weekly-col-area'><col class='weekly-col-kpi'>"
        "<col class='weekly-col-meta'><col class='weekly-col-meta'><col class='weekly-col-meta'>"
        + "<col class='weekly-col-summary'>" * len(summary_columns)
        + "<col class='weekly-col-day'>" * len(days)
        + "</colgroup>"
    )
    layout_class = "weekly-layout" if days else "monthly-layout"
    rows = []
    area_counts = {area: sum(item["area"] == area for item in directory) for area in {item["area"] for item in directory}}
    seen_areas = set()
    for item in directory:
        area_cell = ""
        if item["area"] not in seen_areas:
            area_cell = f"<td class='weekly-area' rowspan='{area_counts[item['area']]}'>{escape(item['area'])}</td>"
            seen_areas.add(item["area"])
        cells = [
            area_cell,
            f"<td class='weekly-kpi-name'>{escape(item['kpi'])}</td>",
            f"<td>{escape(weekly_kpi_value_label(item['target'], item['direction']))}</td>",
            f"<td>{escape(item['gbr'])}</td>",
            f"<td>{escape(item['jovi'])}</td>",
        ]
        for _, summary, summary_exceptions in summary_columns:
            summary_value = summary.get(item["source"])
            exception = (summary_exceptions or {}).get(item["source"])
            summary_class = " exception" if exception else " below" if weekly_kpi_is_below_target(summary_value, item["target"], item["direction"]) else " on-target" if summary_value is not None else " unavailable"
            label = "×" if exception else weekly_kpi_value_label(summary_value, item["direction"])
            tooltip = f" title='{escape(str(exception), quote=True)}'" if exception else ""
            cells.append(f"<td class='weekly-value{summary_class}'{tooltip}>{escape(label)}</td>")
        for day in days:
            daily_value = daily.get(item["source"], {}).get(day)
            exception = (daily_exceptions or {}).get(item["source"], {}).get(day)
            daily_class = " exception" if exception else " below" if weekly_kpi_is_below_target(daily_value, item["target"], item["direction"]) else " on-target" if daily_value is not None else " unavailable"
            label = "×" if exception else weekly_kpi_value_label(daily_value, item["direction"])
            tooltip = f" title='{escape(str(exception), quote=True)}'" if exception else ""
            cells.append(f"<td class='weekly-value{daily_class}'{tooltip}>{escape(label)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f"<div class='weekly-review-wrap {layout_class}'><table class='weekly-review-table {layout_class}'>" + colgroup + "<thead><tr>" + "".join(f"<th>{header}</th>" for header in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    install_kpi_table_copy_controls()


def weekly_kpi_slide_panels(
    area: str,
    directory: tuple[dict, ...],
    previous_label: str,
    current_label: str,
    previous_totals: dict[str, float | None],
    totals: dict[str, float | None],
    daily: dict[str, dict[date, float | None]],
    visible_days: list[date],
    previous_exceptions: dict[str, str],
    total_exceptions: dict[str, str],
    daily_exceptions: dict[str, dict[date, str]],
):
    """Build area-specific PowerPoint panels from the Weekly KPI Review values."""
    import pandas as pd

    panel_sources = {
        "SMT": (
            ("Functional Pass Rate", "smt_function", "percent"),
            ("SMT Process NG Rate (PPM)", "smt_process", "ppm"),
            ("Assembly SMT Process Duty NG Rate (PPM)", "smt_assembly_duty", "ppm"),
            ("SMT OQC Pass Rate", "smt_oqc", "percent"),
        ),
        "Assembly": (
            ("Functional Pass Rate", "assembly_function", "percent"),
            ("Appearance Pass Rate", "assembly_appearance", "percent"),
            ("Function Mando (PPM)", "assembly_mando", "ppm"),
            ("Assembly OQC × FQC Pass Rate", "assembly_oqc_fqc", "percent"),
        ),
    }
    if area not in panel_sources:
        raise ValueError(f"Unsupported KPI graph area: {area}")
    # Use each area's functional input calendar for all four panels. A manual
    # inspection on a weekend must not create an otherwise absent daily point.
    functional_source = "smt_function" if area == "SMT" else "assembly_function"
    daily_days = [day for day in visible_days if day in daily.get(functional_source, {})]

    def frame_for(source: str) -> pd.DataFrame:
        rows = [
            {
                "Period": previous_label,
                "Value": previous_totals.get(source),
                "IsException": bool(previous_exceptions.get(source)),
            },
            {
                "Period": current_label,
                "Value": totals.get(source),
                "IsException": bool(total_exceptions.get(source)),
            },
        ]
        for day in daily_days:
            rows.append(
                {
                    "Period": day.strftime("%d-%b"),
                    "Value": daily.get(source, {}).get(day),
                    "IsException": bool(daily_exceptions.get(source, {}).get(day)),
                }
            )
        return pd.DataFrame(rows)

    targets = {item["source"]: item["target"] for item in directory}
    slide_panels = []
    for title, source, value_type in panel_sources[area]:
        frame = frame_for(source)
        slide_panels.append(
            {
                "title": title,
                "frame": frame,
                "x_column": "Period",
                "y_column": "Value",
                "value_type": value_type,
                "target": targets[source],
                "exceptions": frame.loc[frame["IsException"]],
            }
        )
    return slide_panels


def kpi_review_email(
    period_label: str,
    period_name: str,
    directory: tuple[dict, ...],
    previous_totals: dict[str, float | None],
    totals: dict[str, float | None],
    candidates_by_source: dict[str, list[dict]],
) -> str:
    below = [item for item in directory if weekly_kpi_is_below_target(totals.get(item["source"]), item["target"], item["direction"])]
    available = [item for item in directory if totals.get(item["source"]) is not None]
    lines = ["Hi, Team,", "", f"Please check the results for Major KPIs from the selected {period_name} ({period_label}).", "", "1. Major KPI Review", ""]
    if not available:
        lines.append("No KPI source data is available for the selected period.")
    elif not below:
        lines.append("All available KPIs achieved their targets for the selected week.")
    else:
        lines.extend(["2. Major Problems – Reason for not achieving the KPI", ""])
        for index, item in enumerate(below, start=1):
            value = totals.get(item["source"])
            gap = (float(value) - item["target"]) if item["direction"] == "max" else (item["target"] - float(value))
            top = candidates_by_source.get(item["source"], [])
            description = f"Top issue: {top[0]['defect']} ({top[0]['cases']} cases)" if top else "Describe the main issue and containment."
            lines.extend([
                f"2.{index}. {item['area']} {item['kpi']}",
                f"Target: {weekly_kpi_value_label(item['target'], item['direction'])}",
                f"Previous week: {weekly_kpi_value_label(previous_totals.get(item['source']), item['direction'])}",
                f"Achieved: {weekly_kpi_value_label(value, item['direction'])} (gap {weekly_kpi_value_label(gap, item['direction'])})",
                f"Description: {description}",
                "",
            ])
        lines.extend(["3. Action Plan", ""])
        for index, item in enumerate(below, start=1):
            lines.append(f"3.{index}. {item['area']} {item['kpi']}: @{item['gbr']}, @{item['jovi']} — please provide containment and an action plan to recover the target.")
    lines.extend(["", "Owners, please help provide and share an action plan to bring the KPI to the target."])
    return "\n".join(lines)


def weekly_kpi_review_page() -> None:
    import pandas as pd

    st.markdown("<div class='smart-report-title'>Weekly KPI Review</div><div class='smart-report-subtitle'>Major KPI achievement status and action follow-up, generated from the same validated portal calculations.</div>", unsafe_allow_html=True)
    default_week_end = date.today() - timedelta(days=date.today().weekday() + 1)
    controls, visibility_column, action_column = st.columns([1.1, 1.55, 0.75])
    with controls:
        week_end = st.date_input("Week ending", value=default_week_end, key="weekly_kpi_week_end", persist_state="session", help="Select the Sunday that closes the report week.")
    start_date = week_end - timedelta(days=6)
    days = [start_date + timedelta(days=offset) for offset in range(7)]
    week_label = f"WK{week_end.isocalendar().week:02d} · {start_date.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}"
    with visibility_column:
        hidden_days = st.multiselect(
            "Hide daily columns (print only)",
            options=days,
            default=[],
            format_func=lambda value: value.strftime("%d-%b"),
            key=f"weekly_kpi_hidden_days_{week_end.isoformat()}",
            persist_state="session",
            help="The selected columns are removed only from the displayed and copied table. Weekly KPI calculations remain unchanged.",
        )
    visible_days = [day for day in days if day not in hidden_days]
    with action_column:
        st.markdown("<div class='smart-control-label'>&nbsp;</div>", unsafe_allow_html=True)
        if st.button("Refresh weekly review", key="weekly_kpi_refresh", type="primary", use_container_width=True):
            st.toast("Weekly KPI review refreshed from the stored source data.")
    directory = configured_kpi_directory()
    if is_admin():
        with st.expander("Edit GBR and Jovi responsible owners"):
            owner_rows = pd.DataFrame(
                [
                    {
                        "Area": item["area"],
                        "KPI": item["kpi"],
                        "Target": item["target"] * 100 if item["direction"] == "min" else item["target"],
                        "Unit": "%" if item["direction"] == "min" else "PPM",
                        "GBR": item["gbr"],
                        "Jovi": item["jovi"],
                        "source": item["source"],
                        "direction": item["direction"],
                    }
                    for item in directory
                ]
            )
            edited_owners = st.data_editor(
                owner_rows,
                key="weekly_kpi_owner_directory",
                hide_index=True,
                disabled=["Area", "KPI", "Unit", "source", "direction"],
                column_config={"source": None, "direction": None, "Target": st.column_config.NumberColumn("Target", min_value=0.0, format="%.2f")},
                use_container_width=True,
            )
            if st.button("Save KPI settings", key="save_weekly_kpi_owners", type="primary"):
                try:
                    records = edited_owners.rename(columns={"GBR": "gbr", "Jovi": "jovi", "Target": "target"}).to_dict("records")
                    for record in records:
                        if record["Unit"] == "%":
                            record["target"] = float(record["target"]) / 100
                    save_weekly_kpi_owners(records)
                    st.success("Targets and responsible owners saved for future KPI reviews.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    st.markdown(f"<div class='weekly-review-period'>{escape(week_label)}</div>", unsafe_allow_html=True)
    totals, daily, errors, total_exceptions, daily_exceptions = weekly_kpi_review_data(start_date, week_end)
    previous_start = start_date - timedelta(days=7)
    previous_end = week_end - timedelta(days=7)
    previous_totals, _, previous_errors, previous_total_exceptions, _ = weekly_kpi_review_data(previous_start, previous_end)
    kpi_review_table(
        directory,
        [
            (f"WK{previous_end.isocalendar().week:02d}", previous_totals, previous_total_exceptions),
            (f"WK{week_end.isocalendar().week:02d}", totals, total_exceptions),
        ],
        daily,
        visible_days,
        daily_exceptions,
    )
    previous_label = f"WK{previous_end.isocalendar().week:02d}"
    current_label = f"WK{week_end.isocalendar().week:02d}"
    for area in ("SMT", "Assembly"):
        with st.expander(f"{area} KPI Graphs · PowerPoint", expanded=False):
            st.caption(
                "Cada gráfico usa os mesmos acumulados WK e os mesmos dias visíveis da tabela acima. "
                "Use PPT para baixar o SVG vetorial já dimensionado para 16,17 cm × 8,17 cm no PowerPoint; "
                "use ⧉ para copiar um PNG 4K."
            )
            panels = weekly_kpi_slide_panels(
                area,
                directory,
                previous_label,
                current_label,
                previous_totals,
                totals,
                daily,
                visible_days,
                previous_total_exceptions,
                total_exceptions,
                daily_exceptions,
            )
            chart_tabs = st.tabs([panel["title"] for panel in panels])
            for chart_tab, panel in zip(chart_tabs, panels):
                with chart_tab:
                    chart_name = re.sub(r"[^a-z0-9]+", "_", panel["title"].lower()).strip("_")
                    show_chart(
                        build_kpi_panel_chart(panel),
                        image_filename=(
                            f"quality_{area.lower()}_{chart_name}_"
                            f"{previous_start.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}"
                        ),
                    )
    if hidden_days:
        st.caption(
            "Hidden from this table and its copied image: "
            + ", ".join(day.strftime("%d-%b") for day in hidden_days)
            + ". WK calculations still use the full seven-day week."
        )
    for area, error in errors.items():
        st.info(f"{area}: {error}")
    for area, error in previous_errors.items():
        st.info(f"Previous week · {area}: {error}")

    candidates_by_source = smart_report_kpi_candidates(start_date, week_end)
    below = [item for item in directory if weekly_kpi_is_below_target(totals.get(item["source"]), item["target"], item["direction"])]
    available = [item for item in directory if totals.get(item["source"]) is not None]
    st.markdown("### Major problems and action follow-up")
    if not available:
        st.info("No KPI source data is available for the selected week.")
    elif below:
        for item in below:
            top = candidates_by_source.get(item["source"], [])
            defect = f" Top issue: {top[0]['defect']} ({top[0]['cases']} cases)." if top else ""
            st.warning(f"**{item['area']} · {item['kpi']}** is below target. Responsible: {item['gbr']} / {item['jovi']}.{defect}")
    else:
        st.success("All available KPIs achieved the configured targets in the selected week.")
    email_text = kpi_review_email(week_label, "week", directory, previous_totals, totals, candidates_by_source)
    with st.expander("Copyable weekly e-mail", expanded=True):
        st.code(email_text, language=None)
    st.caption("Targets match the validated KPI Track configuration. Empty cells indicate that the corresponding source or manual OQC/FQC record has not yet been loaded.")
    st.caption("× indicates that defects exceeded the available input for that KPI period, so the KPI was intentionally not calculated.")


def monthly_kpi_review_page() -> None:
    st.markdown("<div class='smart-report-title'>Monthly KPI Review</div><div class='smart-report-subtitle'>Independent SMT or Assembly monthly review, with the same KPI status, problem and action-plan structure used in the weekly report.</div>", unsafe_allow_html=True)
    today = datetime.now(ZoneInfo("America/Manaus")).date()
    default_month = today.strftime("%Y-%m")
    controls, area_control, _ = st.columns([0.6, 0.6, 1.8], gap="small")
    with controls:
        with st.container(key="monthly_kpi_start_month_control"):
            selected_month = st.text_input(
                "Start date",
                value=default_month,
                key="monthly_kpi_start_month",
                persist_state="session",
                max_chars=7,
            ).strip()
    with area_control:
        area = st.segmented_control("Area", ["SMT", "Assembly"], default="SMT", selection_mode="single", key="monthly_kpi_area", persist_state="session") or "SMT"
    try:
        start_date = datetime.strptime(selected_month, "%Y-%m").date().replace(day=1)
    except ValueError:
        st.error("Start date must use the YYYY-MM format, for example 2026-08.")
        return
    following_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_date = following_month - timedelta(days=1)
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    period_label = start_date.strftime("%b %Y")
    directory = tuple(item for item in configured_kpi_directory() if item["area"] == area)
    st.markdown(f"<div class='weekly-review-period'>{escape(area)} · {escape(period_label)} · {start_date.strftime('%d/%m')} – {end_date.strftime('%d/%m/%Y')}</div>", unsafe_allow_html=True)
    # KPI Track is authoritative for the monthly result. A defect file may have
    # no row on the final production day simply because that day had no defect;
    # its last defect timestamp is not a reliable file-coverage boundary.
    totals, daily, errors, total_exceptions, _ = weekly_kpi_review_data(start_date, end_date)
    previous_totals, _, previous_errors, previous_total_exceptions, _ = weekly_kpi_review_data(previous_start, previous_end)
    two_months_ago_end = previous_start - timedelta(days=1)
    two_months_ago_start = two_months_ago_end.replace(day=1)
    two_months_ago_totals, _, _, two_months_ago_total_exceptions, _ = weekly_kpi_review_data(
        two_months_ago_start, two_months_ago_end
    )
    kpi_review_table(
        directory,
        [
            (two_months_ago_start.strftime("%b"), two_months_ago_totals, two_months_ago_total_exceptions),
            (previous_start.strftime("%b"), previous_totals, previous_total_exceptions),
            (start_date.strftime("%b"), totals, total_exceptions),
        ],
        {},
        [],
    )
    if errors.get(area):
        st.info(f"{area}: {errors[area]}")
    if previous_errors.get(area):
        st.info(f"Previous month · {area}: {previous_errors[area]}")

    candidates_by_source = smart_report_kpi_candidates(start_date, end_date)
    below = [item for item in directory if weekly_kpi_is_below_target(totals.get(item["source"]), item["target"], item["direction"])]
    available = [item for item in directory if totals.get(item["source"]) is not None]
    st.markdown("### Major problems and action follow-up")
    if not available:
        st.info(f"No {area} KPI source data is available for {period_label}.")
    elif below:
        for item in below:
            top = candidates_by_source.get(item["source"], [])
            defect = f" Top issue: {top[0]['defect']} ({top[0]['cases']} cases)." if top else ""
            st.warning(f"**{item['kpi']}** is below target. Responsible: {item['gbr']} / {item['jovi']}.{defect}")
    else:
        st.success(f"All available {area} KPIs achieved the configured targets in {period_label}.")
    email_text = kpi_review_email(period_label, "month", directory, previous_totals, totals, candidates_by_source)
    with st.expander("Copyable monthly e-mail", expanded=True):
        st.code(email_text, language=None)
    st.caption("Targets and responsible owners use the shared directory in Weekly KPI Review. The monthly report shows only the selected area.")
    st.caption("× indicates that defects exceeded the available input for that KPI period, so the KPI was intentionally not calculated.")


def smart_report_page() -> None:
    weekly_tab, monthly_tab, defect_tab = st.tabs(["Weekly KPI Review", "Monthly KPI Review", "Defect Action Report"])
    with weekly_tab:
        weekly_kpi_review_page()
    with monthly_tab:
        monthly_kpi_review_page()
    with defect_tab:
        defect_action_report_page()


@st.cache_data(show_spinner=False)
def _repair_info_events_cached(
    smt_signatures: tuple[tuple[str, int, int], ...],
    assembly_signatures: tuple[tuple[str, int, int], ...],
):
    from tools.repair_info import combine_repair_files

    return combine_repair_files({
        "SMT": [Path(signature[0]) for signature in smt_signatures],
        "Assembly": [Path(signature[0]) for signature in assembly_signatures],
    })


def _repair_info_hours(value) -> str:
    import pandas as pd

    if value is None or pd.isna(value):
        return "N/A"
    if value < 1 / 60:
        return "<1 min"
    if value < 1:
        return f"{value * 60:.0f} min"
    return f"{value:,.1f} h"


def repair_info_page() -> None:
    """Operational repair view based solely on the existing stored MES files."""
    import pandas as pd
    import plotly.graph_objects as go
    from tools import repair_info, smt_quality_dashboard

    st.markdown(
        "<h1 class='section-title' style='color:#2861EB;'>Repair Info</h1>"
        "<p class='small-muted'>Repair throughput and time from defect entry to recorded repair.</p>",
        unsafe_allow_html=True,
    )
    try:
        smt_sources = smt_quality_dashboard.stored_smt_sources_v2()["repair"]
        assembly_sources = stored_assembly_sources_v2()["repair"]
        events, audit = _repair_info_events_cached(
            tuple(smt_quality_dashboard.path_signature(path) for path in smt_sources),
            tuple(path_signature(path) for path in assembly_sources),
        )
    except Exception as exc:
        st.error(f"Stored repair files could not be loaded: {exc}")
        return
    for error in audit["errors"]:
        st.warning(f"Skipped repair file: {error}")
    if events.empty:
        st.info("No repair records with a PCB SN and RepairDate are stored yet. An administrator can add repair exports in Data Upload.")
        return

    first_day = events["Repair day"].min().date()
    last_day = events["Repair day"].max().date()
    default_start = max(first_day, last_day - timedelta(days=6))
    if "repair_info_period_preset" not in st.session_state:
        st.session_state["repair_info_period_preset"] = "Last 7 days"
    filter_period, filter_area, filter_model, filter_repairer = st.columns([1.3, 0.7, 0.95, 0.95], gap="medium")
    with filter_period:
        start_date, end_date = analysis_period_control(
            "repair_info_period", first_day, last_day,
            default_start=default_start, default_end=last_day,
        )
    with filter_area:
        area = st.segmented_control(
            "Area", ["Both", "SMT", "Assembly"], default="Both",
            key="repair_info_area", persist_state="session",
        ) or "Both"
    dated = events[events["Repair day"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))].copy()
    if area != "Both":
        dated = dated[dated["Area"].eq(area)].copy()
    with filter_model:
        models = sorted(value for value in dated["Model"].unique() if value)
        if st.session_state.get("repair_info_model") not in ["All models", *models]:
            st.session_state["repair_info_model"] = "All models"
        model = st.selectbox("Model", ["All models", *models], key="repair_info_model", persist_state="session")
    if model != "All models":
        dated = dated[dated["Model"].eq(model)].copy()
    with filter_repairer:
        repairers = sorted(value for value in dated["Repairer"].unique() if value)
        if st.session_state.get("repair_info_repairer") not in ["All repairers", *repairers]:
            st.session_state["repair_info_repairer"] = "All repairers"
        repairer = st.selectbox("Repairer", ["All repairers", *repairers], key="repair_info_repairer", persist_state="session")
    if repairer != "All repairers":
        dated = dated[dated["Repairer"].eq(repairer)].copy()

    st.caption(
        f"Stored repair dates: {first_day:%d/%m/%Y} – {last_day:%d/%m/%Y} · "
        f"{audit['files']} source file(s) · {audit['duplicates']:,} repeated snapshot rows reconciled · "
        f"{audit['undated']:,} records without RepairDate excluded."
    )
    if dated.empty:
        st.info("No recorded repairs match these filters.")
        return
    summary = repair_info.repair_summary(dated)
    cards = [
        ("Repaired PCBs", f"{summary['pcbs']:,}", "Unique Area + PCB SN", "#0B7E48"),
        ("Average elapsed time", _repair_info_hours(summary["avg_h"]), "Entry to recorded repair", "#1D5FBF"),
        ("Median elapsed time", _repair_info_hours(summary["median_h"]), "Less affected by long cases", "#6532C8"),
        ("Within 24 hours", f"{summary['within_24_pct']:.0f}%" if summary["within_24_pct"] is not None else "N/A", "Of valid elapsed-time records", "#B45309"),
    ]
    for column, (label, value, note, accent) in zip(st.columns(4, gap="medium"), cards):
        with column:
            st.markdown(
                f"<div style='background:#fff;border:1px solid #C9D8EC;border-left:6px solid {accent};"
                "border-radius:12px;padding:16px 18px;min-height:125px;box-shadow:0 4px 12px #112A5012;'>"
                f"<div style='font-size:.76rem;font-weight:800;color:#17345C;text-transform:uppercase;'>{label}</div>"
                f"<div style='font-size:1.85rem;font-weight:800;color:{accent};margin:8px 0;'>{value}</div>"
                f"<div style='font-size:.78rem;color:#607999;'>{note}</div></div>",
                unsafe_allow_html=True,
            )
    st.caption(
        f"Elapsed-time coverage: {summary['coverage_pct']:.0f}% of recorded repairs. "
        "Elapsed time includes waiting after defect entry; it is not technician hands-on repair time."
    )
    if summary["near_zero_pct"] is not None and summary["near_zero_pct"] >= 20:
        st.info(
            f"{summary['near_zero_pct']:.0f}% of valid elapsed times are under one minute. "
            "Review the MES timestamps before interpreting the average as a process-speed measure."
        )

    daily = repair_info.daily_summary(dated, start_date, end_date)
    chart_column, duration_column = st.columns([1.75, 1], gap="medium")
    with chart_column:
        st.markdown("#### Repaired PCBs per day")
        volume = go.Figure()
        day_ms = 86_400_000
        bar_width = day_ms * (0.32 if area == "Both" else 0.52)
        for label, color in (("SMT", "#0B7E48"), ("Assembly", "#6532C8")):
            if area == "Both" or area == label:
                volume.add_bar(
                    x=daily["Date"], y=daily[label], name=label, marker_color=color,
                    width=bar_width,
                    text=[f"{value:,}" if value else "" for value in daily[label]],
                    textposition="outside", textfont=dict(size=11, color="#17345C"),
                    cliponaxis=False,
                    hovertemplate="%{x|%d/%m/%Y}<br>%{y:,} unique PCBs<extra>" + label + "</extra>",
                )
        tick_stride = max(1, (len(daily) + 8) // 9)
        tick_days = daily["Date"].iloc[::tick_stride].tolist()
        if tick_days and tick_days[-1] != daily["Date"].iloc[-1]:
            tick_days.append(daily["Date"].iloc[-1])
        peak = max(int(daily["SMT"].max()), int(daily["Assembly"].max()), 1)
        volume.update_layout(barmode="group", height=350, margin=dict(l=10, r=18, t=12, b=25),
                             paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", legend_orientation="h",
                             legend_y=1.14, font_color="#17345C", dragmode="zoom")
        volume.update_xaxes(
            tickmode="array", tickvals=tick_days, ticktext=[day.strftime("%d %b") for day in tick_days],
            range=[daily["Date"].iloc[0] - pd.Timedelta(days=1),
                   daily["Date"].iloc[-1] + pd.Timedelta(days=1)],
            showgrid=False,
        )
        volume.update_yaxes(title="Unique PCBs", gridcolor="#DDE7F3", range=[0, peak * 1.18])
        st.plotly_chart(volume, use_container_width=True, config={"displayModeBar": False})
    with duration_column:
        st.markdown("#### Elapsed-time distribution")
        valid = dated["Elapsed (h)"].dropna()
        bucket_labels = ["Under 1 h", "1–4 h", "4–24 h", "Over 24 h"]
        bucket_counts = [int(valid.lt(1).sum()), int(valid.between(1, 4, inclusive="left").sum()),
                         int(valid.between(4, 24, inclusive="left").sum()), int(valid.ge(24).sum())]
        distribution = go.Figure(go.Bar(
            x=bucket_counts, y=bucket_labels, orientation="h",
            marker_color=["#0B7E48", "#1D5FBF", "#6532C8", "#C76A06"],
            text=[f"{count / len(valid) * 100:.0f}%" if len(valid) else "N/A" for count in bucket_counts],
            textposition="outside", hovertemplate="%{y}: %{x:,} repair events<extra></extra>",
        ))
        distribution.update_layout(height=350, margin=dict(l=10, r=35, t=12, b=25),
                                   paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", font_color="#17345C")
        distribution.update_yaxes(autorange="reversed")
        distribution.update_xaxes(title="Repair events", gridcolor="#DDE7F3", rangemode="tozero")
        st.plotly_chart(distribution, use_container_width=True, config={"displayModeBar": False})
        st.caption(f"Median {_repair_info_hours(summary['median_h'])} · P90 {_repair_info_hours(summary['p90_h'])}")

    st.markdown("#### Daily detail")
    daily_view = daily.copy().sort_values("Date", ascending=False)
    daily_view["Date"] = daily_view["Date"].dt.strftime("%d/%m/%Y")
    for name in ("Avg elapsed (h)", "Median (h)", "P90 (h)"):
        daily_view[name] = daily_view[name].map(_repair_info_hours)
    daily_view["Coverage (%)"] = daily_view["Coverage (%)"].map(lambda value: f"{value:.0f}%" if pd.notna(value) else "N/A")
    st.dataframe(daily_view, hide_index=True, use_container_width=True, height=250)
    st.download_button(
        "Download daily detail", daily.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"repair_daily_{start_date:%Y-%m-%d}_{end_date:%Y-%m-%d}.csv", mime="text/csv",
        key="repair_info_daily_download",
    )

    st.markdown("#### Repaired PCB details")
    st.caption("Search PCB SN or device Barcode. One SN can have multiple repair events; the daily volume counts it once per area and day.")
    positive_days = daily.loc[daily["Total PCBs"].gt(0), "Date"].dt.date.tolist()
    day_options = [None, *reversed(positive_days)]
    if st.session_state.get("repair_info_detail_day") not in day_options:
        st.session_state["repair_info_detail_day"] = None
    day_column, search_column = st.columns([0.55, 1.45])
    with day_column:
        selected_day = st.selectbox(
            "Repair day", day_options, key="repair_info_detail_day", persist_state="session",
            format_func=lambda value: "All selected days" if value is None else value.strftime("%d/%m/%Y"),
        )
    with search_column:
        search = st.text_input("Search PCB SN / Barcode", key="repair_info_search", persist_state="session")
    details = dated.copy()
    if selected_day is not None:
        details = details[details["Repair day"].eq(pd.Timestamp(selected_day))]
    if search.strip():
        term = search.strip().casefold()
        details = details[
            details["PCB SN"].str.casefold().str.contains(term, regex=False)
            | details["Device Barcode"].str.casefold().str.contains(term, regex=False)
        ]
    details = details.sort_values(["Repair date", "Area", "PCB SN"], ascending=[False, True, True]).reset_index(drop=True)
    st.caption(f"{len(details):,} repair event(s) · {details[['Area', 'PCB SN']].drop_duplicates().shape[0]:,} unique Area + PCB SN")
    detail_view = details[repair_info.DISPLAY_COLUMNS].copy()
    for name in ("Defect entry", "Repair date"):
        detail_view[name] = detail_view[name].dt.strftime("%d/%m/%Y %H:%M").fillna("—")
    detail_view["Elapsed (h)"] = detail_view["Elapsed (h)"].map(_repair_info_hours)
    detail_view["Repair #"] = detail_view["Repair #"].map(lambda value: str(int(value)) if pd.notna(value) else "—")
    visible = ["PCB SN", "Device Barcode", "Area", "Model", "Defect entry", "Repair date", "Elapsed (h)", "Repairer", "Repair #"]
    selection = st.dataframe(
        detail_view[visible], hide_index=True, use_container_width=True, height=300,
        on_select="rerun", selection_mode="single-row", key="repair_info_records",
    )
    selected_rows = selection.selection.rows
    if selected_rows and selected_rows[0] < len(detail_view):
        record = detail_view.iloc[selected_rows[0]]
        with st.container(border=True):
            st.markdown(f"**Selected PCB SN: {escape(str(record['PCB SN']))}**")
            left, right = st.columns(2)
            with left:
                st.write(f"**TestOperation:** {record['TestOperation'] or '—'}")
                st.write(f"**Fault Phenomenon:** {record['Fault Phenomenon'] or '—'}")
                st.write(f"**Fault reason:** {record['Fault reason'] or '—'}")
            with right:
                st.write(f"**RepaireRemark:** {record['RepaireRemark'] or '—'}")
                st.write(f"**DutyType:** {record['DutyType'] or '—'}")
                st.write(f"**Repairer:** {record['Repairer'] or '—'}")
    st.download_button(
        "Download matching repair records", detail_view.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"repair_pcb_details_{start_date:%Y-%m-%d}_{end_date:%Y-%m-%d}.csv",
        mime="text/csv", key="repair_info_records_download",
    )


def _home_kpi_chart(frame, area: str, kpi: str, grain: str, models: list[str], target: dict | None) -> None:
    import plotly.graph_objects as go
    import pandas as pd

    if frame.empty or frame["Value"].notna().sum() == 0:
        st.info(f"No {area} {kpi} result is available for the selected models and time scale.")
        return
    colors = ("#087A8C", "#6532C8", "#D65B55", "#D3981F", "#1C6CC8", "#7F9A39")
    fig = go.Figure()
    for index, model in enumerate(models):
        data = frame.loc[frame["Model"].eq(model)].sort_values("PeriodDate")
        if data.empty or data["Value"].notna().sum() == 0:
            continue
        x = pd.to_datetime(data["PeriodDate"])
        hover = [
            f"<b>{escape(model)} · {escape(label)}</b><br>{escape(kpi)}: "
            + (f"{value * 100:.2f}%" if "Pass Rate" in kpi else f"{value:,.0f} PPM")
            + f"<br>Defect PCBs: {int(ng)} · Input: {int(count):,}"
            if pd.notna(value) else f"<b>{escape(model)} · {escape(label)}</b><br>{escape(status)}"
            for label, value, ng, count, status in zip(data["Period"], data["Value"], data["DefectPCBs"], data["Input"], data["Status"])
        ]
        fig.add_trace(go.Scatter(
            x=x, y=data["Value"] * (100 if "Pass Rate" in kpi else 1),
            name=model, mode="lines+markers", line=dict(color=colors[index % len(colors)], width=2.5),
            marker=dict(size=7), text=hover, hovertemplate="%{text}<extra></extra>",
            connectgaps=False,
        ))
    if target:
        threshold = target["target"] * (100 if "Pass Rate" in kpi else 1)
        fig.add_hline(y=threshold, line_color="#E56B2F", line_dash="dash", line_width=1.6)
    periods = frame[["PeriodDate", "Period"]].drop_duplicates().sort_values("PeriodDate")
    # Keep Plotly's draggable range handles, but place the range-slider preview
    # y-axis below every valid KPI value so it remains a clean selection bar.
    range_bar = dict(visible=len(periods) > 6, thickness=0.075,
                     bgcolor="#EEF3FA", bordercolor="#8EADD8", borderwidth=1,
                     yaxis=dict(range=[-2, -1], rangemode="fixed"))
    if grain == "Days":
        xaxis = dict(type="date", tickformat="%d/%m", nticks=12, showgrid=False,
                     rangeslider=range_bar)
    else:
        tick_step = max(1, math.ceil(len(periods) / 12))
        visible_ticks = periods.iloc[::tick_step]
        if not visible_ticks.empty and visible_ticks.index[-1] != periods.index[-1]:
            visible_ticks = pd.concat([visible_ticks, periods.tail(1)])
        xaxis = dict(tickmode="array", tickvals=pd.to_datetime(visible_ticks["PeriodDate"]),
                     ticktext=visible_ticks["Period"], tickangle=0, showgrid=False,
                     rangeslider=range_bar)
    fig.update_layout(
        height=min(580, 330 + max(0, len(models) - 4) * 18),
        margin=dict(l=38, r=24, t=35, b=18), dragmode="zoom",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", hovermode="x unified",
        legend=dict(orientation="h", y=1.16, x=0.25, font=dict(size=11)),
        font=dict(family="Arial", color="#17375F", size=11),
        yaxis=dict(title="%" if "Pass Rate" in kpi else "PPM",
                   gridcolor="#E6ECF4", zeroline=False),
        xaxis=xaxis,
    )
    if target:
        target_value = f"{threshold:,.2f}%" if "Pass Rate" in kpi else f"{threshold:,.0f} PPM"
        direction = "≥" if target["direction"] == "min" else "≤"
        fig.add_annotation(
            x=1, y=1, xref="paper", yref="paper", xanchor="right", yanchor="top", yshift=24,
            text=f"<b>Target {direction} {escape(target_value)}</b>", showarrow=False,
            font=dict(color="#C95823", size=12), align="right",
        )
    if "Pass Rate" in kpi:
        fig.update_yaxes(ticksuffix="%", range=[max(-1, min(float(frame["Value"].min() * 100) - 2, 95)), 101])
    else:
        upper_value = max(float(frame["Value"].max()), float(threshold) if target else 0, 1)
        padding = max(upper_value * 0.04, 0.02)
        fig.update_yaxes(range=[-padding, upper_value + padding])
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"home_{area.lower()}_{kpi.lower().replace(' ', '_')}_chart")
    if len(periods) > 6:
        st.caption("Drag the handles below the chart to change the visible period; double-click the chart to reset.")


def _home_detail_table(frames: dict[str, object], models: list[str], grain: str, targets: dict) -> None:
    import pandas as pd
    from tools.home_analysis import KPI_TARGETS

    combined = pd.concat([frame for frame in frames.values() if not frame.empty], ignore_index=True) if any(not frame.empty for frame in frames.values()) else pd.DataFrame()
    if combined.empty:
        st.info("No model detail is available for the selected period.")
        return
    periods = combined[["PeriodDate", "Period"]].drop_duplicates().sort_values("PeriodDate")
    period_keys = list(periods["PeriodDate"])
    period_labels = list(periods["Period"])
    search_col, _, export_col = st.columns([1.1, 2, 0.8], gap="small")
    with search_col:
        search = st.text_input("Search model", key="home_detail_search", placeholder="Search model...", label_visibility="collapsed").strip().casefold()
    export = combined.copy()
    export["PeriodDate"] = pd.to_datetime(export["PeriodDate"]).dt.strftime("%Y-%m-%d")
    with export_col:
        st.download_button("↓  Export detail", export.to_csv(index=False).encode("utf-8-sig"),
                           file_name="jovi-home-kpi-detail.csv", mime="text/csv", key="home_detail_export", width="stretch")
    parts = ["<div class='home-detail-scroll'><table class='home-detail-table'><thead><tr>",
             "<th class='sticky-model'>Model</th><th class='sticky-kpi'>Area / KPI</th>"]
    for label in period_labels:
        parts.append(f"<th>{escape(str(label))}</th>")
    parts.append("</tr></thead><tbody>")
    for area, frame in frames.items():
        if frame.empty:
            continue
        kpi = str(frame["KPI"].iloc[0])
        target = targets.get(KPI_TARGETS.get((area, kpi)))
        lookup = {(row.Model, row.PeriodDate): row for row in frame.itertuples(index=False)}
        for model in models:
            if search and search not in model.casefold():
                continue
            parts.append("<tr>")
            parts.append(f"<th class='sticky-model'>{escape(model)}</th><th class='sticky-kpi'>{escape(area)} · {escape(kpi)}</th>")
            for period in period_keys:
                row = lookup.get((model, period))
                if row is None or pd.isna(row.Value):
                    note = escape(str(row.Status)) if row is not None and row.Status != "No data" else "—"
                    parts.append(f"<td class='empty'><span>{note}</span></td>")
                    continue
                label = f"{row.Value * 100:.2f}%" if "Pass Rate" in kpi else f"{row.Value:,.0f} PPM"
                note = f"{int(row.DefectPCBs)} NG / {int(row.Input):,} input"
                cell_class = kpi_target_state(row.Value, target["target"], target["direction"]) if target else "plain"
                parts.append(f"<td class='{cell_class}'><strong>{escape(label)}</strong><small>{escape(note)}</small></td>")
            parts.append("</tr>")
    parts.append("</tbody></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
    st.caption(f"{len(period_keys)} {grain.lower()} in the selected period · scroll the table horizontally to view every column.")


def home_model_performance(smt_context: dict, assembly_context: dict, smt_target: float, assembly_target: float) -> None:
    """Show every model with FPY input, newest production first."""
    from tools.home_model_performance import (
        assembly_model_daily, mini_trend_svg, recent_models, smt_model_daily,
    )
    import pandas as pd

    smt_daily = (
        smt_model_daily(smt_context["analysis"])
        if smt_context.get("ready") and "analysis" in smt_context
        else pd.DataFrame(columns=["Model", "Date", "Input", "PPM", "Status"])
    )
    assembly_daily = (
        assembly_model_daily(assembly_context["metrics"])
        if assembly_context.get("ready") and "metrics" in assembly_context
        else pd.DataFrame(columns=["Model", "Date", "Input", "PPM", "Status"])
    )
    ranking = recent_models(smt_daily, assembly_daily)
    st.markdown(
        '<div class="home-model-heading"><div><h2>Model performance</h2>'
        '<p>Up to 10 recent days with daily FPY input per model · newest input first</p></div>'
        f'<div class="home-model-count">{len(ranking)} models</div></div>',
        unsafe_allow_html=True,
    )
    if not ranking:
        st.info("No models have FPY input in the selected period.")
        return

    def panel(model_rows, title: str, target: float, color: str) -> tuple[str, str | None]:
        latest = model_rows.iloc[-1] if not model_rows.empty else None
        actual = float(latest["PPM"]) if latest is not None and latest["Status"] == "Valid" else None
        state = kpi_target_state(actual, target, "max")
        value_color = "#087A47" if state == "on-target" else "#CB2424" if state else "#657B98"
        value = f"{fmt_ppm(actual)} PPM" if actual is not None else "N/A"
        if latest is None:
            note = "No daily FPY input in the selected period"
        else:
            day = pd.Timestamp(latest["Date"]).strftime("%d/%m")
            note = (
                f"{day} · Target ≤ {fmt_ppm(target)} PPM"
                if latest["Status"] == "Valid"
                else f"{day} · {latest['Status']}"
            )
        html = (
            f'<div class="home-model-chart" style="--value-color:{value_color}">'
            f'<div class="home-model-chart-head"><b>{escape(title)}</b><strong>{escape(value)}</strong></div>'
            f'<div class="home-model-chart-note">{escape(note)}</div>'
            f'{mini_trend_svg(model_rows, target, color)}</div>'
        )
        return html, state

    html_rows = []
    for item in ranking:
        model = str(item["Model"])
        smt_rows = smt_daily[smt_daily["Model"].eq(model)]
        assembly_rows = assembly_daily[assembly_daily["Model"].eq(model)]
        smt_panel, smt_state = panel(smt_rows, "SMT · Process NG PPM", smt_target, "#087A8C")
        assembly_panel, assembly_state = panel(
            assembly_rows, "Assembly · Function Mando PPM", assembly_target, "#6532C8"
        )
        states = (smt_state, assembly_state)
        attention_count = states.count("below-target")
        if attention_count:
            badge = "2 KPIs need attention" if attention_count == 2 else "1 KPI needs attention"
            badge_bg, badge_color, row_color = "#FDEBEC", "#C52329", "#D63A3A"
        elif states.count("on-target") == 2:
            badge = "Both on target"
            badge_bg, badge_color, row_color = "#E6F6EC", "#087A47", "#0B7A4B"
        elif states.count("on-target") == 1:
            badge = "1 KPI on target"
            badge_bg, badge_color, row_color = "#EAF2FC", "#2768C7", "#2D70DF"
        else:
            badge = "Awaiting KPI data"
            badge_bg, badge_color, row_color = "#EEF2F7", "#61758F", "#8A9AB0"
        latest_label = pd.Timestamp(item["LatestInput"]).strftime("%d/%m/%Y")
        html_rows.append(
            f'<div class="home-model-row" style="--row-color:{row_color};'
            f'--badge-bg:{badge_bg};--badge-color:{badge_color}">'
            f'<div class="home-model-id"><strong>{escape(model)}</strong>'
            f'<small>Latest FPY input · {latest_label}</small>'
            f'<span class="home-model-badge">{escape(badge)}</span></div>'
            f'{smt_panel}{assembly_panel}</div>'
        )
    st.markdown("".join(html_rows), unsafe_allow_html=True)


def home_page() -> None:
    """Shared filters, independent SMT/Assembly KPI charts, and full-period details."""
    import pandas as pd
    from tools import smt_quality_dashboard
    from tools.home_analysis import KPI_OPTIONS, KPI_TARGETS, build_home_kpi_rows

    st.markdown("<div class='home-overview-head'><h1>Quality Overview</h1></div>", unsafe_allow_html=True)
    st.caption("Compare model performance in SMT and Assembly on the same time scale.")
    smt_inputs, smt_defects = smt_quality_dashboard.stored_smt_sources()
    assembly_sources = stored_assembly_sources_v2()
    smt_ready = bool(smt_inputs and smt_defects)
    assembly_ready = all(assembly_sources[source] for source in ("input", "defects", "repair"))
    if not smt_ready and not assembly_ready:
        st.info("Upload validated SMT or Assembly FPY source files in Data Upload to populate the Home analysis.")
        return
    bounds = []
    if smt_ready:
        smt_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in smt_inputs)
        low, high = smt_quality_dashboard.input_bounds(smt_signatures)
        bounds.append((low.date(), high.date()))
    if assembly_ready:
        low, high = assembly_input_bounds(assembly_sources["input"])
        bounds.append((low, high))
    minimum = min(value[0] for value in bounds)
    maximum = max(value[1] for value in bounds)
    period_col, model_col, scale_col, action_col = st.columns([1.8, 1.2, 0.9, 0.65], gap="medium")
    with period_col:
        start_date, end_date = analysis_period_control("home_trends_period", minimum, maximum,
                                                       default_start=minimum, default_end=maximum)
    analyses = {}
    if smt_ready:
        try:
            analyses["SMT"] = smt_quality_dashboard.analyze_smt_quality_paths(
                smt_signatures,
                tuple(smt_quality_dashboard.path_signature(path) for path in smt_defects),
                start_date.isoformat(), end_date.isoformat(), smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
            )
        except Exception as exc:
            st.warning(f"SMT source data could not be analyzed: {exc}")
    if assembly_ready:
        try:
            analyses["Assembly"] = calculate_assembly_kpi_metrics(start_date, end_date)
        except Exception as exc:
            st.warning(f"Assembly source data could not be analyzed: {exc}")
    if not analyses:
        return
    latest = {}
    volume = {}
    if "SMT" in analyses:
        for row in analyses["SMT"]["selected_input"].itertuples(index=False):
            latest[row.Model] = max(latest.get(row.Model, pd.Timestamp.min), pd.Timestamp(row.BeginDate))
            volume[row.Model] = volume.get(row.Model, 0) + int(row.Input)
    if "Assembly" in analyses:
        for row in analyses["Assembly"]["inputs"].itertuples(index=False):
            latest[row.Model] = max(latest.get(row.Model, pd.Timestamp.min), pd.Timestamp(row.Date))
            volume[row.Model] = volume.get(row.Model, 0) + int(row.Input)
    options = sorted(latest, key=lambda model: (-latest[model].value, -volume[model], model))
    with model_col:
        models = st.multiselect("Models", options, default=options[:3], key="home_trends_models",
                                placeholder="Select models")
    with scale_col:
        grain = st.segmented_control("Time scale", ["Days", "Weeks", "Months"], default="Weeks",
                                     key="home_trends_scale") or "Weeks"
    with action_col:
        st.markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
        st.button("Update view", key="home_trends_update", type="primary", width="stretch")
    if not models:
        st.info("Select at least one model to display its KPI trends.")
        return
    targets = {item["source"]: item for item in configured_kpi_directory()}
    frames = {}
    for area in ("SMT", "Assembly"):
        if area not in analyses:
            continue
        with st.container(border=True, key=f"home_trends_{area.lower()}"):
            left, right = st.columns([2.2, 1], gap="medium")
            with right:
                kpi = st.selectbox(f"{area} KPI", KPI_OPTIONS[area],
                                   index=1 if area == "SMT" else 2,
                                   key=f"home_trends_{area.lower()}_kpi")
                target_source = KPI_TARGETS.get((area, kpi))
                target = targets.get(target_source)
            with left:
                st.markdown(
                    f"<div class='home-trend-heading' style='--home-area:{'#0D7A45' if area == 'SMT' else '#6532C8'}'>"
                    f"<strong>{escape(area)} · {escape(kpi)}</strong>"
                    f"<small>{escape(grain)} trend by model · selected period</small></div>",
                    unsafe_allow_html=True,
                )
            if area == "SMT" and kpi != "Assembly SMT Process Duty NG Rate (PPM)":
                analysis = analyses[area]
                source_input, source_defects = analysis["selected_input"], analysis["covered_raw"]
            else:
                analysis = analyses.get("Assembly")
                if analysis is None:
                    st.info("Assembly FPY input, defect, and repair data are required for this KPI.")
                    continue
                source_input, source_defects = analysis["inputs"], analysis["defects"]
            frame = build_home_kpi_rows(area, kpi, grain, models, start_date, end_date,
                                        source_input, source_defects)
            frames[area] = frame
            _home_kpi_chart(frame, area, kpi, grain, models, target)
    st.markdown("### Selected KPI details · full analysis period")
    _home_detail_table(frames, models, grain, targets)


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


def fmt_kpi_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    try:
        if value != value:
            return "N/A"
    except TypeError:
        return "N/A"
    return f"{float(value) * 100:,.2f}%"


def kpi_target_state(value: float | None, target: float | None, direction: str | None) -> str | None:
    """Return the visual target state only when the KPI result can be evaluated."""
    if value is None or target is None or direction not in {"min", "max"}:
        return None
    try:
        numeric_value = float(value)
        numeric_target = float(target)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric_value) or not math.isfinite(numeric_target):
        return None
    return "below-target" if (numeric_value > numeric_target if direction == "max" else numeric_value < numeric_target) else "on-target"


def smt_kpi_card(
    label: str,
    value: str,
    note: str,
    color: str,
    *,
    actual_value: float | None = None,
    target_value: float | None = None,
    target_direction: str | None = None,
) -> None:
    state = kpi_target_state(actual_value, target_value, target_direction)
    target_status = ""
    target_icon = ""
    card_style = ""
    value_style = ""
    if state is not None:
        target_label = fmt_ppm(target_value) + " PPM" if target_direction == "max" else fmt_kpi_pct(target_value)
        status_label = "Below target" if state == "below-target" else "On target"
        target_status = (
            f'<div class="kpi-target-status {state}">{status_label} · Target {escape(target_label)}</div>'
        )
        icon = "!" if state == "below-target" else "✓"
        target_icon = f'<div class="kpi-target-icon {state}" aria-label="{escape(status_label)}">{icon}</div>'
        if state == "below-target":
            card_style = "background:#FFE8E8 !important;border:1px solid #F39A9A !important;border-left:6px solid #DC2626 !important;box-shadow:0 8px 22px rgba(220,38,38,.16);"
            value_style = "color:#B91C1C !important;"
        else:
            card_style = "background:#E8FAEF !important;border:1px solid #86D5A6 !important;border-left:6px solid #0D7A45 !important;"
            value_style = "color:#08703B !important;"
    card_class = (" kpi-target-below" if state == "below-target" else " kpi-target-on") if state is not None else ""
    st.markdown(
        f'<div class="metric-card{card_class}" style="{card_style}">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value" style="color:{color};{value_style}">{escape(value)}</div>'
        f'<div class="small-muted">{escape(note)}</div>{target_status}{target_icon}</div>',
        unsafe_allow_html=True,
    )


def smt_kpi_line_chart(
    frame,
    x_column: str,
    y_column: str,
    title: str,
    color: str,
    value_type: str,
    target_value: float | None = None,
    exception_rows=None,
    exception_count_column: str = "ClassifiedDefectPCBs",
    exception_count_label: str = "Classified NG PCBs",
    exception_reason_column: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
):
    import pandas as pd
    import plotly.graph_objects as go

    daily_axis = (
        period_start is not None
        and period_end is not None
        and analysis_period_days(period_start, period_end) <= 31
    )
    date_column = next((name for name in ("PeriodDate", "PeriodStart") if name in frame.columns), None)
    plot_frame = frame
    if daily_axis and date_column is not None:
        plot_frame = frame.copy()
        plot_frame[date_column] = pd.to_datetime(plot_frame[date_column], errors="coerce").dt.normalize()
        plot_frame = plot_frame.loc[plot_frame[date_column].between(pd.Timestamp(period_start), pd.Timestamp(period_end))]
    x_values = pd.to_datetime(plot_frame[date_column]) if date_column is not None and period_start is not None else plot_frame[x_column]
    hover_x = "%{x|%d/%m/%Y}" if date_column is not None and period_start is not None else "%{x}"
    values = pd.to_numeric(plot_frame[y_column], errors="coerce")
    # Plotly treats an explicit null as a gap.  Keep it distinct from zero so
    # an invalid daily denominator never draws a line down to the x-axis.
    chart_values = values.astype(object).where(values.notna(), None)
    valid_values = values.dropna()
    axis_values = valid_values.copy()
    if target_value is not None:
        axis_values = pd.concat([axis_values, pd.Series([target_value])], ignore_index=True)
    dense_labels = len(values) >= 6
    if value_type == "percent":
        labels = ["" if pd.isna(value) else f"{float(value) * 100:,.2f}%" for value in values]
        text_positions = [
            (
                "top center"
                if dense_labels and index % 2 == 0
                else "bottom center"
                if dense_labels or pd.notna(value) and float(value) >= 0.97
                else "top center"
            )
            for index, value in enumerate(values)
        ]
    else:
        labels = ["" if pd.isna(value) else f"{float(value):,.0f}" for value in values]
        low_value_threshold = float(axis_values.max()) * 0.08 if not axis_values.empty else 0.0
        text_positions = [
            (
                "bottom center"
                if dense_labels
                and index % 2 == 1
                and pd.notna(value)
                and float(value) > low_value_threshold
                else "top center"
            )
            for index, value in enumerate(values)
        ]
    chart = go.Figure(
        data=[
            go.Scatter(
                x=x_values,
                y=chart_values,
                mode="lines+markers+text",
                connectgaps=False,
                line=dict(color=color, width=3),
                marker=dict(color=color, size=8),
                text=labels,
                textposition=text_positions,
                textfont=dict(color=color, size=11),
                cliponaxis=False,
                hovertemplate=(
                    f"{hover_x}<br>Rate: %{{y:.2%}}<extra></extra>"
                    if value_type == "percent"
                    else f"{hover_x}<br>PPM: %{{y:,.0f}}<extra></extra>"
                ),
            )
        ]
    )
    if value_type == "percent" and not axis_values.empty:
        minimum = float(axis_values.min())
        maximum = float(axis_values.max())
        span = max(maximum - minimum, 0.005)
        axis_range = [max(0.0, minimum - span), min(1.0, maximum + span * 1.6)]
    elif not axis_values.empty and float(axis_values.max()) > 0:
        axis_range = [0, float(axis_values.max()) * 1.22]
    else:
        axis_range = None
    if axis_range is None and exception_rows is not None and not exception_rows.empty:
        fallback_top = float(target_value) * 1.22 if target_value and target_value > 0 else (1.0 if value_type == "percent" else 1_000_000.0)
        axis_range = [0.0, fallback_top]
    if exception_rows is not None and not exception_rows.empty and axis_range is not None:
        exception_y = axis_range[1] - ((axis_range[1] - axis_range[0]) * 0.04)
        empty_exception_values = pd.Series(0, index=exception_rows.index, dtype="float64")
        exception_counts = pd.to_numeric(
            exception_rows.get(exception_count_column, empty_exception_values), errors="coerce"
        ).fillna(0)
        exception_inputs = pd.to_numeric(
            exception_rows.get("Input", exception_rows.get("Produced", empty_exception_values)),
            errors="coerce",
        ).fillna(0)
        exception_reasons = (
            exception_rows.get(exception_reason_column, pd.Series("Data consistency exception", index=exception_rows.index))
            if exception_reason_column
            else pd.Series("Data consistency exception", index=exception_rows.index)
        )
        chart.add_trace(
            go.Scatter(
                x=(pd.to_datetime(exception_rows[date_column]) if date_column is not None and period_start is not None else exception_rows[x_column]),
                y=[exception_y] * len(exception_rows),
                mode="markers",
                marker=dict(color="#DC2626", size=13, symbol="x"),
                customdata=pd.DataFrame(
                    {
                        "Input": exception_inputs,
                        "Defects": exception_counts,
                        "Reason": exception_reasons,
                    }
                ).to_numpy(),
                hovertemplate=(
                    "<b>Data consistency exception</b><br>"
                    "Input: %{customdata[0]:,.0f}<br>"
                    + escape(exception_count_label)
                    + ": %{customdata[1]:,.0f}<br>"
                    "Reason: %{customdata[2]}<br>"
                    "KPI not calculated for this period<extra></extra>"
                ),
            )
        )
    chart.update_layout(
        title=title,
        height=420,
        margin=dict(l=55, r=35, t=80, b=75),
        paper_bgcolor="white",
        plot_bgcolor="#F8FAFD",
        showlegend=False,
    )
    if period_start is not None and period_end is not None and date_column is not None:
        grain = requested_trend_grain(period_start, period_end)
        if grain == "day":
            ticks = pd.date_range(period_start, period_end, freq="D")
        elif grain == "week":
            ticks = pd.date_range(period_start, period_end, freq="W-MON")
        else:
            ticks = pd.date_range(period_start, period_end, freq="MS")
        start_tick = pd.Timestamp(period_start)
        if len(ticks) == 0 or ticks[0] != start_tick:
            ticks = ticks.insert(0, start_tick)
        chart.update_xaxes(
            type="date",
            range=[start_tick - pd.Timedelta(hours=12), pd.Timestamp(period_end) + pd.Timedelta(hours=12)],
            tickmode="array",
            tickvals=ticks,
            ticktext=[tick.strftime("%d/%m" if grain != "month" else "%b/%y") for tick in ticks],
            tickangle=-45 if len(ticks) > 10 else 0,
            automargin=True,
        )
    else:
        chart.update_xaxes(tickangle=-35 if len(frame) > 10 else 0, automargin=True)
    chart.update_yaxes(
        range=axis_range,
        tickformat=".1%" if value_type == "percent" else ",.0f",
        title_text="Pass rate" if value_type == "percent" else "PPM",
        automargin=True,
    )
    if target_value is not None:
        valid_indices = [index for index, value in enumerate(values) if pd.notna(value)]
        final_label_position = text_positions[valid_indices[-1]] if valid_indices else "bottom center"
        target_label_position = "bottom right" if final_label_position.startswith("top") else "top right"
        target_text = fmt_kpi_pct(target_value) if value_type == "percent" else f"{fmt_ppm(target_value)} PPM"
        chart.add_hline(
            y=target_value,
            line_color="#DC2626",
            line_width=2,
            line_dash="dash",
            annotation_text=target_text,
            annotation_position=target_label_position,
            annotation_font=dict(color="#DC2626", size=11),
        )
    return chart


def build_smt_oqc_trend(oqc_records, start_date: date, end_date: date):
    import pandas as pd

    settings = trend_granularity(pd.Timestamp(start_date), pd.Timestamp(end_date))
    selected = oqc_records.copy()
    selected["InspectionDate"] = parse_date_series(selected["InspectionDate"]).dt.normalize()
    selected = selected.loc[selected["InspectionDate"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
    oqc_trend = add_trend_period(selected, "InspectionDate", settings)
    oqc_trend = oqc_trend.groupby("PeriodDate", as_index=False).agg(
        Inspected=("Inspected", "sum"),
        OK=("OK", "sum"),
        NG=("NG", "sum"),
    )
    oqc_trend["PeriodDate"] = oqc_trend["PeriodDate"].clip(lower=pd.Timestamp(start_date))
    oqc_trend["Period"] = oqc_trend["PeriodDate"].map(
        lambda value: format_trend_period(value, settings["grain"])
    )
    oqc_trend["PassRate"] = oqc_trend["OK"] / oqc_trend["Inspected"].replace(0, pd.NA)
    return oqc_trend.sort_values("PeriodDate"), settings


def calculate_assembly_smt_duty_kpi(start_date: date, end_date: date) -> dict:
    metrics = calculate_assembly_kpi_metrics(start_date, end_date)
    duty_rows = metrics["defects"][metrics["defects"]["IsSMTDuty"]].copy()
    trend = metrics["trend"][["PeriodDate", "Period", "Produced", "SMTDutyPCBs", "SMTDutyPPM", "SMTDutyStatus"]].copy()
    trend = trend.rename(columns={"SMTDutyPCBs": "DutyDefects", "SMTDutyPPM": "DutyPPM"})
    breakdown = (
        duty_rows.groupby("FinalDutyType", as_index=False)["PCBNormalized"]
        .nunique()
        .rename(columns={"FinalDutyType": "DutyType", "PCBNormalized": "DefectPCBs"})
        .sort_values("DefectPCBs", ascending=False)
    )
    return {
        "produced": metrics["produced"],
        "duty_defects": metrics["smt_duty_pcbs"],
        "duty_ppm": metrics["smt_duty_ppm"],
        "smt_duty_status": metrics["smt_duty_status"],
        "trend": trend,
        "trend_settings": metrics["trend_settings"],
        "breakdown": breakdown,
        "source": metrics["source"],
    }


def assembly_input_bounds(input_paths: list[Path]) -> tuple[date, date]:
    signatures = tuple(path_signature(path) for path in input_paths)
    return assembly_input_bounds_cached(signatures)


@st.cache_data(show_spinner=False)
def assembly_input_bounds_cached(
    input_signatures: tuple[tuple[str, int, int], ...],
) -> tuple[date, date]:
    """Avoid reopening every daily input file just to populate the date filter."""
    starts = []
    for signature in input_signatures:
        input_path = Path(signature[0])
        try:
            frame = assembly_kpi_v2.read_daily_input(input_path)
        except Exception:
            continue
        starts.extend(frame["Date"].dropna().tolist())
    if not starts:
        raise RuntimeError("Nenhum arquivo de input diário válido foi encontrado.")
    return min(starts).date(), max(starts).date()


def calculate_assembly_kpi_metrics(start_date: date, end_date: date) -> dict:
    sources = stored_assembly_sources_v2()
    if not sources["input"] or not sources["defects"] or not sources["repair"]:
        raise RuntimeError("Carregue inputs diários, defeitos gerais cumulativos e reparo cumulativo de Assembly.")

    input_signatures = tuple(path_signature(path) for path in sources["input"])
    defect_signatures = tuple(path_signature(path) for path in sources["defects"])
    repair_signatures = tuple(path_signature(path) for path in sources["repair"])
    return calculate_assembly_kpi_metrics_cached(
        input_signatures,
        defect_signatures,
        repair_signatures,
        start_date.isoformat(),
        end_date.isoformat(),
        assembly_kpi_v2.ASSEMBLY_KPI_RULE_VERSION,
    )


@st.cache_data(show_spinner=False)
def prepare_assembly_kpi_sources_cached(
    input_signatures: tuple[tuple[str, int, int], ...],
    defect_signatures: tuple[tuple[str, int, int], ...],
    repair_signatures: tuple[tuple[str, int, int], ...],
    rule_version: str,
) -> tuple:
    """Read the source workbooks only once for every report period sharing the same uploads."""
    _ = rule_version  # Cache key: defect consolidation and classification rules affect prepared data.
    input_paths = [Path(signature[0]) for signature in input_signatures]
    defect_paths = [Path(signature[0]) for signature in defect_signatures]
    repair_paths = [Path(signature[0]) for signature in repair_signatures]
    return assembly_kpi_v2.prepare_sources(input_paths, defect_paths, repair_paths)


@st.cache_data(show_spinner=False)
def calculate_assembly_kpi_metrics_cached(
    input_signatures: tuple[tuple[str, int, int], ...],
    defect_signatures: tuple[tuple[str, int, int], ...],
    repair_signatures: tuple[tuple[str, int, int], ...],
    start_text: str,
    end_text: str,
    rule_version: str,
) -> dict:
    """Read Assembly source workbooks once per source revision and period."""
    _ = rule_version  # Cache key: rules may change without changing a source file.
    import pandas as pd

    inputs, defects = prepare_assembly_kpi_sources_cached(
        input_signatures, defect_signatures, repair_signatures, rule_version
    )
    result = assembly_kpi_v2.calculate_from_prepared(
        inputs,
        defects,
        date.fromisoformat(start_text),
        date.fromisoformat(end_text),
    )
    trend = result["daily"].rename(
        columns={
            "Date": "PeriodDate",
            "Input": "Produced",
            "FunctionalNGPCBs": "FunctionalNGRecords",
            "AppearanceNGPCBs": "AppearanceNGRecords",
            "AppearancePassRate": "AppearanceTotalPassRate",
        }
    )
    trend["Period"] = trend["PeriodDate"].map(lambda value: pd.Timestamp(value).strftime("%d/%m"))
    result.update(
        {
            "source": f"{len(defect_signatures)} FPY defect file(s) + {len(repair_signatures)} repair file(s)",
            "operations": sorted(set(result["defects"]["Operation"])),
            "functional_operations": list(assembly_kpi_v2.FUNCTIONAL_OPERATIONS),
            "appearance_operations": list(assembly_kpi_v2.APPEARANCE_OPERATIONS),
            "unclassified_operations": sorted(set(result["unclassified"]["Operation"])),
            "functional_records": result["functional_pcbs"],
            "appearance_records": result["appearance_pcbs"],
            "functional_mando_pcbs": result["function_mando_pcbs"],
            "trend": trend.sort_values("PeriodDate"),
            "trend_settings": {"grain": "daily", "label": "Daily"},
        }
    )
    return result


def build_assembly_oqc_fqc_trend(records, start_date: date, end_date: date):
    import pandas as pd

    settings = trend_granularity(pd.Timestamp(start_date), pd.Timestamp(end_date))
    selected = records.copy()
    selected["InspectionDate"] = parse_date_series(selected["InspectionDate"]).dt.normalize()
    selected = selected.loc[selected["InspectionDate"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
    trend = add_trend_period(selected, "InspectionDate", settings)
    trend = trend.groupby("PeriodDate", as_index=False).agg(
        OQCInspected=("OQCInspected", "sum"),
        OQCOK=("OQCOK", "sum"),
        FQCInspected=("FQCInspected", "sum"),
        FQCOK=("FQCOK", "sum"),
    )
    trend["PeriodDate"] = trend["PeriodDate"].clip(lower=pd.Timestamp(start_date))
    trend["Period"] = trend["PeriodDate"].map(lambda value: format_trend_period(value, settings["grain"]))
    trend["OQCPassRate"] = trend["OQCOK"] / trend["OQCInspected"].replace(0, pd.NA)
    trend["FQCPassRate"] = trend["FQCOK"] / trend["FQCInspected"].replace(0, pd.NA)
    trend["CombinedPassRate"] = trend["OQCPassRate"] * trend["FQCPassRate"]
    return trend.sort_values("PeriodDate"), settings


def smt_kpi_track_page(color: str) -> None:
    import pandas as pd
    from tools import smt_quality_dashboard

    if (
        getattr(smt_quality_dashboard, "SMT_TREND_POLICY_VERSION", None) != 2
        or smt_quality_dashboard.requested_trend_grain is not requested_trend_grain
    ):
        # The analysis module may still hold the previous grouping function.
        smt_quality_dashboard = importlib.reload(smt_quality_dashboard)
        smt_quality_dashboard.analyze_smt_quality_paths.clear()

    st.markdown(f"<h1 class='section-title' style='color:{color};'>SMT KPI Track</h1>", unsafe_allow_html=True)

    input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
    if not input_paths or not defect_paths:
        st.info("Abra a aba Data Upload e carregue pelo menos o Input FPY e os Defeitos FPY para iniciar os cálculos de SMT.")
        return
    input_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in input_paths)
    minimum_date, maximum_date = smt_quality_dashboard.input_bounds(input_signatures)
    start_date, end_date = analysis_period_control(
        "smt_kpi_period",
        minimum_date.date(),
        maximum_date.date(),
        default_start=minimum_date.date(),
        default_end=maximum_date.date(),
    )
    if end_date < start_date:
        st.error("KPI end date must be on or after the start date.")
        return

    smt_analysis = smt_quality_dashboard.analyze_smt_quality_paths(
        input_signatures,
        tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths),
        start_date.isoformat(),
        end_date.isoformat(),
        smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
        smt_quality_dashboard.SMT_TREND_POLICY_VERSION,
    )
    smt_totals = smt_analysis["totals"]
    function_pass_valid = smt_totals.get("FunctionPassStatus") == "Valid"
    process_ng_valid = smt_totals.get("SMTProcessStatus") == "Valid"
    try:
        assembly_kpi = calculate_assembly_smt_duty_kpi(start_date, end_date)
        assembly_error = ""
    except Exception as exc:
        assembly_kpi = None
        assembly_error = str(exc)
    oqc_records = load_smt_oqc_inspections(start_date, end_date)
    oqc_inspected = int(oqc_records["Inspected"].sum()) if not oqc_records.empty else 0
    oqc_ok = int(oqc_records["OK"].sum()) if not oqc_records.empty else 0
    oqc_ng = int(oqc_records["NG"].sum()) if not oqc_records.empty else 0
    oqc_pass_rate = oqc_ok / oqc_inspected if oqc_inspected else None
    configured_targets = {item["source"]: item for item in configured_kpi_directory()}
    function_target = configured_targets["smt_function"]["target"]
    process_target = configured_targets["smt_process"]["target"]
    duty_target = configured_targets["smt_assembly_duty"]["target"]
    oqc_target = configured_targets["smt_oqc"]["target"]

    period_note = f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"
    cards = st.columns(4)
    with cards[0]:
        smt_kpi_card(
            "Function Pass Rate",
            fmt_kpi_pct(smt_totals["FunctionPassRate"]) if function_pass_valid else "N/A",
            f"{fmt_int(smt_totals['FunctionalDefectPCBs'])} functional NG PCBs · {fmt_int(smt_totals['Produced'])} input",
            color,
            actual_value=smt_totals["FunctionPassRate"] if function_pass_valid else None,
            target_value=function_target,
            target_direction="min",
        )
    with cards[1]:
        smt_kpi_card(
            "SMT Process NG Rate",
            f"{fmt_ppm(smt_totals['SMTProcessNGRatePPM'])} PPM" if process_ng_valid else "N/A",
            (
                f"{fmt_kpi_pct(smt_totals['SMTProcessNGRate'])} · functional + appearance"
                if process_ng_valid
                else f"Input {fmt_int(smt_totals['Produced'])} < classified NG {fmt_int(smt_totals['ClassifiedDefectPCBs'])}"
            ),
            color,
            actual_value=smt_totals["SMTProcessNGRatePPM"] if process_ng_valid else None,
            target_value=process_target,
            target_direction="max",
        )
    with cards[2]:
        smt_kpi_card(
            "Assembly SMT Process Duty NG Rate",
            f"{fmt_ppm(assembly_kpi['duty_ppm'])} PPM" if assembly_kpi else "N/A",
            (
                f"{fmt_int(assembly_kpi['duty_defects'])} defects · {fmt_int(assembly_kpi['produced'])} Assembly input"
                if assembly_kpi
                else assembly_error
            ),
            color,
            actual_value=assembly_kpi["duty_ppm"] if assembly_kpi else None,
            target_value=duty_target,
            target_direction="max",
        )
    with cards[3]:
        smt_kpi_card(
            "SMT OQC Pass Rate",
            fmt_kpi_pct(oqc_pass_rate),
            f"{fmt_int(oqc_ok)} OK · {fmt_int(oqc_ng)} NG · {fmt_int(oqc_inspected)} inspected" if oqc_inspected else "Awaiting manual OQC input",
            color,
            actual_value=oqc_pass_rate,
            target_value=oqc_target,
            target_direction="min",
        )

    if assembly_error:
        st.warning(f"Assembly KPI is unavailable: {assembly_error}")

    formula_rows = [
        {
            "KPI": "Function Pass Rate",
            "Calculation basis": (
                f"{fmt_int(smt_totals['FunctionalDefectPCBs'])} functional NG PCBs | "
                f"{fmt_int(smt_totals['Produced'])} SMT input"
            ),
            "Formula": "(Input − unique functional NG PCB) / Input × 100",
            "Result": fmt_kpi_pct(smt_totals["FunctionPassRate"]) if function_pass_valid else "N/A",
        },
        {
            "KPI": "SMT Process NG Rate (PPM)",
            "Calculation basis": (
                f"{fmt_int(smt_totals['ClassifiedDefectPCBs'])} classified NG PCBs | "
                f"{fmt_int(smt_totals['Produced'])} SMT input"
            ),
            "Formula": "NG PCB / Input × 1,000,000",
            "Result": (
                f"{fmt_ppm(smt_totals['SMTProcessNGRatePPM'])} PPM · {fmt_kpi_pct(smt_totals['SMTProcessNGRate'])}"
                if process_ng_valid
                else "N/A"
            ),
        },
        {
            "KPI": "Assembly SMT Process Duty NG Rate (PPM)",
            "Calculation basis": (
                f"{fmt_int(assembly_kpi['duty_defects'])} SMT-duty defects | "
                f"{fmt_int(assembly_kpi['produced'])} Assembly input"
                if assembly_kpi
                else "Assembly data unavailable"
            ),
            "Formula": "SMT-duty defects / Assembly input × 1,000,000",
            "Result": f"{fmt_ppm(assembly_kpi['duty_ppm'])} PPM" if assembly_kpi else "N/A",
        },
        {
            "KPI": "SMT OQC Pass Rate",
            "Calculation basis": f"{fmt_int(oqc_ok)} OQC OK | {fmt_int(oqc_inspected)} inspected",
            "Formula": "OQC OK / OQC inspected × 100",
            "Result": fmt_kpi_pct(oqc_pass_rate),
        },
    ]
    st.markdown("### KPI formulas")
    styled_table(pd.DataFrame(formula_rows), table_class="kpi-formula-table")

    smt_trend = smt_analysis["trend"].copy()
    smt_period_column = "PeriodDate" if "PeriodDate" in smt_trend.columns else "PeriodStart"
    if smt_period_column in smt_trend.columns:
        smt_trend["Period"] = smt_trend[smt_period_column].map(
            lambda value: format_trend_period(value, requested_trend_grain(start_date, end_date))
        )
    selected_trend_label = trend_grain_labels(requested_trend_grain(start_date, end_date))[0]
    process_exceptions = smt_trend.loc[
        smt_trend.get("SMTProcessStatus", pd.Series("Valid", index=smt_trend.index)).ne("Valid")
    ].copy()
    function_exceptions = smt_trend.loc[
        smt_trend.get("FunctionPassStatus", pd.Series("Valid", index=smt_trend.index)).ne("Valid")
    ].copy()
    function_pass_chart = smt_kpi_line_chart(
        smt_trend,
        "Period",
        "FunctionPassRate",
        f"Function Pass Rate trend · {selected_trend_label}",
        color,
        "percent",
        target_value=function_target,
        exception_rows=function_exceptions,
        exception_count_column="FunctionalDefectPCBs",
        exception_count_label="Functional NG PCBs",
        exception_reason_column="FunctionPassStatus",
        period_start=start_date,
        period_end=end_date,
    )
    process_ng_chart = smt_kpi_line_chart(
        smt_trend,
        "Period",
        "SMTProcessNGRatePPM",
        f"SMT Process NG Rate trend · {selected_trend_label}",
        "#C2410C",
        "ppm",
        target_value=process_target,
        exception_rows=process_exceptions,
        exception_count_column="ClassifiedDefectPCBs",
        exception_count_label="Classified NG PCBs",
        exception_reason_column="SMTProcessStatus",
        period_start=start_date,
        period_end=end_date,
    )
    show_chart(function_pass_chart)
    show_chart(process_ng_chart)

    assembly_trend = assembly_kpi["trend"] if assembly_kpi else pd.DataFrame()
    assembly_duty_exceptions = assembly_trend.loc[
        assembly_trend.get("SMTDutyStatus", pd.Series("Valid", index=assembly_trend.index)).ne("Valid")
    ].copy()
    assembly_chart = (
        smt_kpi_line_chart(
            assembly_trend,
            "Period",
            "DutyPPM",
            f"Assembly SMT Process Duty NG Rate trend · {assembly_kpi['trend_settings']['label']}",
            "#6532C8",
            "ppm",
            target_value=duty_target,
            exception_rows=assembly_duty_exceptions,
            exception_count_column="DutyDefects",
            exception_count_label="SMT-duty NG PCBs",
            exception_reason_column="SMTDutyStatus",
            period_start=start_date,
            period_end=end_date,
        )
        if not assembly_trend.empty
        else None
    )
    if not oqc_records.empty:
        oqc_trend, oqc_trend_settings = build_smt_oqc_trend(oqc_records, start_date, end_date)
        oqc_chart = smt_kpi_line_chart(
            oqc_trend,
            "Period",
            "PassRate",
            f"SMT OQC Pass Rate trend · {oqc_trend_settings['label']}",
            "#1D5FBF",
            "percent",
            target_value=oqc_target,
            period_start=start_date,
            period_end=end_date,
        )
    else:
        oqc_trend = pd.DataFrame()
        oqc_chart = None

    if assembly_chart is not None:
        show_chart(assembly_chart)
    else:
        st.info("Assembly Duty NG trend will appear when Assembly data is available.")
    if oqc_chart is not None:
        show_chart(oqc_chart)
    else:
        st.info("SMT OQC Pass Rate trend will appear after the first manual inspection entry.")

    if not process_exceptions.empty:
        st.markdown("### Data consistency exceptions")
        st.warning(
            "SMT Process NG Rate is not calculated for the periods below because classified NG PCBs exceed the available input. "
            "The defect records remain included when a larger selected period has a valid aggregate denominator."
        )
        exception_view = process_exceptions[["Period", "Input", "ClassifiedDefectPCBs", "SMTProcessStatus"]].copy()
        exception_view = exception_view.rename(
            columns={
                "ClassifiedDefectPCBs": "Classified NG PCBs",
                "SMTProcessStatus": "Reason",
            }
        )
        styled_table(exception_view)

    if not function_exceptions.empty or not process_exceptions.empty or not assembly_duty_exceptions.empty:
        st.caption("A red × marks a daily period where the available input is lower than the defects required by that KPI. The daily KPI is not calculated; a valid larger-period aggregate remains available.")

    with st.expander("Detalhamento dos dados e qualidade", expanded=True):
        detail = smt_trend[[
            "Period", "Granularity", "Input", "FunctionalDefectPCBs", "FunctionPassRate",
            "ClassifiedDefectPCBs", "SMTProcessNGRatePPM", "RejudgeOKRecords",
            "UnclassifiedDefectPCBs", "FunctionPassStatus", "SMTProcessStatus",
        ]].copy()
        detail["FunctionPassRate"] = (detail["FunctionPassRate"] * 100).round(2)
        detail["SMTProcessNGRatePPM"] = detail["SMTProcessNGRatePPM"].round(2)
        detail = detail.rename(columns={
            "Period": "Período", "Granularity": "Granularidade",
            "FunctionalDefectPCBs": "Functional NG", "FunctionPassRate": "Function Pass Rate (%)",
            "ClassifiedDefectPCBs": "Process NG", "SMTProcessNGRatePPM": "Process NG PPM",
            "RejudgeOKRecords": "Rejudge OK", "UnclassifiedDefectPCBs": "Unclassified NG",
            "FunctionPassStatus": "Function status", "SMTProcessStatus": "Process status",
        })
        styled_table(detail)
        totals = smt_analysis["totals"]
        st.caption(
            f"Fonte ativa: {fmt_int(totals['InputFiles'])} arquivo(s) de input FPY e "
            f"{fmt_int(totals['DefectFiles'])} arquivo(s) de defeitos · "
            f"{fmt_int(totals['UncoveredDefectRecords'])} registro(s) sem cobertura de input · "
            f"{fmt_int(totals['RejudgeOKRecords'])} registro(s) Rejudge OK."
        )
        if assembly_kpi is not None and not assembly_trend.empty:
            st.markdown("#### Assembly · SMT Process Duty")
            duty_detail = assembly_trend[["Period", "Produced", "DutyDefects", "DutyPPM", "SMTDutyStatus"]].copy()
            duty_detail["DutyPPM"] = duty_detail["DutyPPM"].round(2)
            duty_detail = duty_detail.rename(columns={
                "Period": "Período", "Produced": "Assembly input", "DutyDefects": "SMT-duty NG",
                "DutyPPM": "SMT-duty PPM", "SMTDutyStatus": "Status",
            })
            styled_table(duty_detail)
            st.caption("Este KPI usa os defeitos de responsabilidade SMT e o input de Assembly.")


def assembly_kpi_track_page(color: str) -> None:
    import pandas as pd

    st.markdown(f"<h1 class='section-title' style='color:{color};'>Assembly KPI Track</h1>", unsafe_allow_html=True)
    sources = stored_assembly_sources_v2()
    stored_inputs = sources["input"]
    if not sources["defects"] or not stored_inputs or not sources["repair"]:
        st.info("Abra a aba Data Upload e carregue os três grupos: Input FPY diário, Defeitos FPY cumulativos e Defeitos de reparo cumulativos.")
        return
    try:
        minimum_date, maximum_date = assembly_input_bounds(stored_inputs)
    except Exception as exc:
        st.error(f"Unable to read Assembly input dates: {exc}")
        return

    start_date, end_date = analysis_period_control(
        "assembly_kpi_period",
        minimum_date,
        maximum_date,
        default_start=minimum_date,
        default_end=maximum_date,
    )
    if end_date < start_date:
        st.error("KPI end date must be on or after the start date.")
        return
    try:
        metrics = calculate_assembly_kpi_metrics(start_date, end_date)
        calculation_error = ""
    except Exception as exc:
        metrics = None
        calculation_error = str(exc)

    if metrics is None:
        st.error(f"Unable to calculate Assembly KPIs: {calculation_error}")
        return

    functional_ready = True
    appearance_ready = True
    st.caption(
        "Regras MES validadas: PCB único no período; defeitos separados por TestOperation; "
        "responsabilidade final atualizada pelo reparo cumulativo."
    )
    oqc_fqc_records = load_assembly_oqc_fqc_inspections(start_date, end_date)
    oqc_inspected = int(oqc_fqc_records["OQCInspected"].sum()) if not oqc_fqc_records.empty else 0
    oqc_ok = int(oqc_fqc_records["OQCOK"].sum()) if not oqc_fqc_records.empty else 0
    fqc_inspected = int(oqc_fqc_records["FQCInspected"].sum()) if not oqc_fqc_records.empty else 0
    fqc_ok = int(oqc_fqc_records["FQCOK"].sum()) if not oqc_fqc_records.empty else 0
    oqc_pass_rate = oqc_ok / oqc_inspected if oqc_inspected else None
    fqc_pass_rate = fqc_ok / fqc_inspected if fqc_inspected else None
    oqc_fqc_pass_rate = oqc_pass_rate * fqc_pass_rate if oqc_pass_rate is not None and fqc_pass_rate is not None else None
    configured_targets = {item["source"]: item for item in configured_kpi_directory()}
    function_target = configured_targets["assembly_function"]["target"]
    appearance_target = configured_targets["assembly_appearance"]["target"]
    mando_target = configured_targets["assembly_mando"]["target"]
    oqc_fqc_target = configured_targets["assembly_oqc_fqc"]["target"]
    period_note = f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"

    cards = st.columns(4)
    with cards[0]:
        smt_kpi_card(
            "Function Pass Rate",
            fmt_kpi_pct(metrics["function_pass_rate"]),
            f"{fmt_int(metrics['functional_records'])} PCBs funcionais NG · {fmt_int(metrics['produced'])} input" if functional_ready else "Classificação indisponível",
            color,
            actual_value=metrics["function_pass_rate"] if functional_ready else None,
            target_value=function_target,
            target_direction="min",
        )
    with cards[1]:
        smt_kpi_card(
            "Appearance Total Pass Rate",
            fmt_kpi_pct(metrics["appearance_pass_rate"]),
            f"{fmt_int(metrics['appearance_records'])} PCBs de aparência NG · {fmt_int(metrics['produced'])} input" if appearance_ready else "Classificação indisponível",
            color,
            actual_value=metrics["appearance_pass_rate"] if appearance_ready else None,
            target_value=appearance_target,
            target_direction="min",
        )
    with cards[2]:
        smt_kpi_card(
            "Function Mando",
            f"{fmt_ppm(metrics['function_mando_ppm'])} PPM" if metrics["function_mando_ppm"] is not None else "N/A",
            f"{fmt_int(metrics['functional_mando_pcbs'])} functional Mando NG PCBs" if functional_ready else "Awaiting Functional Failure stations",
            color,
            actual_value=metrics["function_mando_ppm"] if functional_ready else None,
            target_value=mando_target,
            target_direction="max",
        )
    with cards[3]:
        smt_kpi_card(
            "Assembly OQC × FQC Pass Rate",
            fmt_kpi_pct(oqc_fqc_pass_rate),
            f"OQC {fmt_kpi_pct(oqc_pass_rate)} × FQC {fmt_kpi_pct(fqc_pass_rate)}" if oqc_fqc_pass_rate is not None else "Awaiting manual OQC and FQC input",
            color,
            actual_value=oqc_fqc_pass_rate,
            target_value=oqc_fqc_target,
            target_direction="min",
        )

    formula_rows = [
        {
            "KPI": "Function Pass Rate",
            "Calculation basis": (
                f"{fmt_int(metrics['functional_records'])} functional NG PCBs | "
                f"{fmt_int(metrics['produced'])} Assembly input"
                if functional_ready
                else "Functional classification pending"
            ),
            "Formula": "(Input − unique functional NG PCB) / Input × 100",
            "Result": fmt_kpi_pct(metrics["function_pass_rate"]),
        },
        {
            "KPI": "Appearance Total Pass Rate",
            "Calculation basis": (
                f"{fmt_int(metrics['appearance_records'])} appearance NG PCBs | "
                f"{fmt_int(metrics['produced'])} Assembly input"
                if appearance_ready
                else "Appearance classification pending"
            ),
            "Formula": "(Input − unique appearance NG PCB) / Input × 100",
            "Result": fmt_kpi_pct(metrics["appearance_pass_rate"]),
        },
        {
            "KPI": "Function Mando (PPM)",
            "Calculation basis": (
                f"{fmt_int(metrics['functional_mando_pcbs'])} functional Mando NG PCBs | "
                f"{fmt_int(metrics['produced'])} Assembly input"
                if functional_ready
                else "Functional classification pending"
            ),
            "Formula": "Functional Mando NG PCB / Input × 1,000,000",
            "Result": f"{fmt_ppm(metrics['function_mando_ppm'])} PPM" if metrics["function_mando_ppm"] is not None else "N/A",
        },
        {
            "KPI": "Assembly OQC × FQC Pass Rate",
            "Calculation basis": f"OQC {fmt_kpi_pct(oqc_pass_rate)} | FQC {fmt_kpi_pct(fqc_pass_rate)}",
            "Formula": "(OQC OK / inspected) × (FQC OK / inspected) × 100",
            "Result": fmt_kpi_pct(oqc_fqc_pass_rate),
        },
    ]
    st.markdown("### KPI formulas")
    styled_table(pd.DataFrame(formula_rows), table_class="kpi-formula-table")

    trend = metrics["trend"]
    trend_label = metrics["trend_settings"]["label"]
    function_exceptions = trend.loc[
        trend.get("FunctionPassStatus", pd.Series("Valid", index=trend.index)).ne("Valid")
    ].copy()
    appearance_exceptions = trend.loc[
        trend.get("AppearancePassStatus", pd.Series("Valid", index=trend.index)).ne("Valid")
    ].copy()
    mando_exceptions = trend.loc[
        trend.get("FunctionMandoStatus", pd.Series("Valid", index=trend.index)).ne("Valid")
    ].copy()
    function_chart = (
        smt_kpi_line_chart(
            trend, "Period", "FunctionPassRate", f"Function Pass Rate trend · {trend_label}", color, "percent",
            target_value=function_target,
            exception_rows=function_exceptions,
            exception_count_column="FunctionalNGRecords",
            exception_count_label="Functional NG PCBs",
            exception_reason_column="FunctionPassStatus",
            period_start=start_date,
            period_end=end_date,
        )
        if functional_ready else None
    )
    appearance_chart = (
        smt_kpi_line_chart(
            trend, "Period", "AppearanceTotalPassRate", f"Appearance Total Pass Rate trend · {trend_label}", "#1D5FBF", "percent",
            target_value=appearance_target,
            exception_rows=appearance_exceptions,
            exception_count_column="AppearanceNGRecords",
            exception_count_label="Appearance NG PCBs",
            exception_reason_column="AppearancePassStatus",
            period_start=start_date,
            period_end=end_date,
        )
        if appearance_ready else None
    )
    mando_chart = (
        smt_kpi_line_chart(
            trend, "Period", "FunctionMandoPPM", f"Function Mando trend · {trend_label}", "#C2410C", "ppm",
            target_value=mando_target,
            exception_rows=mando_exceptions,
            exception_count_column="FunctionMandoPCBs",
            exception_count_label="Function Mando NG PCBs",
            exception_reason_column="FunctionMandoStatus",
            period_start=start_date,
            period_end=end_date,
        )
        if functional_ready else None
    )
    oqc_fqc_chart = None
    if not oqc_fqc_records.empty:
        oqc_fqc_trend, oqc_fqc_settings = build_assembly_oqc_fqc_trend(oqc_fqc_records, start_date, end_date)
        oqc_fqc_chart = smt_kpi_line_chart(
            oqc_fqc_trend,
            "Period",
            "CombinedPassRate",
            f"Assembly OQC × FQC Pass Rate trend · {oqc_fqc_settings['label']}",
            "#0D7A45",
            "percent",
            target_value=oqc_fqc_target,
            period_start=start_date,
            period_end=end_date,
        )
    charts = [
        (function_chart, "Function Pass Rate trend will appear after Functional Failure stations are defined."),
        (appearance_chart, "Appearance Total Pass Rate trend will appear after Appearance Failure stations are defined."),
        (mando_chart, "Function Mando trend will appear after Functional Failure stations are defined."),
        (oqc_fqc_chart, "Assembly OQC × FQC Pass Rate trend will appear after the first manual inspection entry."),
    ]
    for chart, empty_message in charts:
        if chart is not None:
            show_chart(chart)
        else:
            st.info(empty_message)

    if not function_exceptions.empty or not appearance_exceptions.empty or not mando_exceptions.empty:
        st.caption("A red × marks a daily period where the available input is lower than the defects required by that KPI. The daily KPI is not calculated; a valid larger-period aggregate remains available.")

    with st.expander("Detalhamento dos dados e qualidade", expanded=True):
        daily_view = metrics["daily"].copy()
        daily_view["Date"] = pd.to_datetime(daily_view["Date"]).dt.strftime("%d/%m/%Y")
        daily_view["Function Pass Rate"] = (daily_view["FunctionPassRate"] * 100).round(2)
        daily_view["Appearance Pass Rate"] = (daily_view["AppearancePassRate"] * 100).round(2)
        daily_view["Function Mando PPM"] = daily_view["FunctionMandoPPM"].round(2)
        daily_view = daily_view.rename(
            columns={
                "Date": "Data",
                "FunctionalNGPCBs": "Functional NG",
                "AppearanceNGPCBs": "Appearance NG",
                "FunctionMandoPCBs": "Function Mando NG",
                "PendingResponsibilityPCBs": "Responsabilidade pendente",
            }
        )
        styled_table(
            daily_view[
                [
                    "Data", "Input", "Functional NG", "Function Pass Rate",
                    "Appearance NG", "Appearance Pass Rate", "Function Mando NG",
                    "Function Mando PPM", "Responsabilidade pendente",
                ]
            ]
        )
        st.caption(
            f"Fonte ativa: {metrics['source']} · "
            f"{fmt_int(metrics['pending_responsibility_pcbs'])} PCB(s) funcionais com responsabilidade pendente · "
            f"{fmt_int(len(metrics['unclassified']))} ocorrência(s) fora do escopo."
        )


def _dashboard_defect_key(frame, pcb_column: str = "PCB"):
    import pandas as pd

    if frame.empty:
        return pd.Series(dtype="object", index=frame.index)
    pcb = frame.get(pcb_column, pd.Series("", index=frame.index)).fillna("").astype(str).str.strip()
    return pcb.where(pcb.ne(""), "ROW-" + frame.index.astype(str))


def _dashboard_priority(value: float, target: float | None = None) -> str:
    if value is None:
        return "Review data"
    try:
        if value != value:
            return "Review data"
    except TypeError:
        return "Review data"
    if not isinstance(value, Number):
        return "Review data"
    if target and target > 0:
        ratio = float(value) / float(target)
        if ratio >= 1.5:
            return "Critical"
        if ratio >= 1:
            return "High"
        if ratio >= 0.6:
            return "Medium"
        return "Monitor"
    if value >= 5_000:
        return "Critical"
    if value >= 2_500:
        return "High"
    if value >= 1_000:
        return "Medium"
    return "Monitor"


def _build_smt_dashboard_view(analysis: dict, model: str | list[str], station: str, failure_type: str, duty_type: str = "All") -> dict:
    import pandas as pd
    from tools import smt_quality_dashboard

    covered = analysis["covered_raw"].copy()
    calendar = analysis["raw"].copy()
    selected_input = analysis["selected_input"].copy()
    selected_models = (
        None
        if model == "All" or model == []
        else {model} if isinstance(model, str) else set(model)
    )
    use_model_scoped_board_keys = selected_models is None or len(selected_models) > 1

    def apply_filters(frame):
        view = frame.copy()
        if selected_models is not None:
            view = view[view["Model"].isin(selected_models)]
        if station != "All":
            view = view[view["Operation"].eq(station)]
        if failure_type != "All":
            view = view[view["FailureType"].eq(failure_type)]
        if duty_type != "All":
            view = view[view["DutyType"].eq(duty_type)]
        return view

    covered = apply_filters(covered)
    calendar = apply_filters(calendar)
    if selected_models is not None:
        selected_input = selected_input[selected_input["Model"].isin(selected_models)].copy()

    covered["_DefectKey"] = _dashboard_defect_key(covered)
    calendar["_DefectKey"] = _dashboard_defect_key(calendar)
    if use_model_scoped_board_keys:
        covered["_DefectKey"] = covered["Model"].fillna("").astype(str) + "::" + covered["_DefectKey"]
        calendar["_DefectKey"] = calendar["Model"].fillna("").astype(str) + "::" + calendar["_DefectKey"]
    confirmed = covered[~covered["IsRejudgeOK"].fillna(False).astype(bool)].copy()
    rejudge = covered[covered["IsRejudgeOK"].fillna(False).astype(bool)].copy()
    classified = confirmed[
        confirmed["FailureType"].isin(["Functional Failure", "Appearance Failure"])
    ].copy()
    functional = confirmed[confirmed["FailureType"].eq("Functional Failure")].copy()
    appearance = confirmed[confirmed["FailureType"].eq("Appearance Failure")].copy()

    produced = int(selected_input["Input"].sum())

    def unique_count(frame) -> int:
        return int(frame["_DefectKey"].nunique()) if not frame.empty else 0

    confirmed_pcbs = unique_count(confirmed)
    classified_pcbs = unique_count(classified)
    functional_pcbs = unique_count(functional)
    appearance_pcbs = unique_count(appearance)
    functional_keys = set(functional["_DefectKey"])
    appearance_keys = set(appearance["_DefectKey"])
    both_type_pcbs = len(functional_keys & appearance_keys)
    functional_only_pcbs = len(functional_keys - appearance_keys)
    appearance_only_pcbs = len(appearance_keys - functional_keys)

    daily_input = smt_quality_dashboard.distribute_smt_input_to_days(selected_input)
    trend_rows = []
    for row in analysis["trend"].itertuples(index=False):
        begin = pd.Timestamp(row.PeriodStart)
        end = pd.Timestamp(row.PeriodEndExclusive)
        period_input = int(
            daily_input.loc[
                daily_input["BeginDate"].ge(begin) & daily_input["BeginDate"].lt(end),
                "Input",
            ].sum()
        )
        period_confirmed = confirmed[
            confirmed["KPIDate"].ge(begin) & confirmed["KPIDate"].lt(end)
        ]
        period_classified = period_confirmed[
            period_confirmed["FailureType"].isin(["Functional Failure", "Appearance Failure"])
        ]
        period_functional = period_confirmed[
            period_confirmed["FailureType"].eq("Functional Failure")
        ]
        period_appearance = period_confirmed[
            period_confirmed["FailureType"].eq("Appearance Failure")
        ]
        confirmed_count = unique_count(period_confirmed)
        classified_count = unique_count(period_classified)
        functional_count = unique_count(period_functional)
        appearance_count = unique_count(period_appearance)
        valid = bool(period_input and classified_count <= period_input)
        trend_rows.append(
            {
                "PeriodDate": begin,
                "Period": row.Period,
                "Input": period_input,
                "ConfirmedDefectPCBs": confirmed_count,
                "ClassifiedDefectPCBs": classified_count,
                "FunctionalDefectPCBs": functional_count,
                "AppearanceDefectPCBs": appearance_count,
                "OverallPPM": (
                    confirmed_count / period_input * 1_000_000
                    if period_input and confirmed_count <= period_input
                    else None
                ),
                "ProcessPPM": classified_count / period_input * 1_000_000 if valid else None,
                "FunctionalPPM": (
                    functional_count / period_input * 1_000_000
                    if period_input and functional_count <= period_input
                    else None
                ),
                "AppearancePPM": (
                    appearance_count / period_input * 1_000_000
                    if period_input and appearance_count <= period_input
                    else None
                ),
                "Status": "Valid" if valid else "Blocked: classified NG PCB exceeds input",
            }
        )
    trend = pd.DataFrame(trend_rows)

    input_by_model = (
        selected_input.groupby("Model", as_index=False).agg(Input=("Input", "sum"))
        if not selected_input.empty
        else pd.DataFrame(columns=["Model", "Input"])
    )
    defects_by_model = (
        confirmed.groupby("Model", as_index=False).agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(columns=["Model", "NGPCBs"])
    )
    models = input_by_model.merge(defects_by_model, on="Model", how="left").fillna(0)
    models["PPM"] = models["NGPCBs"] / models["Input"].replace(0, pd.NA) * 1_000_000

    pareto = (
        confirmed.groupby("Phenomenon", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["Phenomenon", "NGPCBs"])
    )

    model_station = (
        confirmed.groupby(["Model", "Operation"], as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(columns=["Model", "Operation", "NGPCBs"])
    )
    if not model_station.empty:
        model_station = model_station.merge(input_by_model, on="Model", how="left")
        model_station["PPM"] = (
            model_station["NGPCBs"] / model_station["Input"].replace(0, pd.NA) * 1_000_000
        )
        top_models = (
            model_station.groupby("Model")["NGPCBs"].sum().nlargest(6).index.tolist()
        )
        top_stations = (
            model_station.groupby("Operation")["NGPCBs"].sum().nlargest(7).index.tolist()
        )
        heatmap = (
            model_station[
                model_station["Model"].isin(top_models)
                & model_station["Operation"].isin(top_stations)
            ]
            .pivot_table(index="Model", columns="Operation", values="PPM", aggfunc="sum", fill_value=0)
            .reindex(index=top_models, columns=top_stations, fill_value=0)
        )
    else:
        heatmap = pd.DataFrame()

    priority = (
        confirmed.groupby(["Phenomenon", "Operation", "Model", "DutyType"], as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(columns=["Phenomenon", "Operation", "Model", "DutyType", "NGPCBs"])
    )
    if not priority.empty:
        priority = priority.merge(input_by_model, on="Model", how="left")
        priority["ImpactPPM"] = priority["NGPCBs"] / priority["Input"].replace(0, pd.NA) * 1_000_000
        priority["Priority"] = priority["ImpactPPM"].map(
            lambda value: _dashboard_priority(value, 5_000)
        )
        priority = priority.sort_values(
            ["ImpactPPM", "NGPCBs"], ascending=[False, False]
        ).head(8)

    operation_summary = (
        confirmed.groupby("Operation", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["Operation", "NGPCBs"])
    )
    duty_summary = (
        confirmed.groupby("DutyType", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["DutyType", "NGPCBs"])
    )

    repeat_counts = (
        covered.groupby("_DefectKey").size().sort_values(ascending=False)
        if not covered.empty
        else pd.Series(dtype="int64")
    )
    repeated_keys = repeat_counts[repeat_counts > 1].index
    repeat_detail = covered[covered["_DefectKey"].isin(repeated_keys)].copy()
    repeat_detail["Occurrences"] = repeat_detail["_DefectKey"].map(repeat_counts)

    coverage_rate = (
        float(calendar["HasExactInputCoverage"].fillna(False).mean())
        if len(calendar) and "HasExactInputCoverage" in calendar.columns
        else (len(covered) / len(calendar) if len(calendar) else 1.0)
    )
    classification_rate = (
        len(classified) / len(confirmed) if len(confirmed) else 1.0
    )
    unknown_reason_records = int(
        confirmed["FaultReason"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"", "unknown", "unknownothers"})
        .sum()
    )
    process_valid = bool(produced and classified_pcbs <= produced)
    overall_valid = bool(produced and confirmed_pcbs <= produced)
    return {
        "produced": produced,
        "confirmed_pcbs": confirmed_pcbs,
        "classified_pcbs": classified_pcbs,
        "functional_pcbs": functional_pcbs,
        "appearance_pcbs": appearance_pcbs,
        "functional_only_pcbs": functional_only_pcbs,
        "appearance_only_pcbs": appearance_only_pcbs,
        "both_type_pcbs": both_type_pcbs,
        "overall_ppm": confirmed_pcbs / produced * 1_000_000 if overall_valid else None,
        "process_ppm": classified_pcbs / produced * 1_000_000 if process_valid else None,
        "trend": trend,
        "models": models,
        "pareto": pareto,
        "heatmap": heatmap,
        "priority": priority,
        "operation_summary": operation_summary,
        "duty_summary": duty_summary,
        "confirmed": confirmed,
        "rejudge": rejudge,
        "repeat_detail": repeat_detail,
        "coverage_rate": coverage_rate,
        "classification_rate": classification_rate,
        "unknown_reason_records": unknown_reason_records,
        "period_pooled_records": int(
            calendar.get("UsesPeriodPooledInput", pd.Series(False, index=calendar.index))
            .fillna(False)
            .sum()
        ),
        "unclassified_records": int(
            confirmed["FailureType"].eq("Unclassified").sum()
        ),
        "exceptions": int(trend["Status"].ne("Valid").sum()) if not trend.empty else 0,
    }


def smt_dashboard_issue_pareto(confirmed):
    """Aggregate detractors by repair conclusion, with phenomenon as fallback."""
    import pandas as pd
    from tools.smart_report_rules import top_issue_reasons

    data = confirmed.copy()
    if data.empty:
        return pd.DataFrame(columns=["TopIssue", "NGPCBs"])
    data["TopIssue"] = top_issue_reasons(data)
    return (
        data.groupby("TopIssue", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values(["NGPCBs", "TopIssue"], ascending=[False, True])
    )


def smt_dashboard_driver_detail(confirmed):
    """Give the operational context for the ranked repair conclusions."""
    import pandas as pd
    from tools.smart_report_rules import top_issue_reasons

    data = confirmed.copy()
    if data.empty:
        return pd.DataFrame(columns=["TopIssue", "Operation", "Model", "NGPCBs"])
    data["TopIssue"] = top_issue_reasons(data)
    return (
        data.groupby(["TopIssue", "Operation", "Model"], as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values(["NGPCBs", "TopIssue"], ascending=[False, True])
    )


SMT_DEFECT_DIMENSIONS = (
    ("Model", "Model", "Product model", "#2259B8"),
    ("Functional vs appearance", "FailureType", "Failure classification", "#2677D8"),
    ("TestOperation", "Operation", "Station where the failure was recorded", "#6532C8"),
    ("Fault Phenomenon", "Phenomenon", "Observed symptom", "#0C936C"),
    ("Fault reason", "FaultReason", "Recorded cause", "#D97706"),
    ("BadMachLocation", "Location", "Recorded defect location", "#B45309"),
    ("RepaireRemark", "RepairRemark", "Repair conclusion", "#C54B80"),
    ("DutyType", "DutyType", "Assigned responsibility", "#1E7191"),
    ("ItemCode", "ItemCode", "Recorded defective item", "#4F46A5"),
)

ASSEMBLY_DEFECT_DIMENSIONS = (
    ("Model", "Model", "Product model", "#2259B8"),
    ("Functional vs appearance", "FailureType", "Failure classification", "#2677D8"),
    ("TestOperation", "TestOperation", "Station where the failure was recorded", "#6532C8"),
    ("Fault Phenomenon", "Phenomenon", "Observed symptom", "#0C936C"),
    ("Fault reason", "FaultReason", "Recorded cause", "#D97706"),
    ("BadMachLocation", "BadMachLocation", "Recorded defect location", "#B45309"),
    ("RepaireRemark", "RepairRemark", "Repair conclusion", "#C54B80"),
    ("DutyType", "DutyType", "Assigned responsibility", "#1E7191"),
    ("ItemCode", "ItemCode", "Recorded defective item", "#4F46A5"),
)


def _smt_breakdown_source(confirmed):
    """Normalize MES breakdown fields once, keeping one row per confirmed record."""
    source = confirmed.copy()
    for _, column, _, _ in SMT_DEFECT_DIMENSIONS:
        if column not in source:
            source[column] = ""
        source[column] = source[column].fillna("").astype(str).str.strip()
        source[column] = source[column].replace({"": "Not specified", "nan": "Not specified"})
    return source


def _smt_breakdown_scope(source, selections, excluded_column=None):
    """Apply other-card selections; a card keeps its own category distribution."""
    scope = source
    for column, category in selections.items():
        if category != "All" and column != excluded_column:
            scope = scope[scope[column].eq(category)]
    return scope


def _clear_smt_breakdown_selections() -> None:
    for _, column, _, _ in SMT_DEFECT_DIMENSIONS:
        st.session_state[f"smt_breakdown_{column}"] = "All"


def _select_smt_breakdown_category(column: str, category: str) -> None:
    key = f"smt_breakdown_{column}"
    st.session_state[key] = "All" if st.session_state.get(key) == category else category


def render_smt_defect_dimension_cards(confirmed):
    """Render cross-filtering cards and return records matching all selections."""
    source = _smt_breakdown_source(confirmed)
    selections = {}
    for _, column, _, _ in SMT_DEFECT_DIMENSIONS:
        selections[column] = st.session_state.get(f"smt_breakdown_{column}", "All")

    css = [
        '<style>',
        '.smt-dimension-title{color:#102D5B;font-size:1.04rem;font-weight:800;line-height:1.25}',
        '.smt-dimension-subtitle{color:#6680A6;font-size:.73rem;margin:5px 0 14px;min-height:29px}',
        '.smt-dimension-track{height:5px;border-radius:6px;background:#EDF2F9;margin:0 8px 8px;overflow:hidden}.smt-dimension-track i{display:block;height:100%;border-radius:6px}',
        '.smt-dimension-empty{color:#6680A6;font-size:.75rem;margin-top:12px}',
        'div[class*="st-key-smt_breakdown_item_"]{padding:0 3px}',
        'div[class*="st-key-smt_breakdown_item_"] .stButton button{width:100%;min-height:32px;padding:4px 8px;justify-content:space-between;text-align:left;border:1px solid transparent;background:transparent;color:#17375F;font-size:.78rem;font-weight:600;box-shadow:none}',
        'div[class*="st-key-smt_breakdown_item_"] .stButton button:hover{background:#F1F6FD;border-color:#CFDBEE}',
        'div[class*="st-key-smt_breakdown_item_"] .stButton button p{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    ]
    for index, (_, _, _, accent) in enumerate(SMT_DEFECT_DIMENSIONS):
        css.append(
            f'div[class*="st-key-smt_dimension_{index}"]{{background:#fff;border:1px solid #CFDBEE;'
            f'border-top:3px solid {accent};border-radius:13px;padding:16px 17px 12px;'
            'min-height:332px;box-shadow:0 2px 7px rgba(19,48,91,.04)}'
        )
    css.append('</style>')
    st.markdown(''.join(css), unsafe_allow_html=True)

    for start in range(0, len(SMT_DEFECT_DIMENSIONS), 3):
        columns = st.columns(3, gap="medium")
        for offset, slot in enumerate(columns):
            index = start + offset
            if index >= len(SMT_DEFECT_DIMENSIONS):
                break
            title, column, subtitle, accent = SMT_DEFECT_DIMENSIONS[index]
            with slot:
                with st.container(key=f"smt_dimension_{index}"):
                    scope = _smt_breakdown_scope(source, selections, excluded_column=column)
                    counts = (
                        scope.groupby(column)["_DefectKey"].nunique().sort_values(ascending=False, kind="stable")
                        if not scope.empty else None
                    )
                    maximum = max(int(counts.iloc[0]), 1) if counts is not None and not counts.empty else 1
                    selected = selections[column]
                    st.markdown(
                        f'<div class="smt-dimension-title">{escape(title)}</div>'
                        f'<div class="smt-dimension-subtitle">{escape(subtitle)} · unique NG PCBs per category</div>',
                        unsafe_allow_html=True,
                    )
                    ranked = counts.index.tolist() if counts is not None else []
                    if selected != "All" and selected not in ranked:
                        ranked.insert(0, selected)
                    with st.container(height=208, border=False, key=f"smt_dimension_list_{index}"):
                        if not ranked:
                            st.markdown('<div class="smt-dimension-empty">No defects match the other selections.</div>', unsafe_allow_html=True)
                        for rank, category in enumerate(ranked):
                            count = int(counts.get(category, 0)) if counts is not None else 0
                            width = max(3, round(count / maximum * 100)) if count else 0
                            item_key = f"smt_breakdown_item_{index}_{rank}"
                            with st.container(key=item_key):
                                st.button(
                                    f"{category}   ·   {count:,}", key=f"smt_breakdown_click_{index}_{rank}",
                                    on_click=_select_smt_breakdown_category, args=(column, category),
                                    use_container_width=True,
                                )
                                st.markdown(
                                    f'<div class="smt-dimension-track"><i style="width:{width}%;background:{accent}"></i></div>',
                                    unsafe_allow_html=True,
                                )
                            if category == selected:
                                st.markdown(
                                    f'<style>div[class*="st-key-{item_key}"] .stButton button{{background:{accent}18;'
                                    f'border-color:{accent};color:{accent};font-weight:800}}</style>',
                                    unsafe_allow_html=True,
                                )

    active = [
        f"{title}: {selections[column]}"
        for title, column, _, _ in SMT_DEFECT_DIMENSIONS if selections[column] != "All"
    ]
    if active:
        st.caption("Selected: " + " · ".join(active))
    return _smt_breakdown_scope(source, selections)


def _clear_assembly_breakdown_selections() -> None:
    for _, column, _, _ in ASSEMBLY_DEFECT_DIMENSIONS:
        st.session_state[f"assembly_breakdown_{column}"] = "All"


def _select_assembly_breakdown_category(column: str, category: str) -> None:
    key = f"assembly_breakdown_{column}"
    st.session_state[key] = "All" if st.session_state.get(key) == category else category


def render_assembly_defect_dimension_cards(confirmed):
    """Show the same clickable, scrolling breakdown for Assembly."""
    source = confirmed.copy()
    selections = {}
    for _, column, _, _ in ASSEMBLY_DEFECT_DIMENSIONS:
        if column not in source:
            source[column] = ""
        source[column] = source[column].fillna("").astype(str).str.strip()
        source[column] = source[column].replace({"": "Not specified", "nan": "Not specified"})
        selections[column] = st.session_state.get(f"assembly_breakdown_{column}", "All")

    css = ["""<style>
    .assembly-dimension-title{color:#102D5B;font-size:1.04rem;font-weight:800;line-height:1.25}
    .assembly-dimension-subtitle{color:#6680A6;font-size:.73rem;margin:5px 0 14px;min-height:29px}
    .assembly-dimension-track{height:5px;border-radius:6px;background:#EDF2F9;margin:0 8px 8px;overflow:hidden}
    .assembly-dimension-track i{display:block;height:100%;border-radius:6px}
    .assembly-dimension-empty{color:#6680A6;font-size:.75rem;margin-top:12px}
    div[class*="st-key-assembly_breakdown_item_"]{padding:0 3px}
    div[class*="st-key-assembly_breakdown_item_"] .stButton button{width:100%;min-height:32px;padding:4px 8px;justify-content:space-between;text-align:left;border:1px solid transparent;background:transparent;color:#17375F;font-size:.78rem;font-weight:600;box-shadow:none}
    div[class*="st-key-assembly_breakdown_item_"] .stButton button:hover{background:#F1F6FD;border-color:#CFDBEE}
    div[class*="st-key-assembly_breakdown_item_"] .stButton button p{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    div[class*="st-key-assembly_breakdown_clear"]{max-width:245px}
    div[class*="st-key-assembly_breakdown_clear"] button{min-height:40px;background:linear-gradient(135deg,#2F80ED,#1D5FBF)!important;border:1px solid #4B8DEF!important;border-radius:.55rem!important;color:#F8FBFF!important;font-weight:750}
    div[class*="st-key-assembly_breakdown_clear"] button p{color:#F8FBFF!important}
    """]
    for index, (_, _, _, accent) in enumerate(ASSEMBLY_DEFECT_DIMENSIONS):
        css.append(
            f'div[class*="st-key-assembly_dimension_{index}"]{{background:#fff;'
            f'border:1px solid #CFDBEE;border-top:3px solid {accent};border-radius:13px;'
            'padding:16px 17px 12px;min-height:332px;box-shadow:0 2px 7px rgba(19,48,91,.04)}',
        )
    css.append('</style>')
    st.markdown(''.join(css), unsafe_allow_html=True)
    for start in range(0, len(ASSEMBLY_DEFECT_DIMENSIONS), 3):
        slots = st.columns(3, gap="medium")
        for offset, slot in enumerate(slots):
            index = start + offset
            if index >= len(ASSEMBLY_DEFECT_DIMENSIONS):
                break
            title, column, subtitle, accent = ASSEMBLY_DEFECT_DIMENSIONS[index]
            with slot:
                with st.container(key=f"assembly_dimension_{index}"):
                    scope = _smt_breakdown_scope(source, selections, excluded_column=column)
                    counts = (
                        scope.groupby(column)["_DefectKey"].nunique().sort_values(ascending=False, kind="stable")
                        if not scope.empty else None
                    )
                    maximum = max(int(counts.iloc[0]), 1) if counts is not None and not counts.empty else 1
                    selected = selections[column]
                    st.markdown(
                        f'<div class="assembly-dimension-title">{escape(title)}</div>'
                        f'<div class="assembly-dimension-subtitle">{escape(subtitle)} · unique NG PCBs per category</div>',
                        unsafe_allow_html=True,
                    )
                    ranked = counts.index.tolist() if counts is not None else []
                    if selected != "All" and selected not in ranked:
                        ranked.insert(0, selected)
                    with st.container(height=208, border=False, key=f"assembly_dimension_list_{index}"):
                        if not ranked:
                            st.markdown('<div class="assembly-dimension-empty">No defects match the other selections.</div>', unsafe_allow_html=True)
                        for rank, category in enumerate(ranked):
                            count = int(counts.get(category, 0)) if counts is not None else 0
                            width = max(3, round(count / maximum * 100)) if count else 0
                            item_key = f"assembly_breakdown_item_{index}_{rank}"
                            with st.container(key=item_key):
                                st.button(
                                    f"{category}   ·   {count:,}", key=f"assembly_breakdown_click_{index}_{rank}",
                                    on_click=_select_assembly_breakdown_category, args=(column, category),
                                    use_container_width=True,
                                )
                                st.markdown(
                                    f'<div class="assembly-dimension-track"><i style="width:{width}%;background:{accent}"></i></div>',
                                    unsafe_allow_html=True,
                                )
                            if category == selected:
                                st.markdown(
                                    f'<style>div[class*="st-key-{item_key}"] .stButton button{{background:{accent}18;'
                                    f'border-color:{accent};color:{accent};font-weight:800}}</style>',
                                    unsafe_allow_html=True,
                                )
    active = [f"{title}: {selections[column]}" for title, column, _, _ in ASSEMBLY_DEFECT_DIMENSIONS if selections[column] != "All"]
    if active:
        st.caption("Selected: " + " · ".join(active))
    return _smt_breakdown_scope(source, selections)


def _render_smt_model_comparison(
    model_a: str,
    model_b: str,
    view_a: dict,
    view_b: dict,
    history_a: dict,
    history_b: dict,
    history_start: date,
    end_date: date,
    color: str,
) -> None:
    import pandas as pd
    from tools import dashboard_charts
    from tools.recurrence_watchlist import build_recurrence_watchlist

    target_directory = {item["source"]: item for item in configured_kpi_directory()}
    function_target = target_directory["smt_function"]["target"]
    process_target = target_directory["smt_process"]["target"]
    recurrence_a = build_recurrence_watchlist(history_a["confirmed"], history_start, end_date)
    recurrence_b = build_recurrence_watchlist(history_b["confirmed"], history_start, end_date)

    def pass_rate(view: dict, defect_key: str) -> float | None:
        produced = view["produced"]
        defects = view[defect_key]
        return 1 - defects / produced if produced and defects <= produced else None

    def metric_specs(view: dict, recurrence: dict) -> list[tuple[str, object, str, str]]:
        return [
            ("SMT input", view["produced"], "count", "—"),
            ("Defect PCB", view["confirmed_pcbs"], "count", "Lower is better"),
            ("Overall defect PPM", view["overall_ppm"], "ppm", "Lower is better"),
            ("Functional Pass Rate", pass_rate(view, "functional_pcbs"), "rate", f"Target {function_target:.2%}"),
            ("Appearance Pass Rate", pass_rate(view, "appearance_pcbs"), "rate", "Higher is better"),
            ("SMT Process NG Rate", view["process_ppm"], "ppm", f"Target ≤ {fmt_ppm(process_target)} PPM"),
            ("Recurring defect causes", recurrence["summary"]["recurring_issues"], "count", "Present in 2+ weeks"),
            ("Repeated PCBs", int(view["repeat_detail"]["_DefectKey"].nunique()), "count", "Multiple confirmed records"),
        ]

    specs_a = metric_specs(view_a, recurrence_a)
    specs_b = metric_specs(view_b, recurrence_b)

    def formatted(value, kind: str) -> str:
        if value is None or pd.isna(value):
            return "N/A"
        if kind == "rate":
            return fmt_kpi_pct(float(value))
        if kind == "ppm":
            return f"{fmt_ppm(float(value))} PPM"
        return fmt_int(value)

    rows = []
    for (label, value_a, kind, target), (_, value_b, _, _) in zip(specs_a, specs_b):
        if value_a is None or value_b is None or pd.isna(value_a) or pd.isna(value_b):
            delta = "N/A"
        elif kind == "rate":
            delta = f"{(float(value_a) - float(value_b)) * 100:+.2f} pp"
        elif kind == "ppm":
            delta = f"{float(value_a) - float(value_b):+,.0f} PPM"
        else:
            delta = f"{int(value_a) - int(value_b):+,.0f}"

        if label == "Functional Pass Rate" and value_a is not None and value_b is not None:
            good_a, good_b = value_a >= function_target, value_b >= function_target
            status = "Both on target" if good_a and good_b else "Both below" if not good_a and not good_b else f"{model_a} on target" if good_a else f"{model_b} on target"
        elif label == "SMT Process NG Rate" and value_a is not None and value_b is not None:
            good_a, good_b = value_a <= process_target, value_b <= process_target
            status = "Both on target" if good_a and good_b else "Both above" if not good_a and not good_b else f"{model_a} on target" if good_a else f"{model_b} on target"
        elif kind == "rate":
            status = "Higher is better"
        elif label in {"Defect PCB", "Overall defect PPM", "Recurring defect causes", "Repeated PCBs"}:
            status = f"{model_a} lower" if value_a < value_b else f"{model_b} lower" if value_b < value_a else "Equal"
        else:
            status = "Same scope"
        rows.append(
            {
                "KPI": label,
                "Target / guide": target,
                model_a: formatted(value_a, kind),
                model_b: formatted(value_b, kind),
                "Δ A − B": delta,
                "Status": status,
            }
        )

    primary_labels = {
        "Functional Pass Rate", "SMT Process NG Rate", "Appearance Pass Rate", "Repeated PCBs"
    }
    primary_rows = [row for row in rows if row["KPI"] in primary_labels]
    primary_rows.sort(key=lambda row: [
        "Functional Pass Rate", "SMT Process NG Rate", "Appearance Pass Rate", "Repeated PCBs"
    ].index(row["KPI"]))

    def table_markup(headers: list[str], values: list[list[str]], *, emph_first: bool = True) -> str:
        head = "".join(f"<th>{escape(str(value))}</th>" for value in headers)
        body = "".join(
            "<tr>" + "".join(
                f'<td class="{"strong" if emph_first and index == 0 else ""}">{value}</td>'
                for index, value in enumerate(line)
            ) + "</tr>"
            for line in values
        )
        return f'<table class="smt-compare-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

    kpi_values = []
    for row in primary_rows:
        status = row["Status"]
        status_class = "good" if "on target" in status.lower() or "lower" in status.lower() else "alert" if "below" in status.lower() or "above" in status.lower() else "neutral"
        delta = row["Δ A − B"]
        delta_class = "positive" if delta.startswith("+") else "negative" if delta.startswith("−") or delta.startswith("-") else ""
        kpi_values.append([
            escape(row["KPI"].replace("Repeated PCBs", "Repeated defect boards")),
            escape(row["Target / guide"]),
            f'<strong>{escape(row[model_a])}</strong>',
            f'<strong>{escape(row[model_b])}</strong>',
            f'<strong class="{delta_class}">{escape(delta)}</strong>',
            f'<span class="smt-compare-pill {status_class}">{escape(status)}</span>',
        ])
    st.markdown(
        '<div class="smt-compare-card smt-compare-kpi-card">'
        '<h3>KPI comparison</h3><p>Rates show percentage-point difference; defect rates show PPM difference.</p>'
        + table_markup(["KPI", "TARGET / GUIDE", model_a, model_b, "DELTA A − B", "STATUS"], kpi_values)
        + '</div>', unsafe_allow_html=True,
    )

    issues_a = smt_dashboard_issue_pareto(view_a["confirmed"]).rename(columns={"NGPCBs": model_a})
    issues_b = smt_dashboard_issue_pareto(view_b["confirmed"]).rename(columns={"NGPCBs": model_b})
    issue_comparison = issues_a.merge(issues_b, on="TopIssue", how="outer").fillna(0)
    if issue_comparison.empty:
        issue_comparison = pd.DataFrame(columns=["TopIssue", model_a, model_b, "Δ A − B"])
    else:
        issue_comparison[[model_a, model_b]] = issue_comparison[[model_a, model_b]].astype(int)
        issue_comparison["Δ A − B"] = issue_comparison[model_a] - issue_comparison[model_b]
        issue_comparison = issue_comparison.sort_values(
            [model_a, model_b, "TopIssue"], ascending=[False, False, True]
        ).head(10)
        issue_comparison["Δ A − B"] = issue_comparison["Δ A − B"].map(lambda value: f"{value:+,}")
    from tools.smart_report_rules import top_issue_reasons
    phenomenon_map = {}
    for frame in (view_a["confirmed"], view_b["confirmed"]):
        if not frame.empty:
            frame = frame.copy()
            frame["TopIssue"] = top_issue_reasons(frame)
            dominant = (
                frame.groupby(["TopIssue", "Phenomenon"], dropna=False).size()
                .reset_index(name="Count").sort_values(["TopIssue", "Count"], ascending=[True, False])
                .drop_duplicates("TopIssue")
            )
            for issue, phenomenon in dominant[["TopIssue", "Phenomenon"]].itertuples(index=False, name=None):
                phenomenon_map.setdefault(issue, phenomenon)

    trend_a = view_a["trend"][["PeriodDate", "Period", "ConfirmedDefectPCBs"]].rename(columns={"ConfirmedDefectPCBs": "ModelA_NG"})
    trend_b = view_b["trend"][["PeriodDate", "ConfirmedDefectPCBs"]].rename(columns={"ConfirmedDefectPCBs": "ModelB_NG"})
    trend = trend_a.merge(trend_b, on="PeriodDate", how="outer").sort_values("PeriodDate")

    left, right = st.columns([1.45, 0.8], gap="medium")
    with left:
        cause_values = []
        for row in issue_comparison.head(3).itertuples(index=False):
            cause, count_a, count_b, delta = row[0], row[1], row[2], row[3]
            cause_values.append([
                escape(str(cause)), escape(str(phenomenon_map.get(cause, "—"))),
                f"<strong>{int(count_a):,}</strong>", f"<strong>{int(count_b):,}</strong>",
                escape(str(delta)),
            ])
        if not cause_values:
            cause_values = [["No confirmed defects", "—", "—", "—", "—"]]
        st.markdown(
            '<div class="smt-compare-card smt-compare-bottom-card">'
            '<h3>Defect causes · item-by-item</h3>'
            '<p>Primary grouping: RepaireRemark · fallback: Fault Phenomenon</p>'
            + table_markup(["REPAIR REMARK / CAUSE", "PHENOMENON", model_a, model_b, "Δ BOARDS"], cause_values)
            + '<span class="smt-compare-hint">Select a cause below for station, DutyType and PCB detail</span>'
            + '</div>', unsafe_allow_html=True,
        )
    with right:
        with st.container(key="smt_compare_trend_card"):
            grain = requested_trend_grain(history_start, end_date)
            st.markdown(
                f'<h3>{"Weekly" if grain == "week" else "Defect"} defect trend</h3>'
                '<p>Confirmed defect boards · same date buckets</p>', unsafe_allow_html=True,
            )
            if trend.empty:
                st.info("No comparable trend data is available for these models.")
            else:
                import plotly.graph_objects as go
                figure = go.Figure()
                for column, name, line_color in (("ModelA_NG", model_a, "#2879DF"), ("ModelB_NG", model_b, "#6532C8")):
                    figure.add_trace(go.Scatter(
                        x=trend["Period"], y=trend[column], mode="lines+markers",
                        name=name, line=dict(color=line_color, width=2), marker=dict(size=6),
                        connectgaps=False,
                    ))
                figure.update_layout(
                    height=220, margin=dict(l=8, r=8, t=10, b=15),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11, color="#6380A6"),
                    legend=dict(orientation="h", y=-0.22, x=0),
                    xaxis=dict(title=None, showgrid=False, linecolor="#C7D4E7"),
                    yaxis=dict(title=None, rangemode="tozero", gridcolor="#E8EEF7", zeroline=False),
                )
                st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})

    with st.expander("More comparison metrics and defect details"):
        styled_table(pd.DataFrame([row for row in rows if row["KPI"] not in primary_labels]), table_class="compact-dashboard-table")
        if not issue_comparison.empty:
            styled_table(issue_comparison.rename(columns={"TopIssue": "Repair conclusion / cause"}), max_rows=10, table_class="compact-dashboard-table")


def smt_model_comparison_page(color: str) -> None:
    """Compare two or three SMT models over one period and the same defect dimensions."""
    import pandas as pd
    from tools import smt_quality_dashboard
    from tools.smt_model_comparison import build_comparison_workbook, build_dimension_rows, defect_ppm

    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>SMT · Model Comparison</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Compare two or three models over the same period, KPI by KPI and defect category by defect category.")
    input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
    if not input_paths or not defect_paths:
        st.warning("SMT data is incomplete. Open Data Upload to add the required files.")
        return
    input_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in input_paths)
    defect_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths)
    minimum_date, maximum_date = smt_quality_dashboard.input_bounds(input_signatures)
    start_date, end_date = analysis_period_control(
        "smt_compare_period", minimum_date.date(), maximum_date.date(),
        default_start=minimum_date.date(), default_end=maximum_date.date(), show_presets=False,
    )
    try:
        analysis = smt_quality_dashboard.analyze_smt_quality_paths(
            input_signatures, defect_signatures, start_date.isoformat(), end_date.isoformat(),
            smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
        )
    except Exception as exc:
        st.error(f"Unable to calculate the SMT comparison: {exc}")
        return

    model_options = sorted(set(analysis["selected_input"]["Model"].dropna().astype(str)))
    if len(model_options) < 2:
        st.info("At least two models with input in the selected period are needed for comparison.")
        return
    st.markdown(
        """<style>
        div[class*="st-key-smt_compare_model_"] [data-baseweb="select"] > div,
        div[class*="st-key-smt_compare_model_"] [data-testid="stSelectbox"] > div > div {
            background:linear-gradient(135deg,#2F80ED 0%,#1D5FBF 100%) !important;
            border-color:#4B8DEF !important;color:#F8FBFF !important;
        }
        div[class*="st-key-smt_compare_model_"] [data-baseweb="select"] * {color:#F8FBFF !important;}
        div[class*="st-key-smt_compare_run"] button {
            min-height:40px;background:linear-gradient(135deg,#2F80ED,#1D5FBF) !important;
            border:1px solid #4B8DEF !important;color:#fff !important;font-weight:800;
            box-shadow:0 4px 12px rgba(8,45,97,.18);
        }
        div[class*="st-key-smt_compare_run"] button p {color:#fff !important;}
        .smt-model-compare-table-wrap {max-height:410px;overflow:auto;border:1px solid #D6E2F1;border-radius:10px;margin:8px 0 18px;}
        .smt-model-compare-table-wrap.compare-kpi-wrap {max-height:none;overflow:visible;}
        .smt-model-compare-table-wrap.compare-kpi-wrap th {position:static;}
        .smt-model-compare-table {width:100%;border-collapse:collapse;table-layout:fixed;background:#fff;color:#17375F;font-size:.82rem;}
        .smt-model-compare-table th {position:sticky;top:0;z-index:1;padding:12px 13px;background:#EAF2FF;color:#0B2D5A;text-align:left;border-bottom:2px solid #A9C9EF;overflow-wrap:anywhere;}
        .smt-model-compare-table td {padding:10px 13px;border-bottom:1px solid #E6EDF7;vertical-align:top;overflow-wrap:anywhere;}
        .smt-model-compare-table tbody tr:nth-child(even) {background:#F7FAFE;}
        .smt-model-compare-table th:first-child,.smt-model-compare-table td:first-child {width:28%;font-weight:750;}
        .smt-model-compare-table small {display:block;margin-top:3px;color:#607A9F;font-size:.71rem;font-weight:500;}
        .smt-model-compare-table .compare-bad {color:#B91C1C;font-weight:800;}
        .smt-model-compare-table .compare-good {color:#087C4B;font-weight:800;}
        .smt-model-compare-table .compare-value {font-weight:800;}
        </style>""",
        unsafe_allow_html=True,
    )
    slots = st.columns([1, 1, 1, 0.72], gap="small", vertical_alignment="bottom")
    selected = []
    for index in range(3):
        with slots[index]:
            choice = st.selectbox(
                f"Model {index + 1}" + (" · optional" if index == 2 else ""),
                ["Select a model", *model_options], key=f"smt_compare_model_{index + 1}",
                persist_state="session",
            )
            if choice != "Select a model":
                selected.append(choice)
    valid_selection = len(selected) >= 2 and len(set(selected)) == len(selected)
    with slots[3]:
        compare_clicked = st.button(
            "Compare →", key="smt_compare_run", use_container_width=True,
            disabled=not valid_selection,
        )
    request = (tuple(selected), start_date, end_date)
    if compare_clicked:
        st.session_state["smt_compare_request"] = request
    if not valid_selection:
        st.info("Select two different models. A third model is optional.")
        return
    if st.session_state.get("smt_compare_request") != request:
        st.info("Click Compare to view the selected models over this period.")
        return

    views = {
        model: _build_smt_dashboard_view(analysis, model, "All", "All")
        for model in selected
    }
    models = list(views)
    targets = {item["source"]: item["target"] for item in configured_kpi_directory()}
    function_target = targets["smt_function"]
    process_target = targets["smt_process"]

    def table(headers: list[str], rows: list[tuple[str, list[str]]], *, scroll: bool = True) -> str:
        header = "".join(f"<th>{escape(value)}</th>" for value in headers)
        body = "".join(
            "<tr><td>" + label + "</td>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
            for label, cells in rows
        )
        wrap_class = "smt-model-compare-table-wrap" if scroll else "smt-model-compare-table-wrap compare-kpi-wrap"
        return (
            f'<div class="{wrap_class}"><table class="smt-model-compare-table">'
            f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"
        )

    def pass_rate(view: dict, defect_field: str) -> float | None:
        input_count = view["produced"]
        defect_count = view[defect_field]
        return 1 - defect_count / input_count if input_count > 0 and defect_count <= input_count else None

    def metric_cell(value: object, kind: str, target: float | None = None, lower_is_better: bool = False) -> str:
        if value is None or pd.isna(value):
            return "N/A"
        numeric = float(value)
        formatted = (
            fmt_kpi_pct(numeric) if kind == "rate" else
            f"{fmt_ppm(numeric)} PPM" if kind == "ppm" else fmt_int(int(numeric))
        )
        if target is None:
            return f'<span class="compare-value">{escape(formatted)}</span>'
        on_target = numeric <= target if lower_is_better else numeric >= target
        status = "On target" if on_target else "Off target"
        style = "compare-good" if on_target else "compare-bad"
        return f'<span class="{style}">{escape(formatted)}</span><small>{status}</small>'

    metric_specs = [
        ("SMT input", "produced", "count", None, False),
        ("Defect PCB", "confirmed_pcbs", "count", None, False),
        ("Overall defect PPM", "overall_ppm", "ppm", None, True),
        (f"Functional Pass Rate<small>Target {fmt_kpi_pct(function_target)}</small>", "functional_rate", "rate", function_target, False),
        ("Appearance Pass Rate", "appearance_rate", "rate", None, False),
        (f"SMT Process NG Rate<small>Target {fmt_ppm(process_target)} PPM</small>", "process_ppm", "ppm", process_target, True),
        ("Functional NG PCBs", "functional_pcbs", "count", None, False),
        ("Appearance NG PCBs", "appearance_pcbs", "count", None, False),
    ]
    metric_rows = []
    workbook_metrics = []
    for label, field, kind, target, lower_is_better in metric_specs:
        cells = []
        values = {}
        for model in models:
            view = views[model]
            value = (
                pass_rate(view, "functional_pcbs") if field == "functional_rate" else
                pass_rate(view, "appearance_pcbs") if field == "appearance_rate" else view[field]
            )
            values[model] = value
            cells.append(metric_cell(value, kind, target, lower_is_better))
        metric_rows.append((label, cells))
        workbook_metrics.append({
            "label": label.split("<small>", 1)[0], "kind": kind, "target": target,
            "lower_is_better": lower_is_better, "values": values,
        })
    top_detractors = []
    top_detractor_values = {}
    for model in models:
        issue_pareto = smt_dashboard_issue_pareto(views[model]["confirmed"])
        if issue_pareto.empty:
            top_detractors.append("—")
            top_detractor_values[model] = "—"
        else:
            first = issue_pareto.iloc[0]
            top_detractors.append(
                f'<span class="compare-value">{escape(str(first.TopIssue))}</span>'
                f'<small>{fmt_int(int(first.NGPCBs))} NG PCBs</small>'
            )
            top_detractor_values[model] = f"{first.TopIssue} · {int(first.NGPCBs)} NG PCBs"
    metric_rows.append(("Top detractor", top_detractors))
    workbook_metrics.append({
        "label": "Top detractor", "kind": "text", "target": None,
        "lower_is_better": False, "values": top_detractor_values,
    })
    st.markdown("### KPI comparison")
    st.markdown(table(["KPI", *models], metric_rows, scroll=False), unsafe_allow_html=True)

    st.markdown("### Defect breakdown comparison")
    st.caption("Each category shows unique NG PCBs and PPM based on that model's input. A PCB can appear in multiple categories.")
    workbook_dimensions = []
    for index, (title, column, _, _) in enumerate(SMT_DEFECT_DIMENSIONS):
        rows = build_dimension_rows(views, column)
        workbook_dimensions.append((title, rows))
        with st.expander(f"{title} · {len(rows)} categories", expanded=index < 2):
            if not rows:
                st.info("No confirmed defects for these models in the selected period.")
                continue
            display_rows = []
            for row in rows:
                cells = []
                for model in models:
                    count = row["counts"][model]
                    ppm = defect_ppm(count, views[model]["produced"])
                    cells.append(
                        f'<span class="compare-value">{fmt_int(count)} PCBs</span>'
                        f'<small>{fmt_ppm(ppm) if ppm is not None else "N/A"} PPM</small>'
                    )
                display_rows.append((escape(row["category"]), cells))
            st.markdown(table([title, *models], display_rows), unsafe_allow_html=True)
    workbook_bytes = build_comparison_workbook(
        models, start_date, end_date, workbook_metrics, workbook_dimensions,
        {model: views[model]["produced"] for model in models},
    )
    st.download_button(
        "Download formatted Excel report", data=workbook_bytes,
        file_name=f"smt_model_comparison_{start_date:%Y-%m-%d}_{end_date:%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="smt_compare_download",
    )


def smt_quality_dashboard_v2(color: str) -> None:
    from tools import smt_quality_dashboard

    page_started = perf_counter()
    source_started = perf_counter()
    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>SMT · Quality Dashboard</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Analyze confirmed SMT defects by failure class, station, symptom, cause, repair conclusion and responsibility.")
    input_paths, defect_paths = smt_quality_dashboard.stored_smt_sources()
    source_seconds = perf_counter() - source_started
    if not input_paths or not defect_paths:
        st.warning("Os dados de SMT estão incompletos. Abra a aba Data Upload para carregar os arquivos necessários.")
        return

    input_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in input_paths)
    defect_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in defect_paths)
    minimum_date, maximum_date = smt_quality_dashboard.input_bounds(input_signatures)
    filter_panel = st.container(key="smt_quality_v2_filter_panel")
    with filter_panel:
        period_column, model_column, failure_column, duty_column, station_column = st.columns(
            [1.35, 1.15, 0.85, 0.75, 1.0], gap="small"
        )
        with period_column:
            start_date, end_date = analysis_period_control(
                "smt_quality_v2_period", minimum_date.date(), maximum_date.date(),
                default_start=minimum_date.date(), default_end=maximum_date.date(),
                show_presets=False,
            )

    analysis_started = perf_counter()
    try:
        analysis = smt_quality_dashboard.analyze_smt_quality_paths(
            input_signatures,
            defect_signatures,
            start_date.isoformat(),
            end_date.isoformat(),
            smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
        )
    except Exception as exc:
        st.error(f"Unable to calculate the SMT dashboard: {exc}")
        return
    analysis = {
        **analysis,
        "trend": smt_quality_dashboard.refresh_chart_period_labels(analysis["trend"]),
    }
    analysis_seconds = perf_counter() - analysis_started
    raw = analysis["raw"]
    model_options = sorted(set(analysis["selected_input"]["Model"].dropna().astype(str)))
    station_options = ["All", *sorted(set(raw["Operation"].dropna().astype(str)))]
    failure_options = ["All", "Functional Failure", "Appearance Failure", "Unclassified"]
    duty_options = ["All", *sorted(set(raw["DutyType"].dropna().astype(str)))]
    with filter_panel:
        with model_column:
            selected_models = st.multiselect(
                "Model",
                model_options,
                key="smt_quality_v2_models",
                persist_state="session",
                placeholder="All models",
                help="Select one or more models. With no selection, all models are included.",
            )
        with failure_column:
            failure_type = st.selectbox("Failure type", failure_options, key="smt_quality_v2_failure_type", persist_state="session")
        with duty_column:
            duty_type = st.selectbox("DutyType", duty_options, key="smt_quality_v2_duty_type", persist_state="session")
        with station_column:
            station = st.selectbox("Process / Station", station_options, key="smt_quality_v2_station", persist_state="session")

    model_filter = selected_models or "All"
    view = _build_smt_dashboard_view(analysis, model_filter, station, failure_type, duty_type)
    issue_pareto = smt_dashboard_issue_pareto(view["confirmed"])
    top_issue = issue_pareto.iloc[0] if not issue_pareto.empty else None

    cards = st.columns(4)
    with cards[0]:
        smt_kpi_card("SMT input", fmt_int(view["produced"]), "Boards in the selected scope", color)
    with cards[1]:
        smt_kpi_card("Defect PCB", fmt_int(view["confirmed_pcbs"]), "Confirmed general defects", color)
    with cards[2]:
        smt_kpi_card(
            "Overall defect PPM",
            fmt_ppm(view["overall_ppm"]) if view["overall_ppm"] is not None else "N/A",
            "All confirmed defect PCBs",
            color,
        )
    with cards[3]:
        smt_kpi_card(
            "Top detractor",
            f"{fmt_int(top_issue.NGPCBs)} PCBs" if top_issue is not None else "—",
            str(top_issue.TopIssue) if top_issue is not None else "No confirmed defects",
            color,
        )

    st.markdown("### Defect breakdown")
    st.markdown(
        """<style>
        div[class*="st-key-smt_breakdown_clear"] {max-width:245px;}
        div[class*="st-key-smt_breakdown_clear"] button {
            min-height:40px;
            background:linear-gradient(135deg,#2F80ED 0%,#1D5FBF 100%) !important;
            border:1px solid #4B8DEF !important;
            border-radius:.55rem !important;
            box-shadow:0 4px 12px rgba(8,45,97,.18);
            color:#F8FBFF !important;
        }
        div[class*="st-key-smt_breakdown_clear"] button p {color:#F8FBFF !important;font-weight:750;}
        div[class*="st-key-smt_breakdown_clear"] button:hover {
            border-color:#93C5FD !important;
            box-shadow:0 5px 14px rgba(37,99,235,.28);
        }
        </style>""",
        unsafe_allow_html=True,
    )
    st.button(
        "Clear breakdown selections", key="smt_breakdown_clear",
        on_click=_clear_smt_breakdown_selections,
        use_container_width=True,
    )
    breakdown_detail = render_smt_defect_dimension_cards(view["confirmed"])

    active_breakdown = any(
        st.session_state.get(f"smt_breakdown_{column}", "All") != "All"
        for _, column, _, _ in SMT_DEFECT_DIMENSIONS
    )
    if active_breakdown:
        st.markdown("### Matching PCB details")
        unique_boards = breakdown_detail["_DefectKey"].nunique() if not breakdown_detail.empty else 0
        st.caption(
            f"{fmt_int(unique_boards)} unique NG PCBs · {fmt_int(len(breakdown_detail))} confirmed records "
            "match the selected breakdown categories."
        )
        detail_columns = [
            "PCB", "Model", "KPIDate", "Operation", "FailureType", "Phenomenon",
            "FaultReason", "Location", "RepairRemark", "DutyType", "ItemCode",
        ]
        details = breakdown_detail[
            [column for column in detail_columns if column in breakdown_detail.columns]
        ].copy()
        if details.empty:
            st.info("No confirmed defects match this combination. Clear a selection to broaden the view.")
        else:
            st.dataframe(details, hide_index=True, width="stretch", height=310)
            st.download_button(
                "Download matching defect records",
                data=details.to_csv(index=False).encode("utf-8-sig"),
                file_name="smt_breakdown_selection.csv", mime="text/csv",
                width="stretch", key="smt_breakdown_download",
            )

    record_dashboard_performance(
        "SMT Quality Dashboard",
        start_date,
        end_date,
        source_seconds,
        analysis_seconds,
        perf_counter() - page_started,
        len(input_paths) + len(defect_paths),
    )


def _assembly_duty_category(value: object) -> str:
    text = " ".join(str(value or "").strip().split())
    compact = compact_text(text)
    if compact.startswith("smt"):
        return "SMT"
    if "mando" in compact or "man-do" in text.lower() or "man do" in text.lower():
        return "Mando"
    if "equipment" in compact:
        return "Equipment"
    if "process" in compact:
        return "Process"
    if not text or text.lower() in {"nan", "none", "null"}:
        return "Unknown"
    return "Assembly"


def _build_assembly_dashboard_view(
    analysis: dict,
    rules: dict,
    model: str,
    station: str,
    failure_type: str,
    duty_category: str,
) -> dict:
    import pandas as pd

    raw = analysis["raw"].copy()
    production_detail = analysis["production_detail"].copy()
    operation_column = "TestOperation"
    duty_column = rules["mando_column"]
    functional_operations = {
        str(value).strip()
        for value in rules.get("assembly_functional_operations", [])
        if str(value).strip()
    }
    appearance_operations = {
        str(value).strip()
        for value in rules.get("assembly_appearance_operations", [])
        if str(value).strip()
    }
    raw["FailureType"] = "Unclassified"
    raw.loc[raw[operation_column].isin(functional_operations), "FailureType"] = "Functional Failure"
    raw.loc[raw[operation_column].isin(appearance_operations), "FailureType"] = "Appearance Failure"
    raw["DutyCategory"] = raw[duty_column].map(_assembly_duty_category)

    if model != "All":
        raw = raw[raw["Model"].eq(model)].copy()
        production_detail = production_detail[production_detail["Model"].eq(model)].copy()
    if station != "All":
        raw = raw[raw[operation_column].eq(station)].copy()
    if failure_type != "All":
        raw = raw[raw["FailureType"].eq(failure_type)].copy()
    if duty_category != "All":
        raw = raw[raw["DutyCategory"].eq(duty_category)].copy()

    raw["_DefectKey"] = _dashboard_defect_key(raw)
    confirmed = raw[raw["ConfirmedDefect"].fillna(False).astype(bool)].copy()
    rejudge = raw[raw["IsRejudgeOK"].fillna(False).astype(bool)].copy()
    functional = confirmed[confirmed["FailureType"].eq("Functional Failure")].copy()
    appearance = confirmed[confirmed["FailureType"].eq("Appearance Failure")].copy()
    functional_mando = confirmed[
        confirmed.get("IsFunctionMando", False).fillna(False).astype(bool)
    ].copy()
    smt_origin = confirmed[
        confirmed.get("IsSMTDuty", False).fillna(False).astype(bool)
    ].copy()
    produced = int(production_detail["Produced"].sum())

    def unique_count(frame) -> int:
        return int(frame["_DefectKey"].nunique()) if not frame.empty else 0

    confirmed_pcbs = unique_count(confirmed)
    functional_pcbs = unique_count(functional)
    appearance_pcbs = unique_count(appearance)
    mando_pcbs = unique_count(functional_mando)
    smt_pcbs = unique_count(smt_origin)

    settings = analysis["trend_settings"]
    production_for_trend = (
        distribute_production_to_days(production_detail)
        if settings.get("input_distributed")
        else production_detail
    )
    production_period = add_trend_period(
        production_for_trend, "ProductionStart", settings
    )
    production_trend = (
        production_period.groupby("PeriodDate", as_index=False).agg(Input=("Produced", "sum"))
        if not production_period.empty
        else pd.DataFrame(columns=["PeriodDate", "Input"])
    )

    def period_count(frame, column_name: str):
        if frame.empty:
            return pd.DataFrame(columns=["PeriodDate", column_name])
        period_frame = add_trend_period(frame, "_Date", settings)
        return period_frame.groupby("PeriodDate", as_index=False).agg(
            **{column_name: ("_DefectKey", "nunique")}
        )

    trend = production_trend.copy()
    for frame, column in [
        (confirmed, "ConfirmedPCBs"),
        (functional, "FunctionalPCBs"),
        (appearance, "AppearancePCBs"),
        (functional_mando, "MandoPCBs"),
        (smt_origin, "SMTOriginPCBs"),
    ]:
        trend = trend.merge(period_count(frame, column), on="PeriodDate", how="outer")
    if trend.empty:
        trend = pd.DataFrame(
            columns=[
                "PeriodDate", "Period", "Input", "ConfirmedPCBs", "FunctionalPCBs",
                "AppearancePCBs", "MandoPCBs", "SMTOriginPCBs", "ConfirmedPPM",
                "FunctionalPPM", "AppearancePPM", "MandoPPM", "SMTOriginPPM", "Status",
            ]
        )
    else:
        count_columns = [
            "Input", "ConfirmedPCBs", "FunctionalPCBs", "AppearancePCBs",
            "MandoPCBs", "SMTOriginPCBs",
        ]
        trend[count_columns] = trend[count_columns].fillna(0).astype(int)
        trend = trend.sort_values("PeriodDate")
        trend["Period"] = trend["PeriodDate"].map(
            lambda value: format_trend_period(value, settings["grain"])
        )
        for count_column, ppm_column in [
            ("ConfirmedPCBs", "ConfirmedPPM"),
            ("FunctionalPCBs", "FunctionalPPM"),
            ("AppearancePCBs", "AppearancePPM"),
            ("MandoPCBs", "MandoPPM"),
            ("SMTOriginPCBs", "SMTOriginPPM"),
        ]:
            trend[ppm_column] = (
                trend[count_column] / trend["Input"].replace(0, pd.NA) * 1_000_000
            )
            trend.loc[trend[count_column] > trend["Input"], ppm_column] = pd.NA
        trend["Status"] = "Valid"
        trend.loc[trend["ConfirmedPCBs"] > trend["Input"], "Status"] = (
            "Blocked: confirmed NG PCB exceeds input"
        )
        # The confirmed, functional, appearance and Mando series share the
        # full Assembly defect denominator. SMT-origin PPM is a separate KPI
        # and remains valid when its own defect count fits the daily input.
        blocked = trend["Status"].ne("Valid")
        for ppm_column in ("ConfirmedPPM", "FunctionalPPM", "AppearancePPM", "MandoPPM"):
            trend.loc[blocked, ppm_column] = pd.NA
        trend["FunctionalStatus"] = trend["Status"]
        trend["AppearanceStatus"] = trend["Status"]
        trend["MandoStatus"] = trend["Status"]
        trend["SMTOriginStatus"] = "Valid"
        trend.loc[trend["SMTOriginPCBs"] > trend["Input"], "SMTOriginStatus"] = (
            "Blocked: SMT-origin NG PCB exceeds input"
        )
        trend["PPMChartStatus"] = trend["Status"]
        trend["PPMChartDefects"] = trend["ConfirmedPCBs"]

    input_by_model = (
        production_detail.groupby("Model", as_index=False).agg(Input=("Produced", "sum"))
        if not production_detail.empty
        else pd.DataFrame(columns=["Model", "Input"])
    )
    defects_by_model = (
        confirmed.groupby("Model", as_index=False).agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(columns=["Model", "NGPCBs"])
    )
    models = input_by_model.merge(defects_by_model, on="Model", how="left").fillna(0)
    models["PPM"] = models["NGPCBs"] / models["Input"].replace(0, pd.NA) * 1_000_000

    pareto = (
        confirmed.groupby("Phenomenon", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["Phenomenon", "NGPCBs"])
    )
    duty_summary = (
        confirmed.groupby("DutyCategory", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["DutyCategory", "NGPCBs"])
    )
    duty_summary["PPM"] = (
        duty_summary["NGPCBs"] / max(produced, 1) * 1_000_000
    )
    line_summary = (
        confirmed.groupby("Line", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not confirmed.empty
        else pd.DataFrame(columns=["Line", "NGPCBs"])
    )
    smt_pareto = (
        smt_origin.groupby("Phenomenon", as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        .sort_values("NGPCBs", ascending=False)
        if not smt_origin.empty
        else pd.DataFrame(columns=["Phenomenon", "NGPCBs"])
    )

    model_station = (
        confirmed.groupby(["Model", operation_column], as_index=False)
        .agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(columns=["Model", operation_column, "NGPCBs"])
    )
    if not model_station.empty:
        model_station = model_station.merge(input_by_model, on="Model", how="left")
        model_station["PPM"] = (
            model_station["NGPCBs"] / model_station["Input"].replace(0, pd.NA) * 1_000_000
        )
        top_models = model_station.groupby("Model")["NGPCBs"].sum().nlargest(6).index.tolist()
        top_stations = (
            model_station.groupby(operation_column)["NGPCBs"].sum().nlargest(7).index.tolist()
        )
        heatmap = (
            model_station[
                model_station["Model"].isin(top_models)
                & model_station[operation_column].isin(top_stations)
            ]
            .pivot_table(index="Model", columns=operation_column, values="PPM", aggfunc="sum", fill_value=0)
            .reindex(index=top_models, columns=top_stations, fill_value=0)
        )
    else:
        heatmap = pd.DataFrame()

    priority = (
        confirmed.groupby(
            ["Phenomenon", operation_column, "Model", duty_column, "DutyCategory"],
            as_index=False,
        ).agg(NGPCBs=("_DefectKey", "nunique"))
        if not confirmed.empty
        else pd.DataFrame(
            columns=["Phenomenon", operation_column, "Model", duty_column, "DutyCategory", "NGPCBs"]
        )
    )
    if not priority.empty:
        priority = priority.merge(input_by_model, on="Model", how="left")
        priority["ImpactPPM"] = priority["NGPCBs"] / priority["Input"].replace(0, pd.NA) * 1_000_000
        priority["Priority"] = priority["ImpactPPM"].map(_dashboard_priority)
        priority = priority.sort_values(
            ["ImpactPPM", "NGPCBs"], ascending=[False, False]
        ).head(8)

    classification_rate = (
        confirmed["FailureType"].ne("Unclassified").mean() if len(confirmed) else 1.0
    )
    input_stats = analysis.get("production_input_stats", {})
    exceptions = int(input_stats.get("selected_blocked_rows", input_stats.get("blocked_rows", 0)))
    exceptions += int(trend["Status"].ne("Valid").sum()) if not trend.empty else 0
    overall_valid = bool(produced and confirmed_pcbs <= produced)
    mando_valid = bool(produced and mando_pcbs <= produced)
    return {
        "raw": raw,
        "confirmed": confirmed,
        "rejudge": rejudge,
        "produced": produced,
        "confirmed_pcbs": confirmed_pcbs,
        "functional_pcbs": functional_pcbs,
        "appearance_pcbs": appearance_pcbs,
        "mando_pcbs": mando_pcbs,
        "smt_pcbs": smt_pcbs,
        "overall_ppm": confirmed_pcbs / produced * 1_000_000 if overall_valid else None,
        "mando_ppm": mando_pcbs / produced * 1_000_000 if mando_valid else None,
        "smt_ppm": smt_pcbs / produced * 1_000_000 if produced and smt_pcbs <= produced else None,
        "trend": trend,
        "models": models,
        "pareto": pareto,
        "duty_summary": duty_summary,
        "line_summary": line_summary,
        "smt_pareto": smt_pareto,
        "heatmap": heatmap,
        "priority": priority,
        "classification_rate": float(classification_rate),
        "unclassified_operations": sorted(
            set(raw[operation_column].dropna().astype(str))
            - functional_operations
            - appearance_operations
        ),
        "exceptions": exceptions,
    }


def _assembly_analysis_from_metrics(metrics: dict, start_date: date, end_date: date) -> tuple[dict, dict]:
    """Use the validated Assembly KPI records for dashboard and comparison alike."""
    import pandas as pd

    rules = load_rules().copy()
    rules["assembly_functional_operations"] = list(assembly_kpi_v2.FUNCTIONAL_OPERATIONS)
    rules["assembly_appearance_operations"] = list(assembly_kpi_v2.APPEARANCE_OPERATIONS)
    rules["mando_column"] = "DutyType"
    rules["date_start"] = start_date.isoformat()
    rules["date_end"] = end_date.isoformat()
    raw = metrics["defects"].copy()
    raw["TestOperation"] = raw["Operation"]
    raw["DutyType"] = raw["FinalDutyType"]
    raw["ConfirmedDefect"] = True
    raw["IsRejudgeOK"] = False
    raw["_Date"] = raw["DefectDate"]
    if "Line" not in raw:
        raw["Line"] = raw["TestLine"] if "TestLine" in raw else ""
    if "Maintenance" not in raw:
        raw["Maintenance"] = ""
    production_detail = metrics["inputs"].rename(
        columns={"Date": "ProductionStart", "Input": "Produced"}
    ).copy()
    production_detail["ProductionEnd"] = production_detail["ProductionStart"]
    analysis = {
        "raw": raw,
        "production_detail": production_detail,
        "trend_settings": trend_granularity(
            pd.Timestamp(start_date), pd.Timestamp(end_date), production_detail
        ),
        "defect_merge_stats": {"merged_updates": 0},
        "production_input_audit": pd.DataFrame(),
        "production_input_stats": {},
    }
    return analysis, rules


def assembly_model_comparison_page(color: str) -> None:
    """Compare Assembly models with the validated MES KPI rules and defect records."""
    import pandas as pd
    from tools.smt_model_comparison import build_comparison_workbook, build_dimension_rows, defect_ppm

    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>Assembly · Model Comparison</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Compare two or three models over the same period, KPI by KPI and defect category by defect category.")
    sources = stored_assembly_sources_v2()
    if not sources["input"] or not sources["defects"] or not sources["repair"]:
        st.warning("Assembly data is incomplete. Open Data Upload to add input, FPY defects and repair files.")
        return
    try:
        minimum_date, maximum_date = assembly_input_bounds(sources["input"])
        start_date, end_date = analysis_period_control(
            "assembly_compare_period", minimum_date, maximum_date,
            default_start=minimum_date, default_end=maximum_date, show_presets=False,
        )
        metrics = calculate_assembly_kpi_metrics(start_date, end_date)
        analysis, rules = _assembly_analysis_from_metrics(metrics, start_date, end_date)
    except Exception as exc:
        st.error(f"Unable to calculate the Assembly comparison: {exc}")
        return

    model_options = sorted(set(analysis["production_detail"]["Model"].dropna().astype(str)))
    if len(model_options) < 2:
        st.info("At least two models with input in the selected period are needed for comparison.")
        return
    st.markdown("""<style>
    div[class*="st-key-assembly_compare_model_"] [data-baseweb="select"] > div,
    div[class*="st-key-assembly_compare_model_"] [data-testid="stSelectbox"] > div > div {
        background:linear-gradient(135deg,#2F80ED,#1D5FBF)!important;border-color:#4B8DEF!important;color:#F8FBFF!important}
    div[class*="st-key-assembly_compare_model_"] [data-baseweb="select"] * {color:#F8FBFF!important}
    div[class*="st-key-assembly_compare_run"] button {min-height:40px;background:linear-gradient(135deg,#2F80ED,#1D5FBF)!important;border:1px solid #4B8DEF!important;color:#fff!important;font-weight:800}
    div[class*="st-key-assembly_compare_run"] button p {color:#fff!important}
    .assembly-compare-wrap {max-height:410px;overflow:auto;border:1px solid #D6E2F1;border-radius:10px;margin:8px 0 18px}
    .assembly-compare-wrap.kpi {max-height:none;overflow:visible}
    .assembly-compare-table {width:100%;border-collapse:collapse;table-layout:fixed;background:#fff;color:#17375F;font-size:.82rem}
    .assembly-compare-table th {position:sticky;top:0;z-index:1;padding:12px 13px;background:#EAF2FF;color:#0B2D5A;text-align:left;border-bottom:2px solid #A9C9EF;overflow-wrap:anywhere}
    .assembly-compare-wrap.kpi th {position:static}
    .assembly-compare-table td {padding:10px 13px;border-bottom:1px solid #E6EDF7;vertical-align:top;overflow-wrap:anywhere}
    .assembly-compare-table tbody tr:nth-child(even) {background:#F7FAFE}
    .assembly-compare-table th:first-child,.assembly-compare-table td:first-child {width:28%;font-weight:750}
    .assembly-compare-table small {display:block;margin-top:3px;color:#607A9F;font-size:.71rem;font-weight:500}
    .assembly-compare-table .bad {color:#B91C1C;font-weight:800}
    .assembly-compare-table .good {color:#087C4B;font-weight:800}
    .assembly-compare-table .value {font-weight:800}
    </style>""", unsafe_allow_html=True)
    slots = st.columns([1, 1, 1, .72], gap="small", vertical_alignment="bottom")
    selected = []
    for index in range(3):
        with slots[index]:
            choice = st.selectbox(
                f"Model {index + 1}" + (" · optional" if index == 2 else ""),
                ["Select a model", *model_options], key=f"assembly_compare_model_{index + 1}",
                persist_state="session",
            )
            if choice != "Select a model":
                selected.append(choice)
    valid = len(selected) >= 2 and len(set(selected)) == len(selected)
    with slots[3]:
        clicked = st.button("Compare →", key="assembly_compare_run", use_container_width=True, disabled=not valid)
    request = (tuple(selected), start_date, end_date)
    if clicked:
        st.session_state["assembly_compare_request"] = request
    if not valid:
        st.info("Select two different models. A third model is optional.")
        return
    if st.session_state.get("assembly_compare_request") != request:
        st.info("Click Compare to view the selected models over this period.")
        return

    views = {model: _build_assembly_dashboard_view(analysis, rules, model, "All", "All", "All") for model in selected}
    targets = {item["source"]: item["target"] for item in configured_kpi_directory()}

    def table(headers, rows, *, kpi=False):
        head = "".join(f"<th>{escape(value)}</th>" for value in headers)
        body = "".join(
            "<tr><td>" + label + "</td>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
            for label, cells in rows
        )
        return f'<div class="assembly-compare-wrap{" kpi" if kpi else ""}"><table class="assembly-compare-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    def pass_rate(view, field):
        produced, defects = view["produced"], view[field]
        return 1 - defects / produced if produced > 0 and defects <= produced else None

    def cell(value, kind, target=None, lower_is_better=False):
        if value is None or pd.isna(value):
            return "N/A"
        numeric = float(value)
        formatted = fmt_kpi_pct(numeric) if kind == "rate" else f"{fmt_ppm(numeric)} PPM" if kind == "ppm" else fmt_int(int(numeric))
        if target is None:
            return f'<span class="value">{escape(formatted)}</span>'
        on_target = numeric <= target if lower_is_better else numeric >= target
        return f'<span class="{"good" if on_target else "bad"}">{escape(formatted)}</span><small>{"On target" if on_target else "Off target"}</small>'

    specs = [
        ("Assembly input", "produced", "count", None, False),
        ("Defect PCB", "confirmed_pcbs", "count", None, False),
        ("Overall defect PPM", "overall_ppm", "ppm", None, True),
        ("Functional Pass Rate", "functional_rate", "rate", targets["assembly_function"], False),
        ("Appearance Pass Rate", "appearance_rate", "rate", targets["assembly_appearance"], False),
        ("Function Mando", "mando_ppm", "ppm", targets["assembly_mando"], True),
        ("Assembly SMT Process Duty NG Rate", "smt_ppm", "ppm", targets["smt_assembly_duty"], True),
        ("Functional NG PCBs", "functional_pcbs", "count", None, False),
        ("Appearance NG PCBs", "appearance_pcbs", "count", None, False),
        ("Function Mando NG PCBs", "mando_pcbs", "count", None, False),
        ("SMT-origin NG PCBs", "smt_pcbs", "count", None, False),
    ]
    metric_rows, workbook_metrics = [], []
    for label, field, kind, target, lower_is_better in specs:
        values = {
            model: (pass_rate(view, "functional_pcbs") if field == "functional_rate" else
                    pass_rate(view, "appearance_pcbs") if field == "appearance_rate" else view[field])
            for model, view in views.items()
        }
        display_label = escape(label)
        if target is not None:
            target_text = fmt_kpi_pct(target) if kind == "rate" else f"{fmt_ppm(target)} PPM"
            display_label += f"<small>Target {escape(target_text)}</small>"
        metric_rows.append((display_label, [cell(values[model], kind, target, lower_is_better) for model in selected]))
        workbook_metrics.append({
            "label": label, "kind": kind, "target": target,
            "lower_is_better": lower_is_better, "values": values,
        })
    top_values = {}
    top_cells = []
    for model, view in views.items():
        if view["pareto"].empty:
            top_values[model] = "—"
            top_cells.append("—")
        else:
            first = view["pareto"].iloc[0]
            top_values[model] = f"{first.Phenomenon} · {int(first.NGPCBs)} NG PCBs"
            top_cells.append(f'<span class="value">{escape(str(first.Phenomenon))}</span><small>{fmt_int(int(first.NGPCBs))} NG PCBs</small>')
    metric_rows.append(("Top detractor", top_cells))
    workbook_metrics.append({"label": "Top detractor", "kind": "text", "target": None, "lower_is_better": False, "values": top_values})
    st.markdown("### KPI comparison")
    st.markdown(table(["KPI", *selected], metric_rows, kpi=True), unsafe_allow_html=True)

    st.markdown("### Defect breakdown comparison")
    st.caption("Each category shows unique NG PCBs and PPM based on that model's input. A PCB can appear in multiple categories.")
    workbook_dimensions = []
    for index, (title, column, _, _) in enumerate(ASSEMBLY_DEFECT_DIMENSIONS):
        rows = build_dimension_rows(views, column)
        workbook_dimensions.append((title, rows))
        with st.expander(f"{title} · {len(rows)} categories", expanded=index < 2):
            if not rows:
                st.info("No confirmed defects for these models in the selected period.")
                continue
            display_rows = []
            for row in rows:
                cells = []
                for model in selected:
                    count = row["counts"][model]
                    ppm = defect_ppm(count, views[model]["produced"])
                    cells.append(f'<span class="value">{fmt_int(count)} PCBs</span><small>{fmt_ppm(ppm) if ppm is not None else "N/A"} PPM</small>')
                display_rows.append((escape(row["category"]), cells))
            st.markdown(table([title, *selected], display_rows), unsafe_allow_html=True)
    workbook_bytes = build_comparison_workbook(
        selected, start_date, end_date, workbook_metrics, workbook_dimensions,
        {model: views[model]["produced"] for model in selected}, area="Assembly",
    )
    st.download_button(
        "Download formatted Excel report", data=workbook_bytes,
        file_name=f"assembly_model_comparison_{start_date:%Y-%m-%d}_{end_date:%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="assembly_compare_download",
    )


def model_comparison_page(color: str) -> None:
    """Compare selected models across SMT and Assembly using one period."""
    import pandas as pd
    from tools import smt_quality_dashboard
    from tools.smt_model_comparison import build_comparison_workbook, build_dimension_rows, defect_ppm

    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>Model Comparison</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Select two or three models once to compare their SMT and Assembly quality over the same period.")
    smt_inputs, smt_defects = smt_quality_dashboard.stored_smt_sources()
    assembly_sources = stored_assembly_sources_v2()
    smt_ready = bool(smt_inputs and smt_defects)
    assembly_ready = all(assembly_sources[kind] for kind in ("input", "defects", "repair"))
    if not smt_ready and not assembly_ready:
        st.warning("Upload SMT and/or Assembly input and defect files before comparing models.")
        return

    bounds = []
    smt_input_signatures = smt_defect_signatures = ()
    try:
        if smt_ready:
            smt_input_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in smt_inputs)
            smt_defect_signatures = tuple(smt_quality_dashboard.path_signature(path) for path in smt_defects)
            lower, upper = smt_quality_dashboard.input_bounds(smt_input_signatures)
            bounds.append((lower.date(), upper.date()))
        if assembly_ready:
            bounds.append(assembly_input_bounds(assembly_sources["input"]))
    except Exception as exc:
        st.error(f"Unable to read model comparison input dates: {exc}")
        return
    start_date, end_date = analysis_period_control(
        "model_compare_period", min(lower for lower, _ in bounds), max(upper for _, upper in bounds),
        show_presets=False,
    )

    smt_analysis = assembly_analysis = assembly_rules = None
    if smt_ready:
        try:
            smt_analysis = smt_quality_dashboard.analyze_smt_quality_paths(
                smt_input_signatures, smt_defect_signatures, start_date.isoformat(), end_date.isoformat(),
                smt_quality_dashboard.SMT_FAILURE_RULE_VERSION,
            )
        except Exception as exc:
            st.warning(f"SMT data could not be calculated for this period: {exc}")
    else:
        st.info("SMT source files are incomplete; SMT rows will be unavailable until they are uploaded.")
    if assembly_ready:
        try:
            assembly_metrics = calculate_assembly_kpi_metrics(start_date, end_date)
            assembly_analysis, assembly_rules = _assembly_analysis_from_metrics(
                assembly_metrics, start_date, end_date
            )
        except Exception as exc:
            st.warning(f"Assembly data could not be calculated for this period: {exc}")
    else:
        st.info("Assembly source files are incomplete; Assembly rows will be unavailable until they are uploaded.")
    if smt_analysis is None and assembly_analysis is None:
        return

    model_options = set()
    if smt_analysis is not None:
        model_options.update(smt_analysis["selected_input"]["Model"].dropna().astype(str))
    if assembly_analysis is not None:
        model_options.update(assembly_analysis["production_detail"]["Model"].dropna().astype(str))
    model_options = sorted(model for model in model_options if model.strip())
    if len(model_options) < 2:
        st.info("At least two models with input in the selected period are needed for comparison.")
        return

    st.markdown("""<style>
    div[class*="st-key-model_compare_model_"] [data-baseweb="select"] > div,
    div[class*="st-key-model_compare_model_"] [data-testid="stSelectbox"] > div > div {
        background:linear-gradient(135deg,#2F80ED,#1D5FBF)!important;border-color:#4B8DEF!important;color:#F8FBFF!important}
    div[class*="st-key-model_compare_model_"] [data-baseweb="select"] * {color:#F8FBFF!important}
    div[class*="st-key-model_compare_run"] button {min-height:40px;background:linear-gradient(135deg,#2F80ED,#1D5FBF)!important;border:1px solid #4B8DEF!important;color:#fff!important;font-weight:800}
    div[class*="st-key-model_compare_run"] button p {color:#fff!important}
    .model-compare-wrap {max-height:410px;overflow:auto;border:1px solid #D6E2F1;border-radius:10px;margin:8px 0 18px}
    .model-compare-wrap.kpi {max-height:none;overflow:visible}
    .model-compare-table {width:100%;border-collapse:collapse;table-layout:fixed;background:#fff;color:#17375F;font-size:.82rem}
    .model-compare-table th {position:sticky;top:0;z-index:1;padding:12px 13px;background:#EAF2FF;color:#0B2D5A;text-align:left;border-bottom:2px solid #A9C9EF;overflow-wrap:anywhere}
    .model-compare-wrap.kpi th {position:static}
    .model-compare-table td {padding:10px 13px;border-bottom:1px solid #E6EDF7;vertical-align:top;overflow-wrap:anywhere}
    .model-compare-table tbody tr:nth-child(even) {background:#F7FAFE}
    .model-compare-table th:first-child,.model-compare-table td:first-child {width:28%;font-weight:750}
    .model-compare-table small {display:block;margin-top:3px;color:#607A9F;font-size:.71rem;font-weight:500}
    .model-compare-table .bad {color:#B91C1C;font-weight:800}
    .model-compare-table .good {color:#087C4B;font-weight:800}
    .model-compare-table .value {font-weight:800}
    </style>""", unsafe_allow_html=True)
    slots = st.columns([1, 1, 1, .72], gap="small", vertical_alignment="bottom")
    selected = []
    for index in range(3):
        with slots[index]:
            choice = st.selectbox(
                f"Model {index + 1}" + (" · optional" if index == 2 else ""),
                ["Select a model", *model_options], key=f"model_compare_model_{index + 1}",
                persist_state="session",
            )
            if choice != "Select a model":
                selected.append(choice)
    valid = len(selected) >= 2 and len(set(selected)) == len(selected)
    with slots[3]:
        clicked = st.button("Compare →", key="model_compare_run", use_container_width=True, disabled=not valid)
    request = (tuple(selected), start_date, end_date)
    if clicked:
        st.session_state["model_compare_request"] = request
    if not valid:
        st.info("Select two different models. A third model is optional.")
        return
    if st.session_state.get("model_compare_request") != request:
        st.info("Click Compare to view the selected models over this period.")
        return

    views = {}
    if smt_analysis is not None:
        views["SMT"] = {
            model: _build_smt_dashboard_view(smt_analysis, model, "All", "All") for model in selected
        }
    if assembly_analysis is not None:
        views["Assembly"] = {
            model: _build_assembly_dashboard_view(assembly_analysis, assembly_rules, model, "All", "All", "All")
            for model in selected
        }
    targets = {item["source"]: item["target"] for item in configured_kpi_directory()}

    def table(headers, rows, *, kpi=False):
        head = "".join(f"<th>{escape(value)}</th>" for value in headers)
        body = "".join(
            "<tr><td>" + label + "</td>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
            for label, cells in rows
        )
        return f'<div class="model-compare-wrap{" kpi" if kpi else ""}"><table class="model-compare-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    def metric_cell(value, kind, target=None, lower_is_better=False):
        if value is None or pd.isna(value):
            return "N/A"
        numeric = float(value)
        formatted = fmt_kpi_pct(numeric) if kind == "rate" else f"{fmt_ppm(numeric)} PPM" if kind == "ppm" else fmt_int(int(numeric))
        if target is None:
            return f'<span class="value">{escape(formatted)}</span>'
        on_target = numeric <= target if lower_is_better else numeric >= target
        return f'<span class="{"good" if on_target else "bad"}">{escape(formatted)}</span><small>{"On target" if on_target else "Off target"}</small>'

    specs = {
        "SMT": [
            ("SMT input", "produced", "count", None, False),
            ("Defect PCB", "confirmed_pcbs", "count", None, False),
            ("Overall defect PPM", "overall_ppm", "ppm", None, True),
            ("Functional Pass Rate", "functional_rate", "rate", targets["smt_function"], False),
            ("Appearance Pass Rate", "appearance_rate", "rate", None, False),
            ("SMT Process NG Rate", "process_ppm", "ppm", targets["smt_process"], True),
            ("Functional NG PCBs", "functional_pcbs", "count", None, False),
            ("Appearance NG PCBs", "appearance_pcbs", "count", None, False),
        ],
        "Assembly": [
            ("Assembly input", "produced", "count", None, False),
            ("Defect PCB", "confirmed_pcbs", "count", None, False),
            ("Overall defect PPM", "overall_ppm", "ppm", None, True),
            ("Functional Pass Rate", "functional_rate", "rate", targets["assembly_function"], False),
            ("Appearance Pass Rate", "appearance_rate", "rate", targets["assembly_appearance"], False),
            ("Function Mando", "mando_ppm", "ppm", targets["assembly_mando"], True),
            ("Assembly SMT Process Duty NG Rate", "smt_ppm", "ppm", targets["smt_assembly_duty"], True),
            ("Functional NG PCBs", "functional_pcbs", "count", None, False),
            ("Appearance NG PCBs", "appearance_pcbs", "count", None, False),
            ("Function Mando NG PCBs", "mando_pcbs", "count", None, False),
            ("SMT-origin NG PCBs", "smt_pcbs", "count", None, False),
        ],
    }
    workbook_metrics = []
    st.markdown("### KPI comparison")
    st.caption("SMT and Assembly use separate production inputs and targets. N/A means no input or an invalid rate for that model and area.")
    for area in ("SMT", "Assembly"):
        st.markdown(f"#### {area}")
        if area not in views:
            st.info(f"{area} source data is unavailable for this comparison.")
            continue
        metric_rows = []
        for label, field, kind, target, lower_is_better in specs[area]:
            values = {}
            for model, view in views[area].items():
                if view["produced"] <= 0:
                    value = None
                elif field == "functional_rate":
                    defects = view["functional_pcbs"]
                    value = 1 - defects / view["produced"] if defects <= view["produced"] else None
                elif field == "appearance_rate":
                    defects = view["appearance_pcbs"]
                    value = 1 - defects / view["produced"] if defects <= view["produced"] else None
                else:
                    value = view[field]
                values[model] = value
            display_label = escape(label)
            if target is not None:
                target_text = fmt_kpi_pct(target) if kind == "rate" else f"{fmt_ppm(target)} PPM"
                display_label += f"<small>Target {escape(target_text)}</small>"
            metric_rows.append((display_label, [metric_cell(values[model], kind, target, lower_is_better) for model in selected]))
            workbook_metrics.append({
                "label": f"{area} · {label}", "kind": kind, "target": target,
                "lower_is_better": lower_is_better, "values": values,
            })
        st.markdown(table(["KPI", *selected], metric_rows, kpi=True), unsafe_allow_html=True)

    st.markdown("### Defect breakdown comparison")
    st.caption("Counts are unique NG PCBs within each category. PPM always uses that model's input in the same area.")
    workbook_dimensions = []
    for area, dimensions in (("SMT", SMT_DEFECT_DIMENSIONS), ("Assembly", ASSEMBLY_DEFECT_DIMENSIONS)):
        st.markdown(f"#### {area}")
        if area not in views:
            st.info(f"{area} source data is unavailable for this comparison.")
            continue
        area_inputs = {model: views[area][model]["produced"] for model in selected}
        for index, (title, column, _, _) in enumerate(dimensions):
            rows = build_dimension_rows(views[area], column)
            workbook_dimensions.append((f"{area} · {title}", rows, area_inputs))
            with st.expander(f"{title} · {len(rows)} categories", expanded=index < 2):
                if not rows:
                    st.info("No confirmed defects for these models in the selected period.")
                    continue
                display_rows = []
                for row in rows:
                    cells = []
                    for model in selected:
                        count = row["counts"][model]
                        ppm = defect_ppm(count, area_inputs[model])
                        cells.append(f'<span class="value">{fmt_int(count)} PCBs</span><small>{fmt_ppm(ppm) if ppm is not None else "N/A"} PPM</small>')
                    display_rows.append((escape(row["category"]), cells))
                st.markdown(table([title, *selected], display_rows), unsafe_allow_html=True)
    workbook_bytes = build_comparison_workbook(
        selected, start_date, end_date, workbook_metrics, workbook_dimensions,
        {model: 0 for model in selected}, area="SMT + Assembly",
    )
    st.download_button(
        "Download formatted Excel report", data=workbook_bytes,
        file_name=f"model_comparison_{start_date:%Y-%m-%d}_{end_date:%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="model_compare_download",
    )


def _assembly_upload_section_v2(store_status: dict) -> None:
    st.caption(
        "Carregue inputs FPY diariamente. Defeitos FPY e reparo aceitam arquivos de qualquer período: o portal preserva o histórico e atualiza apenas eventos repetidos."
    )
    cards = st.columns(4)
    with cards[0]:
        smt_kpi_card("FPY Input", fmt_int(store_status["input"]), "Arquivos diários", "#6532C8")
    with cards[1]:
        smt_kpi_card("FPY Defects", fmt_int(store_status["defects"]), "Arquivos incrementais", "#6532C8")
    with cards[2]:
        smt_kpi_card("Repair Defects", fmt_int(store_status["repair"]), "Arquivos incrementais", "#6532C8")
    with cards[3]:
        smt_kpi_card("Stored size", f"{store_status['bytes'] / 1024 / 1024:.1f} MB", "Local files", "#6532C8")
    st.caption(f"Última importação: {store_status['latest']}")
    uploaded_inputs = st.file_uploader(
        "Input FPY — Assembly",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        key="assembly_quality_v2_inputs_upload",
    )
    uploaded_defects = st.file_uploader(
        "Defeitos FPY — Assembly (qualquer período)", type=["xls", "xlsx"], key="assembly_quality_v2_defects_upload"
    )
    uploaded_repair = st.file_uploader(
        "Defeitos de reparo — Assembly (qualquer período)", type=["xls", "xlsx"], key="assembly_quality_v2_repair_upload"
    )
    if st.button(
        "Salvar arquivos de Assembly",
        use_container_width=True,
        key="assembly_quality_v2_save",
        disabled=not (uploaded_defects or uploaded_repair or uploaded_inputs),
    ):
        results = []
        try:
            for uploaded in uploaded_inputs or []:
                assembly_kpi_v2.read_daily_input(uploaded)
                results.append(persist_assembly_source(uploaded, "input", "manual upload"))
            if uploaded_defects:
                assembly_kpi_v2.read_fpy_defects(uploaded_defects)
                results.append(persist_assembly_source(uploaded_defects, "defects", "manual upload"))
            if uploaded_repair:
                assembly_kpi_v2.read_repair(uploaded_repair)
                results.append(persist_assembly_source(uploaded_repair, "repair", "manual upload"))
        except Exception as exc:
            st.error(str(exc))
        else:
            st.session_state["assembly_last_import_results"] = results
            st.success("Arquivos de Assembly processados.")
            st.rerun()
    if st.button(
        "Refresh monitored folder",
        use_container_width=True,
        key="assembly_quality_v2_refresh_folder",
    ):
        st.session_state["assembly_last_import_results"] = import_assembly_monitored_folder()
        st.rerun()
    if "assembly_last_import_results" in st.session_state:
        import_results_table(st.session_state["assembly_last_import_results"])
    render_assembly_source_manager()



def _smt_oqc_data_management() -> None:
    """Manual SMT OQC entry and record history, managed from Data Upload."""
    import pandas as pd

    st.markdown("### Manual SMT OQC input")
    with st.form("smt_oqc_input_form", clear_on_submit=True):
        form_columns = st.columns(5)
        with form_columns[0]:
            oqc_date = st.date_input("Inspection date", value=date.today(), key="smt_oqc_inspection_date")
        with form_columns[1]:
            oqc_model = st.text_input("Model (optional)", key="smt_oqc_model")
        with form_columns[2]:
            inspected_qty = st.number_input("Inspected", min_value=0, value=0, step=1, key="smt_oqc_inspected")
        with form_columns[3]:
            ok_qty = st.number_input("OK", min_value=0, value=0, step=1, key="smt_oqc_ok")
        with form_columns[4]:
            ng_qty = st.number_input("NG", min_value=0, value=0, step=1, key="smt_oqc_ng")
        oqc_notes = st.text_input("Notes (optional)", key="smt_oqc_notes")
        st.caption("Use 0 inspected, 0 OK and 0 NG to register a day with no OQC sampling.")
        oqc_submit = st.form_submit_button("Save OQC inspection", use_container_width=True)
    if oqc_submit:
        try:
            save_smt_oqc_inspection(oqc_date, oqc_model, int(inspected_qty), int(ok_qty), int(ng_qty), oqc_notes)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("SMT OQC no-sampling record saved." if int(inspected_qty) == 0 else "SMT OQC inspection saved.")
            st.rerun()

    oqc_records = load_smt_oqc_inspections()
    st.markdown("### OQC inspection history")
    if oqc_records.empty:
        st.info("No SMT OQC inspection records have been entered yet.")
        return
    oqc_view = oqc_records.copy()
    oqc_view["InspectionDate"] = oqc_view["InspectionDate"].dt.strftime("%d/%m/%Y")
    oqc_view["CreatedAt"] = pd.to_datetime(oqc_view["CreatedAt"], errors="coerce").dt.strftime("%d/%m/%y %H:%M")
    oqc_view["PassRatePct"] = (pd.to_numeric(oqc_view["PassRate"], errors="coerce").astype("float64") * 100).round(2)
    oqc_view["Sampling"] = oqc_view["Inspected"].map(lambda value: "No sampling" if int(value) == 0 else "Sampled")
    styled_table(
        oqc_view[["ID", "InspectionDate", "Model", "Sampling", "Inspected", "OK", "NG", "PassRatePct", "Notes", "CreatedAt"]],
        table_class="inspection-history-table",
    )
    st.download_button(
        "Download OQC history CSV",
        data=oqc_view.to_csv(index=False).encode("utf-8-sig"),
        file_name="smt_oqc_inspection_history.csv",
        mime="text/csv",
        use_container_width=True,
    )
    with st.expander("Delete an OQC inspection record"):
        st.caption("Select the incorrect manual record, then confirm its deletion. This action cannot be undone.")
        delete_options = {
            int(row.ID): f"ID {int(row.ID)} · {row.InspectionDate} · {row.Model or 'No model'} · {int(row.Inspected)} inspected"
            for row in oqc_view.itertuples(index=False)
        }
        record_id = st.selectbox("OQC record to delete", options=list(delete_options), format_func=lambda value: delete_options[value], key="smt_oqc_delete_id")
        if st.button("Delete selected OQC record", type="secondary", key="smt_oqc_delete_button"):
            try:
                delete_smt_oqc_inspection(record_id)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("SMT OQC inspection record deleted.")
                st.rerun()


def _assembly_oqc_fqc_data_management() -> None:
    """Manual Assembly OQC/FQC entry and record history, managed from Data Upload."""
    import pandas as pd

    st.markdown("### Manual Assembly OQC and FQC input")
    with st.form("assembly_oqc_fqc_input_form", clear_on_submit=True):
        header_columns = st.columns(2)
        with header_columns[0]:
            inspection_date = st.date_input("Inspection date", value=date.today(), key="assembly_oqc_fqc_inspection_date")
        with header_columns[1]:
            inspection_model = st.text_input("Model (optional)", key="assembly_oqc_fqc_model")
        oqc_column, fqc_column = st.columns(2)
        with oqc_column:
            st.markdown("#### OQC")
            oqc_inspected_input = st.number_input("OQC inspected", min_value=0, value=0, step=1, key="assembly_oqc_inspected")
            oqc_ok_input = st.number_input("OQC OK", min_value=0, value=0, step=1, key="assembly_oqc_ok")
            oqc_ng_input = st.number_input("OQC NG", min_value=0, value=0, step=1, key="assembly_oqc_ng")
        with fqc_column:
            st.markdown("#### FQC")
            fqc_inspected_input = st.number_input("FQC inspected", min_value=0, value=0, step=1, key="assembly_fqc_inspected")
            fqc_ok_input = st.number_input("FQC OK", min_value=0, value=0, step=1, key="assembly_fqc_ok")
            fqc_ng_input = st.number_input("FQC NG", min_value=0, value=0, step=1, key="assembly_fqc_ng")
        inspection_notes = st.text_input("Notes (optional)", key="assembly_oqc_fqc_notes")
        st.caption("For an unsampled stage, enter 0 inspected, 0 OK and 0 NG. OQC and FQC can be recorded independently.")
        submit = st.form_submit_button("Save Assembly OQC and FQC inspection", use_container_width=True)
    if submit:
        try:
            save_assembly_oqc_fqc_inspection(
                inspection_date, inspection_model, int(oqc_inspected_input), int(oqc_ok_input), int(oqc_ng_input),
                int(fqc_inspected_input), int(fqc_ok_input), int(fqc_ng_input), inspection_notes,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            unsampled_stages = [stage for stage, inspected in (("OQC", oqc_inspected_input), ("FQC", fqc_inspected_input)) if int(inspected) == 0]
            suffix = f" No sampling recorded for {', '.join(unsampled_stages)}." if unsampled_stages else ""
            st.success(f"Assembly OQC and FQC inspection saved.{suffix}")
            st.rerun()

    records = load_assembly_oqc_fqc_inspections()
    st.markdown("### Assembly OQC and FQC inspection history")
    if records.empty:
        st.info("No Assembly OQC or FQC inspection records have been entered yet.")
        return
    view = records.copy()
    view["InspectionDate"] = view["InspectionDate"].dt.strftime("%d/%m/%Y")
    view["CreatedAt"] = pd.to_datetime(view["CreatedAt"], errors="coerce").dt.strftime("%d/%m/%y %H:%M")
    for source, output in [("OQCPassRate", "OQCPassRatePct"), ("FQCPassRate", "FQCPassRatePct"), ("CombinedPassRate", "OQCxFQCPassRatePct")]:
        view[output] = (pd.to_numeric(view[source], errors="coerce").astype("float64") * 100).round(2)
    view["OQCSampling"] = view["OQCInspected"].map(lambda value: "No sampling" if int(value) == 0 else "Sampled")
    view["FQCSampling"] = view["FQCInspected"].map(lambda value: "No sampling" if int(value) == 0 else "Sampled")
    visible = ["ID", "InspectionDate", "Model", "OQCSampling", "OQCInspected", "OQCOK", "OQCNG", "OQCPassRatePct", "FQCSampling", "FQCInspected", "FQCOK", "FQCNG", "FQCPassRatePct", "OQCxFQCPassRatePct", "Notes", "CreatedAt"]
    styled_table(view[visible], table_class="inspection-history-table assembly-inspection-history-table")
    st.download_button(
        "Download Assembly OQC and FQC history CSV",
        data=view.to_csv(index=False).encode("utf-8-sig"),
        file_name="assembly_oqc_fqc_inspection_history.csv",
        mime="text/csv",
        use_container_width=True,
    )
    with st.expander("Delete an Assembly OQC/FQC inspection record"):
        st.caption("Select the incorrect manual record, then confirm its deletion. This action cannot be undone.")
        delete_options = {
            int(row.ID): f"ID {int(row.ID)} · {row.InspectionDate} · {row.Model or 'No model'} · OQC {int(row.OQCInspected)} · FQC {int(row.FQCInspected)}"
            for row in view.itertuples(index=False)
        }
        record_id = st.selectbox("Assembly OQC/FQC record to delete", options=list(delete_options), format_func=lambda value: delete_options[value], key="assembly_oqc_fqc_delete_id")
        if st.button("Delete selected Assembly OQC/FQC record", type="secondary", key="assembly_oqc_fqc_delete_button"):
            try:
                delete_assembly_oqc_fqc_inspection(record_id)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Assembly OQC/FQC inspection record deleted.")
                st.rerun()


def data_upload_page(module: str, color: str) -> None:
    """Central upload workspace for the three validated MES source groups."""
    require_admin_access(st.session_state)
    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>{module} · Data Upload</h1>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Gerencie aqui os arquivos que alimentam o KPI Track e o Quality Dashboard desta área. "
        "Cada área mantém sua própria base de Input FPY, Defeitos FPY e Defeitos de reparo."
    )
    if module == "SMT":
        import importlib
        from tools import smt_quality_dashboard

        importlib.reload(smt_quality_dashboard)
        smt_quality_dashboard._upload_section(color)
        st.divider()
        _smt_oqc_data_management()
        return
    if module == "Assembly":
        st.markdown("### Upload Data")
        _assembly_upload_section_v2(assembly_store_status())
        st.divider()
        _assembly_oqc_fqc_data_management()


def assembly_quality_dashboard_v2(color: str) -> None:
    page_started = perf_counter()
    source_started = perf_counter()
    if is_admin() and not st.session_state.get("assembly_auto_import_checked", False):
        results = import_assembly_monitored_folder()
        st.session_state["assembly_auto_import_checked"] = True
        if any(result["status"] == "imported" for result in results):
            st.session_state["assembly_last_import_results"] = results
    sources = stored_assembly_sources_v2()
    stored_inputs = sources["input"]
    store_status = assembly_store_status(sync=False)
    source_seconds = perf_counter() - source_started
    st.markdown(
        f"<h1 class='section-title' style='color:{color};'>Assembly · Quality Dashboard</h1>",
        unsafe_allow_html=True,
    )
    if not stored_inputs or not sources["defects"] or not sources["repair"]:
        st.warning(
            "Os dados de Assembly estão incompletos. Abra Data Upload e carregue input FPY diário, "
            "defeitos FPY cumulativos e defeitos de reparo cumulativos."
        )
        return

    minimum_date, maximum_date = assembly_input_bounds(stored_inputs)
    filter_panel = st.container(key="assembly_quality_v2_filter_panel")
    with filter_panel:
        start_date, end_date = analysis_period_control(
            "assembly_quality_v2_period",
            minimum_date,
            maximum_date,
            default_start=minimum_date,
            default_end=maximum_date,
        )

    analysis_started = perf_counter()
    try:
        metrics = calculate_assembly_kpi_metrics(start_date, end_date)
    except Exception as exc:
        st.error(f"Unable to calculate the Assembly dashboard: {exc}")
        return
    analysis, rules = _assembly_analysis_from_metrics(metrics, start_date, end_date)
    analysis_seconds = perf_counter() - analysis_started

    raw = analysis["raw"].copy()
    raw["FailureType"] = "Unclassified"
    raw.loc[
        raw["TestOperation"].isin(rules.get("assembly_functional_operations", [])),
        "FailureType",
    ] = "Functional Failure"
    raw.loc[
        raw["TestOperation"].isin(rules.get("assembly_appearance_operations", [])),
        "FailureType",
    ] = "Appearance Failure"
    raw["DutyCategory"] = raw[rules["mando_column"]].map(_assembly_duty_category)
    model_options = ["All", *sorted(set(analysis["production_detail"]["Model"].dropna().astype(str)))]
    station_options = ["All", *sorted(set(raw["TestOperation"].dropna().astype(str)))]
    failure_options = ["All", "Functional Failure", "Appearance Failure", "Unclassified"]
    duty_options = ["All", *sorted(set(raw["DutyCategory"].dropna().astype(str)))]
    with filter_panel:
        filter_columns = st.columns(4)
        with filter_columns[0]:
            model = st.selectbox("Model", model_options, key="assembly_quality_v2_model", persist_state="session")
        with filter_columns[1]:
            station = st.selectbox(
                "Process / Station", station_options, key="assembly_quality_v2_station", persist_state="session"
            )
        with filter_columns[2]:
            failure_type = st.selectbox(
                "Failure type", failure_options, key="assembly_quality_v2_failure", persist_state="session"
            )
        with filter_columns[3]:
            duty_category = st.selectbox(
                "DutyType", duty_options, key="assembly_quality_v2_duty", persist_state="session"
            )

    view = _build_assembly_dashboard_view(
        analysis, rules, model, station, failure_type, duty_category
    )

    total_classified = view["functional_pcbs"] + view["appearance_pcbs"]
    functional_share = (
        view["functional_pcbs"] / total_classified if total_classified else 0
    )
    cards = st.columns(4)
    with cards[0]:
        smt_kpi_card("Assembly input", fmt_int(view["produced"]), "Units in the selected scope", color)
    with cards[1]:
        smt_kpi_card(
            "Confirmed defect PCBs",
            fmt_int(view["confirmed_pcbs"]),
            (
                f"Overall PPM {fmt_ppm(view['overall_ppm'])}"
                if view["overall_ppm"] is not None
                else "Overall PPM N/A"
            ),
            color,
        )
    with cards[2]:
        smt_kpi_card(
            "Failure mix",
            f"{functional_share:.0%} / {1 - functional_share:.0%}" if total_classified else "0% / 0%",
            f"{fmt_int(view['functional_pcbs'])} functional · {fmt_int(view['appearance_pcbs'])} appearance",
            color,
        )
    with cards[3]:
        smt_kpi_card(
            "Function Mando",
            f"{fmt_ppm(view['mando_ppm'])} PPM" if view["mando_ppm"] is not None else "N/A",
            f"{fmt_int(view['mando_pcbs'])} functional Mando NG PCBs",
            color,
        )

    st.markdown("### Defect breakdown")
    st.button(
        "Clear breakdown selections", key="assembly_breakdown_clear",
        on_click=_clear_assembly_breakdown_selections,
        use_container_width=True,
    )
    breakdown_detail = render_assembly_defect_dimension_cards(view["confirmed"])
    if any(
        st.session_state.get(f"assembly_breakdown_{column}", "All") != "All"
        for _, column, _, _ in ASSEMBLY_DEFECT_DIMENSIONS
    ):
        st.markdown("### Matching PCB details")
        unique_boards = breakdown_detail["_DefectKey"].nunique() if not breakdown_detail.empty else 0
        st.caption(
            f"{fmt_int(unique_boards)} unique NG PCBs · {fmt_int(len(breakdown_detail))} confirmed records "
            "match the selected breakdown categories."
        )
        detail_columns = [
            "PCB", "Model", "DefectDate", "TestOperation", "FailureType", "Phenomenon",
            "FaultReason", "BadMachLocation", "RepairRemark", "DutyType", "ItemCode",
        ]
        details = breakdown_detail[
            [column for column in detail_columns if column in breakdown_detail.columns]
        ].copy()
        if details.empty:
            st.info("No confirmed defects match this combination. Clear a selection to broaden the view.")
        else:
            st.dataframe(details, hide_index=True, width="stretch", height=310)
            st.download_button(
                "Download matching defect records",
                data=details.to_csv(index=False).encode("utf-8-sig"),
                file_name="assembly_breakdown_selection.csv", mime="text/csv",
                width="stretch", key="assembly_breakdown_download",
            )

    record_dashboard_performance(
        "Assembly Quality Dashboard",
        start_date,
        end_date,
        source_seconds,
        analysis_seconds,
        perf_counter() - page_started,
        sum(len(paths) for paths in sources.values()),
    )


def kpi_track_page(module: str, color: str) -> None:
    if module == "SMT":
        smt_kpi_track_page(color)
        return
    if module == "Assembly":
        assembly_kpi_track_page(color)
        return
    st.markdown(f"<h1 class='section-title' style='color:{color};'>{module} KPI Track</h1>", unsafe_allow_html=True)
    cols = st.columns(4)
    metrics = [("FPY", "98.65%"), ("OEE", "85.42%"), ("Defect Rate", "0.68%"), ("Rework Rate", "1.25%")]
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value' style='color:{color};'>{value}</div><div class='small-muted'>Demo target</div></div>", unsafe_allow_html=True)
    trend_chart(color)


def dashboard_page(module: str, color: str) -> None:
    if module == "Assembly":
        assembly_quality_dashboard_v2(color)
        return

    if module == "SMT":
        smt_quality_dashboard_v2(color)
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


def render_cloud_storage_panel() -> None:
    require_admin_access(st.session_state)
    status = cloud_store_status()
    files = [
        path for path in DATA_STORE_DIR.rglob("*")
        if path.is_file() and path.name not in {SYNC_MANIFEST_FILENAME, DATA_VERSION_FILENAME}
    ] if DATA_STORE_DIR.is_dir() else []
    local_mb = sum(path.stat().st_size for path in files) / 1024 / 1024

    st.markdown("<h3 class='section-title'>Cloud data storage</h3>", unsafe_allow_html=True)
    with st.expander("Supabase persistent storage", expanded=not bool(status["active"])):
        st.caption(
            "Supabase keeps uploaded Excel files, OQC/FQC records and Smart Report actions outside the temporary "
            "Streamlit filesystem. The current local data store is only used as a working cache."
        )
        st.write(f"**Status:** {status['mode']}")
        st.caption(str(status["message"]))
        st.caption(f"Current local migration set: {len(files):,} files · {local_mb:.2f} MB")

        if not bool(status["configured"]):
            st.info(
                "Add SUPABASE_URL and SUPABASE_SECRET_KEY in Streamlit Community Cloud: "
                "App settings > Secrets. A safe example is included in config/supabase.secrets.example.toml."
            )
            return

        if str(status["mode"]) == "Configuration error":
            st.error("Supabase could not be reached. Verify the URL and server-side secret key in Streamlit Secrets.")
            return

        if bool(status["active"]):
            st.success("Persistent Supabase storage is active. New uploads and record updates are saved to the cloud.")
            st.caption("Automatic sync downloads only new or changed cloud files. Use the full refresh below when you want to rebuild the complete local cache.")
            last_refresh = st.session_state.get("supabase_full_refresh_at")
            if last_refresh:
                st.caption(f"Last full refresh in this session: {last_refresh}")
            if st.button(
                "Full cloud refresh",
                help="Downloads every current portal file from Supabase. This may take a few minutes and never deletes cloud data.",
                use_container_width=True,
                key="supabase_full_cloud_refresh_button",
            ):
                try:
                    with st.spinner("Refreshing every portal file from Supabase..."):
                        result = full_cloud_refresh()
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["supabase_full_refresh_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    st.success(f"Full cloud refresh complete: {result['files']:,} files refreshed ({result['bytes'] / 1024 / 1024:.2f} MB).")
            return

        confirmed = st.checkbox(
            "I confirm that the current local data store is the approved baseline to migrate to Supabase.",
            key="supabase_initial_migration_confirm",
        )
        if st.button(
            "Migrate current portal data to Supabase",
            type="primary",
            disabled=not confirmed,
            use_container_width=True,
            key="supabase_initial_migration_button",
        ):
            try:
                init_quality_store()
                result = migrate_local_data_store(DATA_STORE_DIR)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success(f"Migration complete: {result['files']:,} files saved to Supabase ({result['bytes'] / 1024 / 1024:.2f} MB).")
                st.rerun()


def about_page() -> None:
    st.markdown("<h1 class='section-title'>About</h1>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="card">
            <h3>Jovi Quality Center</h3>
            <p><b>Current version:</b> {APP_VERSION}</p>
            <p><b>Developed by:</b> {DEVELOPER}<br><b>Role:</b> {ROLE}<br><b>Manager:</b> {MANAGER}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if is_admin():
        st.write("")
        render_cloud_storage_panel()
    st.write("")
    render_performance_diagnostics_panel()
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
        elif tab == "BOM Comparison Tool - Assembly":
            bom_tool_assy_page()
        elif tab == "Data Upload":
            if is_admin():
                data_upload_page(module, color)
            else:
                st.error("Administrator access is required for Data Upload.")
    elif module == "IQC":
        iqc_page()
    elif module == "Smart Report":
        smart_report_page()
    elif module == "Repair Info":
        repair_info_page()
    elif module == "Model Comparison":
        model_comparison_page(MODULES[module]["color"])
    elif module == "About":
        about_page()


init_state()
if st.session_state.get("auth_logout_pending"):
    render_auth_cookie()
    login_page()
    st.stop()
restore_authentication()
if not st.session_state.get("authenticated", False):
    login_page()
    st.stop()
if (token := st.session_state.get("auth_cookie_token")) and st.context.cookies.get(COOKIE_NAME) != token:
    render_auth_cookie(token)

sync_navigation_from_query()
apply_global_css()
install_chart_copy_controls()
top_navigation()
context_navigation()
render_page()
footer()
