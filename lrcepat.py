import io, re
from typing import List, Dict, Any, Optional, Tuple
import streamlit as st

# ---------- Normalisasi ----------
_ZW = "\u200b\u200c\u200d\u2060\ufeff"
ZW_TRANS = dict.fromkeys(map(ord, _ZW), None)

WA_HEADER_RE = re.compile(
    r"""^\[
        \d{2}/\d{2}/\d{2},\s*
        \d{1,2}\.\d{2}\.\d{2}
    \]\s[^:]+:\s*""", re.MULTILINE | re.VERBOSE
)

SECTION_RE = re.compile(r"(?im)^\s*(POLI\s+INTEGRASI|BAKSOS\b[^\n]*)\s*$")
START_RE = re.compile(r"(?m)^\s*(\d{1,3})\.\s*Nama\s*:\s*.+$")

def read_text(uploaded) -> str:
    name = uploaded.name.lower()
    data = uploaded.read()
    if name.endswith(".docx"):
        try:
            from docx import Document
        except ImportError:
            st.error("Tambahkan `python-docx` di requirements.txt")
            st.stop()
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace")

def normalize(t: str) -> str:
    t = t.translate(ZW_TRANS).replace("\xa0", " ")
    t = WA_HEADER_RE.sub("", t)
    t = t.replace("Read more", "").replace("‎Read more", "")
    t = "\n".join(line.rstrip() for line in t.splitlines())
    return t

def find_sections(t: str) -> List[Tuple[int, str]]:
    secs = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(t)]
    secs.sort(key=lambda x: x[0])
    return secs

# ---------- Ekstraksi blok ----------
FIELD_PATTERNS = {
    "nama":        re.compile(r"(?im)^\s*\d{1,3}\.\s*Nama\s*:\s*.+$"),
    "tgl_lahir":   re.compile(r"(?im)^\s*•\s*Tanggal\s*lahir\s*:\s*\d{2}/\d{2}/\d{4}\s*$"),
    "rm":          re.compile(r"(?im)^\s*•\s*RM\s*:\s*[\d./]+\s*$"),
    "diagnosa":    re.compile(r"(?im)^\s*•\s*Diagnosa\s*:\s*.+$"),
    "tindakan":    re.compile(r"(?ims)^\s*•\s*Tindakan\s*:\s*(?:.+?)(?=^\s*•\s*(Kontrol|DPJP|No\.\s*Telp|Operator)\s*:|\Z)"),
    "kontrol":     re.compile(r"(?im)^\s*•\s*Kontrol\s*:\s*.+$"),
    "dpjp":        re.compile(r"(?im)^\s*•\s*DPJP\s*:\s*.+$"),
    "operator":    re.compile(r"(?im)^\s*•\s*Operator\s*:\s*.+$"),
    # No. Telp opsional
}

REJECT_HINTS = re.compile(
    r"(?i)\b(assalamualaikum|maaf\s+mengganggu|izin\s+melaporkan|rawat\s+(jalan|inap)|S:|O:|A:|P:|operator\s*:|gak review|baik( bang| mbak)?|siap( bang| mbak)?|tabe|cek lagi|lokal bukan|gelar dokter|kontrol pod)\b"
)

def slice_blocks(t: str) -> List[Tuple[int, int, str]]:
    """potong per blok mulai dari baris 'N. Nama : ...' sampai sebelum blok berikutnya/section/divider"""
    starts = [m.start() for m in START_RE.finditer(t)]
    if not starts: return []
    ends = starts[1:] + [len(t)]
    raw_blocks = []
    # hindari pecah kena header section di tengah
    cut = re.compile(r"(?m)^\s*(POLI\s+INTEGRASI|BAKSOS\b.*)$|^\s*-{6,}\s*$")
    for s, e in zip(starts, ends):
        chunk = t[s:e]
        parts = cut.split(chunk, maxsplit=1)
        raw_blocks.append((s, s + len(parts[0]), parts[0].rstrip()))
    return raw_blocks

def is_valid_block(txt: str) -> bool:
    # harus tidak mengandung kata-kata obrolan/noise umum
    if REJECT_HINTS.search(txt): 
        # NOTE: kata "Operator:" memang ada di format valid.
        # tapi yang noise biasanya muncul di SOAP bebas tanpa nomor awal.
        # Karena kita sudah slice berdasarkan START_RE, aman. Tetap biarkan pengecekan ini,
        # tapi longgarkan: kalau semua field wajib ada, tetap lolos.
        pass

    # wajib: Nama + Tgl Lahir + RM + Diagnosa + Tindakan + (Kontrol atau "-") + DPJP + Operator
    needed = ["nama", "tgl_lahir", "rm", "diagnosa", "tindakan", "dpjp", "operator"]
    for key in needed:
        if not FIELD_PATTERNS[key].search(txt):
            return False

    # Kontrol boleh "-" atau ada tanggal
    if not FIELD_PATTERNS["kontrol"].search(txt):
        # izinkan "•  Kontrol : -"
        if not re.search(r"(?im)^\s*•\s*Kontrol\s*:\s*-\s*$", txt):
            return False

    return True

def attach_section_name(pos: int, sections: List[Tuple[int, str]]) -> Optional[str]:
    label = None
    for spos, sname in sections:
        if spos <= pos: label = sname
        else: break
    return label

def extract_blocks_with_section(raw_text: str):
    t = normalize(raw_text)
    sections = find_sections(t)
    blocks = []
    for s, e, chunk in slice_blocks(t):
        if not is_valid_block(chunk): 
            continue
        sec = attach_section_name(s, sections)
        # Ambil nomor urut
        mnum = re.search(r"^\s*(\d{1,3})\.", chunk, flags=re.M)
        num = int(mnum.group(1)) if mnum else 0
        blocks.append({"num": num, "block": chunk.strip(), "section": sec})
    blocks.sort(key=lambda x: x["num"])
    return blocks

# ---------- Klasifikasi rekap ----------
PROC_KW_DEFAULT = [
    "Odontektomi","Ekstraksi","Cuci luka","Aff hecting","Aff drain","Wound Debridement",
    "Reposisi","IDW","Composite Wiring","Sinus washout","Marsupialisasi",
    "Alveolektomi","Enukleasi","Apeks reseksi"
]
def has_kw(s: str, kws: List[str]) -> bool:
    s = s.lower()
    return any(kw.lower() in s for kw in kws)

def classify(block: str, proc_kws: List[str], ga_kws: List[str], ignore_pod_for_ga=True):
    tindakan = re.search(r"(?ims)^\s*•\s*Tindakan\s*:\s*(.+?)(?=^\s*•\s*(Kontrol|DPJP|No\.\s*Telp|Operator)\s*:|\Z)", block)
    diagnosa = re.search(r"(?im)^\s*•\s*Diagnosa\s*:\s*(.+)$", block)
    t = tindakan.group(1).strip() if tindakan else ""
    d = diagnosa.group(1).strip() if diagnosa else ""

    is_proc = has_kw(t, proc_kws)
    is_cons = "konsultasi" in t.lower()
    is_pod  = ("pod" in d.lower()) or ("post operasi" in t.lower())

    text_ga = t + "\n" + d
    terjaring_ga = has_kw(text_ga, ga_kws) and (not is_pod if ignore_pod_for_ga else True)
    vip = "vip" in (t + "\n" + d).lower()

    return {
        "classify": "TINDAKAN" if is_proc else "KONSULTASI",
        "terjaring_ga": terjaring_ga,
        "vip": vip
    }

def pad2(n: int) -> str:
    return f"{n:02d}" if n < 100 else str(n)

def format_header(title: str, c: Dict[str,int]) -> str:
    return (
        f"{title}\n\n"
        f"Jumlah pasien    : {pad2(c['total'])} Pasien \n"
        f"Tindakan             : {pad2(c['tindakan'])} Pasien \n"
        f"Konsultasi           : {pad2(c['konsultasi'])} Pasien\n"
        f"Terjaring GA        : {pad2(c['ga'])} Pasien\n"
        f"VIP                       : {pad2(c['vip'])} Pasien\n"
        f"Baksos                 : {pad2(c['baksos'])} Pasien \n\n"
        f"------------------------------------------------------------\n\n"
    )

def build_report(blocks: List[Dict[str,Any]], title: str,
                 proc_kws: List[str], ga_kws: List[str], ignore_pod_for_ga=True):
    enriched = []
    for b in blocks:
        enriched.append({**b, **classify(b["block"], proc_kws, ga_kws, ignore_pod_for_ga)})

    main = [x for x in enriched if not (x["section"] or "").lower().startswith("baksos")]
    baks = [x for x in enriched if (x["section"] or "").lower().startswith("baksos")]

    total = len(enriched)
    tindakan = sum(1 for x in enriched if x["classify"]=="TINDAKAN")
    konsultasi = total - tindakan
    ga = sum(1 for x in enriched if x["terjaring_ga"])
    vip = sum(1 for x in enriched if x["vip"])
    baksos = len(baks)

    counts = dict(total=total, tindakan=tindakan, konsultasi=konsultasi, ga=ga, vip=vip, baksos=baksos)

    def join(bls): return "\n\n".join(b["block"] for b in bls)

    out = []
    out.append(format_header(title, counts))
    if main:
        out.append("POLI INTEGRASI\n")
        out.append(join(main)); out.append("")
    if baks:
        out.append("BAKSOS CCC\n")
        out.append(join(baks)); out.append("")
    return "\n".join(out).strip()+"\n", counts, main, baks

# ---------- UI ----------
st.set_page_config(page_title="Rekap Poli BM — WA Parser (strict)", layout="wide")
st.title("Rekap Pasien Poli Bedah Mulut — WA Parser (strict format only)")

with st.sidebar:
    st.header("Pengaturan")
    title_line = st.text_area("Judul laporan", value="Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, Sabtu, (27/09/2025)", height=80)
    proc_kws = st.text_area("Kata kunci tindakan (pisah dengan koma)",
                            value=", ".join(PROC_KW_DEFAULT), height=90)
    proc_kws = [x.strip() for x in proc_kws.split(",") if x.strip()]
    ga_kws = st.text_area("Kata kunci 'Terjaring GA' (pisah koma)",
                          value="Pro , general anestesi, Acc TS Anestesi, Konsul TS. Anestesi, Konsul TS Anestesi, Mouth Preparation, GA, CT, BT, HbsAg, GDS, Thorax",
                          height=90)
    ga_kws = [x.strip() for x in ga_kws.split(",") if x.strip()]
    ignore_pod_for_ga = st.checkbox("Jangan hitung kasus POD sebagai 'Terjaring GA'", value=True)
    show_dropped = st.checkbox("Tampilkan blok yang dibuang (debug)", value=False)

uploaded = st.file_uploader("Upload chat (.docx / .txt) — hanya format review pasien yang diambil", type=["docx","txt"])

if not uploaded:
    st.info("📄 Upload file dulu. Hanya blok yang cocok format review yang akan dipakai.")
    st.stop()

raw = read_text(uploaded)
norm = normalize(raw)

# simpan dulu blok kasar (berdasar START_RE), lalu filter ketat
all_slices = slice_blocks(norm)
valid_blocks = extract_blocks_with_section(norm)

if not valid_blocks:
    st.error("Tidak ada blok review pasien yang valid. Pastikan format tepat seperti contoh (Nomor. Nama, bullet '•', label field).")
    if show_dropped and all_slices:
        st.warning("Berikut contoh blok yang terdeteksi namun dibuang (tidak memenuhi field wajib):")
        for _,_,chunk in all_slices[:10]:
            st.code(chunk, language="markdown")
    st.stop()

report_text, counts, main_blocks, baks_blocks = build_report(
    valid_blocks, title_line, proc_kws, ga_kws, ignore_pod_for_ga
)

col1, col2 = st.columns([3,2], gap="large")
with col1:
    st.subheader("Preview Laporan (siap kirim)")
    st.code(report_text, language="markdown")
    st.download_button("⬇️ Download .txt", data=report_text.encode("utf-8"),
                       file_name="rekap_poli_bm.txt", mime="text/plain")

with col2:
    st.subheader("Rekap Otomatis")
    st.metric("Jumlah Pasien", counts["total"])
    st.metric("Tindakan", counts["tindakan"])
    st.metric("Konsultasi", counts["konsultasi"])
    st.metric("Terjaring GA", counts["ga"])
    st.metric("VIP", counts["vip"])
    st.metric("Baksos", counts["baksos"])

    if show_dropped:
        st.subheader("Debug: Blok Dibuang")
        for s, e, chunk in all_slices:
            # tampilkan yang tidak masuk valid
            if not any(b["block"] == chunk.strip() for b in valid_blocks):
                st.code(chunk, language="markdown")
