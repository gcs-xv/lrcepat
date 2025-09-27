
import io
import re
from datetime import datetime, date
import streamlit as st

# ============ Helpers ============

HIERARCHY = [
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

ID_DAY = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]

def indo_today_string(d: date) -> str:
    # Friday is index 4 for weekday() (Mon=0)
    day = ID_DAY[d.weekday()]
    return f"{day} ({d.strftime('%d/%m/%Y')})"

def read_file_to_text(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    if name.endswith(".txt"):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="ignore")
    elif name.endswith(".docx"):
        try:
            import docx  # python-docx
        except Exception as e:
            st.error("python-docx belum terpasang. Tambahkan ke requirements.txt")
            return ""
        f = io.BytesIO(data)
        doc = docx.Document(f)
        paragraphs = []
        for p in doc.paragraphs:
            paragraphs.append(p.text)
        return "\n".join(paragraphs)
    else:
        try:
            return data.decode("utf-8")
        except Exception:
            return ""

def normalize(s: str) -> str:
    # Hilangkan karakter zero-width dan rapikan spasi
    if s is None:
        return ""
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "").replace("\u2060", "")
    s = s.replace("\t", "    ")
    # Samakan bullet
    s = s.replace("•", "•")
    return s

def split_patient_blocks(text: str):
    # Cari blok yang dimulai oleh baris berisi angka + "Nama"
    # Mencakup variasi spasi/karakter
    pattern = re.compile(r"(?ms)(?:^|\n)\s*\d+\D*\s*Nama\s*:.*?(?=(?:\n\s*\d+\D*\s*Nama\s*:)|\Z)")
    blocks = pattern.findall(text)
    return [b.strip() for b in blocks]

def extract_field(pattern, block, default="Missing", flags=re.IGNORECASE):
    m = re.search(pattern, block, flags)
    if not m:
        return default.strip()
    val = m.group(1).strip()
    return val if val else default.strip()

def extract_multiline_after(label, block):
    # Ambil isi setelah "label :" sampai ketemu label berikut (Kontrol/DPJP/No. Telp/Operator/Nama/titik baris baru)
    # Terima variasi kapital dan spasi
    start = re.search(rf"{label}\s*:\s*(.*)", block, flags=re.IGNORECASE)
    if not start:
        return "Missing"
    start_idx = start.end(0)
    # cari batas
    nxt = re.search(r"\n\s*•?\s*(Kontrol|DPJP|No\.?\s*Telp|Operator|Nama|RM|Tanggal lahir|Diagnosa)\s*:", block[start_idx:], flags=re.IGNORECASE)
    content = block[start_idx:] if not nxt else block[start_idx:start_idx+nxt.start()]
    # bersihkan bullet-bulletnya, tapi tetap pertahankan format garis baru dan *
    content = content.strip()
    return content if content else "Missing"

def parse_patient_block(block: str, index: int):
    nama = extract_field(r"Nama\s*:\s*(.*)", block)
    tgl = extract_field(r"Tanggal\s+lahir\s*:\s*(.*)", block)
    rm  = extract_field(r"RM\s*:\s*(.*)", block)
    diagnosa = extract_multiline_after("Diagnosa", block)
    tindakan = extract_multiline_after("Tindakan", block)
    kontrol  = extract_multiline_after("Kontrol", block)
    dpjp     = extract_field(r"DPJP\s*:\s*(.*)", block)
    telp     = extract_field(r"No\.?\s*Telp\.?\s*:\s*(.*)", block)
    operator = extract_field(r"Operator\s*:\s*(.*)", block)

    # Flag konsultasi
    is_konsultasi = bool(re.search(r"\bKonsultasi\b", tindakan, flags=re.IGNORECASE))

    # Flag Terjaring GA -> ada frasa "dalam general anestesi (menunggu penjadwalan)" di KONTROL atau di rencana (tindakan/diagnosa)
    ga_phrase = r"dalam\s+general\s+anestesi\s*\(menunggu\s+penjadwalan\)"
    is_terjaring_ga = bool(re.search(ga_phrase, block, flags=re.IGNORECASE))

    # Susun kembali format blok sesuai template, dengan fallback Missing
    def safe(v): 
        return v if v and v.strip() else "Missing"

    # Pastikan sub-bullets * tetap tampil baris per baris
    tindakan_fmt = safe(tindakan)
    kontrol_fmt  = safe(kontrol)

    text = []
    text.append(f"{index:>2}. Nama            : {safe(nama)}")
    text.append(f"•  Tanggal lahir  : {safe(tgl)}")
    text.append(f"•  RM             : {safe(rm)}")
    text.append(f"•  Diagnosa       : {safe(diagnosa)}")
    text.append(f"•  Tindakan       : {tindakan_fmt}")
    text.append(f"•  Kontrol        : {kontrol_fmt}")
    text.append(f"•  DPJP           : {safe(dpjp)}")
    text.append(f"•  No. Telp.      : {safe(telp)}")
    text.append(f"•  Operator       : {safe(operator)}")
    return {
        "render": "\n".join(text),
        "is_konsultasi": is_konsultasi,
        "is_terjaring_ga": is_terjaring_ga,
        "dpjp": extract_field(r"DPJP\s*:\s*(.*)", block, default="").strip()
    }

def sort_dpjp_unique(dpjp_list):
    seen = set()
    unique = []
    for d in dpjp_list:
        d_clean = d.strip().rstrip(".")
        if not d_clean:
            continue
        if d_clean not in seen:
            seen.add(d_clean)
            unique.append(d_clean)

    # urut sesuai hierarki, yang tidak ada di hierarki ditaruh di bawah secara alfabetis
    order = {name: i for i, name in enumerate(HIERARCHY)}
    in_h = [d for d in unique if d in order]
    not_in_h = [d for d in unique if d not in order]
    in_h.sort(key=lambda x: order[x])
    not_in_h.sort()
    return in_h + not_in_h

def make_header(date_str, total, tindakan, konsultasi, terjaring_ga, vip, baksos):
    lines = []
    lines.append(f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {date_str}")
    lines.append("")
    lines.append(f"Jumlah pasien    : {total:02d} Pasien ")
    lines.append(f"Tindakan         : {tindakan:02d} Pasien ")
    lines.append(f"Konsultasi       : {konsultasi:02d} Pasien")
    lines.append(f"Terjaring GA     : {terjaring_ga:02d} Pasien")
    lines.append(f"VIP              : {vip:02d} Pasien")
    lines.append(f"Baksos           : {baksos:02d} Pasien ")
    lines.append("")
    lines.append("-" * 60)
    lines.append("")
    lines.append("POLI INTEGRASI")
    lines.append("")
    return "\n".join(lines)

def build_footer(date_str, chief_name, dpjp_sorted):
    lines = []
    lines.append("")
    lines.append("-" * 60)
    lines.append("")
    # Tanggal baris bawah (tanpa hari? mengikuti contoh ada hari & tanggal)
    lines.append(f"{date_str.split('(')[0].strip()}, {date_str.split('(')[1].strip(')') if '(' in date_str else date_str}")
    lines.append("")
    lines.append("Chief jaga poli :")
    lines.append(chief_name or "Isi manual")
    lines.append("")
    lines.append("DPJP :")
    for i, d in enumerate(dpjp_sorted, start=1):
        lines.append(f"{i}. {d}")
    return "\n".join(lines)

def to_docx_bytes(text: str) -> bytes:
    try:
        from docx import Document
    except Exception:
        return b""
    doc = Document()
    for block in text.split("\n\n"):
        p = doc.add_paragraph()
        for line in block.split("\n"):
            run = p.add_run(line)
            p.add_run("\n")
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ============ UI ============

st.set_page_config(page_title="Review Poli BM & MF - RSGMP UNHAS", layout="wide")
st.title("Generator Review Pasien - Poli Bedah Mulut & Maksilofasial")

st.markdown("""Upload **file chat harian** (copy WhatsApp/Word) lalu aplikasi akan:
- Menyaring blok **review pasien** saja
- Mengurutkan nomor dan mengisi **Missing** jika ada field kosong
- Menghitung **Jumlah pasien, Konsultasi, Terjaring GA**, dan **Tindakan = Total - Konsultasi - Terjaring GA**
- Mengelompokkan **DPJP** sesuai hierarki
""")

colA, colB = st.columns([2,1])
with colA:
    upl = st.file_uploader("Upload file (.docx atau .txt)", type=["docx","txt"])
    raw_text = read_file_to_text(upl)
    raw_text = normalize(raw_text)
    st.text_area("Preview teks mentah (opsional untuk cek)", raw_text, height=200)

with colB:
    today = date.today()
    # Tanggal otomatis hari ini, bisa diubah
    input_date = st.date_input("Tanggal review", value=today)
    # Render jadi format 'Jumat (26/09/2025)'
    date_str = indo_today_string(input_date)

    vip_count = st.number_input("VIP (isi manual)", min_value=0, value=0, step=1)
    baksos_count = st.number_input("Baksos (isi manual)", min_value=0, value=0, step=1)
    chief = st.text_input("Chief jaga poli (isi manual)", "")

st.divider()

if raw_text.strip():
    blocks = split_patient_blocks(raw_text)
    parsed = []
    for i, b in enumerate(blocks, start=1):
        parsed.append(parse_patient_block(b, i))

    total = len(parsed)
    konsultasi = sum(1 for p in parsed if p["is_konsultasi"])
    terjaring_ga = sum(1 for p in parsed if p["is_terjaring_ga"])
    tindakan = max(0, total - konsultasi - terjaring_ga)

    dpjp_set = sort_dpjp_unique([p["dpjp"] for p in parsed if p["dpjp"]])

    header = make_header(date_str, total, tindakan, konsultasi, terjaring_ga, vip_count, baksos_count)
    body = "\n\n".join(p["render"] for p in parsed)
    footer = build_footer(date_str, chief, dpjp_set)

    final_text = "\n".join([header, body, "", footer])

    st.subheader("Hasil Review (siap salin)")
    st.text_area("Output", final_text, height=600)

    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_poli.txt")

    docx_bytes = to_docx_bytes(final_text)
    if docx_bytes:
        st.download_button("Download .docx", data=docx_bytes, file_name="review_poli.docx")
    else:
        st.info("Install python-docx untuk export .docx")

else:
    st.info("Silakan upload file terlebih dahulu.")
