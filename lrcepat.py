# app.py
import re
import io
import unicodedata
from datetime import date, datetime
import streamlit as st

# ============== UTIL: Tanggal Indonesia ==============
HARI_ID = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
def tanggal_id(dt: date) -> str:
    h = HARI_ID[dt.weekday()]
    return f"{h} ({dt.strftime('%d/%m/%Y')})"

# ============== Prioritas DPJP (hierarki) ==============
DPJP_PRIORITY = [
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
    "drg. Carolina Stevanie, Sp.B.M.M.",
]

# ============== Normalisasi WA text ==============
WHATSAPP_PREFIX_RE = re.compile(
    r'^\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}\.\d{2}\.\d{2}\]\s*[^:]{1,120}:\s*',
    flags=re.MULTILINE
)

def normalize_wa_text(raw: str) -> str:
    # line endings
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    # hapus prefix "[dd/mm/yy, hh.mm.ss] Nama: "
    t = WHATSAPP_PREFIX_RE.sub("", t)
    # buang karakter tak terlihat: kategori Cf (ZWJ, WJ, BOM, dll)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    # ganti semua spasi unicode jadi spasi biasa
    t = "".join(" " if unicodedata.category(ch).startswith("Z") else ch for ch in t)
    # rapikan tab
    t = t.replace("\t", " ")
    # hapus spasi berlebih sebelum newline
    t = re.sub(r"[ ]+\n", "\n", t)
    return t

# ============== Regex Parser ==============
BLOCK_SPLIT_RE = re.compile(
    r'(?P<block>^\s*(?P<num>\d{1,3})\s*[.)]\s*Nama\s*:\s*.*?)(?='
    r'(?:^\s*\d{1,3}\s*[.)]\s*Nama\s*:)|(?:^\s*VIP\b)|(?:^\s*BAKSOS\b)|\Z)',
    flags=re.MULTILINE | re.DOTALL
)

FIELD_RE = {
    "nama": re.compile(r'^\s*\d{1,3}\s*[.)]\s*Nama\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "tgl_lahir": re.compile(r'^\s*•\s*Tanggal\s+lahir\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "rm": re.compile(r'^\s*•\s*RM\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "diagnosa": re.compile(
        r'^\s*•\s*Diagnosa\s*:\s*(?P<val>.*?)'
        r'(?=\n\s*•\s*(?:Tindakan|Kontrol|DPJP|No\.\s*Telp\.?|Operator)\b|\Z)',
        re.MULTILINE | re.DOTALL
    ),
    "tindakan": re.compile(
        r'^\s*•\s*Tindakan\s*:\s*(?P<val>.*?)'
        r'(?=\n\s*•\s*(?:Kontrol|DPJP|No\.\s*Telp\.?|Operator)\b|\Z)',
        re.MULTILINE | re.DOTALL
    ),
    "kontrol": re.compile(r'^\s*•\s*Kontrol\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "dpjp": re.compile(r'^\s*•\s*DPJP\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "telp": re.compile(r'^\s*•\s*No\.\s*Telp\.?\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "operator": re.compile(r'^\s*•\s*Operator\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
}

def tidy_multiline(val: str) -> str:
    # keep bullets and asterisks, rapikan spasi
    lines = [ln.rstrip() for ln in val.strip().splitlines()]
    # buang baris kosong ujung2
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)

def parse_block(txt: str):
    data = {}
    m_num = re.search(r'^\s*(\d{1,3})\s*[.)]\s*Nama\b', txt, flags=re.MULTILINE)
    data["no"] = int(m_num.group(1)) if m_num else None
    for key, rx in FIELD_RE.items():
        m = rx.search(txt)
        val = m.group("val").strip() if m else None
        if key in ("diagnosa","tindakan") and val:
            val = tidy_multiline(val)
        data[key] = val
    return data

def extract_reviews(clean_text: str):
    blocks = []
    for m in BLOCK_SPLIT_RE.finditer(clean_text):
        blocks.append(parse_block(m.group("block")))
    blocks.sort(key=lambda d: (9999 if d["no"] is None else d["no"]))
    return blocks

# ============== Deteksi Konsultasi / Terjaring GA ==============
CONSULT_PAT = re.compile(r'(?im)^\s*[\*\-•]\s*Konsultasi\b')
GA_QUEUE_PAT = re.compile(r'(?i)dalam\s+general\s+anestesi\s*\(menunggu\s+penjadwalan\)')

def is_konsultasi(tindakan_text: str) -> bool:
    if not tindakan_text:
        return False
    return CONSULT_PAT.search(tindakan_text) is not None

def is_terjaring_ga(kontrol_text: str, tindakan_text: str) -> bool:
    blob = " ".join([tindakan_text or "", kontrol_text or ""])
    return GA_QUEUE_PAT.search(blob) is not None

# ============== Format Output ==============
def format_block(d: dict) -> str:
    spaces = " "
    bullet = "•"
    def V(x): return x if (x and x.strip()) else "Missing"
    lines = []
    no = d.get("no")
    no_str = f"{no:>2d}." if isinstance(no, int) else "  -."
    lines.append(f"{no_str} Nama{spaces*12}: {V(d.get('nama'))}")
    lines.append(f"{bullet}{spaces*2}Tanggal lahir {spaces}: {V(d.get('tgl_lahir'))}")
    lines.append(f"{bullet}{spaces*2}RM{spaces*19}: {V(d.get('rm'))}")
    # Diagnosa (bisa multi-baris)
    diag = V(d.get('diagnosa'))
    if "\n" in diag:
        first, *rest = diag.splitlines()
        lines.append(f"{bullet}{spaces*2}Diagnosa{spaces*8}: {first}")
        for r in rest:
            lines.append(r)
    else:
        lines.append(f"{bullet}{spaces*2}Diagnosa{spaces*8}: {diag}")
    # Tindakan (bisa multi-baris)
    tind = V(d.get('tindakan'))
    if "\n" in tind:
        first, *rest = tind.splitlines()
        lines.append(f"{bullet}{spaces*2}Tindakan{spaces*8}: {first}")
        for r in rest:
            lines.append(r)
    else:
        lines.append(f"{bullet}{spaces*2}Tindakan{spaces*8}: {tind}")
    lines.append(f"{bullet}{spaces*2}Kontrol{spaces*9}: {V(d.get('kontrol'))}")
    lines.append(f"{bullet}{spaces*2}DPJP{spaces*12}: {V(d.get('dpjp'))}")
    lines.append(f"{bullet}{spaces*2}No. Telp.{spaces*6}: {V(d.get('telp'))}")
    lines.append(f"{bullet}{spaces*2}Operator{spaces*8}: {V(d.get('operator'))}")
    return "\n".join(lines)

def build_dpjp_list(blocks):
    found = set()
    for b in blocks:
        dp = b.get("dpjp")
        if dp and dp.strip():
            # normalisasi spasi/kapital kecil besar gak diubah biar asli, tapi untuk set cocokkan longgar
            found.add(dp.strip())
    # urutkan berdasarkan prioritas; yang tidak ada di prioritas taruh belakang alfabetis
    def prio_key(name: str):
        try:
            return (0, DPJP_PRIORITY.index(name))
        except ValueError:
            return (1, name.lower())
    ordered = sorted(found, key=prio_key)
    return ordered

# ============== Streamlit UI ==============
st.set_page_config(page_title="Review Poli OMFS - Parser WA", layout="wide")
st.title("Aplikasi Review Poli Bedah Mulut & Maksilofasial (Parser Chat WhatsApp)")

colL, colR = st.columns([2,1])

with colL:
    up = st.file_uploader("Upload file chat (.docx atau .txt)", type=["docx","txt"])
    tgl = st.date_input("Tanggal laporan (otomatis hari ini, bisa ubah)", value=date.today())
    chief = st.text_input("Chief jaga poli (isi manual)", value="Isi manual")
    vip_manual = st.text_input("Jumlah VIP (isi manual)", value="00")
    baksos_manual = st.text_input("Jumlah Baksos (isi manual)", value="00")
    proses = st.button("Proses")

def read_file(uploaded):
    if uploaded is None:
        return ""
    if uploaded.type == "text/plain" or uploaded.name.lower().endswith(".txt"):
        return uploaded.read().decode("utf-8", errors="ignore")
    # .docx
    try:
        from docx import Document
        doc = Document(io.BytesIO(uploaded.read()))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        st.error(f"Gagal membaca DOCX: {e}")
        return ""

with colR:
    st.markdown("**Catatan parsing:**")
    st.markdown("- Karakter tak terlihat WA dinormalisasi.")
    st.markdown("- Prefix timestamp WA dihapus.")
    st.markdown("- Field kosong otomatis menjadi **Missing**.")
    st.markdown("- **Jumlah pasien** = nomor terbesar yang terdeteksi (meski ada nomor yang lompat).")
    st.markdown("- **Konsultasi**: ada bullet `* Konsultasi` pada Tindakan.")
    st.markdown("- **Terjaring GA**: ada frasa `dalam general anestesi (menunggu penjadwalan)` di Tindakan/Kontrol.")
    st.markdown("- **Tindakan** = Jumlah − Konsultasi − Terjaring GA.")
    st.markdown("- VIP & Baksos di-input manual.")

if proses:
    raw = read_file(up)
    if not raw.strip():
        st.error("Silakan upload file terlebih dahulu.")
        st.stop()

    cleaned = normalize_wa_text(raw)
    blocks = extract_reviews(cleaned)

    if not blocks:
        st.error("Tidak ditemukan blok review. Pastikan ada baris seperti '11. Nama : ...' setelah normalisasi.")
        with st.expander("Lihat cuplikan teks yang sudah dinormalisasi"):
            st.text(cleaned[:4000])
        st.stop()

    # Hitung statistik
    max_no = max([b["no"] for b in blocks if isinstance(b.get("no"), int)], default=0)
    total_pasien = max_no if max_no > 0 else len(blocks)  # pakai nomor terbesar sesuai aturanmu
    jumlah_konsultasi = sum(1 for b in blocks if is_konsultasi(b.get("tindakan")))
    jumlah_ga = sum(1 for b in blocks if is_terjaring_ga(b.get("kontrol"), b.get("tindakan")))
    tindakan_count = max(total_pasien - jumlah_konsultasi - jumlah_ga, 0)

    # DPJP list
    dpjp_list = build_dpjp_list(blocks)

    # Format hasil
    today_str = tanggal_id(tgl)
    header = [
        f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {today_str}",
        "",
        f"Jumlah pasien   : {total_pasien:02d} Pasien ",
        f"Tindakan         : {tindakan_count:02d} Pasien ",
        f"Konsultasi       : {jumlah_konsultasi:02d} Pasien",
        f"Terjaring GA     : {jumlah_ga:02d} Pasien",
        f"VIP              : {vip_manual} Pasien",
        f"Baksos           : {baksos_manual} Pasien ",
        "",
        "------------------------------------------------------------",
        "",
        "POLI INTEGRASI",
        ""
    ]
    body_blocks = []
    for b in blocks:
        body_blocks.append(format_block(b))
        body_blocks.append("")  # spasi antar blok

    footer = [
        "------------------------------------------------------------",
        "",
        today_str,
        "",
        "Chief jaga poli :",
        chief if chief.strip() else "Isi manual",
        "",
        "DPJP :"
    ]
    # urutkan dan beri nomor
    for i, nm in enumerate(dpjp_list, start=1):
        footer.append(f"{i}. {nm}")

    final_text = "\n".join(header + body_blocks + footer)

    st.success("Berhasil diproses!")
    st.text_area("Hasil akhir (siap copy-paste):", value=final_text, height=700)
    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_poli.txt", mime="text/plain")

    # Debug (opsional)
    with st.expander("Debug: header blok yang terdeteksi"):
        heads = []
        for m in BLOCK_SPLIT_RE.finditer(cleaned):
            h = re.search(r'^\s*\d{1,3}\s*[.)]\s*Nama\s*:\s*(.*)$', m.group("block"), re.MULTILINE)
            if h:
                heads.append(h.group(1))
        st.write(heads[:100])
