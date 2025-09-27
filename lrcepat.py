# app.py
import re
import io
import unicodedata
from datetime import date
import streamlit as st

# ================== Tanggal Indonesia ==================
HARI_ID = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
def tanggal_id(dt: date) -> str:
    h = HARI_ID[dt.weekday()]
    return f"{h} ({dt.strftime('%d/%m/%Y')})"

# ================== Hierarki DPJP (format baku) ==================
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

# buat “key sederhana” untuk pencocokan longgar
def simple_key(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    # hapus 'drg.' berulang & koma/gelar supaya fokus ke nama inti
    n = n.replace("drg.", " ").replace("drg", " ")
    n = re.sub(r'\b(ph\.?d|m\.?ars|m\.?kes|m\.?kg|sp\.?\.?b\.?\.?m\.?\.?m\.?|subsp[^,)]*)\b', ' ', n)
    # hapus tanda baca & spasi ganda
    n = re.sub(r'[^a-z0-9 ]+', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

# peta “key sederhana” ke entri baku dari hierarki
DPJP_KEY_MAP = {simple_key(std): std for std in DPJP_PRIORITY}

def map_dpjp_to_priority(raw: str) -> str:
    if not raw or not raw.strip():
        return raw
    # bersihkan duplikasi 'drg.'
    raw_norm = re.sub(r'\bdrg\.\s*drg\.\b', 'drg.', raw, flags=re.IGNORECASE)
    key = simple_key(raw_norm)
    if not key:
        return raw
    # strategi matching:
    # 1) coba cocok langsung
    if key in DPJP_KEY_MAP:
        return DPJP_KEY_MAP[key]
    # 2) cocok berdasar kemiripan token dengan semua prioritas — pilih skor tertinggi
    tokens = set(key.split())
    best_std, best_score = None, -1
    for std_key, std_val in DPJP_KEY_MAP.items():
        std_tokens = set(std_key.split())
        score = len(tokens & std_tokens)  # irisan token
        # bonus jika salah satu mengandung yang lain
        if key.replace(" ", "") in std_key.replace(" ", "") or std_key.replace(" ", "") in key.replace(" ", ""):
            score += 2
        if score > best_score:
            best_score, best_std = score, std_val
    # kalau tidak ada irisan sama sekali, kembalikan raw_norm (biar nggak salah mapping)
    return best_std if best_score > 0 else raw_norm.strip()

# ================== Normalisasi teks WA ==================
WHATSAPP_PREFIX_RE = re.compile(
    r'^\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}\.\d{2}\.\d{2}\]\s*[^:]{1,120}:\s*',
    flags=re.MULTILINE
)

def normalize_wa_text(raw: str) -> str:
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    # JANGAN hapus semua prefix dulu — simpan posisi untuk "terbaru"
    # → Kita akan parsing blok dengan posisi indeks .start()
    # Tapi tetap hapus prefix pada teks bloknya agar rapi
    return t

def strip_wa_prefix(segment: str) -> str:
    s = WHATSAPP_PREFIX_RE.sub("", segment)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    s = "".join(" " if unicodedata.category(ch).startswith("Z") else ch for ch in s)
    s = s.replace("\t", " ")
    s = re.sub(r"[ ]+\n", "\n", s)
    return s

# ================== Regex blok & field ==================
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
    if val is None:
        return None
    lines = [ln.rstrip() for ln in val.strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)

def parse_block(txt: str, pos: int):
    segment = strip_wa_prefix(txt)  # bersihkan prefix di isi blok
    data = {"_pos": pos}  # posisi di file (buat “ambil terbaru”)
    m_num = re.search(r'^\s*(\d{1,3})\s*[.)]\s*Nama\b', segment, flags=re.MULTILINE)
    data["no"] = int(m_num.group(1)) if m_num else None
    for key, rx in FIELD_RE.items():
        m = rx.search(segment)
        val = m.group("val").strip() if m else None
        if key in ("diagnosa","tindakan") and val:
            val = tidy_multiline(val)
        data[key] = val
    return data

def extract_reviews(full_text: str):
    blocks = []
    for m in BLOCK_SPLIT_RE.finditer(full_text):
        blocks.append(parse_block(m.group("block"), m.start()))
    # deduplicate: gunakan key (nama_normal, rm_normal), ambil yang pos paling besar (terbaru)
    dedup = {}
    for b in blocks:
        nama_key = (b.get("nama") or "").strip().lower()
        rm_key = re.sub(r'\D+', '', (b.get("rm") or ""))  # angka saja
        key = (nama_key, rm_key)
        if key not in dedup or b["_pos"] > dedup[key]["_pos"]:
            dedup[key] = b
    blocks = list(dedup.values())
    # sort by nomor (naik), yang tidak ada nomor taruh belakang
    blocks.sort(key=lambda d: (9999 if d.get("no") is None else d["no"], d["_pos"]))
    return blocks

# ================== Detektor Konsultasi / GA ==================
CONSULT_PAT = re.compile(r'(?im)^\s*[\*\-•]\s*Konsultasi\b')
GA_QUEUE_PAT = re.compile(r'(?i)dalam\s+general\s+anestesi\s*\(menunggu\s+penjadwalan\)')

def is_konsultasi(tindakan_text: str) -> bool:
    if not tindakan_text:
        return False
    return CONSULT_PAT.search(tindakan_text) is not None

def is_terjaring_ga(kontrol_text: str, tindakan_text: str) -> bool:
    blob = " ".join([tindakan_text or "", kontrol_text or ""])
    return GA_QUEUE_PAT.search(blob) is not None

# ================== Format Output ==================
def V(x): 
    return x if (x and str(x).strip()) else "Missing"

def format_block(d: dict) -> str:
    spaces = " "
    bullet = "•"
    no = d.get("no")
    no_str = f"{no:>2d}." if isinstance(no, int) else "  -."

    # seragamkan DPJP ke format hierarki
    dpjp_std = map_dpjp_to_priority(d.get("dpjp"))

    lines = []
    lines.append(f"{no_str} Nama{spaces*12}: {V(d.get('nama'))}")
    lines.append(f"{bullet}{spaces*2}Tanggal lahir {spaces}: {V(d.get('tgl_lahir'))}")
    lines.append(f"{bullet}{spaces*2}RM{spaces*19}: {V(d.get('rm'))}")

    diag = V(d.get('diagnosa'))
    if "\n" in diag:
        first, *rest = diag.splitlines()
        lines.append(f"{bullet}{spaces*2}Diagnosa{spaces*8}: {first}")
        lines += rest
    else:
        lines.append(f"{bullet}{spaces*2}Diagnosa{spaces*8}: {diag}")

    tind = V(d.get('tindakan'))
    if "\n" in tind:
        first, *rest = tind.splitlines()
        lines.append(f"{bullet}{spaces*2}Tindakan{spaces*8}: {first}")
        lines += rest
    else:
        lines.append(f"{bullet}{spaces*2}Tindakan{spaces*8}: {tind}")

    lines.append(f"{bullet}{spaces*2}Kontrol{spaces*9}: {V(d.get('kontrol'))}")
    lines.append(f"{bullet}{spaces*2}DPJP{spaces*12}: {V(dpjp_std)}")
    lines.append(f"{bullet}{spaces*2}No. Telp.{spaces*6}: {V(d.get('telp'))}")
    lines.append(f"{bullet}{spaces*2}Operator{spaces*8}: {V(d.get('operator'))}")
    return "\n".join(lines)

def build_dpjp_list(blocks):
    found = set()
    for b in blocks:
        dp = map_dpjp_to_priority(b.get("dpjp"))
        if dp and dp.strip():
            found.add(dp.strip())
    # urut sesuai prioritas; sisanya (kalau ada) taruh belakang alfabetis
    def prio_key(name: str):
        try:
            return (0, DPJP_PRIORITY.index(name))
        except ValueError:
            return (1, name.lower())
    return sorted(found, key=prio_key)

# ================== Streamlit UI ==================
st.set_page_config(page_title="Review Poli OMFS - Parser WA", layout="wide")
st.title("Aplikasi Review Poli Bedah Mulut & Maksilofasial (Parser Chat WhatsApp)")

colL, colR = st.columns([2,1])

with colL:
    up = st.file_uploader("Upload file chat (.docx atau .txt)", type=["docx","txt"])
    tgl = st.date_input("Tanggal laporan (otomatis hari ini, bisa ubah)", value=date.today())
    chief = st.text_input("Chief jaga poli (isi manual)", value="Isi manual")
    vip_manual = st.text_input("Jumlah VIP (isi manual, 2 digit)", value="00")
    baksos_manual = st.text_input("Jumlah Baksos (isi manual, 2 digit)", value="00")
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
    st.markdown("- Ambil blok yang diawali nomor `X. Nama : ...` meski ada prefix timestamp WA.")
    st.markdown("- Jika *duplikat pasien* (Nama+RM sama), **dipakai yang paling baru** (kemunculan terakhir).")
    st.markdown("- DPJP di-*override* ke format baku sesuai hierarki.")
    st.markdown("- Field kosong → **Missing**.")
    st.markdown("- **Jumlah** = nomor terbesar yang terdeteksi (kalau ada nomor yang lompat tetap ikut nomor terbesar).")
    st.markdown("- **Konsultasi**: ada bullet `* Konsultasi` di Tindakan.")
    st.markdown("- **Terjaring GA**: frasa `dalam general anestesi (menunggu penjadwalan)` ada di Tindakan/Kontrol.")
    st.markdown("- **Tindakan** = Jumlah − Konsultasi − Terjaring GA.")
    st.markdown("- VIP & Baksos input manual.")

if proses:
    raw = read_file(up)
    if not raw.strip():
        st.error("Silakan upload file terlebih dahulu.")
        st.stop()

    text_for_parse = normalize_wa_text(raw)
    blocks = extract_reviews(text_for_parse)

    if not blocks:
        st.error("Tidak ditemukan blok review setelah parsing. Pastikan ada pola 'X. Nama : ...' di file.")
        with st.expander("Lihat cuplikan teks (awal)"):
            st.text(text_for_parse[:4000])
        st.stop()

    # ==== Hitung statistik ====
    max_no = max([b["no"] for b in blocks if isinstance(b.get("no"), int)], default=0)
    total_pasien = max_no if max_no > 0 else len(blocks)

    jumlah_konsultasi = sum(1 for b in blocks if is_konsultasi(b.get("tindakan")))
    jumlah_ga = sum(1 for b in blocks if is_terjaring_ga(b.get("kontrol"), b.get("tindakan")))
    tindakan_count = max(total_pasien - jumlah_konsultasi - jumlah_ga, 0)

    # ==== DPJP List (seragam + urut hierarki) ====
    dpjp_list = build_dpjp_list(blocks)

    # ==== Format hasil ====
    today_str = tanggal_id(tgl)

    header = [
        f"*Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, {today_str}*",
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
        "*POLI INTEGRASI*",
        ""
    ]

    body_blocks = []
    for b in blocks:
        body_blocks.append(format_block(b))
        body_blocks.append("")  # baris kosong antar pasien

    footer = [
        "------------------------------------------------------------",
        "",
        today_str,
        "",
        "Chief jaga poli :",
        chief if chief.strip() else "Isi manual",
        "",
        "*DPJP :*"
    ]
    for i, nm in enumerate(dpjp_list, start=1):
        footer.append(f"{i}. {nm}")

    final_text = "\n".join(header + body_blocks + footer)

    st.success("Berhasil diproses!")
    st.text_area("Hasil akhir (siap copy-paste ke WhatsApp/Word):", value=final_text, height=720)
    st.download_button("Download .txt", data=final_text.encode("utf-8"), file_name="review_poli.txt", mime="text/plain")

    # Debug ringkas
    with st.expander("Debug: DPJP mentah → DPJP standar (10 contoh)"):
        preview = []
        for b in blocks[:10]:
            preview.append([b.get("dpjp"), map_dpjp_to_priority(b.get("dpjp"))])
        st.table(preview)
