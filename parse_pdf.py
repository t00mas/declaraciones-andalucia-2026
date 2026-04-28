#!/usr/bin/env python3
"""Parse BOJA candidate declarations PDF into candidates.json."""
import subprocess, re, json
from pathlib import Path

PDF = Path(__file__).parent / "boja26-207901-00201-5604-01-00336841-combinado.pdf"
OUT = Path(__file__).parent / "candidates.json"

# Column headers per section
COLS = {
    "1.1": ["Entidad u organismo", "Cargo desempeñado", "Fecha de nombramiento"],
    "1.2": ["Entidad, organismo, empresa o sociedad", "Actividad desempeñada", "Fecha de inicio"],
    "1.3": ["Actividad", "Empresa en la que se trabaja/Autónomo"],
    "2.1": ["Clave", "Tipo", "Situación", "Valor catastral (euros)"],
    "2.3": ["Entidad", "Valor (euros)"],
    "2.4": ["Descripción", "Valor (euros)"],
    "2.5": ["Descripción", "Valor (euros)"],
    "2.6": ["Descripción", "Valor (euros)"],
}

# Sections where pdftotext outputs column-major (all values for col1, then all for col2)
COL_MAJOR_SECTIONS = {"2.3", "2.4", "2.5", "2.6"}


def extract_text():
    return subprocess.check_output(
        ["pdftotext", "-nopgbrk", str(PDF), "-"], stderr=subprocess.DEVNULL
    ).decode("utf-8")


def clean_headers(text):
    text = re.sub(r"Depósito Legal:[^\n]+\n\s*https?://[^\n]+\n", "\n", text)
    text = re.sub(r"^\s*00336841\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"(?:BOJA\s*\n\s*)?Boletín Oficial de la Junta de Andalucía\s*\n[^\n]+\n\s*página \d+/\d+",
        "", text,
    )
    text = re.sub(
        r"Boletín Oficial de la Junta de Andalucía\s*\n\s*BOJA\s*\n[^\n]+\n\s*página \d+/\d+",
        "", text,
    )
    return text


def parse_money(s):
    if not s:
        return None
    s = re.sub(r"\s*\(\s*\d+[,.]?\d*\s*%\s*\)", "", s).strip()
    m = re.search(r"([\d.]+),(\d{2})", s)
    if m:
        return float(m.group(1).replace(".", "") + "." + m.group(2))
    m = re.search(r"[\d]+", s)
    if m:
        val = m.group(0)
        return float(val) if val else None
    return None


def section_text(block, sec_num):
    """Return text content after section sec_num until the next X.Y. section."""
    start_pat = re.compile(rf"(?m)^\s*{re.escape(sec_num)}\.")
    # Matches "2. CAPS" or "2.1. CAPS" — section headers at any level
    end_pat = re.compile(r"(?m)^\s*\d+\.(?:\d+\.)?\s+[A-ZÁÉÍÓÚÜÑ]")

    sm = start_pat.search(block)
    if not sm:
        return ""

    # Advance to end of first (title) line
    nl = block.find("\n", sm.end())
    if nl == -1:
        return ""

    # Skip at most 2 continuation title lines:
    # only lines that are ALL-CAPS, end with ".", and don't start a new section (no leading digit)
    for _ in range(2):
        next_nl = block.find("\n", nl + 1)
        if next_nl == -1:
            break
        line = block[nl + 1 : next_nl].strip()
        if (
            line
            and line.endswith(".")
            and not re.match(r"^\d+\.", line)
            and re.match(r"^[A-ZÁÉÍÓÚÜÑ\s,.:€%/()\d]+$", line)
        ):
            nl = next_nl
        else:
            break

    content_start = nl + 1

    em = end_pat.search(block, content_start)
    # Skip matches that are the current section itself
    while em and em.group(0).strip().startswith(sec_num + "."):
        em = end_pat.search(block, em.end())

    content_end = em.start() if em else len(block)
    return block[content_start:content_end]


def _chunks(text):
    parts = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    return [
        p for p in parts
        if p not in ("BOJA", "00336841")
        and not re.match(r"^\d+\.(?:\d+\.)?\s+[A-ZÁÉÍÓÚÜÑ]", p)
    ]


def parse_rowmajor(text, headers):
    """Row-major: first row has header+value chunks, subsequent rows have value-only chunks."""
    hset = set(headers)
    rows, current = [], {}
    col_idx = 0
    for chunk in _chunks(text):
        lines = [l.strip() for l in chunk.split("\n") if l.strip()]
        if not lines:
            continue
        if lines[0] in hset:
            col_idx = headers.index(lines[0])
            value = " ".join(lines[1:])
        else:
            value = " ".join(lines)
        if col_idx == 0 and current:
            rows.append(current)
            current = {}
        current[headers[col_idx]] = value
        col_idx = (col_idx + 1) % len(headers)
    if current:
        rows.append(current)
    return rows


def parse_colmajor(text, headers):
    """Column-major: each chunk = header followed by ALL values for that column."""
    hset = set(headers)
    col_values: dict = {h: [] for h in headers}
    current_header = None
    for chunk in _chunks(text):
        lines = [l.strip() for l in chunk.split("\n") if l.strip()]
        if not lines:
            continue
        if lines[0] in hset:
            current_header = lines[0]
            col_values[current_header].extend(lines[1:])
        elif current_header:
            col_values[current_header].extend(lines)
    max_rows = max((len(v) for v in col_values.values()), default=0)
    rows = []
    for i in range(max_rows):
        row = {}
        for h in headers:
            vals = col_values[h]
            row[h] = vals[i] if i < len(vals) else None
        rows.append(row)
    return rows


def parse_table(sec_num, text):
    headers = COLS[sec_num]
    rows = (
        parse_colmajor(text, headers)
        if sec_num in COL_MAJOR_SECTIONS
        else parse_rowmajor(text, headers)
    )
    for row in rows:
        for k in ("Valor (euros)", "Valor catastral (euros)"):
            if k in row and row[k] is not None:
                row[k] = parse_money(row[k])
    return rows


def sum_values(rows, key="Valor (euros)"):
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return round(sum(vals), 2) if vals else None


def split_nombre(s):
    """Split 'APELLIDOS, NOMBRE' into parts."""
    if "," in s:
        ap, nm = s.split(",", 1)
        return ap.strip().title(), nm.strip().title()
    return s.strip().title(), ""


def parse_candidate(block):
    nm = re.search(r"APELLIDOS, NOMBRE:\s*(.+)", block)
    pm = re.search(r"PARTIDO,[^:]+:\s*(.+)", block)
    cm = re.search(r"CIRCUNSCRIPCIÓN:\s*(.+)", block)
    if not nm:
        return None

    nombre_raw = nm.group(1).strip()
    apellidos, nombre = split_nombre(nombre_raw)

    def sec(n):
        return section_text(block, n)

    bienes = parse_table("2.1", sec("2.1"))
    acciones = parse_table("2.3", sec("2.3"))
    vehiculos = parse_table("2.4", sec("2.4"))
    seguros = parse_table("2.5", sec("2.5"))
    deudas = parse_table("2.6", sec("2.6"))

    saldo_text = sec("2.2")
    saldo_m = re.search(r"[\d.,]+\s*€", saldo_text)
    saldo = parse_money(saldo_m.group(0)) if saldo_m else None

    valor_inmuebles = sum_values(bienes, "Valor catastral (euros)")
    total_acciones = sum_values(acciones)
    total_vehiculos = sum_values(vehiculos)
    total_seguros = sum_values(seguros)
    total_deudas = sum_values(deudas)

    activos_parts = [x for x in [valor_inmuebles, saldo, total_acciones, total_vehiculos] if x is not None]
    total_activos = round(sum(activos_parts), 2) if activos_parts else None
    patrimonio = round(total_activos - total_deudas, 2) if total_activos is not None and total_deudas is not None else total_activos

    return {
        "nombre": nombre_raw,
        "apellidos": apellidos,
        "nombre_pila": nombre,
        "partido": pm.group(1).strip() if pm else "",
        "circunscripcion": cm.group(1).strip() if cm else "",
        # Summary financials (all €)
        "saldo_bancario": saldo,
        "valor_inmuebles": valor_inmuebles,
        "total_acciones": total_acciones,
        "total_vehiculos": total_vehiculos,
        "total_seguros": total_seguros,
        "total_deudas": total_deudas,
        "total_activos": total_activos,
        "patrimonio_neto": patrimonio,
        # Detail tables
        "cargos_publicos": parse_table("1.1", sec("1.1")),
        "actividades_publicas": parse_table("1.2", sec("1.2")),
        "actividades_privadas": parse_table("1.3", sec("1.3")),
        "bienes_inmuebles": bienes,
        "acciones_valores": acciones,
        "vehiculos_otros": vehiculos,
        "seguros_vida": seguros,
        "creditos_deudas": deudas,
    }


def main():
    print("Extracting text from PDF...")
    text = extract_text()
    print(f"  {len(text):,} chars")

    text = clean_headers(text)
    first = text.find("APELLIDOS, NOMBRE:")
    if first > 0:
        text = text[first:]

    blocks = re.split(r"\*{5,}", text)
    blocks = [b.strip() for b in blocks if "APELLIDOS, NOMBRE:" in b]
    print(f"  {len(blocks)} candidate blocks")

    candidates, errors = [], 0
    for block in blocks:
        c = parse_candidate(block)
        if c:
            candidates.append(c)
        else:
            errors += 1

    print(f"  {len(candidates)} parsed, {errors} errors")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    print(f"Written → {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
