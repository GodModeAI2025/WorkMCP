"""O*NET database files (US Department of Labor/ETA, CC BY 4.0).

Files are tab-delimited text with a header row, published per release under
``https://www.onetcenter.org/dl_files/database/db_<major>_<minor>_text/<File Name>.txt``.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..config import Settings
from ..http import HttpClient, NotFoundError

FILES = {
    "berufe": "Occupation Data.txt",
    "aufgaben": "Task Statements.txt",
    "alternativtitel": "Alternate Titles.txt",
}
_VERSION_RE = re.compile(r"db_(\d+)_(\d+)_(?:text|excel|mysql|mssql|oracle)")
SOC_RE = re.compile(r"^\d{2}-\d{4}(\.\d{2})?$")


def normalize_soc(code: str) -> str:
    code = code.strip()
    return code if "." in code else f"{code}.00"


def parse_tsv(text: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        rows.append({header[i]: cells[i].strip() if i < len(cells) else "" for i in range(len(header))})
    return rows


def detect_version_from_html(html: str) -> str | None:
    versions = {(int(a), int(b)) for a, b in _VERSION_RE.findall(html)}
    if not versions:
        return None
    major, minor = max(versions)
    return f"{major}_{minor}"


def task_record(row: dict[str, str]) -> tuple[str, dict[str, Any], str] | None:
    soc = row.get("O*NET-SOC Code", "").strip()
    task_id = row.get("Task ID", "").strip()
    task = row.get("Task", "").strip()
    if not (soc and task_id and task):
        return None
    incumbents = row.get("Incumbents Responding", "").strip()
    data = {
        "soc": soc,
        "task_id": task_id,
        "task": task,
        "task_type": row.get("Task Type", "").strip() or None,
        "incumbents_responding": int(incumbents) if incumbents.isdigit() else None,
        "date": row.get("Date", "").strip() or None,
        "domain_source": row.get("Domain Source", "").strip() or None,
    }
    return f"{soc}#{task_id}", data, task


def occupation_record(row: dict[str, str]) -> tuple[str, dict[str, Any], str] | None:
    soc = row.get("O*NET-SOC Code", "").strip()
    title = row.get("Title", "").strip()
    if not (soc and title):
        return None
    return soc, {"soc": soc, "titel": title, "beschreibung": row.get("Description", "").strip() or None}, title


def alternate_title_rows(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    by_soc: dict[str, list[str]] = {}
    for row in rows:
        soc = row.get("O*NET-SOC Code", "").strip()
        alt = row.get("Alternate Title", "").strip()
        if soc and alt:
            by_soc.setdefault(soc, []).append(alt)
    return by_soc


def read_local(path: str | Path, wanted: list[str]) -> dict[str, str]:
    """Read O*NET text files from a directory or a database zip archive."""
    p = Path(path).expanduser()
    out: dict[str, str] = {}
    if p.is_dir():
        for name in wanted:
            candidates = list(p.rglob(name))
            if candidates:
                out[name] = candidates[0].read_text(encoding="utf-8", errors="replace")
        return out
    if p.is_file() and zipfile.is_zipfile(p):
        return read_zip(p.read_bytes(), wanted)
    if p.is_file() and len(wanted) == 1:
        out[wanted[0]] = p.read_text(encoding="utf-8", errors="replace")
        return out
    raise FileNotFoundError(f"O*NET-Quelle nicht gefunden: {p}")


def read_zip(content: bytes, wanted: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for info in zf.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if base in wanted:
                out[base] = zf.read(info).decode("utf-8", errors="replace")
    return out


class OnetClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def detect_version(self) -> str | None:
        try:
            html = await self.http.get_text(self.settings.onet_database_page)
        except Exception:
            return None
        return detect_version_from_html(html)

    def file_url(self, version: str, filename: str) -> str:
        return f"{self.settings.onet_base}/db_{version}_text/{quote(filename)}"

    async def download(self, version: str, filenames: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        missing = []
        for name in filenames:
            try:
                out[name] = await self.http.get_text(self.file_url(version, name))
            except NotFoundError:
                missing.append(name)
        if missing:
            archive = await self.http.get_bytes(f"{self.settings.onet_base}/db_{version}_text.zip")
            out.update(read_zip(archive, missing))
        return out
