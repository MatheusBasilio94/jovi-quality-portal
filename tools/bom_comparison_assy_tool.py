import hashlib
import re
import unicodedata
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st


TOOL_VERSION = "v2.0.7"

MICROSIGA_ALIASES = {
    "code": ["codigo", "cod", "material code", "child material code"],
    "description": ["descricao", "description", "desc"],
    "quantity": ["qtde necessaria", "quantidade", "quantity", "qty"],
    "position": ["pos mecanica", "posicao mecanica", "bit number", "ref"],
}

JOVI_ALIASES = {
    "code": ["child material code", "material code", "料号", "物料号"],
    "description": ["child material description", "child material english description", "description", "物料描述"],
    "quantity": ["quantity", "qty", "数量"],
    "position": ["bit number", "bitnumber", "位号", "ref"],
}

JOVI_IGNORE_CODE_PREFIXES = ("HQHQ",)
MICROSIGA_IGNORE_EXACT_CODES = {"G701", "G999"}


def clean_col_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def compact_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_col_name(value).lower())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", without_accents)


def find_column(columns, aliases: list[str]):
    columns = list(columns)
    alias_keys = [compact_key(alias) for alias in aliases]
    for column in columns:
        if compact_key(column) in alias_keys:
            return column
    for column in columns:
        column_key = compact_key(column)
        for alias_key in alias_keys:
            if len(alias_key) >= 4 and (alias_key in column_key or column_key in alias_key):
                return column
    return None


def _read_csv(data: bytes) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(BytesIO(data), dtype=str, sep=None, engine="python", encoding=encoding)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Unable to read CSV file: {last_error}")


def read_uploaded_file(uploaded, profile: str) -> pd.DataFrame:
    data = uploaded.getvalue()
    filename = uploaded.name.lower()
    if filename.endswith(".csv"):
        frame = _read_csv(data)
        frame.columns = [clean_col_name(column) for column in frame.columns]
        return frame

    aliases = MICROSIGA_ALIASES if profile == "microsiga" else JOVI_ALIASES
    for header_row in range(10):
        try:
            sample = pd.read_excel(BytesIO(data), dtype=str, header=header_row, nrows=8)
            columns = [clean_col_name(column) for column in sample.columns]
            if find_column(columns, aliases["code"]) and find_column(columns, aliases["quantity"]):
                frame = pd.read_excel(BytesIO(data), dtype=str, header=header_row)
                frame.columns = [clean_col_name(column) for column in frame.columns]
                return frame
        except Exception:
            continue
    raise ValueError(f"Could not identify the header row in {uploaded.name}.")


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def normalize_code(value: Any) -> str:
    text = clean_text(value)
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text.strip()


def parse_number(value: Any) -> float:
    text = clean_text(value).replace(" ", "")
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_positions(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    return sorted({item.strip().upper() for item in re.split(r"[,;|/]+", text) if item.strip()})


def filter_microsiga_ignored_items(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    code_column = find_column(frame.columns, MICROSIGA_ALIASES["code"])
    if code_column is None:
        return frame, 0
    code_text = frame[code_column].astype(str).str.strip().str.upper()
    keep_mask = ~code_text.isin(MICROSIGA_IGNORE_EXACT_CODES)
    return frame.loc[keep_mask].copy().reset_index(drop=True), int((~keep_mask).sum())


def filter_jovi_ignored_items(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    code_column = find_column(frame.columns, JOVI_ALIASES["code"])
    if code_column is None and len(frame.columns) >= 7:
        code_column = frame.columns[6]
    if code_column is None:
        return frame, 0
    code_text = frame[code_column].astype(str).str.strip().str.upper()
    keep_mask = ~code_text.str.startswith(JOVI_IGNORE_CODE_PREFIXES, na=False)
    return frame.loc[keep_mask].copy().reset_index(drop=True), int((~keep_mask).sum())


def normalize_bom(frame: pd.DataFrame, profile: str) -> pd.DataFrame:
    aliases = MICROSIGA_ALIASES if profile == "microsiga" else JOVI_ALIASES
    code_column = find_column(frame.columns, aliases["code"])
    quantity_column = find_column(frame.columns, aliases["quantity"])
    description_column = find_column(frame.columns, aliases["description"])
    position_column = find_column(frame.columns, aliases["position"])

    missing = []
    if code_column is None:
        missing.append("Codigo" if profile == "microsiga" else "Child material code")
    if quantity_column is None:
        missing.append("QTDE.NECESSARIA" if profile == "microsiga" else "Quantity")
    if missing:
        raise ValueError(f"Required column(s) not found in {profile}: {', '.join(missing)}")

    output = pd.DataFrame()
    output["Code"] = frame[code_column].apply(normalize_code)
    output["Description"] = frame[description_column].apply(clean_text) if description_column else ""
    output["Quantity"] = frame[quantity_column].apply(parse_number)
    output["Position"] = frame[position_column].apply(clean_text) if position_column else ""
    output = output[output["Code"].astype(str).str.strip().ne("")].copy()
    output = output[~output["Code"].astype(str).str.lower().isin({"nan", "none", "<na>", "codigo", "codigo:"})]

    return (
        output.groupby("Code", dropna=False)
        .agg(
            Description=("Description", lambda values: " | ".join(sorted({clean_text(value) for value in values if clean_text(value)}))),
            Quantity=("Quantity", "sum"),
            Position=("Position", lambda values: ",".join(sorted({position for value in values for position in normalize_positions(value)}))),
            **{"Line Count": ("Code", "count")},
        )
        .reset_index()
    )


def compare_assembly(microsiga: pd.DataFrame, jovi: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = pd.merge(microsiga, jovi, on="Code", how="outer", suffixes=(" Microsiga", " Jovi"), indicator=True)
    results = []
    issues = []
    for _, row in merged.iterrows():
        code = row["Code"]
        in_microsiga = row["_merge"] in {"left_only", "both"}
        in_jovi = row["_merge"] in {"right_only", "both"}
        qty_microsiga = row.get("Quantity Microsiga", "") if in_microsiga else ""
        qty_jovi = row.get("Quantity Jovi", "") if in_jovi else ""
        desc_microsiga = clean_text(row.get("Description Microsiga", "")) if in_microsiga else ""
        desc_jovi = clean_text(row.get("Description Jovi", "")) if in_jovi else ""

        if in_jovi and not in_microsiga:
            status = "Missing in Microsiga"
            details = "Exists in Jovi official BOM, but not in Microsiga BOM"
        elif in_microsiga and not in_jovi:
            status = "Extra in Microsiga"
            details = "Exists in Microsiga BOM, but not in Jovi official BOM"
        elif abs(float(qty_microsiga) - float(qty_jovi)) > 1e-6:
            status = "Quantity Mismatch"
            details = f"Microsiga Qty={qty_microsiga}; Jovi Qty={qty_jovi}"
        else:
            status = "Match"
            details = ""

        result_row = {
            "Code": code,
            "Description Microsiga": desc_microsiga,
            "Description Jovi": desc_jovi,
            "Quantity Microsiga": qty_microsiga,
            "Quantity Jovi": qty_jovi,
            "Status": status,
        }
        results.append(result_row)
        if status != "Match":
            issues.append({
                "Issue Type": status,
                "Code": code,
                "Description Microsiga": desc_microsiga,
                "Description Jovi": desc_jovi,
                "Quantity Microsiga": qty_microsiga,
                "Quantity Jovi": qty_jovi,
                "Details": details,
                "Severity": "High",
            })

    result = pd.DataFrame(results).sort_values(["Status", "Code"]).reset_index(drop=True)
    issue_columns = ["Issue Type", "Code", "Description Microsiga", "Description Jovi", "Quantity Microsiga", "Quantity Jovi", "Details", "Severity"]
    return result, pd.DataFrame(issues, columns=issue_columns)


def build_summary(result: pd.DataFrame, issues: pd.DataFrame, jovi_count: int) -> dict[str, Any]:
    matches = int(result["Status"].eq("Match").sum())
    missing = int(issues["Issue Type"].eq("Missing in Microsiga").sum()) if not issues.empty else 0
    extra = int(issues["Issue Type"].eq("Extra in Microsiga").sum()) if not issues.empty else 0
    quantity = int(issues["Issue Type"].eq("Quantity Mismatch").sum()) if not issues.empty else 0
    return {
        "Jovi Items": jovi_count,
        "Match": matches,
        "Match Rate": matches / jovi_count if jovi_count else 0.0,
        "Missing": missing,
        "Extra": extra,
        "Quantity Mismatch": quantity,
        "Total Issues": len(issues),
    }


def generate_excel(analysis: dict) -> bytes:
    output = BytesIO()
    summary = pd.DataFrame({"Item": list(analysis["summary"].keys()), "Qty / Value": list(analysis["summary"].values())})
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")
        analysis["issues"].to_excel(writer, index=False, sheet_name="Issues")
        for issue_type, sheet_name in (("Missing in Microsiga", "Missing"), ("Extra in Microsiga", "Extra"), ("Quantity Mismatch", "Qty_Mismatch")):
            analysis["issues"][analysis["issues"]["Issue Type"].eq(issue_type)].to_excel(writer, index=False, sheet_name=sheet_name)
        analysis["result"].to_excel(writer, index=False, sheet_name="All_Results")
        analysis["microsiga"].to_excel(writer, index=False, sheet_name="Microsiga_Normalized")
        analysis["jovi"].to_excel(writer, index=False, sheet_name="Jovi_Normalized")
        audit = pd.DataFrame([
            {"Source": "Microsiga", "Rule": "Exact code G701 or G999", "Ignored Rows": analysis["ignored_microsiga"]},
            {"Source": "Jovi", "Rule": "Child material code starts with HQHQ", "Ignored Rows": analysis["ignored_jovi"]},
        ])
        audit.to_excel(writer, index=False, sheet_name="Filter_Audit")
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            if worksheet.max_row > 1 and worksheet.max_column > 1:
                worksheet.auto_filter.ref = worksheet.dimensions
            for column in worksheet.columns:
                width = max((len(str(cell.value)) if cell.value is not None else 0 for cell in column), default=0)
                worksheet.column_dimensions[column[0].column_letter].width = min(width + 3, 55)
    return output.getvalue()


def _metric_card(label: str, value: str, note: str = "") -> None:
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value' style='color:#6532C8;'>{value}</div><div class='small-muted'>{note}</div></div>",
        unsafe_allow_html=True,
    )


def _file_signature(*files) -> str:
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.name.encode("utf-8", errors="ignore"))
        digest.update(file.getvalue())
    return digest.hexdigest()


def render_bom_comparison_assy_tool(color: str) -> None:
    st.markdown(
        f"""
        <div class="learning-hero" style="border-left:4px solid {color};">
            <div class="small-muted">Assembly Quality Tool · {TOOL_VERSION}</div>
            <h1 class="section-title" style="color:{color};margin:0.25rem 0;">Assembly · BOM Comparison Tool</h1>
            <p class="small-muted">Compare BOM Microsiga against the official Jovi BOM reference.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "Assembly rules: compare Code/Child Material and Quantity only. Description and Position are shown for traceability. "
        "Jovi codes beginning with HQHQ and exact Microsiga codes G701/G999 are excluded before comparison."
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### BOM Microsiga")
        st.caption("Compared structure · XLSX, XLS or CSV")
        microsiga_file = st.file_uploader("Upload BOM Microsiga", type=["xlsx", "xls", "csv"], key="bom_assy_microsiga")
    with right:
        st.markdown("#### BOM Jovi")
        st.caption("Official reference · XLSX, XLS or CSV")
        jovi_file = st.file_uploader("Upload BOM Jovi", type=["xlsx", "xls", "csv"], key="bom_assy_jovi")

    if not microsiga_file or not jovi_file:
        st.info("Upload the Microsiga BOM and Jovi BOM to start the Assembly comparison.")
        return

    signature = _file_signature(microsiga_file, jovi_file)
    if st.session_state.get("bom_assy_signature") != signature:
        st.session_state["bom_assy_signature"] = signature
        st.session_state.pop("bom_assy_analysis", None)

    try:
        microsiga_raw = read_uploaded_file(microsiga_file, "microsiga")
        jovi_raw = read_uploaded_file(jovi_file, "jovi")
        with st.expander("Preview uploaded files"):
            preview_left, preview_right = st.columns(2)
            preview_left.dataframe(microsiga_raw.head(20), use_container_width=True)
            preview_right.dataframe(jovi_raw.head(20), use_container_width=True)

        if st.button("Compare Assembly BOM", type="primary", use_container_width=True, key="bom_assy_compare"):
            microsiga_filtered, ignored_microsiga = filter_microsiga_ignored_items(microsiga_raw)
            jovi_filtered, ignored_jovi = filter_jovi_ignored_items(jovi_raw)
            microsiga = normalize_bom(microsiga_filtered, "microsiga")
            jovi = normalize_bom(jovi_filtered, "jovi")
            result, issues = compare_assembly(microsiga, jovi)
            st.session_state["bom_assy_analysis"] = {
                "result": result,
                "issues": issues,
                "microsiga": microsiga,
                "jovi": jovi,
                "ignored_microsiga": ignored_microsiga,
                "ignored_jovi": ignored_jovi,
                "summary": build_summary(result, issues, len(jovi)),
            }

        analysis = st.session_state.get("bom_assy_analysis")
        if not analysis:
            return

        summary = analysis["summary"]
        first_row = st.columns(4)
        with first_row[0]:
            _metric_card("Jovi Items", f"{summary['Jovi Items']:,}", "Official reference")
        with first_row[1]:
            _metric_card("Match", f"{summary['Match']:,}", f"{summary['Match Rate']:.2%}")
        with first_row[2]:
            _metric_card("Total Issues", f"{summary['Total Issues']:,}", "Action required")
        with first_row[3]:
            _metric_card("Ignored Rows", f"{analysis['ignored_microsiga'] + analysis['ignored_jovi']:,}", "Per Assembly rules")

        second_row = st.columns(3)
        with second_row[0]:
            _metric_card("Missing", f"{summary['Missing']:,}", "Missing in Microsiga")
        with second_row[1]:
            _metric_card("Extra", f"{summary['Extra']:,}", "Extra in Microsiga")
        with second_row[2]:
            _metric_card("Quantity Mismatch", f"{summary['Quantity Mismatch']:,}", "Same code, different quantity")

        issues_tab, results_tab, normalized_tab, report_tab = st.tabs(["Issue Center", "Comparison Result", "Normalized Data", "Report"])
        with issues_tab:
            if analysis["issues"].empty:
                st.success("No issues found.")
            else:
                issue_types = ["All", *sorted(analysis["issues"]["Issue Type"].unique())]
                selected_issue = st.selectbox("Issue type", issue_types, key="bom_assy_issue_filter")
                issue_view = analysis["issues"] if selected_issue == "All" else analysis["issues"][analysis["issues"]["Issue Type"].eq(selected_issue)]
                st.dataframe(issue_view, use_container_width=True, height=390)
        with results_tab:
            statuses = ["All", *sorted(analysis["result"]["Status"].unique())]
            selected_status = st.selectbox("Status", statuses, key="bom_assy_status_filter")
            search = st.text_input("Search code or description", key="bom_assy_search")
            result_view = analysis["result"] if selected_status == "All" else analysis["result"][analysis["result"]["Status"].eq(selected_status)]
            if search.strip():
                term = re.escape(search.strip())
                mask = result_view.astype(str).apply(lambda column: column.str.contains(term, case=False, na=False, regex=True)).any(axis=1)
                result_view = result_view[mask]
            st.dataframe(result_view, use_container_width=True, height=430)
        with normalized_tab:
            normalized_left, normalized_right = st.columns(2)
            normalized_left.markdown("#### Microsiga normalized")
            normalized_left.dataframe(analysis["microsiga"], use_container_width=True, height=390)
            normalized_right.markdown("#### Jovi normalized")
            normalized_right.dataframe(analysis["jovi"], use_container_width=True, height=390)
        with report_tab:
            st.caption("Includes summary, issues, missing/extra/quantity views, normalized BOMs and a filter audit.")
            st.download_button(
                "Download Assembly BOM comparison report",
                data=generate_excel(analysis),
                file_name="Assembly_BOM_Comparison_Report_v2_0_7.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="bom_assy_download",
            )
    except Exception as exc:
        st.error(f"Unable to process the Assembly BOM files: {exc}")
