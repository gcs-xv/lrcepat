import re
import io
import unicodedata
from datetime import datetime
import streamlit as st

try:
    import docx2txt
except Exception:
    docx2txt = None

from docx import Document  # untuk export .docx

# ==============================
# Util: Locale Indonesia (hari)
# ==============================
HARI_ID = {
    0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
    4: "Jumat", 5: "Sabtu", 6: "Minggu"
}

# ==============================
# Hierarki DPJP (dari user)
# ==============================
DPJP_ORDER = [
    "drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D (K)",
    "drg. Abul Fauzi, Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. M. Irfan Rasul, Ph.D., Sp.B.M.M., Subsp.C.O.M.(K)",
    "drg. Nurwahida, M.K.G., Sp.B.M.M., Subsp.C.O.M(K)",
    "drg. Hadira, M.K.G., Sp.B.M.M., Subsp.C.O.M(K)",
    "drg. Mukhtar Nur Anam Sp.B.M.M.",
    "drg. Timurwati, Sp.B.M.M.",
    "drg. Husnul Basyar, Sp. B.M.M.",
    "drg. Husni Mubarak, Sp. B.M.M.",
    "drg. Carolina Stevanie, Sp.B.M.M."
]

# =======================================================
# Normalisasi teks WA & helper buat jaga format karakter
# =======================================================
FIGURE_SPACE = "\u2007"  # untuk rata angka di depan ( )
BULLET = "•"             # bullet utama
STAR = "*"               # sub-bullet tindakan

def normalize_text(s: str) -> str:
    # Bersihin karakter arah/ZWSP dan normalisasi unicode
    s = unicodedata.normalize("NFKC", s)
    # Hilangkan \r, rapikan newline
    s = s.replace("\r", "")
    # Samakan variasi bullet ke satu bentuk
    s = s.replace("•⁠", "•").replace("• ", "•").replace("• ", "• ")
    # Samakan 'Nama    :', spasi aneh, dll
    s = re.sub(r"[ \t]+", " ", s)
    # Balikin newline ganda berlebihan
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

# =======================================================
# Parsing blok review pasien
# =======================================================
# Pola awal: "^(\d+)\.\s*Nama\s*: (.*)" (toleran huruf besar/kecil & variasi spasi)
HEADER_RE = re.compile(
    r"(?mi)^\s*(\d+)\.\s*Nama\s*:?\s*(.+?)\s*$"
)

def split_blocks(raw_text: str):
    """Pisah teks jadi blok-blok review berdasarkan baris 'X. Nama : ...' """
    blocks = []
    positions = []
    for m in HEADER_RE.finditer(raw_text):
        positions.append((m.start(), m.end(), m.group(1), m.group(2).strip()))
    for i, (start, end, num, nama) in enumerate(positions):
        stop = positions[i+1][0] if i+1 < len(positions) else len(raw_text)
        chunk = raw_text[start:stop].strip()
        blocks.append((int(num), nama, chunk))
    return blocks

def extract_field(patterns, text, default="Missing", flags=re.IGNORECASE):
    if isinstance(patterns, str):
        patterns = [patterns]
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            val = m.group(1).strip()
            val = re.sub(r"\s+", " ", val)  # rapikan spasi internal
            return val
    return default

def extract_multiline_after(label, text):
    """
    Ambil multiline setelah '• Tindakan :' sampai ketemu '• ' field berikutnya.
    Izinkan baris yang diawali '*' sebagai item.
    """
    # Temukan awal "• Tindakan"
    m = re.search(r"(?mi)^\s*•\s*Tindakan\s*:?(.*)$", text)
    if not m:
        return []

    start = m.end()
    rest = text[start:]
    lines = []
    for line in rest.splitlines():
        # Jika ketemu field berikutnya (•  Kontrol/DPJP/Diagnosa/No. Telp/Operator/dll) maka stop
        if re.match(r"(?mi)^\s*•\s*(Tanggal lahir|RM|Diagnosa|Kontrol|DPJP|No\.? Telp|Operator)\s*:?", line):
            break
        line = line.rstrip()
        if line.strip().startswith("*"):
            # Simpan apa adanya setelah normalisasi ringan
            lines.append(re.sub(r"\s+", " ", line))
        elif "Konsultasi" == line.strip():
            lines.append("Konsultasi")
        elif line.strip().startswith(BULLET):
            # baris bullet yang salah tempat → treat as item jika setelah Tindakan
            candidate = line.strip()[1:].strip()
            if candidate:
                lines.append(candidate)
        elif line.strip() == "":
            continue
    return lines

def parse_block(num, nama, chunk):
    # Field-field single line
    tgl_lahir = extract_field(r"(?mi)^\s*•\s*Tanggal lahir\s*:?\s*(.+)$", chunk)
    rm = extract_field(r"(?mi)^\s*•\s*RM\s*:?\s*(.+)$", chunk)
    diagnosa = extract_field(r"(?mi)^\s*•\s*Diagnosa\s*:?\s*(.+)$", chunk)
    kontrol = extract_field(r"(?mi)^\s*•\s*Kontrol\s*:?\s*(.+)$", chunk)
    dpjp = extract_field(r"(?mi)^\s*•\s*DPJP\s*:?\s*(.+)$", chunk)
    telp = extract_field(r"(?mi)^\s*•\s*No\.?\s*Telp\.?\s*:?\s*(.+)$", chunk)
    operator = extract_field(r"(?mi)^\s*•\s*Operator\s*:?\s*(.+)$", chunk)

    # Tindakan multiline
    tindakan_items = extract_multiline_after("Tindakan", chunk)
    if (not tindakan_items) and re.search(r"(?mi)^\s*•\s*Tindakan\s*:?\s*(.+)$", chunk):
        # kalau ada 1 baris tindakan setelah kolon
        single = extract_field(r"(?mi)^\s*•\s*Tindakan\s*:?\s*(.+)$", chunk)
        if single and single != "Missing":
            tindakan_items = [single]

    # Flag konsultasi
    is_konsul = any(re.search(r"(?i)\bKonsultasi\b", it) for it in tindakan_items)

    # Flag terjaring GA (cek di Kontrol ada frasa "dalam general anestesi (menunggu penjadwalan)")
    is_terjaring_ga = bool(re.search(r"(?i)dalam\s+general\s+anestesi\s*\(menunggu\s+penjadwalan\)", kontrol))

    return {
        "no": num,
        "nama": nama,
        "tgl_lahir": tgl_lahir,
        "rm": rm,
        "diagnosa": diagnosa,
        "tindakan_items": tindakan_items,
        "kontrol": kontrol,
        "dpjp": dpjp,
        "telp": telp,
        "operator": operator,
        "is_konsul": is_konsul,
        "is_terjaring_ga": is_terjaring_ga,
        "raw": chunk
    }

def format_patient_block(p):
    # jaga format persis (pakai figure space di depan nomor)
    lines = []
    no_str = f"{FIGURE_SPACE}{p['no']}."
    lines.append(f"{no_str}\u200A\u200ANama\u200A\u200A\u200A\u200A          : {p['nama']}")
    lines.append(f"{BULLET}  Tanggal lahir  : {p['tgl_lahir']}")
    lines.append(f"{BULLET}  RM             : {p['rm']}")
    lines.append(f"{BULLET}  Diagnosa       : {p['diagnosa']}")

    # Tindakan
    lines.append(f"{BULLET}  Tindakan       : " + ("" if p['tindakan_items'] else "Missing"))
    for it in p['tindakan_items']:
        # tampilkan sebagai sub-bullet dengan '* '
        # pastikan ada dua spasi indent agar rapi
        lines.append(f"   {STAR} {it}")

    lines.append(f"{BULLET}  Kontrol        : {p['kontrol']}")
    lines.append(f"{BULLET}  DPJP           : {p['dpjp']}")
    lines.append(f"{BULLET}  No. Telp.      : {p['telp']}")
    lines.append(f"{BULLET}  Operator       : {p['operator']}")
    return "\n".join(lines)

def export_docx(full_text: str) -> bytes:
    doc = Document()
    for para in full_text.split("\n"):
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()

# =======================
# Streamlit UI
# =======================
st.set_page_config(page_title="Review Poli Integrasi RSGMP UNHAS", layout="wide")
st.title("Review Poli Integrasi – RSGMP UNHAS")

st.markdown("Upload **file chat** (.docx atau .txt) dari WhatsApp pada hari tersebut. Aplikasi akan mengekstrak review pasien, merapikan format, dan menghitung rekap otomatis.")

uploaded = st.file_uploader("Upload file chat (.docx / .txt)", type=["docx", "txt"])

# Header date defaults (today)
today = datetime.now()
hari_default = HARI_ID[today.weekday()]
tgl_default = today.strftime("%d/%m/%Y")
header_day = st.text_input("Hari (otomatis):", value=hari_default)
header_date = st.text_input("Tanggal (otomatis):", value=tgl_default)

chief = st.text_input("Chief jaga poli (isi manual):", value="Isi manual")

colA, colB, colC = st.columns(3)
with colA:
    vip_count = st.number_input("VIP (jumlah, manual)", min_value=0, value=0, step=1)
with colB:
    baksos_count = st.number_input("Baksos (jumlah, manual)", min_value=0, value=0, step=1)
with colC:
    st.write("")

vip_text = st.text_area("Isi daftar VIP (opsional, format bebas – akan ditempel apa adanya):", height=160)
baksos_text = st.text_area("Isi daftar BAKSOS (opsional, format bebas – akan ditempel apa adanya):", height=160)

if uploaded:
    # Baca text
    if uploaded.type == "text/plain":
        raw_text = uploaded.read().decode("utf-8", errors="replace")
    else:
        # docx
        if docx2txt is None:
            st.error("docx2txt belum terinstal. Jalankan: pip install docx2txt")
            st.stop()
        raw_text = docx2txt.process(uploaded)

    text = normalize_text(raw_text)

    # Split blok & parse
    blocks = split_blocks(text)
    parsed = [parse_block(n, nm, ch) for (n, nm, ch) in blocks]

    if not parsed:
        st.error("Tidak ditemukan blok review dengan pola 'X. Nama : ...'. Pastikan format chat sesuai.")
        st.stop()

    # Urut sesuai nomor
    parsed.sort(key=lambda x: x["no"])

    # Hitung rekap:
    # Jumlah pasien = nomor terbesar (sesuai aturan user)
    max_no = max(p["no"] for p in parsed)
    konsul = sum(1 for p in parsed if p["is_konsul"])
    terjaring_ga = sum(1 for p in parsed if p["is_terjaring_ga"])
    tindakan = max_no - konsul - terjaring_ga

    # Kumpulkan DPJP yang muncul
    dpjp_set = set()
    for p in parsed:
        val = p["dpjp"]
        if val and val != "Missing":
            dpjp_set.add(val.strip())

    # Urutkan DPJP sesuai hierarki tapi hanya yang muncul
    dpjp_list = [name for name in DPJP_ORDER if any(name.lower() in d.lower() for d in dpjp_set)]
    # Tambahkan DPJP di luar list hierarki ke paling bawah (jaga-jaga)
    extra_dpjp = [d for d in sorted(dpjp_set) if not any(base.lower() in d.lower() for base in DPJP_ORDER)]
    dpjp_final = dpjp_list + extra_dpjp

    # Bangun output
    header = f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {header_day} ({header_date})"
    summary_lines = [
        "",
        f"Jumlah pasien    : {max_no:02d} Pasien ",
        f"Tindakan         : {tindakan:02d} Pasien ",
        f"Konsultasi       : {konsul:02d} Pasien",
        f"Terjaring GA     : {terjaring_ga:02d} Pasien",
        f"VIP              : {vip_count:02d} Pasien",
        f"Baksos           : {baksos_count:02d} Pasien ",
        "",
        "------------------------------------------------------------",
        "",
        "POLI INTEGRASI",
        ""
    ]

    patient_text = "\n\n".join([format_patient_block(p) for p in parsed])

    # VIP & Baksos sections (manual paste)
    vip_section = ""
    if vip_text.strip():
        vip_section = "\n\nVIP\n\n" + vip_text.strip()

    baksos_section = ""
    if baksos_text.strip():
        baksos_section = "\n\nBAKSOS CCC\n\n" + baksos_text.strip()

    footer_lines = [
        "",
        "------------------------------------------------------------",
        "",
        f"{header_day}, {header_date}",
        "",
        "Chief jaga poli :",
        chief if chief.strip() else "Isi manual",
        "",
        "DPJP :"
    ]
    for i, d in enumerate(dpjp_final, start=1):
        footer_lines.append(f"{i}. {d}")

    full = header + "\n" + "\n".join(summary_lines) + patient_text + vip_section + baksos_section + "\n\n" + "\n".join(footer_lines)

    st.subheader("Hasil (format dipertahankan)")
    st.code(full, language="text")

    # Unduhan
    txt_bytes = full.encode("utf-8")
    st.download_button("Download .txt", data=txt_bytes, file_name=f"review_poli_{header_date.replace('/','-')}.txt", mime="text/plain")

    docx_bytes = export_docx(full)
    st.download_button("Download .docx", data=docx_bytes, file_name=f"review_poli_{header_date.replace('/','-')}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

else:
    st.info("Silakan upload file chat terlebih dahulu (.docx atau .txt).")
