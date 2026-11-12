import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import datetime

# ---------------------------------------------------------
# 1. 페이지 설정 및 CSS 스타일 (경고 강조 배너 적용)
# ---------------------------------------------------------
st.set_page_config(
    page_title="성당 매일미사 주보",
    page_icon="✝️",
    layout="centered"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 860px;
    }
    .liturgy-card {
        background-color: #f8f9fa;
        border-left: 4px solid #6c5ce7;
        padding: 1.05rem 1.25rem;
        border-radius: 6px;
        margin-bottom: 1.1rem;
        line-height: 1.8;
        color: #1e272e;
        font-size: 1.02rem;
    }
    .liturgy-single {
        background-color: #fffdf7;
        border: 1px solid #ece6d8;
        border-left: 4px solid #8e44ad;
        padding: 1.05rem 1.25rem;
        border-radius: 6px;
        margin-bottom: 1.1rem;
        line-height: 1.8;
        color: #1e272e;
        font-size: 1.02rem;
    }
    .section-title {
        font-size: 1.18rem;
        font-weight: 700;
        margin-top: 1.5rem;
        margin-bottom: 0.45rem;
        color: #2d3436;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
    }
    .ref-badge {
        display: inline-block;
        background-color: #e9ecef;
        color: #495057;
        font-size: 0.86rem;
        font-weight: 600;
        padding: 2px 9px;
        border-radius: 4px;
        margin-bottom: 0.55rem;
    }
    .warn-badge {
        display: inline-block;
        background-color: #ffe3e3;
        border: 1px solid #ff8787;
        color: #c92a2a;
        font-size: 0.85rem;
        font-weight: 700;
        padding: 3px 10px;
        border-radius: 4px;
    }
    .custom-alert-box {
        background-color: #fff0f3;
        border: 2px solid #ff6b6b;
        border-left: 8px solid #fa5252;
        padding: 1.2rem 1.5rem;
        border-radius: 8px;
        margin-top: 1rem;
        margin-bottom: 1.5rem;
        color: #c92a2a;
        font-size: 1.12rem;
        font-weight: 700;
        box-shadow: 0 4px 6px rgba(250, 82, 82, 0.15);
    }
</style>
""", unsafe_allow_html=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}

MONTH_CALENDAR_RE = re.compile(
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+20\d{2}\s+s\s+m\s+t\s+w\s+t\s+f\s+s",
    re.I
)

EN_GOSPEL_REF_RE = re.compile(
    r"\b(Matthew|Matt|Mt|Mark|Mk|Luke|Lk|John|Jn)\.?\s+(\d+)\s*[:.,]\s*(\d+(?:\s*[-–,]\s*\d+)*)",
    re.I
)

EN_GOSPEL_HEADER_RE = re.compile(
    r"\bGospel\s*[,:\-–]?\s*(?:of\s+)?(?:Saint\s+|St\.?\s+)?(Matthew|Matt|Mt|Mark|Mk|Luke|Lk|John|Jn)\.?\s+(\d+)\s*[:.,]\s*(\d+(?:\s*[-–,]\s*\d+)*)",
    re.I
)

def decode_korean_html(content_bytes):
    head_snippet = content_bytes[:2500].decode("ascii", errors="ignore").lower()
    if "euc-kr" in head_snippet or "ks_c_5601" in head_snippet:
        return content_bytes.decode("cp949", errors="replace")
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return content_bytes.decode("cp949", errors="replace")

# ---------------------------------------------------------
# 2. 4복음서 매핑 사전 및 장·절 파싱 (한·영 복음 비교용)
# ---------------------------------------------------------
GOSPEL_BOOKS = [
    (201, ["마태", "마태오", "마태오 복음서"], ["matthew", "matt", "mt"]),
    (202, ["마르", "마르코", "마르코 복음서"], ["mark", "mk"]),
    (203, ["루카", "루카 복음서"], ["luke", "lk"]),
    (204, ["요한", "요한 복음서"], ["john", "jn"]),
]

def parse_gospel_reference(ref_text, lang="ko"):
    if not ref_text:
        return None
    cleaned = ref_text.strip("<>()[] ")
    cleaned = re.sub(r"\([^)]*\)", "", cleaned).strip()
    cleaned = re.sub(r"[ㄱ-ㅎa-d]", "", cleaned)

    matched_code = None
    rest_str = ""

    if lang == "ko":
        for code, ko_names, _ in GOSPEL_BOOKS:
            for name in sorted(ko_names, key=len, reverse=True):
                if cleaned.startswith(name):
                    matched_code = code
                    rest_str = cleaned[len(name):].strip()
                    break
            if matched_code:
                break
    else:
        m_en = EN_GOSPEL_REF_RE.search(cleaned)
        if m_en:
            book_tok = m_en.group(1).lower()
            for code, _, en_names in GOSPEL_BOOKS:
                if book_tok in en_names:
                    matched_code = code
                    rest_str = f"{m_en.group(2)}:{m_en.group(3)}"
                    break

    if not matched_code or not rest_str:
        return None

    sep = "," if "," in rest_str else (":" if ":" in rest_str else None)
    if not sep:
        return None

    parts = rest_str.split(sep, 1)
    chap_match = re.search(r"\d+", parts[0])
    if not chap_match:
        return None
    chapter = int(chap_match.group())
    verse_part = parts[1]

    verses = set()
    if "," in verse_part or ":" in verse_part:
        verse_part = re.split(r"[,:]", verse_part)[0]

    tokens = re.split(r"[.;]", verse_part)
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok or "–" in tok:
            bounds = re.split(r"[-–]", tok)
            s_m = re.search(r"\d+", bounds[0])
            e_m = re.search(r"\d+", bounds[1])
            if s_m and e_m:
                s_v, e_v = int(s_m.group()), int(e_m.group())
                if e_v >= s_v and (e_v - s_v) < 150:
                    verses.update(range(s_v, e_v + 1))
        else:
            v_m = re.search(r"\d+", tok)
            if v_m:
                verses.add(int(v_m.group()))

    if not verses:
        return None

    return {"code": matched_code, "chapter": chapter, "verses": verses}

# ---------------------------------------------------------
# 3. 매일미사 데이터 크롤링 함수
# ---------------------------------------------------------
def find_goodnews_missaid_url(html_text, base_url, date_str):
    soup = BeautifulSoup(html_text, "html.parser")
    candidates = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "missaid=" in href and date_str in href:
            candidates.append(urljoin(base_url, href))

    if not candidates:
        js_matches = re.findall(
            r"['\"](\d{4,6})['\"]\s*,\s*['\"]" + re.escape(date_str) + r"['\"](?:\s*,\s*['\"]([A-Z]{2})['\"])?",
            html_text
        )
        for mid, mtype in js_matches:
            mt = mtype if mtype else "DA"
            candidates.append(f"https://maria.catholic.or.kr/mi_pr/missa/missa.asp?menu=missa&missaid={mid}&gomonth={date_str}&missatype={mt}")

    if not candidates:
        raw_matches = re.findall(r"missa\.asp\?[^\"'<>\s]*missaid=\d+[^\"'<>\s]*", html_text)
        for rm in raw_matches:
            if date_str in rm:
                candidates.append(urljoin(base_url, rm.replace("&amp;", "&")))

    if candidates:
        da_links = [u for u in candidates if "missatype=DA" in u]
        return da_links[0] if da_links else candidates[0]
    return None

def extract_goodnews_hymns(soup, pre_lines):
    hymn_groups = {"입당": [], "예물준비": [], "영성체": [], "파견": []}

    def parse_cell_group(cells, active_key):
        if not cells:
            return active_key
        first = cells[0].strip()
        m_lbl = re.match(r"^(입당|예물준비|봉헌|영성체|파견)\s*성가$", first)
        if m_lbl:
            lbl = m_lbl.group(1)
            active_key = "예물준비" if lbl == "봉헌" else lbl
            song_part = " ".join(c for c in cells[1:] if c).strip()
            if song_part and re.search(r"\d+", song_part):
                hymn_groups[active_key].append(song_part)
        else:
            m_inline = re.match(r"^(입당|예물준비|봉헌|영성체|파견)\s*성가\s*[:：]?\s*(\d+\s*번.*)$", first)
            if m_inline:
                lbl = m_inline.group(1)
                active_key = "예물준비" if lbl == "봉헌" else lbl
                hymn_groups[active_key].append(m_inline.group(2).strip())
            elif active_key:
                song_part = " ".join(c for c in cells if c).strip()
                if song_part and re.search(r"\d+\s*번", song_part):
                    hymn_groups[active_key].append(song_part)
        return active_key

    for table in soup.find_all("table"):
        if table.find("table"):
            continue
        t_text = table.get_text(" ", strip=True)
        if not any(k in t_text for k in ["입당 성가", "예물준비 성가", "영성체 성가", "파견 성가"]):
            continue

        left_key = None
        right_key = None
        single_key = None

        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if not any(cells):
                continue
            if len(cells) >= 5:
                left_key = parse_cell_group(cells[:3], left_key)
                right_key = parse_cell_group(cells[3:], right_key)
            else:
                single_key = parse_cell_group(cells, single_key)

    if not any(hymn_groups.values()):
        active_key = None
        in_hymn_box = False
        for line in pre_lines:
            if "굿뉴스 추천 성가" in line:
                in_hymn_box = True
                continue
            if "오늘의 강론" in line:
                break
            if not in_hymn_box:
                continue
            m_line = re.match(r"^(입당|예물준비|봉헌|영성체|파견)\s*성가\s*[:：]?\s*(.*)$", line)
            if m_line:
                lbl = m_line.group(1)
                active_key = "예물준비" if lbl == "봉헌" else lbl
                rest = m_line.group(2).strip()
                if rest and re.search(r"\d+", rest):
                    hymn_groups[active_key].append(rest)
            elif active_key and re.search(r"\d+\s*번", line):
                hymn_groups[active_key].append(line)

    result_lines = []
    for k in ["입당", "예물준비", "영성체", "파견"]:
        songs = list(dict.fromkeys(hymn_groups[k]))
        if songs:
            result_lines.append(f"{k} 성가: {' / '.join(songs)}")
    return "\n".join(result_lines)

def extract_ko_intro_ref(lines):
    for i, line in enumerate(lines[:5]):
        m_bracket = re.match(r"^[<(\[]\s*([가-힣0-9\s]+\d+[,:]\d+[^>\)\]]*)[>)\]]$", line)
        if m_bracket:
            rem = lines[:i] + lines[i + 1:]
            return m_bracket.group(1).strip(), rem

        m_intro = re.search(
            r"(?:사도\s*바오로의\s*)?([가-힣0-9\s]+?)\s*(?:말씀입니다|전한\s*거룩한\s*복음입니다)[.\s]*([0-9][0-9,\-.\sㄱ-ㅎ]*)?",
            line
        )
        if m_intro:
            raw_book = re.sub(r"^[^\w가-힣0-9]+", "", m_intro.group(1)).strip()
            raw_book = re.sub(r"^성\s+", "", raw_book)
            if raw_book.endswith(("마태오가", "마르코가", "루카가", "요한이")):
                raw_book = raw_book[:-1]
            ref_num = (m_intro.group(2) or "").strip()
            if not ref_num and i + 1 < len(lines):
                m_next_num = re.match(r"^([0-9][0-9,\-.\sㄱ-ㅎ]*)$", lines[i + 1].strip())
                if m_next_num:
                    ref_num = m_next_num.group(1).strip()
            if ref_num:
                clean_ref = f"{raw_book} {ref_num}"
                prefix_lines = [f"*{l}*" for l in lines[:i]]
                rem = prefix_lines + [line] + lines[i + 1:]
                return clean_ref, rem

        m_psalm = re.match(r"^(시편\s*\d+(?:\(\d+\))?[,:]\d+[0-9,\-.\sㄱ-ㅎ]*)", line)
        if m_psalm:
            rem = lines[:i] + lines[i + 1:]
            return m_psalm.group(1).strip(), rem

    return "", lines

@st.cache_data(ttl=1800)
def fetch_korean_mass(date_str):
    base_url = f"https://maria.catholic.or.kr/mi_pr/missa/missa.asp?gomonth={date_str}"
    data = {
        "title": "",
        "source_url": base_url,
        "hymns": "",
        "today_liturgy": "",
        "reading1_ref": "", "reading1": "",
        "psalm_ref": "", "psalm": "",
        "reading2_ref": "", "reading2": "",
        "acclamation_ref": "", "acclamation": "",
        "gospel_ref": "", "gospel": "",
        "prayers": "",
        "communion_ref": "", "communion": "",
        "meditation": "",
        "error": None
    }
    try:
        res1 = requests.get(base_url, headers=HEADERS, timeout=12)
        res1.raise_for_status()
        html1 = decode_korean_html(res1.content)

        target_url = find_goodnews_missaid_url(html1, base_url, date_str)

        if not target_url:
            month_url = f"https://maria.catholic.or.kr/mi_pr/missa/missa.asp?gomonth={date_str[:7]}-01"
            res_m = requests.get(month_url, headers=HEADERS, timeout=12)
            if res_m.status_code == 200:
                html_m = decode_korean_html(res_m.content)
                target_url = find_goodnews_missaid_url(html_m, month_url, date_str)

        if not target_url:
            target_url = base_url

        data["source_url"] = target_url

        if target_url != base_url:
            res2 = requests.get(target_url, headers=HEADERS, timeout=12)
            res2.raise_for_status()
            html_final = decode_korean_html(res2.content)
        else:
            html_final = html1

        soup = BeautifulSoup(html_final, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        for img in soup.find_all("img"):
            alt_txt = (img.get("alt") or img.get("title") or "").strip()
            src_txt = (img.get("src") or "").lower()
            if not alt_txt:
                for color_k in ["녹", "백", "자", "홍", "흑", "장"]:
                    if f"_{color_k}" in src_txt or f"{color_k}." in src_txt:
                        alt_txt = f"({color_k})"
                        break
            if alt_txt:
                img.replace_with(f" {alt_txt} ")
            else:
                img.decompose()

        raw_lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines() if line.strip()]

        merged_lines = []
        skip_next = False
        for i, line in enumerate(raw_lines):
            if skip_next:
                skip_next = False
                continue
            if re.fullmatch(r"[\(\[\{]?[녹백자홍흑장][\)\]\}]?", line) and i + 1 < len(raw_lines):
                color_char = re.sub(r"[\(\)\[\]\{\}]", "", line)
                next_clean = re.sub(r"^[\)\]\s]+", "", raw_lines[i + 1]).strip()
                merged_lines.append(f"({color_char}) {next_clean}")
                skip_next = True
            else:
                cleaned_line = re.sub(r"\(([녹백자홍흑장])\)\s*[\)\]]+", r"(\1)", line)
                merged_lines.append(cleaned_line)
        raw_lines = merged_lines

        first_section_idx = len(raw_lines)
        for idx, line in enumerate(raw_lines):
            if re.match(r"^[▶■•\s]*(오늘(?:의)?\s*전례|입당송|본기도|제\s*1\s*독서)", line):
                first_section_idx = idx
                break

        pre_liturgy_lines = raw_lines[max(0, first_section_idx - 40):first_section_idx]

        data["hymns"] = extract_goodnews_hymns(soup, pre_liturgy_lines)

        date_heading_idx = -1
        for idx, line in enumerate(pre_liturgy_lines):
            if "오늘의 강론" in line:
                continue
            if re.search(r"20\d{2}년\s*\d{1,2}월\s*\d{1,2}일\s*[월화수목금토일]요일", line):
                date_heading_idx = idx
                break

        if date_heading_idx != -1:
            for line in pre_liturgy_lines[date_heading_idx + 1:date_heading_idx + 5]:
                if "오늘의 강론" in line:
                    continue
                m_lit = re.match(r"^\[?\s*\(([녹백자홍흑장])\)\s*(.+?)\s*\]?$", line)
                if m_lit:
                    data["title"] = f"({m_lit.group(1)}) {m_lit.group(2).strip()}"
                    break

        if not data["title"]:
            for line in reversed(pre_liturgy_lines):
                if "오늘의 강론" in line:
                    continue
                m_lit = re.match(r"^\[?\s*\(([녹백자홍흑장])\)\s*(.+?)\s*\]?$", line)
                if m_lit:
                    data["title"] = f"({m_lit.group(1)}) {m_lit.group(2).strip()}"
                    break

        section_rules = [
            ("today_liturgy", r"^[▶■•\s]*오늘(?:의)?\s*전례$"),
            ("_skip_entrance", r"^[▶■•\s]*입당송(?:\s*[<(\[].*[>)\]])?$"),
            ("_skip_collect", r"^[▶■•\s]*본기도$"),
            ("reading1", r"^[▶■•\s]*제\s*1\s*독서(?:\s*[<(\[].*[>)\]])?$"),
            ("psalm", r"^[▶■•\s]*화답송(?:\s*[<(\[].*[>)\]])?$"),
            ("reading2", r"^[▶■•\s]*제\s*2\s*독서(?:\s*[<(\[].*[>)\]])?$"),
            ("acclamation", r"^[▶■•\s]*복음\s*환호송(?:\s*[<(\[].*[>)\]])?$"),
            ("gospel", r"^[▶■•\s]*복음(?:\s*[<(\[].*[>)\]])?$"),
            ("prayers", r"^[▶■•\s]*보편\s*지향\s*기도$"),
            ("_stop_offerings", r"^[▶■•\s]*예물\s*기도$"),
            ("communion", r"^[▶■•\s]*영성체송(?:\s*[<(\[].*[>)\]])?$"),
            ("_stop_post_comm", r"^[▶■•\s]*영성체\s*후\s*기도$"),
            ("meditation", r"^[▶■•\s]*영성체\s*후\s*묵상$"),
            ("_stop_footer", r"^(이전글|다음글|목록|인쇄하기|Copyright|댓글)"),
        ]

        markers = []
        for idx in range(first_section_idx, len(raw_lines)):
            line = raw_lines[idx]
            for key, pat in section_rules:
                if re.match(pat, line):
                    markers.append((idx, key, line))
                    break

        for m_i, (start_idx, key, header_line) in enumerate(markers):
            if key.startswith(("_stop", "_skip")):
                continue
            end_idx = markers[m_i + 1][0] if m_i + 1 < len(markers) else len(raw_lines)
            content_lines = raw_lines[start_idx + 1:end_idx]

            inline_ref_m = re.search(r"[<(\[]([^>)\]]+)[>)\]]", header_line)
            ref_found = inline_ref_m.group(1).strip() if inline_ref_m else ""

            if key in ["reading1", "psalm", "reading2", "acclamation", "gospel", "communion"]:
                if not ref_found:
                    ref_found, content_lines = extract_ko_intro_ref(content_lines)
                data[f"{key}_ref"] = ref_found
                data[key] = "\n".join(content_lines).strip()
            else:
                data[key] = "\n".join(content_lines).strip()

    except Exception as e:
        data["error"] = f"한글 매일미사 데이터를 불러오는 중 오류가 발생했습니다: {e}"

    return data

@st.cache_data(ttl=1800)
def fetch_english_gospel_ref(date_str):
    url = f"https://www.catholic.org/bible/daily_reading/?select_date={date_str}"
    result = {"source_url": url, "gospel_ref": "", "error": None}
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        full_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        m_hdr = EN_GOSPEL_HEADER_RE.search(full_text)
        if m_hdr:
            result["gospel_ref"] = f"{m_hdr.group(1)} {m_hdr.group(2)}:{m_hdr.group(3)}"
        else:
            for m_g in re.finditer(r"\bGospel\b(?!\s+Acclamation)", full_text, flags=re.I):
                snippet = full_text[m_g.end():m_g.end() + 200]
                m_ref = EN_GOSPEL_REF_RE.search(snippet)
                if m_ref:
                    result["gospel_ref"] = f"{m_ref.group(1)} {m_ref.group(2)}:{m_ref.group(3)}"
                    break

    except Exception as e:
        result["error"] = str(e)

    return result

# ---------------------------------------------------------
# 4. 한·영 복음 비교 판별 함수
# ---------------------------------------------------------
def is_gospel_different(ko_data, en_gospel_data):
    if en_gospel_data.get("error"):
        return False

    ko_ref = ko_data.get("gospel_ref", "")
    en_ref = en_gospel_data.get("gospel_ref", "")
    if not ko_ref or not en_ref:
        return False

    p_ko = parse_gospel_reference(ko_ref, lang="ko")
    p_en = parse_gospel_reference(en_ref, lang="en")
    if not p_ko or not p_en:
        return False

    if p_ko["code"] != p_en["code"] or p_ko["chapter"] != p_en["chapter"]:
        return True
    if p_ko["verses"].isdisjoint(p_en["verses"]):
        return True

    return False

# ---------------------------------------------------------
# 5. 메인 UI 렌더링
# ---------------------------------------------------------
st.title("✝️ 성당 매일미사 주보")

# 오늘 날짜를 기본값으로 설정
selected_date = st.date_input("📅 미사 날짜를 선택하세요", value=datetime.date.today())
date_str = selected_date.strftime("%Y-%m-%d")

with st.spinner("매일미사 전례와 말씀을 불러오는 중입니다..."):
    ko_data = fetch_korean_mass(date_str)
    en_gospel_data = fetch_english_gospel_ref(date_str)

if ko_data.get("error"):
    st.error(ko_data["error"])

gospel_diff = is_gospel_different(ko_data, en_gospel_data)

liturgy_name = ko_data.get("title", "").strip()
header_title = f"매일미사 ({date_str}) [{liturgy_name}]" if liturgy_name else f"매일미사 ({date_str})"
st.subheader(f"📌 {header_title}")

ko_g_disp = ko_data.get("gospel_ref") or "미확인"
en_g_disp = en_gospel_data.get("gospel_ref") or "미확인"
st.caption(
    f"🔗 [가톨릭 굿뉴스 원문]({ko_data['source_url']})  |  "
    f"🔗 [Catholic.org 영문 원문]({en_gospel_data['source_url']})  |  "
    f"복음 대조: 한글 `{ko_g_disp}` / 영문 `{en_g_disp}`"
)

# 눈에 잘 띄는 대형 경고 배너 출력
if gospel_diff:
    st.markdown(
        '<div class="custom-alert-box">'
        '⚠️ [경고] 한글전례가 영문전례와 다릅니다!'
        '</div>',
        unsafe_allow_html=True
    )

st.divider()

def render_single_section(icon, title, text):
    if not text:
        return
    st.markdown(f'<div class="section-title">{icon} {title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="liturgy-single">{text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)

def render_scripture_section(icon, title, key, show_diff_badge=False):
    txt = ko_data.get(key, "")
    ref = ko_data.get(f"{key}_ref", "")
    if not txt and not ref:
        return

    warn_html = '<span class="warn-badge">⚠️ 한글전례가 영문전례와 다릅니다.</span>' if show_diff_badge else ""
    st.markdown(f'<div class="section-title">{icon} {title} {warn_html}</div>', unsafe_allow_html=True)

    ref_tag = f'<div class="ref-badge">{ref}</div><br>' if ref else ""
    body_html = txt.replace("\n", "<br>") if txt else "<span style='color:#adb5bd;'>(해당 전례문 없음)</span>"
    st.markdown(f'<div class="liturgy-card">{ref_tag}{body_html}</div>', unsafe_allow_html=True)

# 1. 성가
render_single_section("🎵", "성가", ko_data.get("hymns", ""))

# 2. 오늘 전례
render_single_section("🕯️", "오늘 전례", ko_data.get("today_liturgy", ""))

# 3~7. 말씀 전례 (제1독서 / 화답송 / 제2독서 / 복음환호송 / 복음)
render_scripture_section("📖", "제1독서", "reading1")
render_scripture_section("🎶", "화답송", "psalm")
render_scripture_section("📖", "제2독서", "reading2")
render_scripture_section("🎺", "복음환호송", "acclamation")
render_scripture_section("✝️", "복음", "gospel", show_diff_badge=gospel_diff)

# 8. 보편지향기도
render_single_section("🕊️", "보편지향기도", ko_data.get("prayers", ""))

# 9. 영성체송
render_scripture_section("🍞", "영성체송", "communion")

# 10. 영성체 후 묵상
render_single_section("💭", "영성체 후 묵상", ko_data.get("meditation", ""))
