# streamlit_app.py
# =================
# Aplikasi Streamlit untuk membuat rekap pasien dari chat WA (.docx/.txt)
# Fitur:
# - Bersihkan header WhatsApp & karakter zero-width
# - Ekstrak blok "XX. Nama : ..."
# - Deteksi BAKSOS vs non-BAKSOS
# - Rekap otomatis (Total, Tindakan, Konsultasi, Terjaring GA, VIP, Baksos)
# - Prioritas klasifikasi: jika ada 'tindakan' ber-prosedur -> Tindakan, else -> Konsultasi
# - Heuristik 'Terjaring GA' bisa diubah di sidebar
# - Hasil akhir diformat seperti contoh, + tombol download .txt

import io
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import streamlit as st

# ============ UTIL ============

_ZW = "\u200b\u200c\u200d\u2060\ufeff"  # zero widths + BOM
ZW_TRANS = dict.fromkeys(map(ord, _ZW), None)

WA_HEADER_RE = re.compile(
    r"""^\[
        \d{2}/\d{2}/\d{2},\s*      # tanggal
        \d{1,2}\.\d{2}\.\d{2}      # jam
    \]\s[^:]+:\s*                  # nama pengirim sampai titik dua
    """,
    re.MULTILINE | re.VERBOSE,
)

START_RE = re.compile(
    r"""(?m)                    # MULTILINE
    ^\s*
    (\d{1,3})\.\s*              # nomor 1-3 digit
    Nama\s*:\s*.+$              # "Nama : ..."
    """,
    re.VERBOSE,
)

SECTION_RE = re.compile(
    r"(?m)^\s*(POLI\s+INTEGRASI|BAKSOS\b[^\n]*)\s*$"
)

DIVIDER_RE = re.compile(r"(?m)^\s*-{6,}\s*$")  # garis pemisah bila ada

def read_text_from_upload(uploaded) -> str:
    name = uploaded.name.lower()
    if name.endswith(".docx"):
        # baca docx
        try:
            from docx import Document
        except ImportError:
            st.error("Paket `python-docx` belum terpasang. Tambahkan di requirements.txt")
            st.stop()
        # Streamlit kasih file-like; simpan buffer sementara ke memori
        data = uploaded.read()
        bio = io.BytesIO(data)
        doc = Document(bio)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        # teks biasa
        raw = uploaded.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")

def normalize(text: str) -> str:
    text = text.translate(ZW_TRANS)
    text = text.replace("\xa0", " ")
    text = re.sub(r"Read more|‎Read more", "", text)
    text = WA_HEADER_RE.sub("", text)
    # rapikan trailing spaces
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text

def find_sections(text: str) -> List[Tuple[int, str]]:
    """
    Temukan header section ("POLI INTEGRASI", "BAKSOS ...") dengan index start.
    return list of (pos, name)
    """
    secs = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(text)]
    secs.sort(key=lambda x: x[0])
    return secs

def extract_blocks_with_section(text: str):
    """
    Menghasilkan list blok: dict {num, block, section, span}
    section: "POLI INTEGRASI" / "BAKSOS ..." / None
    """
    t = normalize(text)
    sections = find_sections(t)

    # indeks awal setiap blok "XX. Nama :"
    starts = [(m.start(), m.end(), int(m.group(1))) for m in START_RE.finditer(t)]
    results = []
    if not starts:
        return results

    def section_for_pos(pos: int) -> Optional[str]:
        # cari section terakhir sebelum pos
        prev = None
        for spos, sname in sections:
            if spos <= pos:
                prev = sname
            else:
                break
        return prev

    for i, (spos, epos, num) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(t)
        raw_block = t[spos:end].rstrip()

        # potong jika ketemu header section/divider berikutnya di dalam raw_block
        split_pat = re.compile(
            r"(?m)^\s*(POLI\s+INTEGRASI|BAKSOS\b.*)$|^\s*-{6,}\s*$"
        )
        pieces = split_pat.split(raw_block, maxsplit=1)
        block = pieces[0].rstrip() if pieces else raw_block

        sec = section_for_pos(spos)
        results.append(
            {"num": num, "block": block, "section": sec, "span": (spos, end)}
        )

    # urutkan by nomor
    results.sort(key=lambda d: d["num"])
    return results

# ============ HEURISTIK KLASIFIKASI ============

DEFAULT_PROCEDURE_KEYWORDS = [
    "Odontektomi", "Ekstraksi", "Cuci luka", "Aff hecting", "Aff drain",
    "Wound Debridement", "Reposisi", "IDW", "Composite Wiring",
    "Sinus washout", "Marsupialisasi", "Alveolektomi", "Enukleasi", "Apeks reseksi",
]

def has_keyword(s: str, keywords: List[str]) -> bool:
    s_low = s.lower()
    for kw in keywords:
        if kw.lower() in s_low:
            return True
    return False

def classify_block(block_text: str, proc_keywords: List[str], ga_keywords: List[str], exclude_postop: bool):
    """
    Kembalikan dict flags:
      - has_consult (ada kata 'Konsultasi' pada Tindakan)
      - has_procedure (ada kata kunci tindakan di Tindakan)
      - classify: 'TINDAKAN' / 'KONSULTASI'
      - terjaring_ga: True/False
      - vip: True/False
    Aturan klasifikasi:
      - Jika has_procedure -> TINDAKAN
      - else -> KONSULTASI
      - Terjaring GA jika ada kata kunci GA, dan (opsional) bukan kasus post-op (POD)
    """
    # cari sub-bagian Tindakan & Diagnosa (opsional)
    tindakan_match = re.search(r"(?ms)^\s*•\s*.*Tindakan\s*:\s*(.+?)(?:^\s*•|\Z)", block_text)
    diagnosa_match = re.search(r"(?m)^\s*•\s*.*Diagnosa\s*:\s*(.+)$", block_text)

    tindakan = tindakan_match.group(1).strip() if tindakan_match else ""
    diagnosa = diagnosa_match.group(1).strip() if diagnosa_match else ""

    has_consult = "konsultasi" in tindakan.lower()
    has_procedure = has_keyword(tindakan, proc_keywords)

    # post-op indicator
    is_postop = ("pod" in diagnosa.lower()) or ("post operasi" in tindakan.lower())

    # GA
    text_for_ga = (tindakan + "\n" + diagnosa)
    ga_hit = has_keyword(text_for_ga, ga_keywords)
    terjaring_ga = ga_hit and (not is_postop if exclude_postop else True)

    vip = "vip" in (tindakan + "\n" + diagnosa).lower()

    classify = "TINDAKAN" if has_procedure else "KONSULTASI"
    return {
        "has_consult": has_consult,
        "has_procedure": has_procedure,
        "classify": classify,
        "terjaring_ga": terjaring_ga,
        "vip": vip,
    }

# ============ FORMAT OUTPUT ============

def pad2(n: int) -> str:
    return f"{n:02d}"

def format_header(title_line: str, counts: Dict[str, int]) -> str:
    """
    Format header rekap sesuai contoh.
    """
    return (
        f"{title_line}\n\n"
        f"Jumlah pasien    : {pad2(counts['total']) if counts['total']<100 else counts['total']} Pasien \n"
        f"Tindakan             : {pad2(counts['tindakan']) if counts['tindakan']<100 else counts['tindakan']} Pasien \n"
        f"Konsultasi           : {pad2(counts['konsultasi']) if counts['konsultasi']<100 else counts['konsultasi']} Pasien\n"
        f"Terjaring GA        : {pad2(counts['ga']) if counts['ga']<100 else counts['ga']} Pasien\n"
        f"VIP                       : {pad2(counts['vip']) if counts['vip']<100 else counts['vip']} Pasien\n"
        f"Baksos                 : {pad2(counts['baksos']) if counts['baksos']<100 else counts['baksos']} Pasien \n\n"
        f"------------------------------------------------------------\n\n"
    )

def format_section_title(name: str) -> str:
    return f"{name.strip().upper()}\n"

def join_blocks(blocks: List[Dict[str, Any]]) -> str:
    return "\n\n".join(b["block"].strip() for b in blocks if b["block"].strip())

def build_report(
    all_blocks: List[Dict[str, Any]],
    title_line: str,
    proc_keywords: List[str],
    ga_keywords: List[str],
    exclude_postop_for_ga: bool = True,
) -> Dict[str, Any]:
    """
    Mengembalikan dict:
      - text_report
      - counts
      - grouped blocks (main/baksos)
    """
    # tandai klasifikasi tiap blok
    enriched = []
    for b in all_blocks:
        cl = classify_block(b["block"], proc_keywords, ga_keywords, exclude_postop_for_ga)
        enriched.append({**b, **cl})

    # kelompokkan BAKSOS vs non
    main_blocks = [b for b in enriched if not (b["section"] or "").lower().startswith("baksos")]
    baksos_blocks = [b for b in enriched if (b["section"] or "").lower().startswith("baksos")]

    # hitung counts
    # - total: semua blok (main + baksos)
    # - tindakan: jumlah blok dengan classify=='TINDAKAN'
    # - konsultasi: sisanya
    # - ga: heuristik
    # - vip: ada 'vip'
    # - baksos: jumlah blok pada section baksos
    total = len(enriched)
    tindakan = sum(1 for b in enriched if b["classify"] == "TINDAKAN")
    konsultasi = total - tindakan
    ga = sum(1 for b in enriched if b["terjaring_ga"])
    vip = sum(1 for b in enriched if b["vip"])
    baksos = len(baksos_blocks)

    counts = dict(total=total, tindakan=tindakan, konsultasi=konsultasi, ga=ga, vip=vip, baksos=baksos)

    # susun teks laporan
    parts = []
    parts.append(format_header(title_line, counts))
    if main_blocks:
        parts.append(format_section_title("POLI INTEGRASI"))
        parts.append(join_blocks(main_blocks))
        parts.append("")  # newline
    if baksos_blocks:
        parts.append(format_section_title("BAKSOS CCC"))
        parts.append(join_blocks(baksos_blocks))
        parts.append("")  # newline

    report_text = "\n".join(p for p in parts if p is not None)
    return {"text_report": report_text.strip() + "\n", "counts": counts,
            "main_blocks": main_blocks, "baksos_blocks": baksos_blocks}

# ============ UI STREAMLIT ============

st.set_page_config(page_title="Rekap Poli BM RSGMP UNHAS", layout="wide")

st.title("Rekap Pasien Poli Bedah Mulut — WA Parser")
st.caption("Upload chat WA (.docx/.txt) ➜ auto rekap ➜ output siap kirim")

with st.sidebar:
    st.header("Pengaturan")
    default_title = "Review jumlah pasien Poli Bedah Mulut dan Maksilofasial RSGMP UNHAS, Sabtu, (27/09/2025)"
    title_line = st.text_area("Judul laporan", value=default_title, height=80)

    st.markdown("**Kata kunci tindakan (untuk klasifikasi 'TINDAKAN')**")
    user_proc = st.text_area(
        "Pisahkan dengan koma",
        value=", ".join(DEFAULT_PROCEDURE_KEYWORDS),
        height=100
    )
    proc_keywords = [x.strip() for x in user_proc.split(",") if x.strip()]

    st.markdown("**Kata kunci 'Terjaring GA'** (boleh edit):")
    default_ga = [
        "Pro ", "general anestesi", "Acc TS Anestesi", "Konsul TS. Anestesi",
        "Konsul TS Anestesi", "Mouth Preparation", "GA", "CT BT HbsAg GDS Thorax"
    ]
    user_ga = st.text_area("Pisahkan dengan koma", value=", ".join(default_ga), height=80)
    ga_keywords = [x.strip() for x in user_ga.split(",") if x.strip()]

    exclude_postop_for_ga = st.checkbox("JANGAN hitung kasus POD sebagai 'Terjaring GA'", value=True)

    st.markdown("---")
    st.caption("Tips: Kalau angka rekap belum pas, sesuaikan kata kunci di atas (terutama GA).")

uploaded = st.file_uploader("Upload file chat WA (.docx atau .txt)", type=["docx", "txt"])

if uploaded:
    raw = read_text_from_upload(uploaded)
    blocks = extract_blocks_with_section(raw)

    if not blocks:
        st.error("Tidak ada blok pasien terdeteksi. Pastikan format baris awal 'XX. Nama : ...' ada di teks.")
        st.stop()

    st.success(f"Terbaca {len(blocks)} blok pasien. (Nomor pertama–terakhir: {blocks[0]['num']}–{blocks[-1]['num']})")

    res = build_report(
        blocks,
        title_line=title_line,
        proc_keywords=proc_keywords,
        ga_keywords=ga_keywords,
        exclude_postop_for_ga=exclude_postop_for_ga,
    )

    col1, col2 = st.columns([3,2], gap="large")

    with col1:
        st.subheader("Preview Laporan (siap kirim)")
        st.code(res["text_report"], language="markdown")

        st.download_button(
            label="⬇️ Download .txt",
            data=res["text_report"].encode("utf-8"),
            file_name="rekap_poli_bm.txt",
            mime="text/plain",
        )

    with col2:
        st.subheader("Rekap Otomatis")
        c = res["counts"]
        st.metric("Jumlah Pasien", c["total"])
        st.metric("Tindakan", c["tindakan"])
        st.metric("Konsultasi", c["konsultasi"])
        st.metric("Terjaring GA", c["ga"])
        st.metric("VIP", c["vip"])
        st.metric("Baksos", c["baksos"])

        with st.expander("Debug — lihat blok & klasifikasi"):
            for b in (res["main_blocks"] + res["baksos_blocks"]):
                st.markdown(f"**#{b['num']}** — *{b['section'] or 'POLI INTEGRASI'}* — `{b['classify']}`"
                            f"{' — GA' if b['terjaring_ga'] else ''}{' — VIP' if b['vip'] else ''}")
                st.code(b["block"], language="markdown")

else:
    st.info("📄 Silakan upload file dulu. Contoh yang didukung: ekspor chat WA hasil copy/paste ke .docx atau .txt")
