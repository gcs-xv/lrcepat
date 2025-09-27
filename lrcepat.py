import re
from io import BytesIO
from datetime import datetime, date
import streamlit as st

# ---------- UTIL: Tanggal & Hari (ID) ----------
HARI_ID = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
BULAN_ID = ["01","02","03","04","05","06","07","08","09","10","11","12"]

def today_id_string(d=None):
    """Return 'Hari (dd/mm/YYYY)' dalam bahasa Indonesia."""
    d = d or date.today()
    hari = HARI_ID[d.weekday()]
    return f"{hari} ({d.strftime('%d/%m/%Y')})"

# ---------- UTIL: Baca DOCX ----------
def read_docx_to_text(file):
    try:
        from docx import Document
    except Exception as e:
        st.error("python-docx belum terinstal. Tambahkan `python-docx` di requirements.txt.")
        raise
    doc = Document(file)
    lines = []
    for p in doc.paragraphs:
        lines.append(p.text)
    return "\n".join(lines)

# ---------- PREPROCESS: Bersihkan prefix chat WhatsApp ----------
WHATSAPP_PREFIX_RE = re.compile(
    r'^\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}\.\d{2}\.\d{2}\]\s*[^:]{1,80}:\s*',
    flags=re.MULTILINE
)

def strip_whatsapp_prefix(raw_text: str) -> str:
    # Hapus prefix “[dd/mm/yy, hh.mm.ss] Pengirim: ”
    return WHATSAPP_PREFIX_RE.sub("", raw_text)

# ---------- PARSER: Ambil blok review ----------
# Blok mulai dengan "N. Nama : ..." (toleran spasi/buletan/variasi titik)
BLOCK_SPLIT_RE = re.compile(
    r'(?P<header>^\s*(?P<num>\d{1,3})\s*[\.\)]\s*Nama\s*:.*?)'   # start
    r'(?=\n\s*\d{1,3}\s*[\.\)]\s*Nama\b|\n\s*VIP\b|\n\s*BAKSOS\b|\Z)',  # until next block/section
    flags=re.DOTALL | re.MULTILINE
)

# Field regex toleran spasi & variasi bullet
FIELD_RE = {
    "nama": re.compile(r'^\s*\d{1,3}\s*[\.\)]\s*Nama\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "tgl_lahir": re.compile(r'^\s*•\s*Tanggal lahir\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "rm": re.compile(r'^\s*•\s*RM\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    # Diagnosa bisa multi-baris sampai sebelum "•  Tindakan" / "•  Kontrol" / "•  DPJP" dsb
    "diagnosa": re.compile(
        r'^\s*•\s*Diagnosa\s*:\s*(?P<val>.*?)'
        r'(?=\n\s*•\s*Tindakan\b|\n\s*•\s*Kontrol\b|\n\s*•\s*DPJP\b|\n\s*•\s*No\.\s*Telp\b|\n\s*•\s*Operator\b|\Z)',
        re.DOTALL | re.MULTILINE
    ),
    # Tindakan bisa berupa satu baris atau bullet-bullet "* ...". Kita serap semuanya hingga field berikutnya
    "tindakan": re.compile(
        r'^\s*•\s*Tindakan\s*:\s*(?P<val>.*?)'
        r'(?=\n\s*•\s*Kontrol\b|\n\s*•\s*DPJP\b|\n\s*•\s*No\.\s*Telp\b|\n\s*•\s*Operator\b|\Z)',
        re.DOTALL | re.MULTILINE
    ),
    "kontrol": re.compile(r'^\s*•\s*Kontrol\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "dpjp": re.compile(r'^\s*•\s*DPJP\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "telp": re.compile(r'^\s*•\s*No\.\s*Telp\.\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
    "operator": re.compile(r'^\s*•\s*Operator\s*:\s*(?P<val>.+?)\s*$', re.MULTILINE),
}

def tidy_multiline(value: str) -> str:
    """Rapihkan spasi dan pertahankan bullet `*` pada Tindakan."""
    if value is None:
        return None
    # Normalisasi line endings dan trim trailing spaces
    lines = [ln.rstrip() for ln in value.strip().splitlines()]
    return "\n".join(lines).strip()

def parse_block(txt: str):
    data = {}
    # nomor
    m_num = re.search(r'^\s*(\d{1,3})\s*[\.\)]\s*Nama\b', txt, flags=re.MULTILINE)
    data["no"] = int(m_num.group(1)) if m_num else None

    # each field
    for key, rx in FIELD_RE.items():
        m = rx.search(txt)
        val = m.group("val").strip() if m else None
        if key in ("diagnosa", "tindakan") and val:
            val = tidy_multiline(val)
        data[key] = val
    return data

def extract_reviews(clean_text: str):
    blocks = []
    for m in BLOCK_SPLIT_RE.finditer(clean_text):
        chunk = m.group(0)
        blocks.append(parse_block(chunk))
    # Urutkan sesuai nomor; kalau ada nomor None, taruh belakang
    blocks.sort(key=lambda d: (9999 if d["no"] is None else d["no"]))
    return blocks

# ---------- COUNTERS ----------
def count_summary(blocks):
    nums = [b["no"] for b in blocks if isinstance(b["no"], int)]
    total = max(nums) if nums else len(blocks)

    def is_konsultasi(b):
        t = (b.get("tindakan") or "").lower()
        # cek baris yang mengandung 'konsultasi'
        return any("konsultasi" in ln.strip().lower() for ln in t.splitlines())

    def is_terjaring_ga(b):
        k = (b.get("kontrol") or "")
        return ("general anestesi" in k.lower()) and ("menunggu penjadwalan" in k.lower())

    konsul = sum(1 for b in blocks if is_konsultasi(b))
    terjaring = sum(1 for b in blocks if is_terjaring_ga(b))
    tindakan = max(total - konsul - terjaring, 0)
    return total, tindakan, konsul, terjaring

# ---------- OUTPUT FORMAT ----------
BULLET = "•"
INDENT = " "  # biar konsisten, pakai spasi biasa
def fmt_field(label, value, allow_multiline=False):
    if not value:
        value = "Missing"
    if allow_multiline and "\n" in value:
        # Setiap baris tindakan yang diawali * kita pertahankan
        return f"{BULLET}{INDENT} {label:<14}: {value}"
    return f"{BULLET}{INDENT} {label:<14}: {value}"

def format_review_section(blocks):
    if not blocks:
        return "POLI INTEGRASI\n\n(No data)"
    out = ["POLI INTEGRASI", ""]
    for b in blocks:
        no = b["no"] if b["no"] is not None else "Missing"
        out.append(f"{no:>2}. Nama            : {b.get('nama') or 'Missing'}")
        out.append(fmt_field("Tanggal lahir", b.get("tgl_lahir")))
        out.append(fmt_field("RM", b.get("rm")))
        out.append(fmt_field("Diagnosa", b.get("diagnosa"), allow_multiline=True))
        # Pastikan tindakan menampilkan bullet-bullet '*' di baris berikutnya tanpa rusak
        tindakan_text = b.get("tindakan")
        if tindakan_text and "\n" in tindakan_text:
            # Pastikan baris bullet `*` tetap di bawahnya
            first_line, *rest = tindakan_text.splitlines()
            if first_line.strip().startswith("*"):
                # Tidak ada header teks setelah colon, kita taruh kosong lalu baris bullet
                header = f"{BULLET}{INDENT} {'Tindakan':<14}: "
                body = "\n".join([ln for ln in tindakan_text.splitlines()])
                out.append(header + body)  # biar sejajar
            else:
                out.append(fmt_field("Tindakan", tindakan_text, allow_multiline=True))
        else:
            out.append(fmt_field("Tindakan", tindakan_text))
        out.append(fmt_field("Kontrol", b.get("kontrol")))
        out.append(fmt_field("DPJP", b.get("dpjp")))
        out.append(fmt_field("No. Telp.", b.get("telp")))
        out.append(fmt_field("Operator", b.get("operator")))
        out.append("")  # spasi antar blok
    return "\n".join(out).rstrip()

# ---------- DPJP HIERARCHY ----------
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
    "drg. Carolina Stevanie, Sp.B.M.M.",
]

def collect_dpjp(blocks):
    found = set()
    for b in blocks:
        val = b.get("dpjp")
        if not val:
            continue
        # Bersihkan trailing titik/koma ekstra
        norm = val.strip()
        # Kadang ada variasi titik-koma — cukup pakai norm langsung
        found.add(norm)
    # Urut sesuai order; tampilkan hanya yang muncul
    ordered = [name for name in DPJP_ORDER if any(name in f for f in found)]
    # Kalau ada nama lain yang tidak di list order, taruh setelahnya
    extras = [f for f in found if not any(k in f for k in DPJP_ORDER)]
    return ordered + sorted(extras)

# ---------- STREAMLIT APP ----------
st.set_page_config(page_title="Review Poli – Parser WA", layout="wide")

st.title("Review Pasien Poli – Parser Chat WA ➜ Format RSGMP")
st.caption("Upload file .docx/.txt berisi copy-paste WhatsApp. Aplikasi akan menyaring blok review saja, merapikan, dan membuat rekap otomatis.")

colL, colR = st.columns([1,1])

with colL:
    uploaded = st.file_uploader("Upload file (.docx atau .txt)", type=["docx", "txt"])
    raw_text = ""
    if uploaded is not None:
        if uploaded.name.lower().endswith(".docx"):
            raw_text = read_docx_to_text(uploaded)
        else:
            raw_text = uploaded.read().decode("utf-8", errors="ignore")
    paste = st.text_area("Atau paste chat di sini", height=180, placeholder="[26/09/25, 10.15.48] Nama: 11. Nama : ...")
    if not raw_text and paste:
        raw_text = paste

with colR:
    # Tanggal otomatis hari ini, bisa diedit
    default_date_str = today_id_string()
    header_date = st.text_input("Tanggal di header (otomatis)", value=default_date_str)

    vip_manual = st.text_input("Jumlah VIP (isi manual)", value="0")
    baksos_manual = st.text_input("Jumlah Baksos (isi manual)", value="0")
    chief = st.text_input("Chief jaga poli (isi manual)", value="Isi manual")

go = st.button("Proses")

if go:
    if not raw_text.strip():
        st.warning("Silakan upload/paste chat terlebih dahulu.")
        st.stop()

    # 1) Bersihkan prefix chat WA
    cleaned = strip_whatsapp_prefix(raw_text)

    # 2) Normalisasi bullet '•' (beberapa copy WA pakai karakter ZWSP/zwj)
    # Hapus Zero-width characters
    cleaned = cleaned.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")

    # Normalisasi label bullet ke satu bentuk konsisten: "•  Label  : ..."
    # (Biarkan variasi spasi, regex field sudah toleran)
    # Tidak perlu penggantian agresif agar tidak merusak baris

    # 3) Ekstrak blok review
    blocks = extract_reviews(cleaned)

    if not blocks:
        st.error("Tidak ditemukan blok review. Pastikan ada baris seperti '11. Nama : ...' di dalam chat.")
        with st.expander("Lihat cuplikan teks setelah dibersihkan"):
            st.code(cleaned[:4000])
        st.stop()

    # 4) Hitung ringkasan
    total, tindakan, konsul, terjaring = count_summary(blocks)

    # 5) Format section pasien
    section_reviews = format_review_section(blocks)

    # 6) DPJP list (urut sesuai hierarki dan hanya yang muncul)
    dpjp_list = collect_dpjp(blocks)

    # 7) Bangun output akhir
    header = f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {header_date}\n"
    resume = (
        f"\nJumlah pasien    : {total:02d} Pasien \n"
        f"Tindakan         : {tindakan:02d} Pasien \n"
        f"Konsultasi       : {konsul:02d} Pasien\n"
        f"Terjaring GA     : {terjaring:02d} Pasien\n"
        f"VIP              : {int(vip_manual):02d} Pasien\n"
        f"Baksos           : {int(baksos_manual):02d} Pasien \n"
        f"\n------------------------------------------------------------\n\n"
    )

    footer_date = header_date
    footer = [
        "------------------------------------------------------------",
        "",
        footer_date.replace(" (", ", ").replace(")", ""),  # contoh: "Jumat (26/09/2025)" ➜ "Jumat, 26/09/2025"
        "",
        "Chief jaga poli :",
        chief,
        "",
        "DPJP :",
    ]
    if dpjp_list:
        for i, name in enumerate(dpjp_list, 1):
            footer.append(f"{i}. {name}")
    else:
        footer.append("(Tidak ada DPJP terdeteksi)")
    footer_text = "\n".join(footer)

    final_text = header + resume + section_reviews + "\n\n" + footer_text

    st.subheader("Hasil Akhir (siap copy-paste)")
    st.code(final_text)

    # Download .txt
    bio = BytesIO(final_text.encode("utf-8"))
    st.download_button("Download sebagai .txt", data=bio, file_name="review_poli.txt", mime="text/plain")

    with st.expander("Debug (opsional) – Lihat blok terdeteksi"):
        st.write(blocks)
