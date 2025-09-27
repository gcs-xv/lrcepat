import re
import io
import unicodedata
from datetime import datetime
from collections import defaultdict, OrderedDict

import streamlit as st
from docx import Document

# ==========================
# Helpers: cleaning
# ==========================
def strip_invisibles(s: str) -> str:
    if s is None:
        return ""
    # buang char kontrol tapi biarkan \n\t
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t"))
    # buang ZWSP, ZWNJ, WJ, NBSP, NNBSP
    s = (s.replace("\u200b", "")
           .replace("\u200c", "")
           .replace("\u200d", "")
           .replace("\u2060", "")
           .replace("\ufeff", "")
           .replace("\u00a0", " ")
           .replace("\u202f", " "))
    # seragamkan colon
    s = s.replace("：", ":")
    # rapikan spasi ganda
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def remove_wa_prefix(line: str) -> str:
    # [26/09/25, 10.15.48] Nama: ...
    return re.sub(r"^\[\d{1,2}/\d{1,2}/\d{2,4},[^\]]+\]\s*[^:]+:\s*", "", line).strip()

def normalize_bullet(line: str) -> str:
    l = line.lstrip()
    if re.match(r"^[•\-\*]\s*", l):
        return "* " + re.sub(r"^[•\-\*]\s*", "", l)
    return line

def collapse_softwraps(lines):
    # gabungkan baris lanjutan yg jelas bukan field baru/section/bullet
    out = []
    buf = ""
    def flush():
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""
    for ln in lines:
        if not ln.strip():
            flush()
            continue
        # deteksi start blok, key:val, bullet, SECTION
        if (re.match(r"^\s*\d{1,3}[.)]?\s*Nama\s*:", ln, flags=re.I) or
            re.match(r"^\s*[A-Za-z].+?:", ln) or
            re.match(r"^\s*\*\s+", ln) or
            is_section_title(ln)):
            flush()
            out.append(ln)
        else:
            # baris lanjutan → sambung
            if buf:
                buf += " " + ln.strip()
            else:
                buf = ln.strip()
    flush()
    return out

# ==========================
# Section detection
# ==========================
SECTION_LABELS = [
    "POLI INTEGRASI",
    "VIP",
    "BAKSOS",
    "BAKSOS CCC",
]

def is_section_title(line: str) -> bool:
    raw = strip_invisibles(line)
    # match “POLI INTEGRASI”, “VIP”, “BAKSOS …” (huruf besar, boleh spasi)
    if raw.upper() in [s.upper() for s in SECTION_LABELS]:
        return True
    # amankan variasi: baris kapital penuh tanpa titik/colon
    if re.match(r"^[A-Z ]{3,}$", raw) and ":" not in raw:
        return True
    return False

def canon_section(line: str) -> str:
    raw = strip_invisibles(line).upper()
    for s in SECTION_LABELS:
        if raw == s.upper():
            return s
    # fallback: pakai raw
    return strip_invisibles(line)

# ==========================
# DPJP canonical
# ==========================
DPJP_CANONICAL = OrderedDict({
    "mohammad gazali": "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "abul fauzi": "drg. Abul Fauzi, Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "m. irfan rasul": "drg. M. Irfan Rasul, Ph.D., Sp.B.M.M., Subsp.C.O.M.(K)",
    "m irfan rasul": "drg. M. Irfan Rasul, Ph.D., Sp.B.M.M., Subsp.C.O.M.(K)",
    "mukhtar nur anam": "drg. Mukhtar Nur Anam, Sp.B.M.M.",
    "husnul basyar": "drg. Husnul Basyar, Sp. B.M.M.",
    "husni mubarak": "drg. Husni Mubarak, Sp.B.M.M.",
    "nurwahida": "drg. Nurwahida, M.KG., Sp.B.M.M., Subsp.C.O.M.(K)",
    "andi tajrin": "drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "carolina stevanie": "drg. Carolina Stevanie, Sp.B.M.M.",
    "timurwati": "drg. Timurwati, Sp.B.M.M.",
    "yossy yoanita": "drg. Yossy Yoanita Ariestiana, Sp.B.M.M., Subsp.Ortognat-D(K).",
})

DPJP_ORDER = [
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. Abul Fauzi, Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. M. Irfan Rasul, Ph.D., Sp.B.M.M., Subsp.C.O.M.(K)",
    "drg. Mukhtar Nur Anam, Sp.B.M.M.",
    "drg. Husnul Basyar, Sp. B.M.M.",
    "drg. Husni Mubarak, Sp.B.M.M.",
    "drg. Nurwahida, M.KG., Sp.B.M.M., Subsp.C.O.M.(K)",
    "drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
    "drg. Timurwati, Sp.B.M.M.",
    "drg. Yossy Yoanita Ariestiana, Sp.B.M.M., Subsp.Ortognat-D(K).",
]

def canonicalize_dpjp(s: str) -> str:
    if not s:
        return s
    s = s.replace("Drg.", "drg.").replace("DRG.", "drg.")
    s = re.sub(r"\bdrg\.\s*drg\.\s*", "drg. ", s, flags=re.I)
    s = strip_invisibles(s)
    low = s.lower()
    name_only = re.sub(r"^drg\.\s*", "", low)
    name_only = re.sub(r",.*$", "", name_only).strip()
    for k, v in DPJP_CANONICAL.items():
        if k in name_only:
            return v
    return s

# ==========================
# Parsing logic
# ==========================
FIELD_ALIASES = {
    "nama": r"Nama",
    "tgl": r"Tanggal lahir",
    "rm": r"RM",
    "diagnosa": r"Diagnosa",
    "tindakan": r"Tindakan",
    "kontrol": r"Kontrol",
    "dpjp": r"DPJP",
    "telp": r"No\.?\s*Telp\.?",
    "operator": r"Operator",
}
KEY_PATTERN = re.compile(r"^([A-Za-z .]+)\s*:\s*(.*)$")

START_BLOCK = re.compile(r"^\s*(\d{1,3})[.)]?\s*Nama\s*:\s*(.*)$", flags=re.I)

def parse_chat(text: str):
    # pre-process
    lines = [normalize_bullet(strip_invisibles(remove_wa_prefix(l))) for l in text.splitlines()]
    lines = [l for l in lines if l is not None]
    lines = collapse_softwraps(lines)

    sections = defaultdict(list)
    current_section = "POLI INTEGRASI"
    current = None
    in_tindakan = False
    last_key = None

    def push_current():
        nonlocal current
        if current:
            # finalize tindakan
            if "tindakan_list" in current:
                current["tindakan"] = [t for t in current["tindakan_list"] if t]
                del current["tindakan_list"]
            sections[current_section].append(current)
        current = None

    for ln in lines:
        if not ln.strip():
            continue

        # SECTION
        if is_section_title(ln):
            push_current()
            current_section = canon_section(ln)
            continue

        # START PATIENT
        m = START_BLOCK.match(ln)
        if m:
            push_current()
            idx = int(m.group(1))
            nama = strip_invisibles(m.group(2))
            current = {"idx": idx, "nama": nama}
            in_tindakan = False
            last_key = None
            continue

        if current is None:
            continue

        # KEY : VALUE line
        kv = KEY_PATTERN.match(ln)
        if kv:
            key_raw = kv.group(1).strip()
            val = kv.group(2).strip()
            std_key = None
            for k, patt in FIELD_ALIASES.items():
                if re.fullmatch(patt, key_raw, flags=re.I):
                    std_key = k
                    break

            if std_key == "tindakan":
                in_tindakan = True
                last_key = "tindakan"
                current.setdefault("tindakan_list", [])
                if val:
                    if val.startswith("*"):
                        current["tindakan_list"].append(val[1:].strip())
                    else:
                        current["tindakan_list"].append(val)
                continue
            else:
                in_tindakan = False

            if std_key:
                # field biasa
                current[std_key] = val
                last_key = std_key
            else:
                last_key = None
            continue

        # BULLET tindakan
        if in_tindakan and ln.lstrip().startswith("*"):
            current.setdefault("tindakan_list", []).append(ln.lstrip()[1:].strip())
            continue

        # MULTILINE untuk Diagnosa/Kontrol (atau field terakhir lain)
        if last_key in ("diagnosa", "kontrol"):
            # tambahkan baris lanjutan (tanpa tanda * )
            extra = ln.lstrip()
            if extra.startswith("*"):
                # beberapa chat menaruh subtugas di diagnosa → simpan sebagai lanjutan teks
                extra = extra[1:].strip()
            joiner = "\n" if "\n" in current.get(last_key, "") else " "
            current[last_key] = (current.get(last_key, "").rstrip() + joiner + extra).strip()
            continue

        # Jika baris lanjutan field lain (mis. operator/telp pernah kebagi)
        if last_key and last_key not in ("tindakan",):
            current[last_key] = (current.get(last_key, "") + " " + ln.strip()).strip()
            continue

    push_current()
    return sections

# ==========================
# Dedup per section (RM>Nama), keep LAST
# ==========================
def dedup_keep_last_per_section(sections: dict):
    deduped = {}
    for sec, blocks in sections.items():
        seen = {}
        for b in blocks:
            key = b.get("rm") or (b.get("nama") or "").lower()
            if not key:
                key = f"__noname_{b.get('idx','?')}"
            seen[key] = b  # overwrite = last wins
        # kembali ke list urut idx
        arr = list(seen.values())
        arr.sort(key=lambda x: int(x.get("idx", 9999)))
        deduped[sec] = arr
    return deduped

# ==========================
# Formatting for WhatsApp
# ==========================
LBL_WIDTH = 14  # lebar label setelah bullet
def line_kv(label, value):
    # bullet '•' + dua spasi, label kiri rata, colon sejajar
    return f"•  {label:<{LBL_WIDTH}}: {value}"

def format_patient(idx, b):
    nama = b.get("nama", "-")
    tgl = b.get("tgl", "-")
    rm = b.get("rm", "-")
    diagnosa = b.get("diagnosa", "-")
    tindakan = b.get("tindakan", [])
    if isinstance(tindakan, str):
        tindakan = [tindakan] if tindakan else []
    kontrol = b.get("kontrol", "-")
    dpjp = canonicalize_dpjp(b.get("dpjp", ""))
    telp = b.get("telp", "-")
    operator = b.get("operator", "-")

    lines = []
    lines.append(f"{idx}. Nama            : {nama}")
    lines.append(line_kv("Tanggal lahir", tgl))
    lines.append(line_kv("RM", rm))
    lines.append(line_kv("Diagnosa", diagnosa))
    if tindakan:
        lines.append(line_kv("Tindakan", ""))
        for t in tindakan:
            lines.append(f"   * {t}")
    else:
        lines.append(line_kv("Tindakan", "-"))
    lines.append(line_kv("Kontrol", kontrol))
    lines.append(line_kv("DPJP", dpjp))
    lines.append(line_kv("No. Telp.", telp))
    lines.append(line_kv("Operator", operator))
    return "\n".join(lines), dpjp

def format_summary_block(text):
    # cari baris “Jumlah pasien”, “Tindakan”, dst lalu rata kolom
    lines = []
    for key in ["Jumlah pasien", "Tindakan", "Konsultasi", "Terjaring GA", "VIP", "Baksos"]:
        m = re.search(rf"^{key}\s*:.*$", text, flags=re.I | re.M)
        if m:
            raw = strip_invisibles(m.group(0))
            label, val = [t.strip() for t in raw.split(":", 1)]
            lines.append(f"{label:<16}: {val}")
    return lines

def build_output(kop_title, raw_text, deduped_sections):
    out = []
    # KOP bold
    if kop_title:
        out.append(f"*{kop_title}*")
        out.append("")
    # summary numbers (optional)
    out.extend(format_summary_block(raw_text))
    if len(out) > 1:  # ada summary
        out.append("")
        out.append("-" * 60)
        out.append("")

    all_dpjp_used = set()

    # urutan section: POLI INTEGRASI, VIP, BAKSOS CCC, BAKSOS, lainnya
    section_order = []
    for s in ["POLI INTEGRASI", "VIP", "BAKSOS CCC", "BAKSOS"]:
        if s in deduped_sections and deduped_sections[s]:
            section_order.append(s)
    # sisanya (kalau ada)
    for s in deduped_sections.keys():
        if s not in section_order and deduped_sections[s]:
            section_order.append(s)

    for sec in section_order:
        out.append(f"*{sec}*")
        out.append("")
        blocks = deduped_sections[sec]
        idx = 1
        pretty = []
        for b in blocks:
            blk, dp = format_patient(idx, b)
            pretty.append(blk)
            if dp:
                all_dpjp_used.add(canonicalize_dpjp(dp))
            idx += 1
        out.extend("\n\n".join(pretty).splitlines())
        out.append("")

    out.append("-" * 60)
    out.append("")
    # DPJP akhir (hanya yang dipakai, urut hirarki)
    used_sorted = [d for d in DPJP_ORDER if d in all_dpjp_used]
    if used_sorted:
        out.append("*DPJP :*")
        for i, d in enumerate(used_sorted, 1):
            out.append(f"{i}. {d}")
        out.append("")

    return "\n".join(out).rstrip()

# ==========================
# Streamlit UI
# ==========================
st.set_page_config(page_title="Parser Review Poli BM → WhatsApp", layout="wide")
st.title("Parser Review Poli BM → WhatsApp")

uploaded = st.file_uploader("Upload chat (.docx)", type=["docx"])
default_kop = f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {datetime.now().strftime('%A (%d/%m/%Y)')}"
kop_title = st.text_input("Kop (akan di-bold)", value=default_kop)

if uploaded:
    try:
        doc = Document(io.BytesIO(uploaded.read()))
        raw_text = "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        st.error(f"Gagal membuka DOCX: {e}")
        st.stop()

    raw_text_clean = "\n".join(strip_invisibles(x) for x in raw_text.splitlines())

    # Parsing
    sections = parse_chat(raw_text_clean)
    if not any(sections.values()):
        st.error("Tidak ditemukan blok review dengan pola 'X. Nama : ...'. Pastikan format chat sesuai.")
        st.stop()

    # Dedup per section (pakai RM > Nama), ambil chat terakhir
    deduped = dedup_keep_last_per_section(sections)

    # Build WA text
    final_text = build_output(kop_title.strip(), raw_text_clean, deduped)

    st.subheader("Hasil (siap copas ke WhatsApp)")
    st.text_area("Output", value=final_text, height=700)
    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_poli_integrasi.txt")

    st.caption("Catatan: Parser tahan format WA, field multi-baris terjaga, DPJP dinormalisasi & dibold sesuai hirarki.")
else:
    st.info("Upload file .docx chat WA untuk diproses.")
