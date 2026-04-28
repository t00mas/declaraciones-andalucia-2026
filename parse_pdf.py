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
    # Depósito Legal line + optional blank line + URL line
    text = re.sub(r"Depósito Legal:[^\n]+\n\s*\n?\s*https?://[^\n]+\n?", "\n", text)
    # Standalone URL lines that slipped through (e.g. when separated by extra whitespace)
    text = re.sub(r"^\s*https?://www\.juntadeandalucia\.es/eboja\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*00336841\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"(?:BOJA\s*\n\s*)?Boletín Oficial de la Junta de Andalucía\s*\n[^\n]+\n\s*página \d+/\d+",
        "", text,
    )
    text = re.sub(
        r"Boletín Oficial de la Junta de Andalucía\s*\n\s*BOJA\s*\n[^\n]+\n\s*página \d+/\d+",
        "", text,
    )
    # Date lines and standalone BOJA residue
    text = re.sub(r"^\s*Número \d+ C\d+ - [^\n]+\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*página \d+/\d+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*BOJA\s*$", "", text, flags=re.MULTILINE)
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


_JUNK = re.compile(
    r"^(?:BOJA|00336841"
    r"|Depósito Legal:[^\n]+"
    r"|https?://www\.juntadeandalucia\.es/eboja"
    r"|Boletín Oficial de la Junta de Andalucía"
    r"|Número \d+ C\d+ - .+"
    r"|página \d+/\d+"
    r")$"
)

def _chunks(text):
    parts = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    return [
        p for p in parts
        if not _JUNK.match(p)
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


_ALL_HEADERS = frozenset(h for v in COLS.values() for h in v)


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
        elif lines[0] in _ALL_HEADERS:
            break  # displaced content from another section starts here
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
    cargos = parse_table("1.1", sec("1.1"))

    # pdftotext sometimes displaces the "Entidad u organismo" column from section 1.1
    # into section 2.1's text range. Detect and recover: remove phantom bienes rows and
    # backfill the entity into the first cargos entry.
    phantom = [r for r in bienes if str(r.get("Clave", "")).startswith("Entidad u organismo")]
    if phantom and cargos:
        entity = re.sub(r"^Entidad u organismo\s*", "", phantom[0]["Clave"]).strip()
        if entity:
            cargos[0].setdefault("Entidad u organismo", entity)
        bienes = [r for r in bienes if r not in phantom]

    # Some bienes rows have the valor catastral stuck in the Clave, Tipo or Situación field
    # because pdftotext displaced columns. Recover the value when Valor catastral is missing.
    _money_pat = re.compile(r"^[\d.,\s]+€")
    _all_money = re.compile(r"[\d.]+,\d{2}")
    for r in bienes:
        if r.get("Valor catastral (euros)") is not None:
            continue
        for field in ("Clave", "Tipo", "Situación"):
            val_str = str(r.get(field) or "")
            if _money_pat.match(val_str):
                # Sum all money values in the field (merged multi-row chunks have multiple)
                vals = [float(m.replace(".", "").replace(",", ".")) for m in _all_money.findall(val_str)]
                r["Valor catastral (euros)"] = round(sum(vals), 2) if vals else None
                if field == "Clave":
                    r["Clave"] = None
                break

    # When two properties are merged into one row, the second value ends up in Situación.
    # Detect: Situación contains money AND its value differs from the already-set Valor
    # (if equal, Situación WAS the valor source and there's no extra row to add).
    extra_bienes = []
    for r in bienes:
        sit = str(r.get("Situación") or "")
        if _money_pat.match(sit):
            sit_val = parse_money(sit)
            existing = r.get("Valor catastral (euros)")
            if sit_val is not None and existing is not None and abs(sit_val - existing) > 0.01:
                extra_bienes.append({"Clave": None, "Tipo": None, "Situación": None,
                                     "Valor catastral (euros)": sit_val})
    bienes = bienes + extra_bienes

    # Filter phantom bienes rows: cross-section leaks and fully-empty ghost rows.
    _phantom_clave = re.compile(
        r"^(?:Actividad|Entidad[ ,]|DEPÓSITOS Y OTROS VALORES|VALORES MOBILIARIOS)",
        re.IGNORECASE,
    )
    bienes = [
        r for r in bienes
        if not _phantom_clave.match(str(r.get("Clave") or ""))
        and any(v for v in r.values() if v is not None and v != "")
    ]

    # Recover displaced Entidad for null-entity acciones. pdftotext sometimes outputs the
    # Entidad column of section 2.3 after subsequent section headers. Look for it in the
    # block text outside the 2.3 range and backfill into rows that have a value but no entity.
    null_acc = [r for r in acciones if r.get("Entidad") is None and r.get("Valor (euros)") is not None]
    if null_acc:
        m23 = re.search(r"(?m)^\s*2\.3\.", block)
        if m23:
            after_23 = block[m23.end():]
            em = re.search(r"(?m)^Entidad\s*$", after_23)
            if em:
                entity_lines = [
                    l.strip() for l in after_23[em.end():].split("\n")
                    if l.strip() and not re.match(r"^\d+\.", l.strip())
                ]
                for r, entity in zip(null_acc, entity_lines[:len(null_acc)]):
                    r["Entidad"] = entity

    # When pdftotext displaces section 2.4/2.5/2.6 content into the 2.3 text range,
    # parse_colmajor produces null-Entidad rows (because "Descripción" != "Entidad").
    # Detect via "Descripción" header in 2.3 text, re-parse using 2.4 column format,
    # then classify: deudas → creditos_deudas, seguros → seguros_vida, rest → vehiculos_otros.
    sec23_text = sec("2.3")
    # seguro check before deuda: "SEGURO VIDA HIPOTECARIO" must match seguro, not hipoteca
    _seg_kw = re.compile(r"(?i)(segur|póliza)")
    _deu_kw = re.compile(r"(?i)(hipoteca|préstamo|prestamo|crédito|credito|financiaci|pago\s+hip)")
    if (any(r.get("Entidad") is None and r.get("Valor (euros)") is not None for r in acciones)
            and re.search(r"(?m)^Descripción\s*$", sec23_text)):
        displaced_rows = parse_table("2.4", sec23_text)
        for row in displaced_rows:
            desc = str(row.get("Descripción") or "").strip()
            val = row.get("Valor (euros)")
            if val is None:
                continue
            if _seg_kw.search(desc):
                seguros.append(row)
            elif _deu_kw.search(desc):
                deudas.append(row)
            else:
                vehiculos.append(row)
        acciones = [r for r in acciones if r.get("Entidad") is not None or r.get("Valor (euros)") is None]

    # Re-route deuda/seguro/acciones items displaced into vehiculos (2.4 area).
    _seg_term = re.compile(r"(?i)(seguro|protec|póliza|amortizac|vida\b)")
    _bank_kw = re.compile(r"(?i)(kutxabank|caizabank|caixabank|kutxa\b|bbva|unicaja|sabadell|ibercaja|bankia|la\s+caixa)")
    veh_clean = []
    for row in vehiculos:
        desc = str(row.get("Descripción") or "").strip()
        if _seg_kw.search(desc):
            seguros.append(row)
        elif _deu_kw.search(desc):
            deudas.append(row)
        elif _bank_kw.search(desc):
            if _seg_term.search(desc):
                seguros.append({"Descripción": desc, "Valor (euros)": row.get("Valor (euros)")})
            else:
                acciones.append({"Entidad": desc, "Valor (euros)": row.get("Valor (euros)")})
        else:
            veh_clean.append(row)
    vehiculos = veh_clean

    # Re-route pure deudas displaced into seguros (2.5 area).
    # "SEGURO DE VIDA HIPOTECARIO" is a valid seguro; plain "HIPOTECA" / "PRÉSTAMO" is a deuda.
    seg_clean = []
    for row in seguros:
        desc = str(row.get("Descripción") or "").strip()
        if _deu_kw.search(desc) and not _seg_term.search(desc):
            deudas.append(row)
        else:
            seg_clean.append(row)
    seguros = seg_clean

    # Drop phantom acciones rows with neither Entidad nor Valor (parse_colmajor artifacts).
    acciones = [r for r in acciones if r.get("Entidad") is not None or r.get("Valor (euros)") is not None]

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
        "cargos_publicos": cargos,
        "actividades_publicas": parse_table("1.2", sec("1.2")),
        "actividades_privadas": parse_table("1.3", sec("1.3")),
        "bienes_inmuebles": bienes,
        "acciones_valores": acciones,
        "vehiculos_otros": vehiculos,
        "seguros_vida": seguros,
        "creditos_deudas": deudas,
    }


# Manually corrected bienes_inmuebles for candidates where pdftotext layout
# is too garbled to fix programmatically. Keyed by nombre (APELLIDOS, NOMBRE).
# Only bienes_inmuebles is overridden; aggregates are recalculated automatically.
BIENES_OVERRIDES = {
    "MORENO BONILLA, JUAN MANUEL": [
        {"Clave": "N", "Tipo": "R", "Situación": "Málaga (50,00 %) - Cártama inmueble rústico (herencia 50 %)", "Valor catastral (euros)": 14933.0},
        {"Clave": "N", "Tipo": "R", "Situación": "Málaga (50,00 %) - Cártama parcela rústica (herencia 50 %)", "Valor catastral (euros)": 4510.0},
    ],
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
    # Some blocks are missing the ***** separator — split at extra APELLIDOS occurrences.
    split_blocks = []
    for b in blocks:
        parts = re.split(r"(?=APELLIDOS, NOMBRE:)", b)
        split_blocks.extend(p.strip() for p in parts if "APELLIDOS, NOMBRE:" in p)
    blocks = split_blocks
    print(f"  {len(blocks)} candidate blocks")

    candidates, errors = [], 0
    for block in blocks:
        c = parse_candidate(block)
        if c:
            if c["nombre"] in BIENES_OVERRIDES:
                rows = BIENES_OVERRIDES[c["nombre"]]
                c["bienes_inmuebles"] = rows
                c["valor_inmuebles"] = sum(r["Valor catastral (euros)"] for r in rows if r.get("Valor catastral (euros)"))
                activos = sum(filter(None, [c["valor_inmuebles"], c["saldo_bancario"],
                                            c["total_acciones"], c["total_vehiculos"], c["total_seguros"]]))
                c["total_activos"] = round(activos, 2) if activos else None
                deudas = c["total_deudas"] or 0
                c["patrimonio_neto"] = round(activos - deudas, 2) if activos else None
            candidates.append(c)
        else:
            errors += 1

    print(f"  {len(candidates)} parsed, {errors} errors")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    print(f"Written → {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
