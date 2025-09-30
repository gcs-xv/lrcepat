import io, re, unicodedata
from typing import List, Tuple
import streamlit as st

# ---------------- Normalization ----------------
def strip_format_chars(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")

def normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u00A0", " ")
    s = unicodedata.normalize("NFKC", s)
    # Samakan bullet jadi "• " untuk label; biarkan sub-bullet (*) tetap
    s = re.sub(r"(?m)^\s*[·‧•◦▪▫●○\-]\s*", "• ", s)
    # Ratakan spasi berlebih (kecuali newline)
    s = re.sub(r"[ \t\u2000-\u200A\u202F\u205F\u3000]+", " ", s)
    return s

# ---------------- Parsers ----------------
START_RE = re.compile(r"(?im)^\s*(\d{1,3})[.)]?\s*Nama\s*:\s*.+$")
OP_RE    = re.compile(r"(?im)^\s*•\s*Operator\s*:\s*.+$")
RM_RE    = re.compile(r"(?im)^\s*•\s*RM\s*:\s*.+$")
DX_RE    = re.compile(r"(?im)^\s*•\s*Diagnosa\s*:\s*.+$")
TDK_RE   = re.compile(r"(?im)^\s*•\s*Tindakan\s*:\s*.*$")
NOISE_RE = re.compile(r"(?i)^\s*(siap|baik|oke|ok|noted|tabe|izin|iya|betul|terima kasih|thanks|read\s*more)\b")

WA_HEADER_RE = re.compile(r"^\s*\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}[:.]\d{2}(?::?\d{2})?\]\s*[^:\n]+:\s*$")

def read_docx_bytes(b: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(b))
    return "\n".join(p.text for p in doc.paragraphs)

def read_pdf_bytes(b: bytes) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return "\n".join(out)

def split_blocks(text: str) -> List[str]:
    """Ambil kandidat blok dari 'N. Nama :' hingga sebelum start berikutnya,
       lalu dipotong di kemunculan terakhir '• Operator :'."""
    starts = [m.start() for m in START_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    raw_blocks = [text[starts[i]:starts[i+1]].strip() for i in range(len(starts)-1)]
    blocks = []
    for blk in raw_blocks:
        last_op = None
        for m in OP_RE.finditer(blk):
            last_op = m
        if last_op:
            blk = blk[: last_op.end()]
            blocks.append(blk.strip())
    return blocks

def clean_inside_block(blk: str) -> str:
    """Di dalam blok, buang baris yang bukan bagian review:
       - Header WA
       - Chit-chat/noise
       - Baris yang tidak diawali start-line, bullet '•', atau sub-bullet ' * ' (tetap simpan OP)."""
    lines = blk.splitlines()
    out = []
    first_line_kept = False
    for i, ln in enumerate(lines):
        if WA_HEADER_RE.match(ln):
            continue
        if NOISE_RE.match(ln.strip()):
            continue
        if not first_line_kept:
            # Harus start line "N. Nama :"
            if START_RE.match(ln):
                out.append(ln.strip())
                first_line_kept = True
            else:
                # abaikan apapun sebelum start line
                continue
            continue

        if OP_RE.match(ln):
            out.append(ln.strip())
            # OP harus jadi baris TERAKHIR blok
            break

        # label bullet '• xxx :' dan sub-bullet (mulai dengan * atau - diindent)
        if re.match(r"^\s*•\s*.+", ln) or re.match(r"^\s{0,8}[\*\-]\s+.+", ln):
            out.append(ln.rstrip())
            continue

        # izinkan baris kosong
        if not ln.strip():
            out.append("")
            continue

        # baris lain (narasi SOAP, koreksi, chat) dibuang
        # pass
    # pastikan baris terakhir adalah OP
    if not out or not OP_RE.match(out[-1] if out else ""):
        # kalau OP belum ketemu karena dipotong, coba cari terakhir di blk asli lalu append
        last_op_line = None
        for ln in lines[::-1]:
            if OP_RE.match(ln):
                last_op_line = ln.strip()
                break
        if last_op_line:
            out.append(last_op_line)
    return "\n".join(out).strip()

def minimal_valid(blk: str) -> bool:
    return bool(START_RE.search(blk) and OP_RE.search(blk) and RM_RE.search(blk) and DX_RE.search(blk) and TDK_RE.search(blk))

def get_name(blk: str) -> str:
    m = re.search(r"(?im)^\s*\d{1,3}[.)]?\s*Nama\s*:\s*(.+?)\s*$", blk)
    return (m.group(1).strip() if m else "").strip()

def get_index(blk: str) -> int:
    m = re.search(r"(?im)^\s*(\d{1,3})[.)]?\s*Nama\s*:", blk)
    return int(m.group(1)) if m else 9999

def names_from_pdf(pdf_text: str) -> List[str]:
    t = normalize_text(strip_format_chars(pdf_text))
    names = []
    for m in re.finditer(r"(?im)^\s*(?:\d{1,3}[.)]?\s*)?Nama\s*:\s*(.+?)\s*$", t):
        nm = " ".join(m.group(1).split())
        if nm and nm not in names:
            names.append(nm)
    return names

def reorder_by_pdf(blocks: List[str], pdf_names: List[str]) -> List[str]:
    pos = {nm.lower(): i for i, nm in enumerate(pdf_names)}
    def key(b):
        nm = get_name(b).lower()
        return (0, pos[nm]) if nm in pos else (1, get_index(b), nm)
    return sorted(blocks, key=key)

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Cleaner Review – Solid", layout="wide")
st.title("Cleaner Review – blok valid only (start: 'N. Nama', end: '• Operator')")

c1, c2 = st.columns(2)
with c1:
    chat_up = st.file_uploader("Upload chat (.docx / .txt)", type=["docx","txt"])
with c2:
    pdf_up  = st.file_uploader("(Opsional) PDF laporan pengunjung", type=["pdf"])

keep_numbers = st.checkbox("Pertahankan nomor asli (tidak renumber)", value=True)
use_pdf_order = st.checkbox("Urutkan mengikuti urutan nama di PDF (jika diunggah)", value=True)

if st.button("Proses"):
    if not chat_up:
        st.error("Upload file chat dulu.")
        st.stop()

    # Baca chat
    if chat_up.name.lower().endswith(".txt"):
        raw = chat_up.read().decode("utf-8", errors="ignore")
    else:
        raw = read_docx_bytes(chat_up.read())

    # Normalisasi
    raw = strip_format_chars(raw)
    text = normalize_text(raw)

    # Ekstrak kandidat blok
    blocks = split_blocks(text)

    # Bersihkan isi blok & validasi minimal
    cleaned = []
    dropped_dbg: List[Tuple[str,str]] = []
    for b in blocks:
        cb = clean_inside_block(b)
        if minimal_valid(cb):
            cleaned.append(cb)
        else:
            dropped_dbg.append((b, "label minimal tidak lengkap (butuh RM, Diagnosa, Tindakan, Operator)"))

    if not cleaned:
        st.error("Tidak ketemu blok review yang valid.")
        with st.expander("Debug potongan yang terdeteksi tapi dibuang"):
            for b, why in dropped_dbg[:10]:
                st.markdown(f"- **Sebab**: {why}")
                st.code(b[:1200])
        st.stop()

    # Urutkan
    if pdf_up and use_pdf_order:
        pdf_text = read_pdf_bytes(pdf_up.read())
        pdf_names = names_from_pdf(pdf_text)
        if pdf_names:
            cleaned = reorder_by_pdf(cleaned, pdf_names)

    # (opsional) renumber
    if not keep_numbers:
        ren = []
        for i, b in enumerate(cleaned, 1):
            ren.append(re.sub(r"(?im)^\s*\d{1,3}[.)]?\s*Nama", f"{i}. Nama", b, count=1))
        cleaned = ren

    # Output
    final_txt = "\n\n".join(cleaned)
    st.subheader("Hasil (blok review bersih)")
    st.text_area("Siap copas", final_txt, height=600)
    st.download_button("Download hasil.txt", final_txt.encode("utf-8"), "hasil.txt", "text/plain")

    with st.expander("Blok yang dipakai"):
        for i, b in enumerate(cleaned, 1):
            st.markdown(f"**{i}. {get_name(b)}**")
            st.code(b)
