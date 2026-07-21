from __future__ import annotations

import hashlib
from html import escape
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st


REF_COL = "位号 (Ref.)"
PN_COL = "料号 (Part Number)"
PN_LIST_COL = "料号列表 (Part Number List)"
ISSUE_CN_COL = "问题类型"

MATCH_STATUS = "匹配 (Match)"
MISSING_STATUS = "存在于表格1，但不存在于表格2 (Only in Table 1)"
EXTRA_STATUS = "存在于表格2，但不存在于表格1 (Only in Table 2)"
MISMATCH_STATUS = "料号不一致 (PN Mismatch)"
DUPLICATE_STATUS = "重复位号 (Duplicate Ref.)"
CRITICAL_DUPLICATE_STATUS = "严重重复位号-不同料号 (Critical Duplicate Ref. - Different PN)"

TEXT = {
    "app_title": "BOM Comparator Tool",
    "app_subtitle": "Compare BOM files by Ref. and Part Number, including PN mismatch, missing items, extra items, and duplicates.",
    "note": "Table 1: one Ref. per row | Table 2: multiple Ref. may be in the same cell, separated by commas.",
    "table1": "Table 1",
    "table2": "Table 2",
    "table1_caption": "Format: one Ref. per row + Part Number",
    "table2_caption": "Format: multiple Ref. may be separated by commas",
    "upload_table1": "Upload Table 1",
    "upload_table2": "Upload Table 2",
    "select_columns": "Select Columns",
    "ref_col_t1": "Table 1 Ref. Column",
    "pn_col_t1": "Table 1 Part Number Column",
    "ref_col_t2": "Table 2 Ref. Column",
    "pn_col_t2": "Table 2 Part Number Column",
    "auto_col_note": "The system suggests columns automatically, but you can still change them manually.",
    "preview_files": "Preview Uploaded Files",
    "compare": "Compare BOM Files",
    "summary": "Executive Summary",
    "total_items": "Total Items",
    "match": "Match",
    "match_rate": "Match Rate",
    "missing": "Missing in Table 2",
    "extra": "Extra in Table 2",
    "pn_mismatch": "PN Mismatch",
    "duplicate_ref": "Duplicate Ref.",
    "critical_dup": "Critical Dup.",
    "total_issues": "Total Issues",
    "result_ok": "Result: Both BOMs are fully matched. No issues found.",
    "result_critical": "Result: Critical duplicate Ref. with different PN found. Please review Critical Duplicate first.",
    "result_mismatch": "Result: PN mismatch found. Please review PN Mismatch first.",
    "result_duplicate": "Result: Duplicate Ref. found. Please review Duplicate Ref.",
    "result_missing_extra": "Result: Missing or extra items found. Please review differences.",
    "issue_center": "Issue Center",
    "comparison_result": "Comparison Result",
    "download_excel": "Download Excel Report",
    "processing_error": "Error processing files",
    "upload_warning": "Please upload both files to start the comparison.",
    "pqc_check_title": "Items for PQC Confirmation",
    "pqc_check_empty": "No items without Ref./Bit Number were found in Table 1 or Table 2.",
    "pqc_check_warning": "item(s) from Table 1/Table 2 have no Ref./Bit Number and require PQC confirmation.",
    "pqc_check_report_note": "The Excel report also contains the PQC_Check sheet with items without Ref./Bit Number for manual confirmation.",
    "result_filter": "Filter result",
    "issue_filter": "Filter issues by severity",
    "search": "Search Ref. or Part Number",
    "all": "All",
    "all_issues": "All",
    "no_result": "No results found with the applied filters.",
    "issue_filter_note": "This filter affects only the Issue Center.",
    "comparison_filter_note": "These filters affect the Comparison Result and search across displayed tables.",
    "supported_files": "Supported formats: XLSX, XLS and CSV",
}

TABLE_TEXT = {
    "ref": "Ref.",
    "pn": "Part Number",
    "pn_t1": "PN Table 1",
    "pn_t2": "PN Table 2",
    "status": "Status",
    "table": "Table",
    "qty": "Qty",
    "pn_count": "PN Count",
    "pn_list": "Part Number List",
    "issue": "Issue",
    "issue_type": "Issue Type",
    "details": "Details",
    "severity": "Severity",
    "match": "Match",
    "missing": "Missing in Table 2",
    "extra": "Extra in Table 2",
    "mismatch": "PN Mismatch",
    "duplicate": "Duplicate Ref.",
    "critical_duplicate": "Critical Duplicate Ref. - Different PN",
    "high": "High",
    "medium": "Medium",
    "critical": "Critical",
    "table1": "Table 1",
    "table2": "Table 2",
    "table1_vs_table2": "Table 1 vs Table 2",
}

STATUS_MAP = {
    MATCH_STATUS: "match",
    "匹配": "match",
    MISSING_STATUS: "missing",
    "表格2缺少项目": "missing",
    EXTRA_STATUS: "extra",
    "表格2多余项目": "extra",
    MISMATCH_STATUS: "mismatch",
    "料号不一致": "mismatch",
    DUPLICATE_STATUS: "duplicate",
    "重复位号": "duplicate",
    CRITICAL_DUPLICATE_STATUS: "critical_duplicate",
    "严重重复位号-不同料号": "critical_duplicate",
}

ISSUE_TYPE_MAP = {
    "PN Mismatch": "mismatch",
    "Missing in Table 2": "missing",
    "Extra in Table 2": "extra",
    "Duplicate Ref.": "duplicate",
    "Critical Duplicate Ref. - Different PN": "critical_duplicate",
}

SEVERITY_MAP = {
    "High": "high",
    "Medium": "medium",
    "Critical": "critical",
}

TABLE_MAP = {
    "Table 1": "table1",
    "Table 2": "table2",
    "Table 1 vs Table 2": "table1_vs_table2",
}


def apply_bom_css() -> None:
    st.markdown(
        """
        <style>
        .bom-intro {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 1rem 1.1rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            margin-bottom: 0.9rem;
        }
        .bom-intro h3 {
            color: #0B1F3A;
            margin: 0 0 0.35rem 0;
            font-size: 1.08rem;
            font-weight: 900;
        }
        .bom-intro p {
            color: #17243A;
            margin: 0.2rem 0;
            font-size: 0.88rem;
            line-height: 1.42;
        }
        .bom-note {
            border: 1px solid #BFD4F2;
            background: #EEF6FF;
            color: #0B1F3A;
            border-radius: 0.65rem;
            font-size: 0.84rem;
            font-weight: 700;
            padding: 0.72rem 0.85rem;
            margin: 0.65rem 0 0.95rem 0;
        }
        .bom-upload-card,
        .bom-report-card {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.75rem;
            padding: 0.9rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            min-height: 116px;
            margin-bottom: 0.4rem;
        }
        .bom-upload-card h4,
        .bom-report-card h4 {
            color: #0B1F3A;
            margin: 0 0 0.42rem 0;
            font-size: 0.98rem;
            font-weight: 900;
        }
        .bom-upload-card p,
        .bom-report-card p {
            color: #17243A;
            margin: 0.15rem 0;
            font-size: 0.82rem;
            line-height: 1.35;
        }
        .bom-summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(135px, 1fr));
            gap: 0.72rem;
            margin: 0.65rem 0 0.9rem 0;
        }
        .bom-metric-card {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-left: 5px solid var(--accent);
            border-radius: 0.72rem;
            padding: 0.82rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            min-height: 96px;
        }
        .bom-metric-label {
            color: #0B1F3A;
            font-size: 0.72rem;
            font-weight: 900;
            text-transform: uppercase;
            line-height: 1.2;
        }
        .bom-metric-value {
            color: #061B36;
            font-size: 1.45rem;
            font-weight: 900;
            margin-top: 0.24rem;
        }
        .bom-metric-note {
            color: #17243A;
            font-size: 0.78rem;
            font-weight: 700;
            margin-top: 0.2rem;
        }
        .bom-section-title {
            color: #0B1F3A;
            font-size: 1rem;
            font-weight: 900;
            margin: 0.35rem 0 0.55rem 0;
        }
        .bom-caption {
            color: #17243A;
            font-size: 0.82rem;
            font-weight: 700;
            margin-top: 0.25rem;
        }
        .bom-tool div[data-testid="stFileUploader"] section {
            background: #FFFFFF !important;
            border: 1px dashed #7EA7D8 !important;
            border-radius: 0.75rem !important;
        }
        .bom-tool div[data-testid="stFileUploader"] * {
            color: #0B1F3A !important;
        }
        .bom-hero-panel {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.8rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            display: grid;
            grid-template-columns: minmax(0, 1.3fr) minmax(300px, 0.9fr);
            gap: 1rem;
            margin-bottom: 0.9rem;
            padding: 1rem 1.1rem;
        }
        .bom-eyebrow {
            color: #0D7A45;
            font-size: 0.76rem;
            font-weight: 900;
            letter-spacing: 0.04em;
            margin-bottom: 0.22rem;
            text-transform: uppercase;
        }
        .bom-hero-title {
            color: #0B1F3A;
            font-size: 1.48rem;
            font-weight: 900;
            line-height: 1.15;
            margin: 0;
        }
        .bom-hero-subtitle {
            color: #17243A;
            font-size: 0.9rem;
            font-weight: 650;
            line-height: 1.38;
            margin-top: 0.42rem;
        }
        .bom-stepper {
            display: grid;
            gap: 0.5rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .bom-step {
            background: #F8FAFD;
            border: 1px solid #D8E2F0;
            border-radius: 0.65rem;
            min-height: 76px;
            padding: 0.62rem;
        }
        .bom-step-no {
            align-items: center;
            background: #0D7A45;
            border-radius: 999px;
            color: #FFFFFF;
            display: inline-flex;
            font-size: 0.72rem;
            font-weight: 900;
            height: 24px;
            justify-content: center;
            margin-bottom: 0.34rem;
            width: 24px;
        }
        .bom-step-title {
            color: #0B1F3A;
            font-size: 0.72rem;
            font-weight: 900;
            line-height: 1.18;
            text-transform: uppercase;
        }
        .bom-step-text {
            color: #17243A;
            font-size: 0.7rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 0.18rem;
        }
        .bom-section-shell {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 0.78rem;
            box-shadow: 0 8px 22px rgba(15, 35, 65, 0.08);
            margin: 0.85rem 0;
            padding: 0.92rem;
        }
        .bom-section-head {
            align-items: center;
            display: flex;
            gap: 0.55rem;
            justify-content: space-between;
            margin-bottom: 0.72rem;
        }
        .bom-section-head-title {
            color: #0B1F3A;
            font-size: 1rem;
            font-weight: 900;
            line-height: 1.2;
        }
        .bom-section-head-note {
            color: #17243A;
            font-size: 0.78rem;
            font-weight: 750;
            text-align: right;
        }
        .bom-upload-card {
            min-height: 120px;
            position: relative;
        }
        .bom-upload-label {
            color: #0B1F3A;
            font-size: 0.98rem;
            font-weight: 900;
            margin: 0 0 0.35rem 0;
        }
        .bom-source-grid {
            display: grid;
            gap: 0.75rem;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            margin: 0.82rem 0 0.72rem 0;
        }
        .bom-source-card {
            background: #F8FAFD;
            border: 1px solid #C8D3E3;
            border-left: 5px solid #0D7A45;
            border-radius: 0.72rem;
            min-height: 112px;
            padding: 0.82rem;
        }
        .bom-source-top {
            align-items: center;
            display: flex;
            gap: 0.6rem;
            justify-content: space-between;
            margin-bottom: 0.48rem;
        }
        .bom-source-title {
            color: #0B1F3A;
            font-size: 0.84rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .bom-status-pill {
            background: #E7F7EE;
            border: 1px solid #A9DEC0;
            border-radius: 999px;
            color: #0D6B3D;
            font-size: 0.68rem;
            font-weight: 900;
            padding: 0.2rem 0.48rem;
            white-space: nowrap;
        }
        .bom-file-name {
            color: #0B1F3A;
            font-size: 0.8rem;
            font-weight: 750;
            line-height: 1.26;
            margin-bottom: 0.58rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .bom-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
        }
        .bom-chip {
            background: #FFFFFF;
            border: 1px solid #C8D3E3;
            border-radius: 999px;
            color: #0B1F3A;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.27rem 0.52rem;
        }
        .bom-chip strong {
            color: #0D7A45;
            font-weight: 900;
        }
        .bom-compare-zone {
            align-items: center;
            background: #F8FAFD;
            border: 1px solid #D8E2F0;
            border-radius: 0.78rem;
            display: grid;
            gap: 0.8rem;
            grid-template-columns: minmax(0, 1fr) minmax(220px, 0.35fr);
            margin-top: 0.85rem;
            padding: 0.75rem;
        }
        .bom-compare-zone-title {
            color: #0B1F3A;
            font-size: 0.9rem;
            font-weight: 900;
        }
        .bom-compare-zone-note {
            color: #17243A;
            font-size: 0.78rem;
            font-weight: 700;
            margin-top: 0.12rem;
        }
        .bom-tool div[data-testid="stButton"] > button[kind="primary"] {
            background: #0D7A45 !important;
            border: 1px solid #0B6B3D !important;
            border-radius: 0.58rem !important;
            box-shadow: 0 10px 18px rgba(13, 122, 69, 0.18) !important;
            color: #FFFFFF !important;
            font-weight: 900 !important;
            min-height: 42px !important;
        }
        .bom-tool div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: #0B6B3D !important;
            border-color: #07572F !important;
            color: #FFFFFF !important;
        }
        .bom-result-shell {
            margin-top: 1rem;
        }
        @media (max-width: 980px) {
            .bom-hero-panel,
            .bom-compare-zone,
            .bom-source-grid {
                grid-template-columns: 1fr;
            }
            .bom-stepper {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .bom-section-head {
                align-items: flex-start;
                flex-direction: column;
            }
            .bom-section-head-note {
                text-align: left;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def fmt_int(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def fmt_pct(value: float) -> str:
    return f"{float(value):.2f}%"


def bom_hero_html(color: str) -> str:
    steps = [
        ("1", "Upload Files", "Load both BOM exports"),
        ("2", "Confirm Columns", "Check Ref. and PN fields"),
        ("3", "Compare", "Run normalization and match"),
        ("4", "Review Results", "Analyze issues and export"),
    ]
    step_html = "".join(
        f'<div class="bom-step"><div class="bom-step-no">{escape(no)}</div>'
        f'<div class="bom-step-title">{escape(title)}</div>'
        f'<div class="bom-step-text">{escape(text)}</div></div>'
        for no, title, text in steps
    )
    return (
        f'<div class="bom-hero-panel" style="border-top:4px solid {escape(color)};">'
        '<div>'
        '<div class="bom-eyebrow">SMT Quality Tool</div>'
        '<h1 class="bom-hero-title">SMT · BOM Comparison Tool</h1>'
        f'<div class="bom-hero-subtitle">{escape(TEXT["app_subtitle"])}</div>'
        f'<div class="bom-note">{escape(TEXT["note"])}</div>'
        '</div>'
        f'<div class="bom-stepper">{step_html}</div>'
        '</div>'
    )


def upload_card_html(title: str, caption: str, supported: str) -> str:
    return (
        '<div class="bom-upload-card">'
        f'<div class="bom-upload-label">{escape(title)}</div>'
        f'<p>{escape(caption)}</p>'
        f'<p>{escape(supported)}</p>'
        '</div>'
    )


def source_card_html(title: str, filename: str, ref_col: str, pn_col: str, note_row: bool, split_refs: bool) -> str:
    chips = [
        f'<span class="bom-chip"><strong>Ref:</strong> {escape(ref_col)}</span>',
        f'<span class="bom-chip"><strong>PN:</strong> {escape(pn_col)}</span>',
    ]
    if note_row:
        chips.append('<span class="bom-chip"><strong>Header:</strong> note row ignored</span>')
    if split_refs:
        chips.append('<span class="bom-chip"><strong>Refs:</strong> comma split</span>')
    return (
        '<div class="bom-source-card">'
        '<div class="bom-source-top">'
        f'<div class="bom-source-title">{escape(title)}</div>'
        '<div class="bom-status-pill">Ready</div>'
        '</div>'
        f'<div class="bom-file-name" title="{escape(filename)}">{escape(filename)}</div>'
        f'<div class="bom-chip-row">{"".join(chips)}</div>'
        '</div>'
    )


def traduzir_status(valor: Any) -> Any:
    chave = STATUS_MAP.get(str(valor))
    return TABLE_TEXT.get(chave, valor) if chave else valor


def traduzir_issue_type(valor: Any) -> Any:
    chave = ISSUE_TYPE_MAP.get(str(valor))
    return TABLE_TEXT.get(chave, valor) if chave else valor


def traduzir_severity(valor: Any) -> Any:
    chave = SEVERITY_MAP.get(str(valor))
    return TABLE_TEXT.get(chave, valor) if chave else valor


def traduzir_tabela(valor: Any) -> Any:
    chave = TABLE_MAP.get(str(valor))
    return TABLE_TEXT.get(chave, valor) if chave else valor


def traduzir_details(valor: Any) -> str:
    texto = str(valor)
    texto = texto.replace("Qty=", "Qty=")
    texto = texto.replace("PN List=", "PN List=")
    texto = texto.replace("Exists in Table 1, but not in Table 2", "Exists in Table 1, but not in Table 2")
    texto = texto.replace("Exists in Table 2, but not in Table 1", "Exists in Table 2, but not in Table 1")
    return texto


def traduzir_resultado_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Status" in out.columns:
        out["Status"] = out["Status"].apply(traduzir_status)
    return out.rename(
        columns={
            REF_COL: TABLE_TEXT["ref"],
            "PN_Tabela1": TABLE_TEXT["pn_t1"],
            "PN_Tabela2": TABLE_TEXT["pn_t2"],
            "Status": TABLE_TEXT["status"],
        }
    )


def traduzir_duplicate_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Table" in out.columns:
        out["Table"] = out["Table"].apply(traduzir_tabela)
    if "Issue" in out.columns:
        out["Issue"] = out["Issue"].apply(traduzir_status)
    return out.rename(
        columns={
            "Table": TABLE_TEXT["table"],
            REF_COL: TABLE_TEXT["ref"],
            "Qty": TABLE_TEXT["qty"],
            "PN Count": TABLE_TEXT["pn_count"],
            PN_LIST_COL: TABLE_TEXT["pn_list"],
            "Issue": TABLE_TEXT["issue"],
        }
    )


def traduzir_issues_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Issue Type" in out.columns:
        out["Issue Type"] = out["Issue Type"].apply(traduzir_issue_type)
    if ISSUE_CN_COL in out.columns:
        out[ISSUE_CN_COL] = out[ISSUE_CN_COL].apply(traduzir_status)
    if "Table" in out.columns:
        out["Table"] = out["Table"].apply(traduzir_tabela)
    if "Severity" in out.columns:
        out["Severity"] = out["Severity"].apply(traduzir_severity)
    if "Details" in out.columns:
        out["Details"] = out["Details"].apply(traduzir_details)
    return out.rename(
        columns={
            "Issue Type": TABLE_TEXT["issue_type"],
            ISSUE_CN_COL: TABLE_TEXT["issue"],
            "Table": TABLE_TEXT["table"],
            REF_COL: TABLE_TEXT["ref"],
            "PN Table 1": TABLE_TEXT["pn_t1"],
            "PN Table 2": TABLE_TEXT["pn_t2"],
            "Details": TABLE_TEXT["details"],
            "Severity": TABLE_TEXT["severity"],
        }
    )


def traduzir_normalizada_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy().rename(columns={REF_COL: TABLE_TEXT["ref"], PN_COL: TABLE_TEXT["pn"]})


def estilizar_issues_df(df: pd.DataFrame):
    severity_col = TABLE_TEXT["severity"]

    def style_severity(value: Any) -> str:
        value_text = str(value).strip().lower()
        if value_text == "critical":
            return "background-color: #7f1d1d; color: #ffffff; font-weight: 800; text-align: center;"
        if value_text == "high":
            return "background-color: #dc2626; color: #ffffff; font-weight: 800; text-align: center;"
        if value_text == "medium":
            return "background-color: #f59e0b; color: #111827; font-weight: 800; text-align: center;"
        return ""

    if severity_col not in df.columns:
        return df
    styler = df.style
    if hasattr(styler, "map"):
        return styler.map(style_severity, subset=[severity_col])
    return styler.applymap(style_severity, subset=[severity_col])


def primeira_linha_eh_comentario(arquivo) -> bool:
    """Detects note/comment rows before the real BOM headers."""
    try:
        if arquivo.name.lower().endswith(".csv"):
            preview = pd.read_csv(arquivo, dtype=str, header=None, nrows=1)
            arquivo.seek(0)
        else:
            preview = pd.read_excel(arquivo, dtype=str, header=None, nrows=1)
            arquivo.seek(0)

        if preview.empty:
            return False

        first_row_text = " ".join(preview.iloc[0].fillna("").astype(str).tolist()).lower()
        comment_keywords = [
            "note:",
            "note：",
            "the red background",
            "unverified material",
            "red background color",
            "备注",
            "说明",
        ]
        header_keywords = [
            "bit number",
            "child material code",
            "ref",
            "part number",
            "料号",
            "位号",
        ]

        if any(keyword in first_row_text for keyword in header_keywords):
            return False
        if any(keyword in first_row_text for keyword in comment_keywords):
            return True
        return False
    except Exception:
        try:
            arquivo.seek(0)
        except Exception:
            pass
        return False


def ler_arquivo(arquivo, skip_first_row: bool = False) -> pd.DataFrame:
    skiprows = 1 if skip_first_row else 0
    if arquivo.name.lower().endswith(".csv"):
        df = pd.read_csv(arquivo, dtype=str, skiprows=skiprows)
        arquivo.seek(0)
        return df

    df = pd.read_excel(arquivo, dtype=str, skiprows=skiprows)
    arquivo.seek(0)
    return df


def limpar_nome_coluna(c: Any) -> str:
    return str(c).replace("\n", " ").strip()


def normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [limpar_nome_coluna(c) for c in out.columns]
    return out


def encontrar_coluna_padrao(colunas, tipo: str) -> int:
    colunas_lista = list(colunas)
    if tipo == "ref":
        candidatos = [
            "bit number",
            "ref",
            "ref.",
            "reference",
            "reference designator",
            "designator",
            "ref des",
            "refdes",
            "location",
            "位号",
            "位置",
            "器件位号",
        ]
    else:
        candidatos = [
            "child material code",
            "part number",
            "part numbe",
            "partnumber",
            "part no",
            "part no.",
            "pn",
            "p/n",
            "material",
            "material number",
            "item number",
            "料号",
            "物料号",
            "物料编码",
            "物料代码",
        ]

    def limpar_texto(txt: Any) -> str:
        return (
            str(txt)
            .lower()
            .replace(" ", "")
            .replace(".", "")
            .replace("_", "")
            .replace("-", "")
            .replace("/", "")
            .strip()
        )

    candidatos_limpos = [limpar_texto(c) for c in candidatos]

    for coluna in colunas_lista:
        coluna_limpa = limpar_texto(coluna)
        if coluna_limpa in candidatos_limpos:
            return colunas_lista.index(coluna)

    for coluna in colunas_lista:
        coluna_limpa = limpar_texto(coluna)
        for candidato in candidatos_limpos:
            if candidato in coluna_limpa or coluna_limpa in candidato:
                return colunas_lista.index(coluna)

    return 0


def limpar_tabela(saida: pd.DataFrame) -> pd.DataFrame:
    out = saida.copy()
    null_values = ["", " ", "None", "none", "NONE", "nan", "NaN", "NAN", "<NA>"]
    out[REF_COL] = out[REF_COL].replace(null_values, pd.NA)
    out = out.dropna(subset=[REF_COL])
    out[REF_COL] = out[REF_COL].astype(str).str.strip()
    out[PN_COL] = out[PN_COL].astype(str).str.strip()
    out[REF_COL] = out[REF_COL].replace(null_values, pd.NA)
    out[PN_COL] = out[PN_COL].replace(null_values, pd.NA)
    return out.dropna(subset=[REF_COL, PN_COL])


def preparar_tabela1(df: pd.DataFrame, col_ref: str, col_pn: str, split_refs: bool = True) -> pd.DataFrame:
    saida = df[[col_ref, col_pn]].copy()
    saida.columns = [REF_COL, PN_COL]
    if split_refs:
        saida[REF_COL] = saida[REF_COL].astype(str).str.split(",")
        saida = saida.explode(REF_COL)
    return limpar_tabela(saida)


def preparar_tabela2(df: pd.DataFrame, col_ref: str, col_pn: str) -> pd.DataFrame:
    saida = df[[col_ref, col_pn]].copy()
    saida.columns = [REF_COL, PN_COL]
    saida[REF_COL] = saida[REF_COL].astype(str).str.split(",")
    saida = saida.explode(REF_COL)
    return limpar_tabela(saida)


def encontrar_coluna_por_nome(colunas, nomes_alvo: list[str]) -> str | None:
    def normalizar_nome(txt: Any) -> str:
        return str(txt).lower().replace("\n", " ").replace("_", " ").replace("-", " ").strip()

    colunas_lista = list(colunas)
    alvos = [normalizar_nome(nome) for nome in nomes_alvo]

    for coluna in colunas_lista:
        coluna_norm = normalizar_nome(coluna)
        if coluna_norm in alvos:
            return coluna

    for coluna in colunas_lista:
        coluna_norm = normalizar_nome(coluna)
        for alvo in alvos:
            if alvo in coluna_norm or coluna_norm in alvo:
                return coluna

    return None


def extrair_itens_para_conferencia(df: pd.DataFrame, col_ref: str) -> pd.DataFrame:
    output_columns = ["Child material code", "Child material English description", "PQC Confirmation"]
    if df is None or df.empty or col_ref not in df.columns:
        return pd.DataFrame(columns=output_columns)

    df_check = df.copy()
    ref_raw = df_check[col_ref]
    ref_text = ref_raw.astype(str).str.strip()
    blank_mask = ref_raw.isna() | ref_text.isin(["", " ", "nan", "NaN", "NAN", "None", "none", "NONE", "<NA>"])
    itens = df_check[blank_mask].copy()
    if itens.empty:
        return pd.DataFrame(columns=output_columns)

    code_col = encontrar_coluna_por_nome(
        itens.columns,
        ["Child material code", "child material code", "料号", "物料号", "物料编码", "material code", "material number"],
    )
    desc_col = encontrar_coluna_por_nome(
        itens.columns,
        [
            "Child material English description",
            "child material english description",
            "English description",
            "material english description",
            "description",
            "物料英文描述",
            "英文描述",
        ],
    )

    output = pd.DataFrame(columns=output_columns)
    output["Child material code"] = itens[code_col].astype(str).str.strip() if code_col else ""
    output["Child material English description"] = itens[desc_col].astype(str).str.strip() if desc_col else ""
    output["PQC Confirmation"] = ""
    output = output.replace(["nan", "NaN", "NAN", "None", "none", "NONE", "<NA>"], "")
    output = output.dropna(how="all", subset=["Child material code", "Child material English description"])
    return output.reset_index(drop=True)


def detectar_ref_duplicada(df: pd.DataFrame, nome_tabela: str) -> pd.DataFrame:
    duplicados = df[df.duplicated(subset=[REF_COL], keep=False)].copy()
    if duplicados.empty:
        return pd.DataFrame(columns=["Table", REF_COL, "Qty", "PN Count", PN_LIST_COL, "Issue"])

    resumo = (
        duplicados.groupby(REF_COL)
        .agg(
            Qty=(REF_COL, "count"),
            **{
                "PN Count": (PN_COL, lambda x: len(set(x.astype(str)))),
                PN_LIST_COL: (PN_COL, lambda x: ", ".join(sorted(set(x.astype(str))))),
            },
        )
        .reset_index()
    )
    resumo.insert(0, "Table", nome_tabela)
    resumo["Issue"] = resumo["PN Count"].apply(lambda x: CRITICAL_DUPLICATE_STATUS if x > 1 else DUPLICATE_STATUS)
    return resumo


def comparar(t1: pd.DataFrame, t2: pd.DataFrame) -> pd.DataFrame:
    t1 = t1.copy().drop_duplicates()
    t2 = t2.copy().drop_duplicates()
    t1 = t1.rename(columns={PN_COL: "PN_Tabela1"})
    t2 = t2.rename(columns={PN_COL: "PN_Tabela2"})

    combinado = pd.merge(t1, t2, on=REF_COL, how="outer", indicator=True)

    def definir_status(row: pd.Series) -> str:
        if row["_merge"] == "left_only":
            return MISSING_STATUS
        if row["_merge"] == "right_only":
            return EXTRA_STATUS
        if row["PN_Tabela1"] == row["PN_Tabela2"]:
            return MATCH_STATUS
        return MISMATCH_STATUS

    combinado["Status"] = combinado.apply(definir_status, axis=1)
    resultado = combinado[[REF_COL, "PN_Tabela1", "PN_Tabela2", "Status"]].copy()
    return resultado.sort_values(["Status", REF_COL])


def criar_issue_center(resultado: pd.DataFrame, dup_tabela1: pd.DataFrame, dup_tabela2: pd.DataFrame) -> pd.DataFrame:
    issues = []

    for _, row in resultado.iterrows():
        if row["Status"] == MISMATCH_STATUS:
            issues.append(
                {
                    "Issue Type": "PN Mismatch",
                    ISSUE_CN_COL: "料号不一致",
                    "Table": "Table 1 vs Table 2",
                    REF_COL: row[REF_COL],
                    "PN Table 1": row["PN_Tabela1"],
                    "PN Table 2": row["PN_Tabela2"],
                    "Details": f'{row["PN_Tabela1"]} -> {row["PN_Tabela2"]}',
                    "Severity": "High",
                }
            )
        elif row["Status"] == MISSING_STATUS:
            issues.append(
                {
                    "Issue Type": "Missing in Table 2",
                    ISSUE_CN_COL: "表格2缺少项目",
                    "Table": "Table 1",
                    REF_COL: row[REF_COL],
                    "PN Table 1": row["PN_Tabela1"],
                    "PN Table 2": "",
                    "Details": "Exists in Table 1, but not in Table 2",
                    "Severity": "Medium",
                }
            )
        elif row["Status"] == EXTRA_STATUS:
            issues.append(
                {
                    "Issue Type": "Extra in Table 2",
                    ISSUE_CN_COL: "表格2多余项目",
                    "Table": "Table 2",
                    REF_COL: row[REF_COL],
                    "PN Table 1": "",
                    "PN Table 2": row["PN_Tabela2"],
                    "Details": "Exists in Table 2, but not in Table 1",
                    "Severity": "Medium",
                }
            )

    duplicate_all = pd.concat([dup_tabela1, dup_tabela2], ignore_index=True)
    for _, row in duplicate_all.iterrows():
        issue_type = "Critical Duplicate Ref. - Different PN" if row["Issue"] == CRITICAL_DUPLICATE_STATUS else "Duplicate Ref."
        issues.append(
            {
                "Issue Type": issue_type,
                ISSUE_CN_COL: row["Issue"],
                "Table": row["Table"],
                REF_COL: row[REF_COL],
                "PN Table 1": "",
                "PN Table 2": "",
                "Details": f'Qty={row["Qty"]}; PN List={row[PN_LIST_COL]}',
                "Severity": "Critical" if issue_type.startswith("Critical") else "Medium",
            }
        )

    return pd.DataFrame(issues, columns=["Issue Type", ISSUE_CN_COL, "Table", REF_COL, "PN Table 1", "PN Table 2", "Details", "Severity"])


def aplicar_busca_resultado(df: pd.DataFrame, termo: str) -> pd.DataFrame:
    if not termo:
        return df
    termo = str(termo).strip().lower()
    if not termo:
        return df

    mask = pd.Series(False, index=df.index)
    for col in [REF_COL, "PN_Tabela1", "PN_Tabela2", "Status"]:
        if col in df.columns:
            mask = mask | df[col].astype(str).str.lower().str.contains(termo, na=False)
    return df[mask]


def coluna_tem_refs_multiplas(df: pd.DataFrame, col_ref: str) -> bool:
    if col_ref not in df.columns:
        return False
    values = df[col_ref].dropna().astype(str)
    return bool(values.str.contains(",", regex=False).any())


def gerar_excel(
    resultado: pd.DataFrame,
    tabela1_normalizada: pd.DataFrame,
    tabela2_normalizada: pd.DataFrame,
    dup_tabela1: pd.DataFrame,
    dup_tabela2: pd.DataFrame,
    issues_df: pd.DataFrame,
    itens_conferencia: pd.DataFrame,
) -> BytesIO:
    output = BytesIO()

    match_df = resultado[resultado["Status"] == MATCH_STATUS].copy()
    missing_df = resultado[resultado["Status"] == MISSING_STATUS].copy()
    extra_df = resultado[resultado["Status"] == EXTRA_STATUS].copy()
    mismatch_df = resultado[resultado["Status"] == MISMATCH_STATUS].copy()

    total_count = len(resultado)
    match_count = len(match_df)
    match_rate = (match_count / total_count * 100) if total_count > 0 else 0
    critical_issues_count = (issues_df["Severity"] == "Critical").sum() if not issues_df.empty else 0
    high_issues_count = (issues_df["Severity"] == "High").sum() if not issues_df.empty else 0

    summary_df = pd.DataFrame(
        {
            "Item": [
                "Total Items",
                "Match",
                "Match Rate",
                "Missing in Table 2",
                "Extra in Table 2",
                "PN Mismatch",
                "Duplicate Ref. Table 1",
                "Duplicate Ref. Table 2",
                "Duplicate Ref. Total",
                "Total Issues",
                "Critical Issues",
                "High Issues",
            ],
            "Qty / Value": [
                total_count,
                match_count,
                f"{match_rate:.2f}%",
                len(missing_df),
                len(extra_df),
                len(mismatch_df),
                len(dup_tabela1),
                len(dup_tabela2),
                len(dup_tabela1) + len(dup_tabela2),
                len(issues_df),
                critical_issues_count,
                high_issues_count,
            ],
        }
    )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Summary")
        traduzir_issues_df(issues_df).to_excel(writer, index=False, sheet_name="Issues")
        itens_conferencia.to_excel(writer, index=False, sheet_name="PQC_Check")
        traduzir_resultado_df(match_df).to_excel(writer, index=False, sheet_name="Match")
        traduzir_resultado_df(missing_df).to_excel(writer, index=False, sheet_name="Missing")
        traduzir_resultado_df(extra_df).to_excel(writer, index=False, sheet_name="Extra")
        traduzir_resultado_df(mismatch_df).to_excel(writer, index=False, sheet_name="PN_Mismatch")
        traduzir_duplicate_df(dup_tabela1).to_excel(writer, index=False, sheet_name="Duplicate_Ref_T1")
        traduzir_duplicate_df(dup_tabela2).to_excel(writer, index=False, sheet_name="Duplicate_Ref_T2")
        traduzir_resultado_df(resultado).to_excel(writer, index=False, sheet_name="All_Results")
        traduzir_normalizada_df(tabela1_normalizada).to_excel(writer, index=False, sheet_name="Table1_Normalized")
        traduzir_normalizada_df(tabela2_normalizada).to_excel(writer, index=False, sheet_name="Table2_Normalized")

        workbook = writer.book
        for sheet_name in workbook.sheetnames:
            ws = workbook[sheet_name]
            for column_cells in ws.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter
                for cell in column_cells:
                    value_length = len(str(cell.value)) if cell.value is not None else 0
                    max_length = max(max_length, value_length)
                ws.column_dimensions[column_letter].width = min(max_length + 3, 45)
            ws.freeze_panes = "A2"
            if ws.max_row > 1 and ws.max_column > 1:
                ws.auto_filter.ref = ws.dimensions

    output.seek(0)
    return output


def calculate_summary(resultado: pd.DataFrame, issues_df: pd.DataFrame, dup_tabela1: pd.DataFrame, dup_tabela2: pd.DataFrame) -> dict[str, Any]:
    total_count = len(resultado)
    match_count = int((resultado["Status"] == MATCH_STATUS).sum())
    missing_count = int((resultado["Status"] == MISSING_STATUS).sum())
    extra_count = int((resultado["Status"] == EXTRA_STATUS).sum())
    mismatch_count = int((resultado["Status"] == MISMATCH_STATUS).sum())
    duplicate_count = len(dup_tabela1) + len(dup_tabela2)
    total_issues_count = len(issues_df)
    critical_duplicate_count = int((issues_df["Issue Type"] == "Critical Duplicate Ref. - Different PN").sum()) if not issues_df.empty else 0
    match_rate = (match_count / total_count * 100) if total_count > 0 else 0
    return {
        "total_count": total_count,
        "match_count": match_count,
        "match_rate": match_rate,
        "missing_count": missing_count,
        "extra_count": extra_count,
        "mismatch_count": mismatch_count,
        "duplicate_count": duplicate_count,
        "critical_duplicate_count": critical_duplicate_count,
        "total_issues_count": total_issues_count,
    }


def metric_card(label: str, value: str, note: str, accent: str) -> str:
    return (
        f'<div class="bom-metric-card" style="--accent:{escape(accent)};">'
        f'<div class="bom-metric-label">{escape(label)}</div>'
        f'<div class="bom-metric-value">{escape(value)}</div>'
        f'<div class="bom-metric-note">{escape(note)}</div>'
        "</div>"
    )


def render_summary_cards(summary: dict[str, Any], color: str, pqc_count: int = 0) -> None:
    cards = [
        metric_card(TEXT["total_items"], fmt_int(summary["total_count"]), "Compared refs", color),
        metric_card(TEXT["match_rate"], fmt_pct(summary["match_rate"]), f"{fmt_int(summary['match_count'])} matched", "#0D7A45"),
        metric_card(TEXT["missing"], fmt_int(summary["missing_count"]), "Only in Table 1", "#B45309"),
        metric_card(TEXT["extra"], fmt_int(summary["extra_count"]), "Only in Table 2", "#B45309"),
        metric_card(TEXT["pn_mismatch"], fmt_int(summary["mismatch_count"]), "Same Ref., different PN", "#C2410C"),
        metric_card("PQC Items", fmt_int(pqc_count), "Manual confirmation", "#1D5FBF"),
    ]
    st.markdown(f"<div class='bom-summary-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def render_result_message(summary: dict[str, Any]) -> None:
    if summary["total_issues_count"] == 0:
        st.success(TEXT["result_ok"])
    elif summary["critical_duplicate_count"] > 0:
        st.error(TEXT["result_critical"])
    elif summary["mismatch_count"] > 0:
        st.error(TEXT["result_mismatch"])
    elif summary["duplicate_count"] > 0:
        st.warning(TEXT["result_duplicate"])
    else:
        st.warning(TEXT["result_missing_extra"])


def process_comparison(
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    col_ref_t1: str,
    col_pn_t1: str,
    col_ref_t2: str,
    col_pn_t2: str,
    split_refs_t1: bool = True,
) -> dict[str, pd.DataFrame]:
    tabela1 = preparar_tabela1(df1, col_ref_t1, col_pn_t1, split_refs=split_refs_t1)
    tabela2 = preparar_tabela2(df2, col_ref_t2, col_pn_t2)
    itens_conferencia = pd.concat(
        [extrair_itens_para_conferencia(df1, col_ref_t1), extrair_itens_para_conferencia(df2, col_ref_t2)],
        ignore_index=True,
    ).drop_duplicates().reset_index(drop=True)
    dup_tabela1 = detectar_ref_duplicada(tabela1, "Table 1")
    dup_tabela2 = detectar_ref_duplicada(tabela2, "Table 2")
    resultado = comparar(tabela1, tabela2)
    issues_df = criar_issue_center(resultado, dup_tabela1, dup_tabela2)
    return {
        "tabela1": tabela1,
        "tabela2": tabela2,
        "dup_tabela1": dup_tabela1,
        "dup_tabela2": dup_tabela2,
        "resultado": resultado,
        "issues_df": issues_df,
        "itens_conferencia": itens_conferencia,
    }


def render_bom_comparison_tool(color: str) -> None:
    apply_bom_css()
    st.markdown("<div class='bom-tool'>", unsafe_allow_html=True)
    st.markdown(bom_hero_html(color), unsafe_allow_html=True)

    st.markdown(
        '<div class="bom-section-head">'
        '<div class="bom-section-head-title">Upload Files</div>'
        '<div class="bom-section-head-note">Supported formats: XLSX, XLS and CSV</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    upload_col1, upload_col2 = st.columns(2)
    with upload_col1:
        st.markdown(upload_card_html(TEXT["table1"], TEXT["table1_caption"], TEXT["supported_files"]), unsafe_allow_html=True)
        arquivo1 = st.file_uploader(
            TEXT["upload_table1"],
            type=["xlsx", "xls", "csv"],
            key="bom_table1_upload",
            label_visibility="collapsed",
        )

    with upload_col2:
        st.markdown(upload_card_html(TEXT["table2"], TEXT["table2_caption"], TEXT["supported_files"]), unsafe_allow_html=True)
        arquivo2 = st.file_uploader(
            TEXT["upload_table2"],
            type=["xlsx", "xls", "csv"],
            key="bom_table2_upload",
            label_visibility="collapsed",
        )

    if not arquivo1 or not arquivo2:
        st.info(TEXT["upload_warning"])
        st.markdown("</div>", unsafe_allow_html=True)
        return

    try:
        skip_first_row_t1 = primeira_linha_eh_comentario(arquivo1)
        df1 = normalizar_colunas(ler_arquivo(arquivo1, skip_first_row=skip_first_row_t1))
        skip_first_row_t2 = primeira_linha_eh_comentario(arquivo2)
        df2 = normalizar_colunas(ler_arquivo(arquivo2, skip_first_row=skip_first_row_t2))

        file_signature = (
            getattr(arquivo1, "name", ""),
            getattr(arquivo1, "size", None),
            getattr(arquivo2, "name", ""),
            getattr(arquivo2, "size", None),
        )
        if st.session_state.get("bom_file_signature") != file_signature:
            st.session_state["bom_file_signature"] = file_signature
            st.session_state["bom_comparison_done"] = False

        suggested_ref_t1 = df1.columns[encontrar_coluna_padrao(df1.columns, "ref")]
        suggested_pn_t1 = df1.columns[encontrar_coluna_padrao(df1.columns, "pn")]
        suggested_ref_t2 = df2.columns[encontrar_coluna_padrao(df2.columns, "ref")]
        suggested_pn_t2 = df2.columns[encontrar_coluna_padrao(df2.columns, "pn")]
        widget_signature = hashlib.md5(repr(("v4", file_signature)).encode("utf-8")).hexdigest()[:12]

        st.markdown(
            '<div class="bom-section-head" style="margin-top:0.95rem;">'
            '<div class="bom-section-head-title">Detected File Structure</div>'
            '<div class="bom-section-head-note">Automatic suggestions can be adjusted below</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="bom-source-grid">'
            + source_card_html(
                TEXT["table1"],
                getattr(arquivo1, "name", ""),
                str(suggested_ref_t1),
                str(suggested_pn_t1),
                skip_first_row_t1,
                coluna_tem_refs_multiplas(df1, suggested_ref_t1),
            )
            + source_card_html(
                TEXT["table2"],
                getattr(arquivo2, "name", ""),
                str(suggested_ref_t2),
                str(suggested_pn_t2),
                skip_first_row_t2,
                True,
            )
            + "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="bom-section-head">'
            f'<div class="bom-section-head-title">{escape(TEXT["select_columns"])}</div>'
            f'<div class="bom-section-head-note">{escape(TEXT["auto_col_note"])}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**{TEXT['table1']}**")
            col_ref_t1 = st.selectbox(
                TEXT["ref_col_t1"],
                df1.columns,
                index=list(df1.columns).index(suggested_ref_t1),
                key=f"bom_ref_t1_{widget_signature}",
            )
            col_pn_t1 = st.selectbox(
                TEXT["pn_col_t1"],
                df1.columns,
                index=list(df1.columns).index(suggested_pn_t1),
                key=f"bom_pn_t1_{widget_signature}",
            )
        with c2:
            st.markdown(f"**{TEXT['table2']}**")
            col_ref_t2 = st.selectbox(
                TEXT["ref_col_t2"],
                df2.columns,
                index=list(df2.columns).index(suggested_ref_t2),
                key=f"bom_ref_t2_{widget_signature}",
            )
            col_pn_t2 = st.selectbox(
                TEXT["pn_col_t2"],
                df2.columns,
                index=list(df2.columns).index(suggested_pn_t2),
                key=f"bom_pn_t2_{widget_signature}",
            )

        auto_split_t1 = coluna_tem_refs_multiplas(df1, col_ref_t1)
        split_refs_t1 = True
        current_config_signature = (
            "v5",
            file_signature,
            col_ref_t1,
            col_pn_t1,
            col_ref_t2,
            col_pn_t2,
            split_refs_t1,
        )
        if st.session_state.get("bom_config_signature") != current_config_signature:
            st.session_state["bom_config_signature"] = current_config_signature
            st.session_state["bom_comparison_done"] = False

        with st.expander(TEXT["preview_files"]):
            if skip_first_row_t1:
                st.caption("Table 1 note row was detected and ignored before loading headers.")
            if skip_first_row_t2:
                st.caption("Table 2 note row was detected and ignored before loading headers.")
            if auto_split_t1:
                st.caption("Table 1 comma-separated refs will be split before comparison.")
            st.write(TEXT["table1"])
            st.dataframe(df1.head(20), use_container_width=True)
            st.write(TEXT["table2"])
            st.dataframe(df2.head(20), use_container_width=True)

        action_col, button_col = st.columns([3, 1.15])
        with action_col:
            st.markdown(
                '<div class="bom-compare-zone-title">Ready to Compare</div>'
                '<div class="bom-compare-zone-note">Files and columns are prepared for BOM normalization, issue detection, PQC review, and Excel export.</div>',
                unsafe_allow_html=True,
            )
        with button_col:
            compare_clicked = st.button(TEXT["compare"], type="primary", use_container_width=True)

        if compare_clicked:
            st.session_state["bom_results"] = process_comparison(
                df1,
                df2,
                col_ref_t1,
                col_pn_t1,
                col_ref_t2,
                col_pn_t2,
                split_refs_t1=split_refs_t1,
            )
            st.session_state["bom_source_preview"] = {"df1": df1, "df2": df2}
            st.session_state["bom_comparison_done"] = True

        if not st.session_state.get("bom_comparison_done", False):
            st.markdown("</div>", unsafe_allow_html=True)
            return

        results = st.session_state["bom_results"]
        tabela1 = results["tabela1"]
        tabela2 = results["tabela2"]
        dup_tabela1 = results["dup_tabela1"]
        dup_tabela2 = results["dup_tabela2"]
        resultado = results["resultado"]
        issues_df = results["issues_df"]
        itens_conferencia = results.get(
            "itens_conferencia",
            pd.DataFrame(columns=["Child material code", "Child material English description", "PQC Confirmation"]),
        )
        summary = calculate_summary(resultado, issues_df, dup_tabela1, dup_tabela2)

        st.markdown(
            '<div class="bom-section-head" style="margin-top:1rem;">'
            f'<div class="bom-section-head-title">{escape(TEXT["summary"])}</div>'
            '<div class="bom-section-head-note">Main comparison indicators</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        render_summary_cards(summary, color, pqc_count=len(itens_conferencia))
        render_result_message(summary)

        upload_tab, issues_tab, pqc_tab, result_tab, duplicates_tab, report_tab = st.tabs(
            ["Upload Preview", TEXT["issue_center"], TEXT["pqc_check_title"], TEXT["comparison_result"], "Duplicates", "Report"]
        )

        with upload_tab:
            st.markdown("<div class='bom-section-title'>Upload / Preview</div>", unsafe_allow_html=True)
            preview = st.session_state.get("bom_source_preview", {"df1": df1, "df2": df2})
            st.write(TEXT["table1"])
            st.dataframe(preview["df1"].head(20), use_container_width=True)
            st.write(TEXT["table2"])
            st.dataframe(preview["df2"].head(20), use_container_width=True)

        with issues_tab:
            issues_filtradas = issues_df.copy()
            if summary["total_issues_count"] == 0:
                st.success(TEXT["result_ok"])
            else:
                issue_col1, issue_col2 = st.columns([2, 4])
                issue_filter_options = [TEXT["all_issues"], TABLE_TEXT["critical"], TABLE_TEXT["high"], TABLE_TEXT["medium"]]
                with issue_col1:
                    issue_filter_label = st.selectbox(TEXT["issue_filter"], issue_filter_options, key="bom_issue_filter")
                with issue_col2:
                    st.markdown(f"<div class='bom-caption'>{escape(TEXT['issue_filter_note'])}</div>", unsafe_allow_html=True)

                if issue_filter_label != TEXT["all_issues"]:
                    issues_filtradas = issues_filtradas[issues_filtradas["Severity"] == issue_filter_label]

                if issues_filtradas.empty:
                    st.info(TEXT["no_result"])
                else:
                    issues_display = traduzir_issues_df(issues_filtradas)
                    st.dataframe(estilizar_issues_df(issues_display), use_container_width=True)

        with pqc_tab:
            st.markdown(f"<div class='bom-section-title'>{escape(TEXT['pqc_check_title'])}</div>", unsafe_allow_html=True)
            if itens_conferencia.empty:
                st.success(TEXT["pqc_check_empty"])
            else:
                st.warning(f"{len(itens_conferencia)} {TEXT['pqc_check_warning']}")
                st.dataframe(itens_conferencia, use_container_width=True)

        with result_tab:
            comp_col1, comp_col2, comp_col3 = st.columns([2, 3, 3])
            result_filter_options = [TEXT["all"], TABLE_TEXT["match"], TABLE_TEXT["mismatch"], TABLE_TEXT["missing"], TABLE_TEXT["extra"]]
            with comp_col1:
                result_filter_label = st.selectbox(TEXT["result_filter"], result_filter_options, key="bom_result_filter")
            with comp_col2:
                search_text = st.text_input(TEXT["search"], key="bom_search_text")
            with comp_col3:
                st.markdown(f"<div class='bom-caption'>{escape(TEXT['comparison_filter_note'])}</div>", unsafe_allow_html=True)

            resultado_filtrado = resultado.copy()
            if result_filter_label != TEXT["all"]:
                status_key = None
                for key in ["match", "mismatch", "missing", "extra"]:
                    if result_filter_label == TABLE_TEXT[key]:
                        status_key = key
                if status_key:
                    internal_statuses = [status for status, mapped in STATUS_MAP.items() if mapped == status_key]
                    resultado_filtrado = resultado_filtrado[resultado_filtrado["Status"].isin(internal_statuses)]

            resultado_filtrado = aplicar_busca_resultado(resultado_filtrado, search_text)
            if resultado_filtrado.empty:
                st.info(TEXT["no_result"])
            else:
                st.dataframe(traduzir_resultado_df(resultado_filtrado), use_container_width=True)

        with duplicates_tab:
            d1, d2 = st.columns(2)
            with d1:
                st.markdown(f"**{TEXT['table1']}**")
                st.dataframe(traduzir_duplicate_df(dup_tabela1), use_container_width=True)
            with d2:
                st.markdown(f"**{TEXT['table2']}**")
                st.dataframe(traduzir_duplicate_df(dup_tabela2), use_container_width=True)

        with report_tab:
            st.markdown(
                f"""
                <div class="bom-report-card">
                    <h4>BOM Comparator Tool Report</h4>
                    <p>{escape(TEXT["total_items"])}: <b>{fmt_int(summary["total_count"])}</b></p>
                    <p>{escape(TEXT["match_rate"])}: <b>{fmt_pct(summary["match_rate"])}</b></p>
                    <p>{escape(TEXT["total_issues"])}: <b>{fmt_int(summary["total_issues_count"])}</b></p>
                    <p>The Excel report includes summary, issues, PQC check, duplicates, full comparison result, and normalized source tables.</p>
                    <p>{escape(TEXT["pqc_check_report_note"])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            excel = gerar_excel(resultado, tabela1, tabela2, dup_tabela1, dup_tabela2, issues_df, itens_conferencia)
            st.download_button(
                label=TEXT["download_excel"],
                data=excel,
                file_name="bom_comparison_result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    except Exception as exc:
        st.error(f"{TEXT['processing_error']}: {exc}")
    finally:
        st.markdown("</div>", unsafe_allow_html=True)
