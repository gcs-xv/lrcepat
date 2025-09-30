import re
import io
import unicodedata
from typing import List, Tuple, Dict, Any
import streamlit as st

# ===== Helpers: load files =====
def read_docx_bytes(file_bytes: bytes) -> str:
    # python-docx sometimes chokes on zero-width chars. We strip before parse.
    from docx import Document
    bio = io.BytesIO(file_bytes)
    doc = Document(bio)
    paras = []
    for p in doc.paragraphs:
        paras.append(p.text)
    return "\n".join(paras)

def read_pdf_bytes(file_bytes: bytes) -> str:
    import pdfplumber
    text_all = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_all.append(t)
    return "\n".join(text_all)

# ===== Normalization =====
ZW = "".join(chr(c) for c in [0x200B, 0x200C, 0x200D, 0xFEFF])  # zero-width chars

def normalize(s: str) -> str:
    # normalize bullets, colons, spaces, zero-width
    s = s.replace("•", "•").replace("‧", "•").replace("·", "•")
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("：", ":")
    s = s.replace("  ", " ")
    s = re.sub(rf"[{ZW}]", "", s)
    # NFKC helps equalize weird spacing
    s = unicodedata.normalize("NFKC", s)
    # ensure bullets start with "• " (space) for easier regex
    s = re.sub(r"\n\s*•\s*", "\n• ", s)
    return s

# ===== Pre-clean WhatsApp noise =====
WA_HEADER = re.compile(
    r"^\s*\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}[:.]\d{2}[:.]?\d{0,2}\]\s*.+?:\s*$",
    re.MULTILINE
)
# Lines to drop entirely (common chatter)
NOISE_LINE = re.compile(
    r"^\s*(siap|baik|oke|ok|noted|tabe|izin|iya|betul|siap bang|baik bang|siap mbak|baik mbak|read more|readmore)\b.*$",
    re.IGNORECASE
)
# SOAP / laporan naratif panjang (kita drop blok yang jelas bukan format review)
SOAP_ANCHOR = re.compile(
    r"^\s*(Assalamualaikum|Maaf mengganggu|Status Generalis|Status Lokalis|S:|O:|A:|P:)\b",
    re.IGNORECASE | re.MULTILINE
)

def strip_whatsapp_noise(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    skip_block = False
    for ln in lines:
        if WA_HEADER.match(ln.strip()):
            # drop header baris
            continue
        if NOISE_LINE.match(ln.strip()):
            continue
        if SOAP_ANCHOR.match(ln.strip()):
            # buang baris SOAP yang tidak dalam format review
            continue
        cleaned.append(ln)
    s = "\n".join(cleaned)
    # hapus potongan "‎Read more" yang muncul sebagai char khusus
    s = re.sub(r"(?i)read\s*more", "", s)
    return s

# ===== Extract review blocks =====
# Start anchor: "N. Nama :"
REVIEW_START = re.compile(
    r"(?im)^\s*(\d{1,3})[.)]?\s*Nama\s*:.*?$"
)

def split_candidate_blocks(text: str) -> List[str]:
    # find all "N. Nama : ..." starts, split to next start
    starts = [m.start() for m in REVIEW_START.finditer(text)]
    blocks = []
    if not starts:
        return blocks
    starts.append(len(text))
    for i in range(len(starts)-1):
        chunk = text[starts[i]:starts[i+1]]
        blocks.append(chunk.strip())
    return blocks

def block_has_operator(block: str) -> bool:
    # must contain Operator line before anything else
    return re.search(r"(?im)^\s*•\s*Operator\s*:", block) is not None

def is_true_review(block: str) -> bool:
    need = [
        r"^\s*\d{1,3}[.)]?\s*Nama\s*:",
        r"^\s*•\s*Tanggal lahir\s*:",
        r"^\s*•\s*RM\s*:",
        r"^\s*•\s*Diagnosa\s*:",
        r"^\s*•\s*Tindakan\s*:",
        r"^\s*•\s*Kontrol\s*:",
        r"^\s*•\s*DPJP\s*:",
        r"^\s*•\s*No\.\s*Telp\.\s*:",
        r"^\s*•\s*Operator\s*:",
    ]
    for pat in need:
        if re.search(pat, block, flags=re.IGNORECASE | re.MULTILINE) is None:
            return False
    return block_has_operator(block)

def clean_block_tail(block: str) -> str:
    # truncate strictly at the Operator line (inclusive)
    m = re.search(r"(?im)^\s*•\s*Operator\s*:.*$", block)
    if not m:
        return block
    end = m.end()
    return block[:end].rstrip()

def parse_name(block: str) -> str:
    m = re.search(r"(?im)^\s*\d{1,3}[.)]?\s*Nama\s*:\s*(.+?)\s*$", block)
    if m:
        return " ".join(m.group(1).split())
    return ""

# ===== PDF precedence ordering =====
def names_from_pdf(pdf_text: str) -> List[str]:
    t = normalize(pdf_text)
    # ambil deret nama dari pola "Nama : X"
    names = []
    for m in re.finditer(r"(?im)^\s*(?:\d{1,3}[.)]?\s*)?Nama\s*:\s*(.+?)\s*$", t):
        nm = " ".join(m.group(1).split())
        if nm and nm not in names:
            names.append(nm)
    return names

def order_blocks_by_pdf(blocks: List[str], pdf_names: List[str]) -> List[str]:
    # map each block name to its index in pdf_names
    key_map = {nm.lower(): i for i, nm in enumerate(pdf_names)}
    def sort_key(b):
        nm = parse_name(b).lower()
        return (0, key_map[nm]) if nm in key_map else (1, parse_name(b).lower())
    return sorted(blocks, key=sort_key)

# ===== Counters =====
ACTION_KEYWORDS = [
    "odontektomi","ekstraksi","insisi","drainase","wound debridement","marsupialisasi",
    "replantasi","reposisi","archbar","wiring","alveolektomi","sinus washout",
    "enukleasi","apeks reseksi","debridement"
]
CONSULT_ONLY_HINTS = [
    "konsultasi","periapikal","opg","x-ray","rujuk","kontrol luka","cuci luka",
    "aff hecting","aff drain","aff archbar","pemeriksaan","laboratorium","thorax x-ray"
]

def classify_block(block: str) -> str:
    tind = re.search(r"(?is)•\s*Tindakan\s*:(.+?)(?:^\s*•|\Z)", block)
    segment = tind.group(1) if tind else ""
    seg_clean = normalize(segment.lower())
    # tindakan jika ada kata tindakan utama
    if any(kw in seg_clean for kw in ACTION_KEYWORDS):
        return "tindakan"
    # kalau hanya konsultatif/supportive
    if any(kw in seg_clean for kw in CONSULT_ONLY_HINTS):
        return "konsultasi"
    # fallback: konsultasi
    return "konsultasi"

def is_baksos_context(block: str, full_text_before: str) -> bool:
    # lihat apakah sebelum blok ada heading BAKSOS dalam 50 baris sebelumnya
    tail = "\n".join(full_text_before.splitlines()[-50:])
    return re.search(r"(?i)BAKSOS", tail) is not None

# ===== Render final text =====
def renumber_blocks(blocks: List[str]) -> List[str]:
    out = []
    for i, b in enumerate(blocks, start=1):
        out.append(re.sub(r"(?im)^\s*\d{1,3}[.)]?\s*Nama", f"{i}. Nama", b, count=1))
    return out

def build_header(date_str: str, totals: Dict[str,int]) -> str:
    return (
f"Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, Sabtu, ({date_str})\n\n"
f"Jumlah pasien    : {totals['jumlah']:02d} Pasien \n"
f"Tindakan             : {totals['tindakan']:02d} Pasien \n"
f"Konsultasi           : {totals['konsultasi']:02d} Pasien\n"
f"Terjaring GA        : {totals['ga']:02d} Pasien\n"
f"VIP                       : {totals['vip']:02d} Pasien\n"
f"Baksos                 : {totals['baksos']:02d} Pasien \n\n"
"------------------------------------------------------------\n\n"
"POLI INTEGRASI\n"
    )

def build_footer(chief: str, dpjp: List[str], date_str: str) -> str:
    lines = ["", "------------------------------------------------------------", "", f"Sabtu,  {date_str}", "", "Chief jaga poli :", chief, "", "DPJP :"]
    for i, d in enumerate(dpjp, start=1):
        lines.append(f"{i}. {d}")
    return "\n".join(lines)

# ===== Streamlit UI =====
st.set_page_config(page_title="Cleaner Review Poli", layout="wide")
st.title("Cleaner Review Poli – PDF Precedence")

col1, col2 = st.columns(2)
with col1:
    chat_file = st.file_uploader("Upload Chat WhatsApp (.docx atau .txt)", type=["docx","txt"])
with col2:
    pdf_file = st.file_uploader("Upload PDF Laporan Pengunjung", type=["pdf"])

date_str = st.text_input("Tanggal untuk header/footer (dd/mm/yyyy)", "27/09/2025")
chief = st.text_input("Chief jaga poli", "drg. I Gede Surya Septaadinata")
dpjp_default = [
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.M., Subsp. C.O.M.(K)",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J.(K)",
    "drg. Nurwahida, M.KG., Sp.B.M.M.,Subsp.C.O.M.(K)",
    "drg. Mukhtar Nur Anam, Sp.B.M.M",
    "drg. Timurwati, Sp.B.M.M",
    "drg. Husni Mubarak, Sp.B.M.M.",
    "drg. Carolina Stevanie, Sp.B.M.M"
]
dpjp_text = st.text_area("DPJP (satu per baris)", "\n".join(dpjp_default), height=140)

col3, col4, col5, col6 = st.columns(4)
with col3:
    vip_override = st.number_input("VIP (override)", min_value=0, value=0, step=1)
with col4:
    ga_override = st.number_input("Terjaring GA (override)", min_value=0, value=0, step=1)
with col5:
    baksos_override = st.number_input("Baksos (override)", min_value=0, value=0, step=1)
with col6:
    st.write(" ")

if st.button("Proses"):
    if not chat_file:
        st.error("Upload file chat dulu.")
        st.stop()

    # ==== Read chat ====
    if chat_file.type.endswith("text/plain") or chat_file.name.lower().endswith(".txt"):
        chat_raw = chat_file.read().decode("utf-8", errors="ignore")
    else:
        chat_raw = read_docx_bytes(chat_file.read())

    chat_norm = normalize(chat_raw)
    chat_clean = strip_whatsapp_noise(chat_norm)

    # ==== Candidate review blocks ====
    cands = split_candidate_blocks(chat_clean)
    review_blocks = []
    # untuk deteksi baksos, kita butuh bagian 'before'; simpan offset
    for b in cands:
        b2 = clean_block_tail(b)
        if is_true_review(b2):
            review_blocks.append(b2)

    if not review_blocks:
        st.warning("Tidak ketemu blok review yang valid (pastikan format tepat dan baris '• Operator :' ada).")
        st.text_area("Chat (setelah dibersihkan)", chat_clean, height=250)
        st.stop()

    # ==== PDF order ====
    pdf_names_order = []
    if pdf_file:
        pdf_text = read_pdf_bytes(pdf_file.read())
        pdf_names_order = names_from_pdf(pdf_text)

    # ==== Sort by PDF precedence ====
    if pdf_names_order:
        review_blocks = order_blocks_by_pdf(review_blocks, pdf_names_order)

    # ==== Classify & count ====
    jumlah = len(review_blocks)
    tindakan = 0
    konsultasi = 0
    ga = 0
    baksos = 0
    vip = 0  # kalau nanti ada penandaan khusus VIP, bisa ditambah tag/keyword

    # terjaring GA: deteksi dari Diagnosa (mengandung "GA" sebagai general anestesi) atau rencana GA
    for idx, b in enumerate(review_blocks):
        cls = classify_block(b)
        if cls == "tindakan":
            tindakan += 1
        else:
            konsultasi += 1

        # GA detection (ringan)
        if re.search(r"(?i)\bgeneral anestesi\b|\bGA\b", b):
            ga += 1

        # Baksos context: cek heading di chat sebelum blok aslinya
        # (gunakan chat_clean sebagai konteks, cari potongan sebelum kemunculan nama)
        nm = parse_name(b)
        pos = chat_clean.lower().find(nm.lower())
        if pos != -1 and is_baksos_context(b, chat_clean[:pos]):
            baksos += 1

    # Override manual jika diisi
    if vip_override:
        vip = vip_override
    if ga_override:
        ga = ga_override
    if baksos_override:
        baksos = baksos_override

    totals = {
        "jumlah": jumlah,
        "tindakan": tindakan,
        "konsultasi": konsultasi,
        "ga": ga,
        "vip": vip,
        "baksos": baksos
    }

    # ==== Renumber & Compose final text ====
    review_blocks = renumber_blocks(review_blocks)
    header = build_header(date_str, totals)
    footer = build_footer(chief, [x.strip() for x in dpjp_text.splitlines() if x.strip()], date_str)
    final_text = header + "\n\n".join(review_blocks) + "\n\n" + footer

    st.subheader("Final Report")
    st.text_area("Hasil akhir (siap copas)", final_text, height=600)

    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_final.txt", mime="text/plain")

    # Debug/preview (opsional)
    with st.expander("Preview blok review yang dipakai"):
        for i, b in enumerate(review_blocks, 1):
            st.markdown(f"**Blok {i} – {parse_name(b)}**")
            st.code(b)
