import re
import io
import unicodedata
from datetime import datetime
import streamlit as st
from docx import Document

# ==========================
# Utilities
# ==========================
def strip_invisibles(s: str) -> str:
    if not s:
        return s
    # buang karakter tak kasat mata (ZWSP, ZWNJ, RLM, LRM, dsb) & normalisasi spaces
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t"))
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    s = s.replace("\u202f", " ").replace("\u00a0", " ")
    # rapikan titik yang aneh
    s = re.sub(r"[：:]", ":", s)
    # satukan multiple spaces
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def remove_wa_prefix(line: str) -> str:
    # contoh: [26/09/25, 10.15.48] Nama Pengirim: <isi>
    return re.sub(r"^\[\d{1,2}/\d{1,2}/\d{2,4},[^\]]+\]\s*[^:]+:\s*", "", line).strip()

def normalize_bullets(line: str) -> str:
    # seragamkan bullet awal baris: "•" atau "*" -> "* "
    line = line.lstrip()
    if re.match(r"^[•\-\*]\s*", line):
        return "* " + re.sub(r"^[•\-\*]\s*", "", line)
    return line

def collapse_softwraps(lines):
    # gabung baris yang “lanjutan” (bukan field baru dan bukan bullet tindakan)
    out = []
    buf = ""
    for ln in lines:
        if not ln.strip():
            if buf:
                out.append(buf)
                buf = ""
            continue
        if re.match(r"^\s*\d{1,3}[.)]?\s*Nama\s*:", ln, flags=re.I) or re.match(r"^\s*[•\*]\s+", ln) or re.match(r"^\s*[A-Za-z].*?:", ln):
            if buf:
                out.append(buf)
                buf = ""
            out.append(ln)
        else:
            if buf:
                buf += " " + ln.strip()
            else:
                buf = ln
    if buf:
        out.append(buf)
    return out

# ==========================
# DPJP canonical map
# ==========================
DPJP_CANONICAL = {
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
}

# fallback urutan hierarki default (untuk bagian DPJP akhir)
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
]

def canonicalize_dpjp(raw: str) -> str:
    if not raw:
        return raw
    s = raw
    s = s.replace("Drg.", "drg.").replace("Dr.", "dr.").replace("DRG.", "drg.")
    s = re.sub(r"\bdrg\.\s*drg\.\s*", "drg. ", s, flags=re.I)  # "drg. drg." -> "drg."
    s = strip_invisibles(s)
    s_low = s.lower()
    # ambil nama inti (buang gelar di belakang ketika matching)
    name_only = re.sub(r"^drg\.\s*", "", s_low)
    name_only = re.sub(r",.*$", "", name_only).strip()

    # cari key terdekat di canonical (contains)
    best = None
    for k, v in DPJP_CANONICAL.items():
        if k in name_only:
            best = v
            break
    return best or s

# ==========================
# Parsing
# ==========================
FIELD_KEYS = {
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

start_pat = re.compile(r"^\s*(\d{1,3})[.)]?\s*Nama\s*:", flags=re.I)

def parse_reviews(text: str):
    lines = [normalize_bullets(strip_invisibles(remove_wa_prefix(l))) for l in text.splitlines()]
    lines = [l for l in lines if l is not None]
    lines = collapse_softwraps(lines)

    blocks = []
    current = None
    in_tindakan = False

    def push_current():
        nonlocal current
        if current:
            # normalize tindakan join
            if "tindakan_list" in current:
                current["tindakan"] = [t for t in current["tindakan_list"] if t]
                del current["tindakan_list"]
            blocks.append(current)
            current = None

    for ln in lines:
        if not ln.strip():
            continue

        if start_pat.match(ln):
            # block baru
            push_current()
            idx = int(re.search(r"\d{1,3}", ln).group(0))
            nama = ln.split(":", 1)[1].strip()
            current = {"idx": idx, "nama": nama}
            in_tindakan = False
            continue

        if current is None:
            # skip baris di luar block
            continue

        # field key-value
        kv = re.match(r"^([A-Za-z .]+)\s*:\s*(.*)$", ln)
        if kv:
            key_raw = kv.group(1).strip().lower()
            val = kv.group(2).strip()

            # map key
            matched_key = None
            for std_key, patt in FIELD_KEYS.items():
                if re.match(rf"^{patt}$", key_raw, flags=re.I):
                    matched_key = std_key
                    break

            if matched_key == "tindakan":
                in_tindakan = True
                current.setdefault("tindakan_list", [])
                if val:
                    # bila di baris sama ada isi
                    if val.startswith("*"):
                        current["tindakan_list"].append(val[1:].strip())
                    else:
                        current["tindakan_list"].append(val.strip())
                continue
            else:
                in_tindakan = False

            if matched_key:
                current[matched_key] = val
            continue

        # baris tindakan lanjutan (bullet)
        if in_tindakan and ln.lstrip().startswith("*"):
            current.setdefault("tindakan_list", []).append(ln.lstrip()[1:].strip())
            continue

        # fallback: kalau bukan bullet, bukan KV — abaikan
        continue

    push_current()
    return blocks

# ==========================
# Dedup logic (pakai RM bila ada, else Nama) -> keep last
# ==========================
def dedup_keep_last(blocks):
    seen = {}
    for b in blocks:
        key = b.get("rm") or b.get("nama", "").lower()
        if not key:
            key = f"__noname_{b.get('idx','?')}"
        seen[key] = b  # overwrite => last one wins
    # urutkan berdasarkan idx naik (kalau sama, biar stabil)
    result = list(seen.values())
    result.sort(key=lambda x: int(x.get("idx", 9999)))
    return result

# ==========================
# Format output WA
# ==========================
def format_patient_block(i, b, dpjp_canon=True):
    nama = b.get("nama", "-")
    tgl = b.get("tgl", "-")
    rm = b.get("rm", "-")
    diagnosa = b.get("diagnosa", "-")
    tindakan = b.get("tindakan", [])
    if isinstance(tindakan, str):
        tindakan = [tindakan] if tindakan else []
    kontrol = b.get("kontrol", "-")
    dpjp = b.get("dpjp", "")
    if dpjp_canon:
        dpjp = canonicalize_dpjp(dpjp)
    telp = b.get("telp", "-")
    operator = b.get("operator", "-")

    # rapikan label agar konsisten (tanpa kolom jagged)
    lines = []
    lines.append(f"{i}. Nama            : {nama}")
    lines.append(f"•  Tanggal lahir  : {tgl}")
    lines.append(f"•  RM             : {rm}")
    lines.append(f"•  Diagnosa       : {diagnosa}")
    if tindakan:
        lines.append(f"•  Tindakan       :")
        for t in tindakan:
            lines.append(f"   * {t}")
    else:
        lines.append(f"•  Tindakan       : -")
    lines.append(f"•  Kontrol        : {kontrol}")
    lines.append(f"•  DPJP           : {dpjp}")
    lines.append(f"•  No. Telp.      : {telp}")
    lines.append(f"•  Operator       : {operator}")
    return "\n".join(lines), dpjp

def format_final(kop_title, summary_lines, patients, dpjp_order=DPJP_ORDER):
    body = []

    # KOP (bold)
    if kop_title:
        body.append(f"*{kop_title}*")
        body.append("")

    # Ringkasan angka kalau ada
    if summary_lines:
        body.extend(summary_lines)
        body.append("")
        body.append("-" * 60)
        body.append("")

    # Section poli (bold)
    body.append("*POLI INTEGRASI*")
    body.append("")

    # Isi pasien
    used_dpjp = set()
    pretty_blocks = []
    for i, b in enumerate(patients, 1):
        block_txt, dpjp = format_patient_block(i, b, dpjp_canon=True)
        pretty_blocks.append(block_txt)
        if dpjp:
            used_dpjp.add(canonicalize_dpjp(dpjp))

    body.extend("\n\n".join(pretty_blocks).splitlines())
    body.append("")
    body.append("-" * 60)
    body.append("")

    # DPJP disusun pakai urutan hirarki; hanya tampilkan yang dipakai hari itu.
    canonical_used = [d for d in dpjp_order if d in used_dpjp]
    if canonical_used:
        body.append("*DPJP :*")
        for idx, d in enumerate(canonical_used, 1):
            body.append(f"{idx}. {d}")
        body.append("")

    return "\n".join(body).rstrip()

def extract_summary_header(text: str):
    # Ambil kop & ringkasan angka jika ada
    kop = None
    lines = []
    kop_m = re.search(r"(Review jumlah pasien.*?\(\w+.*?\))", text, flags=re.I)
    if kop_m:
        kop = strip_invisibles(kop_m.group(1))
    # Ambil baris ringkasan (Jumlah pasien/Tindakan/Konsultasi/Terjaring GA/VIP/Baksos)
    for key in ["Jumlah pasien", "Tindakan", "Konsultasi", "Terjaring GA", "VIP", "Baksos"]:
        m = re.search(rf"^{key}\s*:.*$", text, flags=re.I | re.M)
        if m:
            line = strip_invisibles(m.group(0))
            # rapikan kolom ke format final (spasi tunggal)
            label, val = [t.strip() for t in line.split(":", 1)]
            lines.append(f"{label:<16}: {val}")
    return kop, lines

# ==========================
# Streamlit UI
# ==========================
st.set_page_config(page_title="Parser Review Poli BM", layout="wide")
st.title("Parser Review Poli BM → Output WhatsApp")

uploaded = st.file_uploader("Upload file chat (.docx)", type=["docx"])

default_date = datetime.now().strftime("%A (%d/%m/%Y)")
kop_input = st.text_input(
    "Judul/Kop (optional, akan dibold)",
    value=f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {default_date}"
)

if uploaded:
    try:
        doc = Document(io.BytesIO(uploaded.read()))
        raw_text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        st.error(f"Gagal membuka DOCX: {e}")
        st.stop()

    # pre-clean
    raw_text_clean = "\n".join(strip_invisibles(x) for x in raw_text.splitlines())

    # coba ambil kop & summary dari isi (kalau user kosongkan kop_input)
    auto_kop, summary_lines = extract_summary_header(raw_text_clean)
    if not kop_input and auto_kop:
        kop_title = auto_kop
    else:
        kop_title = kop_input.strip()

    blocks = parse_reviews(raw_text_clean)
    if not blocks:
        st.error("Tidak ditemukan blok review. Pastikan ada baris seperti '11. Nama : ...' di dalam chat.")
        st.stop()

    # dedup keep last
    blocks = dedup_keep_last(blocks)

    # format final
    final_text = format_final(kop_title, summary_lines, blocks)

    st.subheader("Hasil (siap copas ke WhatsApp)")
    st.text_area("Output", value=final_text, height=600)
    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_poli_integrasi.txt")

    # info kecil
    st.caption("Catatan: DPJP dinormalisasi otomatis ke format hirarki. Jika ada variasi penulisan, akan di-override.")
else:
    st.info("Upload file .docx chat WA untuk diproses.")
