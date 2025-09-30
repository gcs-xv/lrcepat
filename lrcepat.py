import re, io, unicodedata
from typing import List
import streamlit as st

# ========== IO helpers ==========
def read_docx_bytes(b: bytes) -> str:
    from docx import Document
    bio = io.BytesIO(b)
    doc = Document(bio)
    return "\n".join(p.text for p in doc.paragraphs)

def read_pdf_bytes(b: bytes) -> str:
    import pdfplumber
    text = []
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for p in pdf.pages:
            text.append(p.extract_text() or "")
    return "\n".join(text)

# ========== Normalization ==========
def strip_format_chars(s: str) -> str:
    # buang seluruh Unicode "format" (zero-width, joiner, feff, dsb)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")

def normalize_whitespace_keep_newlines(s: str) -> str:
    # samakan spasi (termasuk NBSP, en/em space, dsb) -> spasi normal
    # tapi JANGAN ganggu newline
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[ \t\u2000-\u200A\u202F\u205F\u3000]+", " ", s)
    return s

def normalize_bullets(s: str) -> str:
    # standarkan bullet di awal baris jadi "• "
    s = re.sub(r"(?m)^\s*([·‧•◦▪▫●○\-\*])\s*", "• ", s)
    return s

def normalize_all(s: str) -> str:
    s = strip_format_chars(s)
    s = unicodedata.normalize("NFKC", s)
    s = normalize_whitespace_keep_newlines(s)
    s = normalize_bullets(s)
    return s

# ========== WhatsApp noise stripper ==========
WA_HEADER = re.compile(
    r"(?m)^\s*\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}[:.]\d{2}(?::?\d{2})?\]\s*[^:\n]+:\s*$"
)
NOISE_LINE = re.compile(
    r"(?i)^\s*(siap|baik|ok(ay)?|oke|noted|tabe|izin|iya|betul|terima kasih|thanks|read\s*more)\b.*$"
)
SOAP_ANCHOR = re.compile(r"(?im)^\s*(Assalamualaikum|Maaf mengganggu|S:|O:|A:|P:|Status\s+Generalis|Status\s+Lokalis)\b")

def strip_whatsapp_noise(s: str) -> str:
    out = []
    for ln in s.splitlines():
        if WA_HEADER.match(ln):                 # header WA
            continue
        if NOISE_LINE.match(ln.strip()):        # chit-chat/templat
            continue
        if SOAP_ANCHOR.match(ln.strip()):       # laporan SOAP naratif
            continue
        out.append(ln)
    s2 = "\n".join(out)
    s2 = re.sub(r"(?i)read\s*more", "", s2)     # sisa "Read more"
    return s2

# ========== Review block detection ==========
# Start blok: "N. Nama : ..."
REVIEW_START = re.compile(r"(?im)^\s*(\d{1,3})[.)]?\s*Nama\s*:\s*.+?$")

# Operator line (sangat toleran, bullet apapun, spasi bebas, ada ':')
OP_LINE = re.compile(r"(?im)^[^\S\r\n]*[•\-\*][^\S\r\n]*Operator[^\S\r\n]*:[^\n]*$")

# Label wajib (longgar)
LBL = {
    "nama": re.compile(r"(?im)^\s*\d{1,3}[.)]?\s*Nama\s*:\s*.+$"),
    "tgl": re.compile(r"(?im)^\s*•\s*Tanggal\s*lahir\s*:\s*.+$"),
    "rm": re.compile(r"(?im)^\s*•\s*RM\s*:\s*.+$"),
    "dx": re.compile(r"(?im)^\s*•\s*Diagnosa\s*:\s*.+$"),
    "tdk": re.compile(r"(?im)^\s*•\s*Tindakan\s*:\s*.+$"),
    "ktr": re.compile(r"(?im)^\s*•\s*Kontrol\s*:\s*.*$"),
    "dpjp": re.compile(r"(?im)^\s*•\s*DPJP\s*:\s*.+$"),
    "telp": re.compile(r"(?im)^\s*•\s*No\.?\s*Telp\.?\s*:\s*.+$"),
    "opr": OP_LINE
}

def split_candidate_blocks(text: str) -> List[str]:
    starts = [m.start() for m in REVIEW_START.finditer(text)]
    if not starts: return []
    starts.append(len(text))
    blocks = [text[starts[i]:starts[i+1]].strip() for i in range(len(starts)-1)]
    return blocks

def clean_block_tail(block: str) -> str:
    # potong DI AKHIR kemunculan • Operator :
    last = None
    for m in OP_LINE.finditer(block):
        last = m
    if last:
        return block[: last.end()].rstrip()
    return block

def has_all_labels(block: str) -> bool:
    return all(p.search(block) is not None for p in LBL.values())

def parse_name(block: str) -> str:
    m = re.search(r"(?im)^\s*\d{1,3}[.)]?\s*Nama\s*:\s*(.+?)\s*$", block)
    return " ".join(m.group(1).split()) if m else ""

# ========== PDF precedence ==========
def names_from_pdf(pdf_text: str) -> List[str]:
    t = normalize_all(pdf_text)
    names = []
    for m in re.finditer(r"(?im)^\s*(?:\d{1,3}[.)]?\s*)?Nama\s*:\s*(.+?)\s*$", t):
        nm = " ".join(m.group(1).split())
        if nm and nm not in names:
            names.append(nm)
    return names

def order_by_pdf(blocks: List[str], pdf_names: List[str]) -> List[str]:
    idx = {nm.lower(): i for i, nm in enumerate(pdf_names)}
    def key(b):
        nm = parse_name(b).lower()
        return (0, idx[nm]) if nm in idx else (1, nm)
    return sorted(blocks, key=key)

# ========== Counters ==========
ACTION_KW = [
    "odontektomi","ekstraksi","insisi","drainase","wound debridement","marsupialisasi",
    "replantasi","reposisi","archbar","wiring","alveolektomi","sinus washout","enukleasi",
    "apeks reseksi","debridement"
]
CONSULT_HINT = [
    "konsultasi","periapikal","opg","x-ray","rujuk","kontrol luka","cuci luka",
    "aff hecting","aff drain","pemeriksaan","laboratorium","thorax x-ray"
]

def classify_block(block: str) -> str:
    m = re.search(r"(?is)^\s*•\s*Tindakan\s*:(.+?)(?:^\s*•|\Z)", block, re.MULTILINE)
    seg = normalize_all(m.group(1) if m else "").lower()
    if any(kw in seg for kw in ACTION_KW): return "tindakan"
    if any(kw in seg for kw in CONSULT_HINT): return "konsultasi"
    return "konsultasi"

def renumber(blocks: List[str]) -> List[str]:
    out = []
    for i, b in enumerate(blocks, 1):
        out.append(re.sub(r"(?im)^\s*\d{1,3}[.)]?\s*Nama", f"{i}. Nama", b, count=1))
    return out

def header(date_str: str, tot):
    return (
f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, Sabtu, ({date_str})\n\n"
f"Jumlah pasien    : {tot['jumlah']:02d} Pasien \n"
f"Tindakan             : {tot['tindakan']:02d} Pasien \n"
f"Konsultasi           : {tot['konsultasi']:02d} Pasien\n"
f"Terjaring GA        : {tot['ga']:02d} Pasien\n"
f"VIP                       : {tot['vip']:02d} Pasien\n"
f"Baksos                 : {tot['baksos']:02d} Pasien \n\n"
"------------------------------------------------------------\n\n"
"POLI INTEGRASI\n"
    )

def footer(chief: str, dpjp: List[str], date_str: str) -> str:
    lines = ["", "------------------------------------------------------------", "", f"Sabtu,  {date_str}", "", "Chief jaga poli :", chief, "", "DPJP :"]
    for i, d in enumerate(dpjp, 1):
        lines.append(f"{i}. {d}")
    return "\n".join(lines)

# ========== UI ==========
st.set_page_config(page_title="Cleaner Review Poli – Tahan Banting", layout="wide")
st.title("Cleaner Review Poli – PDF Precedence & Hard Trim at Operator")

c1, c2 = st.columns(2)
with c1:
    chat_file = st.file_uploader("Upload Chat (.docx / .txt)", type=["docx","txt"])
with c2:
    pdf_file = st.file_uploader("Upload PDF Laporan Pengunjung", type=["pdf"])

date_str = st.text_input("Tanggal header/footer (dd/mm/yyyy)", "27/09/2025")
chief = st.text_input("Chief jaga poli", "drg. I Gede Surya Septaadinata")
dpjp_default = [
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. Nurwahida, M.KG., Sp.B.M.M.,Subsp.C.O.M.(K)",
    "drg. Mukhtar Nur Anam, Sp.B.M.M",
    "drg. Timurwati, Sp.B.M.M",
    "drg. Husni Mubarak, Sp.B.M.M.",
    "drg. Carolina Stevanie, Sp.B.M.M",
]
dpjp_text = st.text_area("DPJP (satu per baris)", "\n".join(dpjp_default), height=140)

colx = st.columns(3)
vip_override = colx[0].number_input("VIP (override)", min_value=0, step=1, value=0)
ga_override = colx[1].number_input("Terjaring GA (override)", min_value=0, step=1, value=0)
baksos_override = colx[2].number_input("Baksos (override)", min_value=0, step=1, value=0)

if st.button("Proses"):
    if not chat_file:
        st.error("Upload file chat dulu.")
        st.stop()

    # Load chat
    if chat_file.name.lower().endswith(".txt"):
        raw = chat_file.read().decode("utf-8", errors="ignore")
    else:
        raw = read_docx_bytes(chat_file.read())

    norm = normalize_all(raw)
    no_wa = strip_whatsapp_noise(norm)

    # Split -> bersihkan tail di Operator -> validasi label
    cands = split_candidate_blocks(no_wa)
    blocks = []
    for b in cands:
        bt = clean_block_tail(b)
        if has_all_labels(bt):
            blocks.append(bt)

    if not blocks:
        st.error("Tidak ketemu blok review yang valid (cek lagi label & bullet). Lihat 'Debug input' di bawah.")
        with st.expander("Debug input (normalized & cleaned)"):
            st.code(no_wa[:5000])
        st.stop()

    # Urutan ikut PDF kalau ada
    if pdf_file:
        pdf_text = read_pdf_bytes(pdf_file.read())
        pdf_names = names_from_pdf(pdf_text)
        if pdf_names:
            blocks = order_by_pdf(blocks, pdf_names)

    # Hitung ringkasan
    jumlah = len(blocks)
    tindakan = sum(1 for b in blocks if classify_block(b) == "tindakan")
    konsultasi = jumlah - tindakan
    ga = sum(1 for b in blocks if re.search(r"(?i)\bgeneral\s+anestesi\b|\bGA\b", b))
    baksos = 0  # default manual override via input

    # Override
    vip = vip_override
    if ga_override: ga = ga_override
    if baksos_override: baksos = baksos_override

    totals = dict(jumlah=jumlah, tindakan=tindakan, konsultasi=konsultasi, ga=ga, vip=vip, baksos=baksos)

    # Renumber dan render
    blocks = renumber(blocks)
    final_txt = header(date_str, totals) + "\n\n".join(blocks) + "\n\n" + footer(chief, [x for x in dpjp_text.splitlines() if x.strip()], date_str)

    st.subheader("Hasil Akhir")
    st.text_area("Siap copas", final_txt, height=600)
    st.download_button("Download .txt", final_txt.encode("utf-8"), "review_final.txt", "text/plain")

    with st.expander("Preview blok yang dipakai"):
        for i, b in enumerate(blocks, 1):
            st.markdown(f"**Blok {i} – {parse_name(b)}**")
            st.code(b)
