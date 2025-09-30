
import streamlit as st
import re
import io
from io import BytesIO
from typing import List, Dict, Tuple, Optional
import unicodedata
import textwrap

def try_import_python_docx():
    try:
        import docx  # python-docx
        return docx
    except Exception:
        return None

def try_import_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except Exception:
        return None

st.set_page_config(page_title="Review Poli BM & MF RSGMP UNHAS", layout="wide")

st.title("🦷 Review Poli Bedah Mulut & Maksilofasial — RSGMP UNHAS")
st.caption("Upload chat WhatsApp (DOCX/TXT) + Laporan Pengunjung (PDF). Aplikasi akan ambil hanya blok 'review' yang valid, bersihkan chat, lalu urutkan sesuai urutan Nama Pasien di PDF (PDF precedence).")

ZERO_WIDTH = "".join(["\u200b","\u200c","\u200d","\ufeff","\u2060","\u202c","\u202d","\u202e"])
def normalize_text(s: str) -> str:
    s = "".join(ch for ch in s if ch not in ZERO_WIDTH)
    s = s.replace("•⁠", "•").replace("• ", "•").replace("•  ", "• ")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\r\n","\n").replace("\r","\n")
    s = re.sub("[ \t]+"," ", s)
    return s

def extract_text_from_chat(upload) -> str:
    name = upload.name.lower()
    data = upload.read()
    if name.endswith(".txt"):
        return normalize_text(data.decode("utf-8", errors="ignore"))
    elif name.endswith(".docx"):
        docx = try_import_python_docx()
        if docx is None:
            st.error("python-docx belum terpasang. Tambahkan `python-docx` di requirements.txt.")
            st.stop()
        doc = docx.Document(BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs]
        return normalize_text("\n".join(paragraphs))
    else:
        st.error("Format chat tidak didukung. Upload .docx atau .txt")
        st.stop()

def extract_text_from_pdf(upload) -> str:
    pdfplumber = try_import_pdfplumber()
    if pdfplumber is None:
        st.warning("pdfplumber belum terpasang. Tambahkan `pdfplumber` di requirements.txt untuk pembacaan PDF penuh.")
        try:
            raw = upload.read()
            return normalize_text(raw.decode("utf-8", errors="ignore"))
        except Exception:
            return ""
    data = upload.read()
    with pdfplumber.open(BytesIO(data)) as pdf:
        pages_text = []
        for page in pdf.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            pages_text.append(txt)
    return normalize_text("\n".join(pages_text))

REVIEW_START_RE = re.compile(r'^\s*(\d+)\.\s*Nama\s*:.*$', re.IGNORECASE | re.MULTILINE)
OPERATOR_LINE_RE = re.compile(r'^\s*•\s*Operator\s*:', re.IGNORECASE)

def slice_review_blocks(chat_text: str):
    blocks = []
    starts = list(REVIEW_START_RE.finditer(chat_text))
    for i, m in enumerate(starts):
        start = m.start()
        end_limit = starts[i+1].start() if i+1 < len(starts) else len(chat_text)
        chunk = chat_text[start:end_limit]
        op = None
        for line_match in re.finditer(r'.*', chunk):
            line_text = line_match.group(0)
            if OPERATOR_LINE_RE.match(line_text):
                op = line_match.end()
        if op is None:
            continue
        clean_chunk = chunk[:op]
        blocks.append((start, start+len(clean_chunk), clean_chunk.strip()))
    return blocks

def grab_name_from_block(block: str) -> Optional[str]:
    m = re.search(r'^\s*\d+\.\s*Nama\s*:\s*(.+?)\s*$', block, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None

def enforce_operator_last_line(block: str) -> str:
    lines = block.split("\n")
    result = []
    found = False
    for line in lines:
        result.append(line)
        if OPERATOR_LINE_RE.match(line):
            found = True
            break
    return "\n".join(result).strip() if found else ""

def order_blocks_by_pdf(blocks, pdf_text: str):
    pdf_norm = pdf_text.casefold()
    indexed = []
    notfound = []
    for i, b in enumerate(blocks):
        name = grab_name_from_block(b) or ""
        pos = pdf_norm.find(name.casefold())
        if pos == -1:
            tight = re.sub(r"\s+", " ", name.strip()).casefold()
            pos = pdf_norm.find(tight)
        if pos == -1:
            notfound.append((i, b))
        else:
            indexed.append((pos, i, b))
    indexed.sort(key=lambda x: x[0])
    ordered = [b for _, _, b in indexed] + [b for _, b in notfound]
    return ordered

PROCEDURE_KEYWORDS = [
    "odontektomi","ekstraksi","alveolektomi","wound debridement","debridement",
    "replantasi","reposisi","idw","erich archbar","cuci luka","aff hecting",
    "aff drain","kontrol luka","marsupialisasi","sinus washout","fistulektomi",
    "enukleasi","apeks reseksi","marsupial","drain"
]

def classify_block(block: str) -> str:
    text = block.casefold()
    tindakan = ""
    m = re.search(r'^\s*•\s*Tindakan\s*:\s*(.*?)(?:^\s*•\s*\w|\Z)', block, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    if m:
        tindakan = m.group(1).strip().casefold()
    has_proc = any(k in tindakan for k in PROCEDURE_KEYWORDS)
    only_consult_like = ("konsultasi" in tindakan or "consultation" in tindakan) and not has_proc
    if "general anestesi" in text or "general anesthesia" in text:
        category = "GA"
    elif only_consult_like:
        category = "Konsultasi"
    else:
        category = "Tindakan"
    return category

def looks_like_baksos(block: str, raw_chat_text: str) -> bool:
    name = grab_name_from_block(block) or ""
    idx = raw_chat_text.find(block.splitlines()[0])
    if idx == -1:
        return False
    head_start = max(0, idx - 2000)
    context = raw_chat_text[head_start:idx]
    lines = context.splitlines()
    tail = "\n".join(lines[-10:])
    return "BAKSOS" in tail.upper()

st.sidebar.header("Upload Berkas")
chat_file = st.sidebar.file_uploader("Chat WhatsApp (.docx / .txt)", type=["docx", "txt"])
pdf_file = st.sidebar.file_uploader("Laporan Pengunjung (.pdf)", type=["pdf"])

st.sidebar.header("Pengaturan Ringkas")
default_judul = "Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, Sabtu, (27/09/2025)"
judul = st.sidebar.text_input("Judul Laporan", value=default_judul)
tanggal_footer = st.sidebar.text_input("Tanggal footer", value="Sabtu,  27/09/2025")
chief = st.sidebar.text_input("Chief jaga poli", value="drg. I Gede Surya Septaadinata")
dpjp_list_default = [
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. Nurwahida, M.KG., Sp.B.M.M.,Subsp.C.O.M.(K)",
    "drg. Mukhtar Nur Anam, Sp.B.M.M",
    "drg. Timurwati, Sp.B.M.M",
    "drg. Husni Mubarak, Sp.B.M.M.",
    "drg. Carolina Stevanie, Sp.B.M.M",
]
dpjp_list = st.sidebar.text_area("DPJP (ditampilkan di footer, satu per baris)", value="\n".join(dpjp_list_default))

with st.expander("Petunjuk Pakai", expanded=False):
    st.markdown("""
1. Upload chat WhatsApp **DOCX/TXT** dan **PDF Laporan Pengunjung**.
2. Aplikasi otomatis:
   - Ambil **hanya** blok yang valid (berawal dari `N. Nama:` dan **diakhiri** oleh `•  Operator :`).
   - Buang chat intermezzo/komentar yang **bukan bagian review**.
   - Susun **urutan pasien** mengikuti urutan **Nama Pasien** di PDF (*PDF precedence*).
3. Hasil akhir bisa diunduh sebagai **.txt** untuk diposting/arsip.
    """)

if chat_file is not None:
    chat_text = extract_text_from_chat(chat_file)
    st.subheader("Cuplikan Chat (dibersihkan & dinormalisasi)")
    with st.expander("Lihat raw chat", expanded=False):
        st.code(chat_text[:2000] + ("..." if len(chat_text) > 2000 else ""), language="markdown")

    raw_blocks = slice_review_blocks(chat_text)
    only_blocks = [enforce_operator_last_line(b[2]) for b in raw_blocks if enforce_operator_last_line(b[2])]
    st.success(f"Ditemukan {len(only_blocks)} blok review valid (punya baris Operator).")

    names = [grab_name_from_block(b) or "(tanpa nama)" for b in only_blocks]
    st.write("Nama dari blok valid:", ", ".join(names))

    pdf_text = ""
    if pdf_file is not None:
        pdf_text = extract_text_from_pdf(pdf_file)
        st.subheader("Cuplikan PDF (plain text)")
        with st.expander("Lihat raw PDF text", expanded=False):
            st.code(pdf_text[:2000] + ("..." if len(pdf_text) > 2000 else ""), language="markdown")
        ordered_blocks = order_blocks_by_pdf(only_blocks, pdf_text)
    else:
        ordered_blocks = only_blocks

    def renumber_block(i: int, block: str) -> str:
        return re.sub(r'^\s*\d+\.\s*Nama', f"{i}. Nama", block, flags=re.IGNORECASE | re.MULTILINE, count=1)

    ordered_blocks = [renumber_block(i+1, b) for i, b in enumerate(ordered_blocks)]

    kategori = [classify_block(b) for b in ordered_blocks]
    jumlah = len(ordered_blocks)
    jumlah_tindakan = sum(1 for k in kategori if k == "Tindakan")
    jumlah_konsultasi = sum(1 for k in kategori if k == "Konsultasi")
    jumlah_ga = sum(1 for k in kategori if k == "GA")

    baksos_flags = [looks_like_baksos(b, chat_text) for b in ordered_blocks]
    jumlah_baksos_auto = sum(1 for x in baksos_flags if x)
    jumlah_baksos = st.sidebar.number_input("BAKSOS (override manual jika perlu)", min_value=0, value=jumlah_baksos_auto, step=1)
    jumlah_vip = st.sidebar.number_input("VIP (opsional, override)", min_value=0, value=0, step=1)

    header = textwrap.dedent(f"""\
    {judul}
     
    Jumlah pasien    : {jumlah:02d} Pasien 
    Tindakan             : {jumlah_tindakan:02d} Pasien 
    Konsultasi           : {jumlah_konsultasi:02d} Pasien
    Terjaring GA        : {jumlah_ga:02d} Pasien
    VIP                       : {jumlah_vip:02d} Pasien
    Baksos                 : {int(jumlah_baksos):02d} Pasien 

    ------------------------------------------------------------

    POLI INTEGRASI
    """)

    body = "\n\n".join(ordered_blocks)

    footer = textwrap.dedent(f"""\
    ------------------------------------------------------------

    {tanggal_footer}

    Chief jaga poli :
    {chief}

    DPJP :
    """) + "\n".join([f"{i+1}. {line}" for i, line in enumerate(dpjp_list.splitlines()) if line.strip()])

    final_report = header + "\n" + body + "\n\n" + footer

    st.subheader("📝 Hasil Akhir")
    st.text_area("Final Report", value=final_report, height=500)

    st.download_button(
        label="📥 Download .txt",
        data=final_report.encode("utf-8"),
        file_name="review_poli_beres.txt",
        mime="text/plain"
    )

    with st.expander("Detail blok (QA)", expanded=False):
        for i, b in enumerate(ordered_blocks, 1):
            st.markdown(f"**#{i}**")
            st.code(b, language="markdown")
else:
    st.info("Silakan upload chat WhatsApp untuk mulai.")
