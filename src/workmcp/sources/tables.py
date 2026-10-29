"""Tolerant readers for reference tables (KldB 2010, KldB→ISCO-08, ESCO↔O*NET) in XLSX/CSV.

The official files change layout between releases (title rows, renamed headers), so columns are
detected by header keywords *and* by the shape of the values instead of fixed positions.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Callable, Sequence
from typing import Any

KLDB_LEVELS = {
    1: "Berufsbereich",
    2: "Berufshauptgruppe",
    3: "Berufsgruppe",
    4: "Berufsuntergruppe",
    5: "Berufsgattung",
}
KLDB_NIVEAUS = {"1": "Helfer", "2": "Fachkraft", "3": "Spezialist", "4": "Experte"}

ESCO_OCC_RE = re.compile(r"^https?://data\.europa\.eu/esco/occupation/[\w-]+$")
ONET_SOC_RE = re.compile(r"^\d{2}-\d{4}\.\d{2}$")
_DIGITS_RE = re.compile(r"^\d{1,5}$")


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_table(content: bytes, filename: str = "") -> list[list[str]]:
    """Rows of the first non-empty sheet (XLSX) or of a CSV/TSV file, as strings."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")) or content[:2] == b"PK":
        try:
            return _read_xlsx(content)
        except zipfile.BadZipFile:
            pass
    if name.endswith(".xls") or content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("Altes Excel-Format (.xls) wird nicht unterstützt – bitte als .xlsx oder .csv speichern.")
    return _read_csv(content)


def _read_xlsx(content: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    best: list[list[str]] = []
    for ws in wb.worksheets:
        rows = [[cell_text(v) for v in row] for row in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if len(rows) > len(best):
            best = rows
    wb.close()
    return best


def _read_csv(content: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20000]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel_tab if sample.count("\t") > sample.count(";") else csv.excel
        if sample.count(";") > sample.count(",") and sample.count(";") > sample.count("\t"):
            dialect = type("semicolon", (csv.excel,), {"delimiter": ";"})
    rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    return [r for r in rows if any(r)]


def _norm_header(text: str) -> str:
    return text.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("*", "")


def _find_header(rows: Sequence[Sequence[str]], *groups: Sequence[str], scan: int = 30) -> int | None:
    """Index of the first row that contains a cell matching each keyword group."""
    for i, row in enumerate(rows[:scan]):
        cells = [_norm_header(c) for c in row]
        if all(any(any(k in c for k in group) for c in cells) for group in groups):
            return i
    return None


def _col_by_header(header: Sequence[str], keywords: Sequence[str], exclude: Sequence[str] = ()) -> int | None:
    for idx, cell in enumerate(header):
        c = _norm_header(cell)
        if any(k in c for k in keywords) and not any(x in c for x in exclude):
            return idx
    return None


def _col_by_values(rows: Sequence[Sequence[str]], predicate: Callable[[str], bool], min_share: float = 0.6,
                   skip: Sequence[int] = ()) -> int | None:  # fmt: skip
    width = max((len(r) for r in rows), default=0)
    best, best_share = None, 0.0
    for col in range(width):
        if col in skip:
            continue
        values = [r[col] for r in rows if col < len(r) and r[col]]
        if len(values) < 3:
            continue
        share = sum(1 for v in values if predicate(v)) / len(values)
        if share >= min_share and share > best_share:
            best, best_share = col, share
    return best


def _get(row: Sequence[str], idx: int | None) -> str:
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def _strip_prefix(code: str) -> str:
    code = code.strip()
    if code[:2].upper() == "B ":
        code = code[2:]
    return code.replace(" ", "")


def parse_kldb(rows: Sequence[Sequence[str]]) -> list[dict[str, Any]]:
    """KldB 2010 structure: code (1–5 digits), title, level, Anforderungsniveau."""
    header_idx = _find_header(rows, ("schluessel", "kldb", "code", "kennziffer"), ("titel", "bezeichnung", "benennung"))
    body = rows[header_idx + 1 :] if header_idx is not None else rows
    header = rows[header_idx] if header_idx is not None else []

    def looks_like_code(v: str) -> bool:
        return bool(_DIGITS_RE.match(_strip_prefix(v)))

    code_col = _col_by_header(header, ("schluessel", "kldb", "code", "kennziffer"))
    if code_col is not None:
        values = [_get(r, code_col) for r in body if _get(r, code_col)]
        if not values or sum(map(looks_like_code, values)) / len(values) < 0.3:
            code_col = None
    if code_col is None:
        code_col = _col_by_values(body, looks_like_code)
    title_col = _col_by_header(header, ("titel", "bezeichnung", "benennung"), exclude=("ebene",))
    level_col = _col_by_header(header, ("ebene", "gliederungsebene"))
    if code_col is None:
        return []
    if title_col is None or title_col == code_col:
        width = max((len(r) for r in body), default=0)
        lengths = {c: sum(len(_get(r, c)) for r in body) for c in range(width) if c not in (code_col, level_col)}
        title_col = max(lengths, key=lambda c: lengths[c]) if lengths else None
    out: dict[str, dict[str, Any]] = {}
    for row in body:
        code = _strip_prefix(_get(row, code_col))
        if not _DIGITS_RE.match(code):
            continue
        level_txt = _get(row, level_col)
        if level_txt.isdigit() and 1 <= int(level_txt) <= 5 and len(code) < int(level_txt):
            code = code.zfill(int(level_txt))
        title = _get(row, title_col)
        if not title:
            continue
        level = len(code)
        out[code] = {
            "code": code,
            "titel": title,
            "ebene": level,
            "ebene_name": KLDB_LEVELS.get(level),
            "anforderungsniveau": KLDB_NIVEAUS.get(code[4]) if level == 5 else None,
        }
    return list(out.values())


def parse_kldb_isco(rows: Sequence[Sequence[str]]) -> list[dict[str, Any]]:
    """Umsteigeschlüssel KldB 2010 (5-Steller) → ISCO-08 (4-Steller)."""
    header_idx = _find_header(rows, ("kldb",), ("isco",))
    header = rows[header_idx] if header_idx is not None else []
    body = rows[header_idx + 1 :] if header_idx is not None else rows

    def is_kldb(v: str) -> bool:
        return bool(re.match(r"^\d{4,5}$", _strip_prefix(v)))

    def is_isco(v: str) -> bool:
        return bool(re.match(r"^\d{3,4}$", v.strip()))

    kldb_col = _col_by_header(header, ("kldb",), exclude=("bezeichnung", "titel", "name"))
    isco_col = _col_by_header(header, ("isco",), exclude=("bezeichnung", "titel", "name", "label"))
    if kldb_col is None:
        kldb_col = _col_by_values(body, lambda v: bool(re.match(r"^\d{5}$", _strip_prefix(v))))
    if isco_col is None:
        isco_col = _col_by_values(body, lambda v: bool(re.match(r"^\d{4}$", v.strip())), skip=[kldb_col or -1])
    if kldb_col is None or isco_col is None:
        return []
    kldb_title = _col_by_header(header, ("bezeichnung kldb", "kldb-bezeichnung", "berufsgattung", "titel kldb"))
    isco_title = _col_by_header(header, ("bezeichnung isco", "isco-bezeichnung", "unit group", "titel isco"))
    hint_col = _col_by_header(header, ("eindeutig", "kennzeichen", "hinweis", "alternativ", "anmerkung"))
    out = []
    seen = set()
    for row in body:
        k = _strip_prefix(_get(row, kldb_col))
        i = _get(row, isco_col)
        if not (is_kldb(k) and is_isco(i)):
            continue
        k, i = k.zfill(5), i.zfill(4)
        if (k, i) in seen:
            continue
        seen.add((k, i))
        out.append(
            {
                "kldb": k,
                "isco": i,
                "kldb_titel": _get(row, kldb_title) or None,
                "isco_titel": _get(row, isco_title) or None,
                "hinweis": _get(row, hint_col) or None,
            }
        )
    return out


def parse_esco_onet(rows: Sequence[Sequence[str]]) -> list[dict[str, Any]]:
    """ESCO↔O*NET crosswalk: columns detected by value shape (ESCO URI / O*NET-SOC code)."""
    esco_col = _col_by_values(rows, lambda v: bool(ESCO_OCC_RE.match(v.strip())), min_share=0.3)
    onet_col = _col_by_values(rows, lambda v: bool(ONET_SOC_RE.match(v.strip())), min_share=0.3)
    if esco_col is None or onet_col is None:
        return []
    header_idx = _find_header(rows, ("esco",), ("onet", "o*net", "soc"))
    header = rows[header_idx] if header_idx is not None else []
    esco_title = _col_by_header(header, ("esco title", "esco label", "esco occupation title", "esco_title",
                                         "esco preferred"))  # fmt: skip
    onet_title = _col_by_header(
        header, ("onet title", "o*net title", "onet-soc title", "onet_title", "o*net-soc title")
    )
    match_col = _col_by_header(header, ("match", "relation", "mapping type", "type"))
    out = []
    seen = set()
    for row in rows:
        uri = _get(row, esco_col)
        soc = _get(row, onet_col)
        if not (ESCO_OCC_RE.match(uri) and ONET_SOC_RE.match(soc)):
            continue
        if (uri, soc) in seen:
            continue
        seen.add((uri, soc))
        out.append(
            {
                "esco_uri": uri,
                "onet_soc": soc,
                "esco_titel": _get(row, esco_title) or None,
                "onet_titel": _get(row, onet_title) or None,
                "art": _get(row, match_col) or None,
            }
        )
    return out
