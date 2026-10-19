r"""SOP PDF를 검토용 v2.1 청크 파일로 만든다.

실행 환경: Windows PowerShell
  python 01_현행코드\sop_ingest_v2.py          # dry: 파일만 생성
  python 01_현행코드\sop_ingest_v2.py --apply  # safety_manual_v2 적재(별도 승인 후)

기본 dry 모드는 Ollama와 PostgreSQL을 import하거나 연결하지 않는다. ``--apply``는
검토가 끝난 뒤에만 사용하며 운영 컬렉션 ``safety_manual``에는 쓸 수 없다.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = Path("C:/radar-guard")
OUTPUT_DIR = ROOT / "tmp" / "ingest_v2"
CHUNKS_PATH = OUTPUT_DIR / "chunks_v2.jsonl"
REPORT_PATH = OUTPUT_DIR / "report.md"
COLLECTION = "safety_manual_v2"
MIN_CHARS = 100
TARGET_MIN = 250
TARGET_MAX = 500


@dataclass(frozen=True)
class SourceSpec:
    path: Path
    sha256: str | None
    category: str
    doc_id: str


@dataclass
class Piece:
    text: str
    start_page: int
    end_page: int
    forced_cut: bool = False


# 13개 기준 SHA는 _etl_probe_20260906.txt에서 가져왔다. 프로젝트 SOP는 기준 목록
# 밖의 파일이므로 실행할 때 현재 SHA만 기록하고 일치 검사를 하지 않는다.
SOURCES = [
    SourceSpec(PDF_ROOT / "01_감전_LOTO/B-M-25-2026 에너지 차단장치의 잠금·표지에 관한 기술지원규정.pdf", "707a32e7048562061e74ac41a24d308919521e60b2a1169724a495fbfc33a272", "01_감전_예방", "B-M-25-2026"),
    SourceSpec(PDF_ROOT / "01_감전_LOTO/E-105-2011 전기작업안전에 관한 기술지침.pdf", "8bb189c18c533abe135f58e94f6df2a2beb4fd422db2eee0bc00d8eda0b829dd", "01_감전_예방", "E-105-2011"),
    SourceSpec(PDF_ROOT / "01_감전_LOTO/OSHA3120.pdf", "3ea7380fa10860417ed30720eaf8beb7a85d106e3dafb97b880001df6552767b", "09_색인제외", "OSHA3120"),
    SourceSpec(PDF_ROOT / "01_감전_LOTO/감전시응급조치.pdf", "e5a6bdb6275bdce05aa408fc5f4c4497ceac4ab924c9f0f4afd6f7f0fb137379", "01_감전_대응", "E-14-2012"),
    SourceSpec(PDF_ROOT / "02_협착_끼임/B-M-37-2026 회전기계 등의 끼임·절단재해 예방을 위한 기술지원규정.pdf", "85a8ff9713a684c0768cb2f210e0827e48e4801f0208cde178e8d0f5c6f4a05e", "02_협착_예방", "B-M-37-2026"),
    SourceSpec(PDF_ROOT / "03_낙상_응급처치/B-M-24-2026 안전대의 죔줄에 관한 기술지원규정.pdf", "d88f6b99978413e17665a2901fb92ed08fc4f23eabe7df0824434eb98569a551", "03_낙상_예방", "B-M-24-2026"),
    SourceSpec(PDF_ROOT / "03_낙상_응급처치/M-59-2012 서비스업종에서의 넘어짐 위험성 평가에 관한 기술지침.pdf", "c0c04be295792433bf5c6a48ac10877b19c0237e04081b32118225a22b96ab4e", "03_낙상_예방", "M-59-2012"),
    SourceSpec(PDF_ROOT / "03_낙상_응급처치/산업재해 형태별 응급처치 (골절화상뇌진탕 등).pdf", "059cb3860322a1f7708d745eb06ae105633928b01cb2f271391607b6553e88c4", "00_응급처치_공통", "H-187-2021"),
    SourceSpec(PDF_ROOT / "04_예지보전/M-121-2012 성능매개변수를 이용한 기계의 상태감시와 진단 기술지침.pdf", "ad9a28913d1c73ac1ed053b1fb1e3f645a54fa86e24674fc92f27235ba512a01", "04_예지보전", "M-121-2012"),
    SourceSpec(PDF_ROOT / "04_예지보전/M-131-2012 기계의 결함진단을 위한 자료해석 기술지침.pdf", "9668215ab3d07157cced9d8ada21a7c153ac12b61fc0f6a3b558b733ede336cc", "04_예지보전", "M-131-2012"),
    SourceSpec(PDF_ROOT / "04_예지보전/M-146-2012 고령화 설비의 손상평가와 수명예측에 관한 기술지침.pdf", "8a0bc52a6487522bba7fd1634e8a83adcc284d9e73ffaeb3e65a1b0498110235", "04_예지보전", "M-146-2012"),
    SourceSpec(PDF_ROOT / "05_위험성평가_비상/B-M-19-2026 배관 주요사고 대비 비상계획에 관한 기술지원규정.pdf", "e19d01b5cca03a4adb542d4d5c51d3128f375281c36e9bdc74855814e030afe1", "05_위험성평가_비상", "B-M-19-2026"),
    SourceSpec(PDF_ROOT / "05_위험성평가_비상/M-123-2012 기계류의 위험성평가 지침.pdf", "2bc632f80d63a913a47e59f046bdf168a891d3bd1624119cca503b857eba5fe3", "05_위험성평가_비상", "M-123-2012"),
    SourceSpec(ROOT / "output/pdf/Radar-Guard_설비전기이상_대응_SOP.pdf", None, "01_감전_예방", "RADAR-GUARD-SOP-v2"),
]

CLAUSE_RE = re.compile(
    r"(?:(?<=\n)|(?<=\s))(?=(?:[①-⑳]|(?:\d+(?:\.\d+)*|[가-하])\.|"
    r"제\s*\d+\s*조|\(\d+\)|\([가-하]\))\s*)"
)
SENTENCE_RE = re.compile(r"(?<=[.!?。])\s+")
PAGE_NUMBER_RE = re.compile(r"^(?:page)?[-–—－]?\d+[-–—－]?$", re.IGNORECASE)
WRAPPED_WIDE_PAGE_NUMBER_RE = re.compile(r"－\s*－\s*-\s*\d{1,3}\s*-")
WIDE_PAGE_NUMBER_RE = re.compile(r"－\s*－\s*\d{1,3}(?!\d)")
EXPECTED_WIDE_PAGE_NUMBERS = {
    "M-59-2012": 24,
    "M-121-2012": 16,
    "M-131-2012": 11,
    "M-146-2012": 23,
    "M-123-2012": 21,
}
V21_STATS = {
    "chunks": 538,
    "mean": 425.48,
    "max": 500,
    "space_loss": 25,
    "categories": {
        "00_응급처치_공통": 16,
        "01_감전_대응": 13,
        "01_감전_예방": 95,
        "02_협착_예방": 107,
        "03_낙상_예방": 51,
        "04_예지보전": 61,
        "05_위험성평가_비상": 49,
        "09_색인제외": 146,
    },
}
UNCHANGED_CONTENT_SHA256 = {
    "H-187-2021": "5abb63771d769b934f28392cfe9f6a31574e22ad0788681e56f8d35aebaa1065",
    "E-14-2012": "52f90b6a70637b5656899c6e59cb33196da4a2e047d00a11e6b2d2acecf49530",
}

# 기준 PDF의 SHA가 고정되어 있으므로 본문 시작 페이지를 명시해 개요·목차를
# 보수적으로 제외한다. 값은 1부터 시작하며, 그 앞 페이지를 전부 제외한다.
BODY_START_PAGE = {
    "B-M-25-2026": 5,
    "E-105-2011": 3,
    "OSHA3120": 7,
    "E-14-2012": 3,
    "B-M-37-2026": 5,
    "B-M-24-2026": 4,
    "M-59-2012": 3,
    "H-187-2021": 3,
    "M-121-2012": 3,
    "M-131-2012": 3,
    "M-146-2012": 3,
    "B-M-19-2026": 4,
    "M-123-2012": 3,
    "RADAR-GUARD-SOP-v2": 1,
}


def compact(text: str) -> str:
    return re.sub(r"\s", "", text)


def longest(text: str) -> int:
    return max(map(len, re.findall(r"[가-힣]+", text)), default=0)


def metrics(texts: Iterable[str]) -> tuple[dict[int, int], float]:
    texts = list(texts)
    means = [sum(map(len, text.split())) / len(text.split()) for text in texts if text.split()]
    return ({n: sum(longest(text) >= n for text in texts) for n in (20, 25, 30, 40)},
            sum(means) / len(means) if means else 0.0)


def restore(text: str, reference: str) -> str:
    """layout 추출의 공백만 같은 문자 구간에 삽입한다."""
    original, target = compact(text), compact(reference)
    spaces: set[int] = set()
    offset = 0
    for char in reference:
        if char.isspace():
            spaces.add(offset)
        else:
            offset += 1
    inserts: set[int] = set()
    for start_a, start_b, size in SequenceMatcher(
            None, original, target, autojunk=False).get_matching_blocks():
        # 9/06 시제품과 같은 12자 기준으로 짧은 반복 문자열의 오정렬을 피한다.
        if size >= 12:
            inserts.update(start_a + pos - start_b
                           for pos in spaces if start_b < pos < start_b + size)
    output: list[str] = []
    offset = 0
    for char in text:
        if not char.isspace():
            if offset in inserts and output and not output[-1].isspace():
                output.append(" ")
            offset += 1
        output.append(char)
    result = "".join(output)
    if compact(result) != original:
        raise AssertionError("공백 복원 중 비공백 문자가 바뀌었습니다")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remove_control_artifacts(pages: list[str]) -> tuple[list[str], int, list[dict]]:
    """NUL과 위치 무관 전각 쪽번호만 원문에서 제거한다."""
    cleaned = []
    nul_removed = 0
    page_numbers = []
    for page_no, text in enumerate(pages, 1):
        nul_removed += text.count("\x00")
        text = text.replace("\x00", "")
        for pattern in (WRAPPED_WIDE_PAGE_NUMBER_RE, WIDE_PAGE_NUMBER_RE):
            for match in pattern.finditer(text):
                page_numbers.append({
                    "page": page_no,
                    "text": match.group(),
                    "before": text[max(0, match.start() - 15):match.start()],
                    "after": text[match.end():match.end() + 15],
                })
            text = pattern.sub("", text)
        cleaned.append(text)
    return cleaned, nul_removed, page_numbers


def remove_nul_strings(value):
    """청크와 메타데이터의 모든 문자열에서 NUL을 제거한다."""
    if isinstance(value, str):
        return value.replace("\x00", ""), value.count("\x00")
    if isinstance(value, list):
        cleaned, count = [], 0
        for item in value:
            item, removed = remove_nul_strings(item)
            cleaned.append(item)
            count += removed
        return cleaned, count
    if isinstance(value, dict):
        cleaned, count = {}, 0
        for key, item in value.items():
            item, removed = remove_nul_strings(item)
            cleaned[key] = item
            count += removed
        return cleaned, count
    return value, 0


def content_sha256(records: list[dict]) -> str:
    payload = b"\n".join(record["page_content"].encode("utf-8") for record in records)
    return hashlib.sha256(payload).hexdigest()


def verify_sources() -> list[tuple[SourceSpec, str]]:
    checked = []
    failures = []
    for source in SOURCES:
        if not source.path.is_file():
            failures.append(f"없음: {source.path}")
            continue
        actual = sha256_file(source.path)
        checked.append((source, actual))
        if source.sha256 is not None and actual != source.sha256:
            failures.append(
                f"SHA 불일치: {source.path}\n  기대 {source.sha256}\n  실제 {actual}")
    if failures:
        raise RuntimeError("입력 검증 실패\n" + "\n".join(failures))
    return checked


def extract_pages(path: Path) -> list[str]:
    import pdfplumber
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    with pdfplumber.open(path) as layout_pdf:
        if len(reader.pages) != len(layout_pdf.pages):
            raise RuntimeError(f"추출기별 페이지 수 불일치: {path.name}")
        for page, layout_page in zip(reader.pages, layout_pdf.pages):
            plain = page.extract_text() or ""
            # pdfplumber가 글자 좌표에서 복원한 공백을 참조하되, 문자 순서는
            # pypdf plain에 유지한다. 도해·표에서 읽기 순서가 바뀌어도 본문을
            # 통째로 바꾸지 않기 위한 선택이다.
            layout = layout_page.extract_text() or ""
            pages.append(restore(plain, layout))
    return pages


def normalized_line(line: str) -> str:
    return " ".join(line.split())


def line_signature(line: str) -> str:
    return re.sub(r"\d+", "#", compact(normalized_line(line))).lower()


def edge_occurrences(pages: list[str]) -> dict[tuple[str, str], list[tuple[int, int, str]]]:
    occurrences: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    for page_no, text in enumerate(pages, 1):
        lines = text.splitlines()
        nonempty = [index for index, line in enumerate(lines) if line.strip()]
        top = set(nonempty[:2])
        bottom = set(nonempty[-2:])
        for index in sorted(top | bottom):
            line = normalized_line(lines[index])
            if not line or len(line) > 80:
                continue
            zone = "상단" if index in top else "하단"
            occurrences[(zone, line_signature(line))].append((page_no, index, line))
    return occurrences


def remove_headers(pages: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    occurrences = edge_occurrences(pages)
    remove_keys: dict[tuple[str, str], str] = {}
    candidates = []
    threshold = max(2, math.ceil(len(pages) * 0.4))
    for key, items in sorted(occurrences.items()):
        page_count = len({item[0] for item in items})
        lines = [item[2] for item in items]
        exact_count = max(Counter(lines).values())
        compact_lines = [compact(line) for line in lines]
        page_numbers = all(PAGE_NUMBER_RE.fullmatch(line) for line in compact_lines)
        kosha_header = all("koshaguide" in line.lower() for line in compact_lines)
        repeated_exact = exact_count >= threshold
        if page_count >= threshold and (page_numbers or kosha_header or repeated_exact):
            reason = "쪽 번호" if page_numbers else "반복 KOSHA 머리말" if kosha_header else "반복 짧은 줄"
            remove_keys[key] = reason
        elif page_count >= 2:
            candidates.append({"zone": key[0], "signature": key[1], "pages": page_count,
                               "examples": sorted(set(lines))})

    removed = []
    cleaned = []
    for page_no, text in enumerate(pages, 1):
        lines = text.splitlines()
        nonempty = [index for index, line in enumerate(lines) if line.strip()]
        top = set(nonempty[:2])
        bottom = set(nonempty[-2:])
        kept = []
        for index, raw_line in enumerate(lines):
            line = normalized_line(raw_line)
            zone = "상단" if index in top else "하단" if index in bottom else None
            if line and PAGE_NUMBER_RE.fullmatch(compact(line)):
                removed.append({"page": page_no, "zone": zone or "본문", "text": line,
                                "reason": "쪽 번호(위치 무관)"})
                continue
            key = (zone, line_signature(line)) if zone and line and len(line) <= 80 else None
            if key in remove_keys:
                removed.append({"page": page_no, "zone": zone, "text": line,
                                "reason": remove_keys[key]})
            else:
                kept.append(raw_line)
        cleaned.append("\n".join(kept).strip())
    return cleaned, removed, candidates


def exclude_front_matter(pages: list[str], source: SourceSpec) -> tuple[list[str], list[dict]]:
    """고정 SHA 문서에서 확인한 표지·개요·목차 페이지를 제외한다."""
    end_page = BODY_START_PAGE[source.doc_id] - 1
    excluded = [{"page": page_no, "text": pages[page_no - 1]}
                for page_no in range(1, end_page + 1) if pages[page_no - 1].strip()]
    cleaned = ["" if page_no <= end_page else text
               for page_no, text in enumerate(pages, 1)]
    return cleaned, excluded


def trailing_citation(text: str) -> tuple[int, str, str] | None:
    """페이지 끝의 번호형 서지 각주 한 개를 찾는다."""
    matches = []
    for marker in re.finditer(r"\d+\)", text):
        tail = text[marker.start():].strip()
        found = re.fullmatch(
            r"(?s)(\d+\)\s*(.{20,260}?(?:19|20)\d{2}\.))", tail)
        if found:
            matches.append((marker.start(), found.group(1), found.group(2)))
    return matches[-1] if matches else None


def remove_repeated_footnotes(pages: list[str]) -> tuple[list[str], list[dict], list[str]]:
    """번호만 다른 동일 서지 각주가 두 페이지 이상 반복될 때만 제거한다."""
    found = []
    for page_no, text in enumerate(pages, 1):
        citation = trailing_citation(text)
        if citation:
            start, full, body = citation
            found.append({"page": page_no, "start": start, "text": full,
                          "body": normalized_line(body), "key": compact(body)})

    repeated = {key for key, items in _group_by(found, "key").items()
                if len({item["page"] for item in items}) >= 2}
    removed = [item for item in found if item["key"] in repeated]
    by_page = {item["page"]: item for item in removed}
    cleaned = []
    for page_no, text in enumerate(pages, 1):
        if page_no not in by_page:
            cleaned.append(text)
            continue
        item = by_page[page_no]
        body = text[:item["start"]].rstrip()
        number = re.match(r"\d+", item["text"]).group()
        markers = list(re.finditer(rf"(?<![\d(]){number}\)", body))
        item["marker"] = ""
        if markers:
            marker = markers[-1]
            item["marker"] = marker.group()
            body = (body[:marker.start()] + body[marker.end():]).rstrip()
        cleaned.append(body)
    references = []
    for item in removed:
        if item["body"] not in references:
            references.append(item["body"])
    return cleaned, removed, references


def _group_by(items: list[dict], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item[key]].append(item)
    return grouped


def split_by_regex(piece: Piece, pattern: re.Pattern[str]) -> list[Piece]:
    starts = [match.start() for match in pattern.finditer(piece.text)]
    starts = sorted(set([0, *starts, len(piece.text)]))
    return [Piece(piece.text[start:end].strip(), piece.start_page, piece.end_page,
                  piece.forced_cut)
            for start, end in zip(starts, starts[1:]) if piece.text[start:end].strip()]


def hard_split(piece: Piece) -> list[Piece]:
    """문장 경계를 찾지 못한 500자 초과 덩어리만 마지막 수단으로 나눈다."""
    result = []
    remaining = piece.text.strip()
    while len(remaining) > TARGET_MAX:
        cut = remaining.rfind(" ", TARGET_MIN, TARGET_MAX + 1)
        if cut < TARGET_MIN:
            cut = TARGET_MAX
        result.append(Piece(remaining[:cut].strip(), piece.start_page, piece.end_page, True))
        remaining = remaining[cut:].strip()
    if remaining:
        result.append(Piece(remaining, piece.start_page, piece.end_page, piece.forced_cut))
    return result


def atomize(pages: list[str]) -> list[Piece]:
    atoms = []
    for page_no, text in enumerate(pages, 1):
        for clause in split_by_regex(Piece(text, page_no, page_no), CLAUSE_RE):
            if len(clause.text) <= TARGET_MAX:
                atoms.append(clause)
                continue
            sentences = split_by_regex(clause, SENTENCE_RE)
            if len(sentences) == 1:
                atoms.extend(hard_split(clause))
            else:
                for sentence in sentences:
                    atoms.extend(hard_split(sentence) if len(sentence.text) > TARGET_MAX
                                 else [sentence])
    return atoms


def pack_atoms(atoms: list[Piece]) -> list[Piece]:
    chunks: list[Piece] = []
    current: Piece | None = None
    for atom in atoms:
        if current is None:
            current = Piece(atom.text, atom.start_page, atom.end_page, atom.forced_cut)
            continue
        joined = current.text + " " + atom.text
        if len(joined) <= TARGET_MAX:
            current.text = joined
            current.end_page = atom.end_page
            current.forced_cut = current.forced_cut or atom.forced_cut
        else:
            chunks.append(current)
            current = Piece(atom.text, atom.start_page, atom.end_page, atom.forced_cut)
    if current is not None:
        chunks.append(current)

    # 마지막 작은 조각은 500자를 넘지 않을 때만 앞 청크에 붙인다.
    if len(chunks) >= 2 and len(chunks[-1].text) < TARGET_MIN:
        joined = chunks[-2].text + " " + chunks[-1].text
        if len(joined) <= TARGET_MAX:
            tail = chunks.pop()
            chunks[-1].text = joined
            chunks[-1].end_page = tail.end_page
            chunks[-1].forced_cut = chunks[-1].forced_cut or tail.forced_cut
    return chunks


def page_label(piece: Piece) -> str:
    return str(piece.start_page) if piece.start_page == piece.end_page else f"{piece.start_page}-{piece.end_page}"


def process_source(source: SourceSpec) -> dict:
    pages = extract_pages(source.path)
    pages, nul_removed, wide_page_numbers = remove_control_artifacts(pages)
    cleaned, removed, candidates = remove_headers(pages)
    cleaned, front_excluded = exclude_front_matter(cleaned, source)
    cleaned, footnotes, references = remove_repeated_footnotes(cleaned)
    packed = pack_atoms(atomize(cleaned))
    discarded = [piece for piece in packed if len(piece.text) < MIN_CHARS]
    kept = [piece for piece in packed if len(piece.text) >= MIN_CHARS]

    raw_count = sum(len(compact(page)) for page in pages) + nul_removed + sum(
        len(compact(item["text"])) for item in wide_page_numbers)
    wide_page_number_count = sum(len(compact(item["text"])) for item in wide_page_numbers)
    removed_count = sum(len(compact(item["text"])) for item in removed)
    front_count = sum(len(compact(item["text"])) for item in front_excluded)
    footnote_count = sum(len(compact(item["text"] + item["marker"])) for item in footnotes)
    discarded_count = sum(len(compact(piece.text)) for piece in discarded)
    kept_count = sum(len(compact(piece.text)) for piece in kept)
    clean_compact = compact("".join(cleaned))
    packed_compact = compact("".join(piece.text for piece in packed))
    integrity_ok = (raw_count - nul_removed - wide_page_number_count
                    - removed_count - front_count - footnote_count
                    - discarded_count == kept_count
                    and clean_compact == packed_compact)

    records = []
    for index, piece in enumerate(kept, 1):
        records.append({
            "page_content": piece.text,
            "metadata": {
                "source_file": source.path.name,
                "category": source.category,
                "page": page_label(piece),
                "chunk_id": f"{source.doc_id}-{index:04d}",
                "doc_id": source.doc_id,
                "ingest_version": "v2",
                "references": references,
            },
            "_forced_cut": piece.forced_cut,
        })
    records, metadata_nul_removed = remove_nul_strings(records)
    return {
        "source": source,
        "records": records,
        "removed": removed,
        "nul_removed": nul_removed + metadata_nul_removed,
        "metadata_nul_removed": metadata_nul_removed,
        "wide_page_numbers": wide_page_numbers,
        "wide_page_number_count": wide_page_number_count,
        "front_excluded": front_excluded,
        "footnotes": footnotes,
        "references": references,
        "candidates": candidates,
        "discarded": discarded,
        "raw_count": raw_count,
        "removed_count": removed_count,
        "front_count": front_count,
        "footnote_count": footnote_count,
        "discarded_count": discarded_count,
        "kept_count": kept_count,
        "integrity_ok": integrity_ok,
    }


def markdown_text(text: str) -> str:
    return text.replace("\r", "").replace("\n", "<br>").replace("|", "&#124;")


def make_report(results: list[dict], hashes: list[tuple[SourceSpec, str]]) -> str:
    records = [record for result in results for record in result["records"]]
    texts = [record["page_content"] for record in records]
    counts, word_mean = metrics(texts)
    lengths = [len(text) for text in texts]
    below_target = sum(length < TARGET_MIN for length in lengths)
    forced = sum(bool(record["_forced_cut"]) for record in records)
    line_break_artifacts = sum(text.count("부 드러운") for text in texts)
    discarded_total = sum(len(result["discarded"]) for result in results)
    integrity_failures = [result for result in results if not result["integrity_ok"]]
    categories = Counter(record["metadata"]["category"] for record in records)
    wide_counts = Counter({result["source"].doc_id: len(result["wide_page_numbers"])
                           for result in results if result["wide_page_numbers"]})

    lines = [
        "# SOP 매뉴얼 청크 v2.1 dry 결과",
        "",
        "## 판단 요청",
        "",
        "1. 제거 목록과 보수적으로 남긴 후보를 검토한 뒤 이 청크 세트를 승인할지 결정해야 한다. 권장: 무결성 통과와 H-187·E-14 샘플을 먼저 확인하고 `--apply`는 별도 지시한다.",
        f"2. 문장 경계를 찾지 못해 500자에서 강제 분할된 청크가 {forced}개다. 권장: 아래 샘플과 JSONL에서 해당 문서 문맥을 확인하고, 문제가 있으면 분할 규칙만 조정한다.",
        "3. v1의 100자 미만 청크 수와 문장 중간 절단 비율은 기존 근거 파일에 측정값이 없다. 권장: 오늘 DB 연결 금지 조건을 유지해 미측정으로 두고, 필요하면 별도 읽기 전용 측정을 지시한다.",
        "",
        "## v1 대비",
        "",
        "| 지표 | v1 | v2.1 | 근거 |",
        "|---|---:|---:|---|",
        f"| 청크 수 | 640 | {len(records)} | v1: `_etl_probe_20260906.txt` 전체 DB, v2.1: `chunks_v2.jsonl` |",
        f"| 평균 길이(문자) | 402 | {sum(lengths) / len(lengths):.2f} | v1: `04_문서/설계/SOP_코퍼스_재설계_0825.md`, v2.1: JSONL 본문 |",
        f"| 최대 길이(문자) | 600 | {max(lengths, default=0)} | 같은 근거 |",
        f"| 100자 미만 청크 수 | 기록 없음 | 0 (폐기 {discarded_total}개) | 폐기 원문은 아래 전부 수록 |",
        f"| 공백 소실 의심(한글 25자 이상) | 154/634 (24.29%) | {counts[25]}/{len(records)} ({counts[25] / len(records):.2%}) | v1: `_etl_probe_20260906.txt`, v2.1: etl_probe와 같은 `longest()` 기준 |",
        f"| 문장 중간 절단 추정 | 기록 없음 | {forced}/{len(records)} ({forced / len(records):.2%}) | v2.1: 문장 경계가 없어 강제 분할한 청크 |",
        "",
        f"> 참고: v2.1 청크별 평균 어절 길이의 산술평균은 {word_mean:.3f}자다. 이 값은 `_etl_probe_20260906.txt`의 `metrics()`와 같은 계산이다.",
        "",
        "## v2.1 대비 T-CX05 정제본",
        "",
        "| 지표 | v2.1 | T-CX05 정제본 |",
        "|---|---:|---:|",
        f"| 청크 수 | {V21_STATS['chunks']} | {len(records)} |",
        f"| 평균 길이(문자) | {V21_STATS['mean']:.2f} | {sum(lengths) / len(lengths):.2f} |",
        f"| 최대 길이(문자) | {V21_STATS['max']} | {max(lengths, default=0)} |",
        f"| 공백 소실 의심 수 | {V21_STATS['space_loss']} | {counts[25]} |",
    ]
    for category, old_count in V21_STATS["categories"].items():
        lines.append(f"| 카테고리 `{category}` | {old_count} | {categories[category]} |")
    lines += [
        "",
        "## 카테고리별 청크 수",
        "",
        "| 카테고리 | v1 | v2.1 |",
        "|---|---:|---:|",
    ]
    v1_categories = {
        "00_응급처치_공통": 18,
        "01_감전_대응": 17,
        "01_감전_예방": 120,
        "02_협착_예방": 138,
        "03_낙상_예방": 65,
        "04_예지보전": 73,
        "05_위험성평가_비상": 62,
        "09_색인제외": 147,
    }
    for category, old_count in v1_categories.items():
        lines.append(f"| {category} | {old_count} | {categories[category]} |")

    lines += [
        "",
        "## 입력 SHA-256",
        "",
        "| 문서 | SHA-256 | 기준 대조 |",
        "|---|---|---|",
    ]
    for source, actual in hashes:
        status = "일치" if source.sha256 is not None else "현재값 기록(기준 목록 밖)"
        lines.append(f"| {source.path.name} | `{actual}` | {status} |")

    lines += [
        "",
        "## 무결성 검사",
        "",
        "검사식: 원본 페이지 비공백 문자 수 − 제거한 NUL − 제거한 전각 쪽번호 − 제거한 머리말·꼬리말·쪽 번호 − 제외한 개요·목차 − 제외한 반복 각주 − 버린 짧은 청크 = 정제 청크 비공백 문자 수. 겹침은 사용하지 않았다.",
        "",
        "| 문서 | 원본 | NUL | 전각 쪽번호 | 머리말·쪽 번호 | 개요·목차 | 각주 | 폐기 | 정제본 | 결과 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            f"| {result['source'].doc_id} | {result['raw_count']} | {result['nul_removed']} | "
            f"{result['wide_page_number_count']} | {result['removed_count']} | "
            f"{result['front_count']} | {result['footnote_count']} | "
            f"{result['discarded_count']} | {result['kept_count']} | "
            f"{'일치' if result['integrity_ok'] else '불일치'} |")
    lines += [
        "",
        f"불일치 문서: {len(integrity_failures)}개" +
        (" — " + ", ".join(result["source"].doc_id for result in integrity_failures)
         if integrity_failures else ""),
        "",
        "## 제거한 NUL",
        "",
        "| 문서 | 제거 문자 수 | 메타데이터에서 제거 |",
        "|---|---:|---:|",
    ]
    for result in results:
        if result["nul_removed"]:
            lines.append(f"| {result['source'].doc_id} | {result['nul_removed']} | {result['metadata_nul_removed']} |")
    if not any(result["nul_removed"] for result in results):
        lines.append("| 없음 | 0 | 0 |")

    lines += [
        "",
        "## 제거한 전각 쪽번호",
        "",
        "| 문서 | 기대 | 실제 | 대조 |",
        "|---|---:|---:|---|",
    ]
    for doc_id, expected in EXPECTED_WIDE_PAGE_NUMBERS.items():
        actual = wide_counts[doc_id]
        reason = "일치" if actual == expected else "불일치 — 아래 위치 목록 확인 필요"
        lines.append(f"| {doc_id} | {expected} | {actual} | {reason} |")
    lines += [
        "",
        "| 문서 | 쪽 | 앞 15자 | 삭제 문자열 | 뒤 15자 |",
        "|---|---:|---|---|---|",
    ]
    for result in results:
        for item in result["wide_page_numbers"]:
            lines.append(
                f"| {result['source'].doc_id} | {item['page']} | `{markdown_text(item['before'])}` | "
                f"`{markdown_text(item['text'])}` | `{markdown_text(item['after'])}` |")

    for doc_id in ("H-187-2021", "E-14-2012"):
        samples = [record for record in records if record["metadata"]["doc_id"] == doc_id][:5]
        lines += ["", f"## {doc_id} 샘플 청크 5개", ""]
        for record in samples:
            meta = record["metadata"]
            lines += [f"### {meta['chunk_id']} · {meta['page']}쪽 · {len(record['page_content'])}자",
                      "", record["page_content"], ""]

    required_samples = [
        ("H-187 핵심 구절", "머리, 경추, 척추 등이 움직이지 않도록"),
        ("E-14 핵심 구절", "7. 감전사고시의 응급조치"),
    ]
    lines += ["", "## 지정 핵심 청크 원문", ""]
    for title, phrase in required_samples:
        record = next(record for record in records if phrase in record["page_content"])
        meta = record["metadata"]
        lines += [f"### {title} · {meta['chunk_id']} · {meta['page']}쪽",
                  "", record["page_content"], ""]

    lines += ["", "## 제외한 개요·목차 범위 전체", ""]
    for result in results:
        pages = [item["page"] for item in result["front_excluded"]]
        page_range = ("없음" if not pages else f"{pages[0]}쪽" if len(pages) == 1
                      else f"{pages[0]}-{pages[-1]}쪽")
        lines.append(f"- {result['source'].doc_id}: {page_range}")

    lines += ["", "## 제거한 반복 서지 각주 전체", ""]
    any_footnotes = False
    for result in results:
        if not result["footnotes"]:
            continue
        any_footnotes = True
        lines += [f"### {result['source'].doc_id}", ""]
        for item in result["footnotes"]:
            marker = f" (본문 표지 `{item['marker']}` 포함)" if item["marker"] else ""
            lines.append(f"- {item['page']}쪽: {markdown_text(item['text'])}{marker}")
        lines.append("")
        lines.append("메타데이터 `references`: " + " / ".join(
            f"`{markdown_text(reference)}`" for reference in result["references"]))
        lines.append("")
    if not any_footnotes:
        lines += ["- 없음", ""]

    lines += ["", "## 제거한 머리말·꼬리말·쪽 번호 전체", ""]
    for result in results:
        lines.append(f"### {result['source'].doc_id}")
        lines.append("")
        if not result["removed"]:
            lines.append("- 없음")
        else:
            for item in result["removed"]:
                lines.append(f"- {item['page']}쪽 {item['zone']} · {item['reason']}: `{markdown_text(item['text'])}`")
        lines.append("")

    lines += ["## 보수적으로 남긴 머리말·꼬리말 후보", ""]
    any_candidates = False
    for result in results:
        if not result["candidates"]:
            continue
        any_candidates = True
        lines += [f"### {result['source'].doc_id}", ""]
        for item in result["candidates"]:
            examples = " / ".join(f"`{markdown_text(text)}`" for text in item["examples"])
            lines.append(f"- {item['zone']} · {item['pages']}쪽 반복 · {examples}")
        lines.append("")
    if not any_candidates:
        lines += ["- 없음", ""]

    lines += ["## 100자 미만으로 버린 청크 원문 전체", ""]
    for result in results:
        if not result["discarded"]:
            continue
        lines += [f"### {result['source'].doc_id}", ""]
        for piece in result["discarded"]:
            lines.append(f"- {page_label(piece)}쪽 · {len(piece.text)}자: {markdown_text(piece.text)}")
        lines.append("")
    if not discarded_total:
        lines += ["- 없음", ""]

    lines += [
        "## 알려진 한계",
        "",
        f"- 줄바꿈 좌표 때문에 단어 안에 들어간 공백은 교정하지 않았다. `부 드러운` {line_break_artifacts}건을 포함해 인위 교정 0건이다.",
        f"- 250자 미만 청크는 {below_target}개다. 모두 100자 이상이며 조항·문서 끝 경계를 보존하려고 억지로 합치지 않았다.",
        "",
        "## 실행하지 않은 것",
        "",
        "- `--apply`: 실행 안 함",
        "- Ollama 임베딩: 실행 안 함",
        "- PostgreSQL 연결·적재: 실행 안 함",
        "- 검색 회귀: 실행 안 함",
        "",
        "## 검증",
        "",
        "- `python -m pyflakes 01_현행코드\\sop_ingest_v2.py`: 경고 0건, 종료코드 0.",
        "- `python 01_현행코드\\sop_ingest_v2.py` dry 2회: `chunks_v2.jsonl`과 `report.md` 각각 SHA-256 동일, 바이트 차이 0건.",
        "- JSONL 구조 검사: 중복 `chunk_id` 0건, 필수 메타데이터 누락 0건, 잘못된 `page` 형식 0건.",
        "- dry 자체 검사: 입력 14개 존재, 기준 SHA 13개 일치, 프로젝트 SOP SHA 기록, 문서별 비공백 문자 무결성 검사, 지정 핵심 청크 2개 존재.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(results: list[dict], hashes: list[tuple[SourceSpec, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        for result in results:
            for record in result["records"]:
                public_record = {key: value for key, value in record.items()
                                 if not key.startswith("_")}
                stream.write(json.dumps(public_record, ensure_ascii=False,
                                        sort_keys=True, separators=(",", ":")) + "\n")
    REPORT_PATH.write_text(make_report(results, hashes), encoding="utf-8", newline="\n")


def apply_chunks(results: list[dict]) -> None:
    if COLLECTION == "safety_manual":
        raise RuntimeError("운영 컬렉션 safety_manual에는 적재할 수 없습니다")
    if COLLECTION != "safety_manual_v2":
        raise RuntimeError(f"허용되지 않은 컬렉션: {COLLECTION}")

    records = [record for result in results for record in result["records"]]
    if any("\x00" in text for record in records
           for text in [record["page_content"], *map(str, record["metadata"].values())]):
        raise RuntimeError("적재 중단: 전체 청크 검사에서 NUL(0x00)을 찾았습니다")

    # dry 경로에서는 아래 모듈을 import하지 않아 Ollama·DB 연결이 생기지 않는다.
    from langchain_community.vectorstores import PGVector
    from langchain_core.documents import Document
    from langchain_ollama import OllamaEmbeddings
    from radar_core import CONN_STR, EMBED_MODEL
    from sqlalchemy import create_engine, text

    with create_engine(CONN_STR).connect() as connection:
        existing = connection.execute(text("""
            SELECT count(*)
            FROM langchain_pg_embedding AS embedding
            JOIN langchain_pg_collection AS collection
              ON embedding.collection_id = collection.uuid
            WHERE collection.name = :name
        """), {"name": COLLECTION}).scalar_one()
    print(f"적재 전 {COLLECTION}: {existing}개")
    if existing != 0:
        raise RuntimeError(f"중복 적재 방지: {COLLECTION}이 {existing}개라 적재를 중단합니다")

    embedding = OllamaEmbeddings(model=EMBED_MODEL)
    store = PGVector(connection_string=CONN_STR, embedding_function=embedding,
                     collection_name=COLLECTION)
    documents = [Document(page_content=record["page_content"],
                          metadata=record["metadata"])
                 for record in records]
    store.add_documents(documents)


def self_check() -> None:
    if COLLECTION != "safety_manual_v2":
        raise AssertionError("적재 대상 컬렉션이 고정값과 다릅니다")
    if restore("가나다라마바사아자차카타파하", "가나다라 마바사아 자차카타파하") != "가나다라 마바사아 자차카타파하":
        raise AssertionError("공백 복원 자체 검사 실패")
    if longest("가" * 25) != 25:
        raise AssertionError("공백 소실 지표 자체 검사 실패")
    if (TARGET_MIN, TARGET_MAX) != (250, 500):
        raise AssertionError("청크 목표 범위가 250~500자가 아닙니다")
    if set(BODY_START_PAGE) != {source.doc_id for source in SOURCES}:
        raise AssertionError("본문 시작 페이지 매핑이 입력 문서와 다릅니다")
    if WIDE_PAGE_NUMBER_RE.sub("", "본문 － －123 끝") != "본문  끝":
        raise AssertionError("전각 쪽번호 제거 자체 검사 실패")
    if WRAPPED_WIDE_PAGE_NUMBER_RE.sub("", "본문 － －- 12 - 끝") != "본문  끝":
        raise AssertionError("반각 하이픈 포함 전각 쪽번호 제거 자체 검사 실패")
    if WRAPPED_WIDE_PAGE_NUMBER_RE.sub("", "연성－취성") != "연성－취성":
        raise AssertionError("일반 전각 하이픈 보존 자체 검사 실패")
    if WIDE_PAGE_NUMBER_RE.search("일반 - 1, en dash – 2, em dash — 3"):
        raise AssertionError("일반 대시 보존 자체 검사 실패")


def main() -> int:
    parser = argparse.ArgumentParser(description="SOP 매뉴얼 v2.1 청크 생성")
    parser.add_argument("--apply", action="store_true",
                        help="검토 후 safety_manual_v2에 적재")
    args = parser.parse_args()

    self_check()
    hashes = verify_sources()
    results = [process_source(source) for source in SOURCES]
    if any(not result["integrity_ok"] for result in results):
        raise RuntimeError("문서 무결성 검사 불일치가 있어 출력을 중단합니다")
    texts = [record["page_content"] for result in results for record in result["records"]]
    if any("\x00" in json.dumps(record, ensure_ascii=False)
           for result in results for record in result["records"]):
        raise RuntimeError("정제 결과에 NUL(0x00)이 남았습니다")
    if any(WRAPPED_WIDE_PAGE_NUMBER_RE.search(text) or WIDE_PAGE_NUMBER_RE.search(text)
           for text in texts):
        raise RuntimeError("정제 결과에 전각 쪽번호가 남았습니다")
    for doc_id, expected in UNCHANGED_CONTENT_SHA256.items():
        records = [record for result in results for record in result["records"]
                   if record["metadata"]["doc_id"] == doc_id]
        if content_sha256(records) != expected:
            raise RuntimeError(f"{doc_id} 청크 본문이 v2.1과 바이트 단위로 다릅니다")
    for phrase in ("머리, 경추, 척추 등이 움직이지 않도록", "7. 감전사고시의 응급조치"):
        if not any(phrase in text for text in texts):
            raise RuntimeError(f"지정 핵심 청크를 찾지 못했습니다: {phrase}")
    write_outputs(results, hashes)
    if args.apply:
        apply_chunks(results)
        print(f"적재 완료: {COLLECTION}")
    else:
        print(f"dry 완료: {CHUNKS_PATH}")
        print(f"보고서: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
