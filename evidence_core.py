"""Evidence-preserving primitives for 의정소통 MCP.

No network, SDK, authentication, or global mutable state. Text offsets refer to
parsed plain text / parsed turns, never to PDF pages or original HTML bytes.
The rules yield candidates, not adjudicated intentions or verified fulfillment.
"""
from __future__ import annotations
import base64
import copy
import datetime as dt
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import urlsplit, parse_qsl

SCHEMA_VERSION = "2.0"
class EvidenceInputError(ValueError):
    """Invalid input/state; never convert to an empty successful search."""

_STAFF = ("전문위원", "사무국장", "사무과장", "의사팀장", "의사담당", "의정팀장", "속기", "입법조사", "의회사무국")
_CHAIR = ("의장", "부의장", "위원장", "부위원장", "임시의장", "임시위원장", "의장직무대리", "위원장직무대리")
_EXEC = (
    "구청장", "시장", "군수", "도지사", "지사", "교육감", "교육장", "부구청장", "부시장", "부군수", "부지사",
    "국장", "실장", "과장", "소장", "단장", "관장", "담당관", "팀장", "동장", "읍장", "면장", "원장",
    "본부장", "사장", "이사장", "센터장", "감사관", "주무관", "계장", "사무관", "대표이사", "처장", "관리관",
)
_END_LABELS = ("출석", "출사무국", "참석", "불출석", "결석", "배석", "회의록서명", "서명의원", "청가", "출장", "속기사")


def _classify(label: str) -> str:
    lab = label.replace(" ", "")
    if any(lab.startswith(e) for e in _END_LABELS):
        return "end"
    if any(s in lab for s in _STAFF):
        return "staff"
    head = label.split()[0] if label.split() else lab
    if any(head == c or head.endswith(c) and not head.endswith("의원") for c in _CHAIR) and not any(
        e in head for e in ("청장", "시장", "군수", "지사")
    ):
        return "chair"
    if "의원" in lab or re.search(r"(^|[^전문])위원($|\s)", label):
        return "member"
    if any(e in lab for e in _EXEC):
        return "executive"
    return "other"


ROLE_KO = {"chair": "의장·위원장", "member": "의원", "executive": "집행부", "staff": "의회사무국", "other": "기타"}


# 안건 시작·종료 신호(사회자 발언)
_AGENDA_START = re.compile(r"(상정합니다|상정하겠습니다|상정하도록|안건을\s*상정|의사일정\s*제\s*\d+\s*항|다음은\s*[^.?!]{0,30}(소관|업무보고|안건|순서|질의|제안설명|보고))")
_AGENDA_CLOSE = re.compile(r"(질의\s*(답변)?\s*(을|를)?\s*(모두\s*)?(종결|마치)|가결되었음을\s*선포|의결되었음을\s*선포|산회를\s*선포|폐회를\s*선포|이상으로\s*[^.?!]{0,30}(마치|마치겠))")
_PROCEDURAL = re.compile(r"(성원|개의|개회|산회|정회|속개|상정|선포|의석|질의하실|질의해\s*주|발언하여\s*주|발언해\s*주|의견이?\s*(있|없)|이의\s*(가|는)?\s*없|계십니까|없습니까|다음은|의결|종결|수고하셨|순서|진행하겠|마치겠|배부해\s*드린)")
_QMARK = re.compile(r"(\?|습니까|십니까|나요|는지요|궁금|설명해\s*주시|답변해\s*주시|말씀해\s*주시|어떻게\s*(되|생각|하실)|왜\s)")
_REVIEW_LABEL = ("전문위원", "입법조사")
_REPORT_OPEN = re.compile(r"^[^.?!]{0,40}(업무보고|제안설명|보고를?\s*드리|설명을?\s*드리|보고드리도록|보고드리겠습니다|설명드리겠습니다)")


def classify_act(role: str, label: str, text: str) -> str:
    """발언자 역할과 별도로 발언행위를 분류: question·procedural·answer_candidate·report·review·other"""
    if role == "staff" and any(x in label for x in _REVIEW_LABEL):
        return "review"
    if role == "chair":
        for sent in split_sentences(text):
            if _QMARK.search(sent) and not _PROCEDURAL.search(sent) and len(sent) >= 12:
                return "question"
        return "procedural"
    if role == "member":
        if len(text) < 12 and not _QMARK.search(text):
            return "other"
        return "question"
    if role in ("executive", "staff"):
        return "report" if _REPORT_OPEN.search(text) else "answer_candidate"
    return "other"


_FIVE_MIN = re.compile(r"5\s*분\s*자유\s*발언")
_QUESTION_TIME = re.compile(r"(구정|시정|군정|도정|교육행정)\s*질문")


def speech_context(turns: list[dict], i: int) -> str:
    """해당 발언 앞의 사회자 발언을 거슬러 보며 발언유형(5분자유발언·구정질문) 추정."""
    for j in range(i - 1, max(-1, i - 15), -1):
        t = turns[j]
        if t["role"] != "chair":
            continue
        if _FIVE_MIN.search(t["text"]):
            return "5분자유발언"
        if _QUESTION_TIME.search(t["text"]):
            return "구·시정질문"
        if re.search(r"(의사일정\s*제\s*\d+\s*항|상정합니다|안건을\s*상정)", t["text"]):
            return ""
    return ""


def meeting_kind(mtgnm: str) -> str:
    m = mtgnm or ""
    if "감사" in m:
        return "행정사무감사·조사"
    if "예산" in m or "결산" in m:
        return "예산·결산"
    if "본회의" in m:
        return "본회의"
    if "특별" in m:
        return "특별위원회"
    if "위원회" in m:
        return "상임위원회"
    return "기타"


# ───────── 후속조치 후보 분류 (E03·E04·E05) ─────────
_COMMIT_VERB = re.compile(
    r"(검토|추진|반영|조치|개선|보고|협의|마련|확대|점검|시정|노력|제출|드리|챙기|해결|시행|설치|정비|확보|파악|살펴|추가|보완|강화|진행)"
    r"[가-힣\s]{0,8}(하겠습니다|겠습니다|토록\s*하겠습니다|도록\s*하겠습니다|해\s*보겠습니다|될\s*수\s*있도록)"
)
_NEG = re.compile(r"(않겠습니다|않도록\s*하겠습니다\s*$|어렵습니다|곤란합니다|불가합니다|하지\s*않|안\s*하겠습니다)")
_PAST = re.compile(r"(하겠다고\s*(했|말씀|답변|약속)|했었습니다|하였었습니다|겠다고\s*하셨)")
_NOW_REPORT = re.compile(r"(업무보고|보고|설명|제안설명|답변)\s*(을|를)?\s*(드리|올리)(겠|도록)")
_LATER = re.compile(r"(추후|향후|별도로|서면|나중에|다음\s*회기|까지|정리해서|정리하여|확인해서|확인하여|파악해서|파악하여|결과를|결과는|자료를|자료로)")
_COND = re.compile(r"(되면|된다면|될\s*경우|경우에는|경우에|한다면|전제로|여건이\s*되|가능하다면|가능하면|확보되|허락한다면|통과되면)")
_DEADLINE = re.compile(r"(\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}\s*월\s*(초|중순|말)?|연내|올해\s*안|연말|상반기|하반기|내년(도)?(\s*\d{1,2}\s*월)?|다음\s*(달|주|회기)|추경|추가경정|본예산)\s*(까지|중에?|안에|내에|에)?")


def classify_commitment(sentence: str) -> Optional[dict]:
    """집행부 답변 문장에서 후속조치 '후보'를 분류. 약속이 아니면 None.
    반환: {type: 자료제출·검토의사·조건부 추진·시행의사, condition, deadline}
    ※ 기한의 연도는 원문에 없으면 붙이지 않는다. 이행 여부는 판정하지 않는다."""
    x = sentence.strip()
    if not _COMMIT_VERB.search(x):
        return None
    if _NEG.search(x) or _PAST.search(x):
        return None
    if _NOW_REPORT.search(x) and not _LATER.search(x):
        return None                                   # 지금 하는 보고·설명은 약속이 아님
    cond = _COND.search(x)
    dl = _DEADLINE.search(x)
    if re.search(r"(자료|제출|서면)", x):
        typ = "자료제출"
    elif cond:
        typ = "조건부 추진"
    elif re.search(r"(검토|협의|살펴|파악)", x):
        typ = "검토의사"
    else:
        typ = "시행의사"
    return {"type": typ, "condition": x[max(0, cond.start() - 20): cond.end() + 1].strip() if cond else None,
            "deadline": dl.group(0).strip() if dl else None}


def commitment_tag(info: dict) -> str:
    tag = info["type"]
    if info.get("condition"):
        tag += f"·조건 '{info['condition']}'"
    tag += f"·기한 {info['deadline']}" if info.get("deadline") else "·기한 미상"
    return f"[{tag}]"


_COMMIT = type("_CommitCompat", (), {"search": staticmethod(classify_commitment)})()


_DEPT_SUFFIX = re.compile(r"(과장|팀장|국장|실장|소장|단장|센터장|담당관|원장|과|팀|국|실|소|단|센터)$")


def dept_match(answerer: Optional[str], label: str) -> bool:
    """'미래전략과장' 필터가 '미래전략팀장'(대리답변)·'미래전략과장'을 함께 찾도록 부서 어간으로도 비교."""
    if not answerer:
        return True
    a = answerer.replace(" ", "")
    lab = label.replace(" ", "")
    if a in lab:
        return True
    stem = _DEPT_SUFFIX.sub("", a)
    return len(stem) >= 2 and stem in lab


class _PlainText(HTMLParser):
    """Keep block boundaries, discard executable and hidden markup payloads."""
    BLOCKS = {"br", "p", "div", "tr", "td", "li", "hr", "spk", "h1", "h2", "h3", "h4", "section"}
    HIDDEN = {"script", "style", "template", "noscript"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")
        elif not self.hidden and tag in {"b", "strong", "a"}:
            self.parts.append(" ")
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(src: str) -> str:
    parser = _PlainText()
    parser.feed(src or "")
    parser.close()
    return "".join(parser.parts).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


def normalize_match(text: str) -> str:
    """NFKC/case-fold, ignore all Unicode space and format characters."""
    return "".join(c for c in unicodedata.normalize("NFKC", str(text or "")).casefold()
                   if not c.isspace() and unicodedata.category(c) != "Cf")


def match_text(text: str, keyword: Optional[str]) -> bool:
    needle = normalize_match(keyword or "")
    return not needle or needle in normalize_match(text)


def _normalized_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    # Combine marks and conjoining Hangul Jamo before NFKC so NFD Korean matches.
    chunks = []
    a = 0
    def is_jamo(c):
        return '\u1100' <= c <= '\u11ff' or '\ua960' <= c <= '\ua97f' or '\ud7b0' <= c <= '\ud7ff'
    for i in range(1, len(text)):
        if unicodedata.combining(text[i]) or (is_jamo(text[i - 1]) and is_jamo(text[i])):
            continue
        chunks.append((a, i)); a = i
    if text:
        chunks.append((a, len(text)))
    chars, offsets = [], []
    for a, b in chunks:
        for c in unicodedata.normalize("NFKC", text[a:b]).casefold():
            if not c.isspace() and unicodedata.category(c) != "Cf":
                chars.append(c); offsets.append((a, b))
    return "".join(chars), offsets


def snippet(text: str, kw: Optional[str], width: int = 180) -> str:
    if not text:
        return ""
    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 10000:
        raise EvidenceInputError("width는 1~10000 정수여야 합니다.")
    normalized, offsets = _normalized_offsets(text)
    needle = normalize_match(kw or "")
    pos = normalized.find(needle) if needle else -1
    if pos < 0:
        return text[:width * 2] + ("…" if len(text) > width * 2 else "")
    a = max(0, offsets[pos][0] - width)
    b = min(len(text), offsets[pos + len(needle) - 1][1] + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


_NAME = r"[가-힣]{2,5}"
_SPEECH_WORDS = {"다음은", "그러면", "이어서", "먼저", "네", "예", "감사합니다", "존경하는", "의사일정", "좌석을", "의석을", "성원이"}
_LABEL_RE = re.compile(
    rf"(?P<label>{_NAME}[ \t]*(?:의원|위원)|"
    rf"[가-힣·ㆍ()]{{1,28}}(?:위원장직무대리|의장직무대리|전문위원|위원장|의장|의원|위원|청장|시장|군수|지사|교육감|교육장|국장|과장|팀장|실장|소장|단장|담당관|센터장|대표이사|이사장|본부장|원장|관장|처장|계장|사무관|주무관|동장|읍장|면장|사장)[ \t]+{_NAME}|"
    rf"(?:위원장|의장|위원|의원|시장|군수|구청장|전문위원)[ \t]+{_NAME})"
    r"(?=[ \t\n:：]|$)")
_END_RE = re.compile(r"(?:출석|출사무국|참석|불출석|결석|배석|회의록서명|서명의원|청가|출장|속기사)[^\n]{0,50}")
_HEADING = re.compile(r"(?m)^[ \t]*(?:제\s*)?\d+[.．、)]\s*[^\n]{2,180}(?:의\s*건|조례안|규칙안|승인안|동의안|결의안|건의안|계획안|예산안|업무보고|소관)[ \t]*$")


def parse_turns(minutes_html: str) -> list[dict]:
    """Parse mixed bold/plain speaker lines with one scanner.

    Speakers need a recognized role/name shape. Unknown bulleted list items are
    kept inside the current speech. Standalone numbered agenda headings create
    hard boundaries. Speaker/act classification remains heuristic.
    """
    s = plain_text(minutes_html)
    candidates: list[tuple[int, int, str]] = []
    for marker in re.finditer(r"[○◯●][ \t]*", s):
        start = marker.end()
        end = _END_RE.match(s, start)
        if end:
            candidates.append((marker.start(), end.end(), end.group())); continue
        label = _LABEL_RE.match(s, start)
        if label:
            value = label.group("label")
            if value.split()[-1] in _SPEECH_WORDS:
                continue
            body_start = label.end()
            suffix = re.match(r"[ \t]*[:：]?[ \t]*", s[body_start:])
            body_start += suffix.end()
            candidates.append((marker.start(), body_start, value))
        else:
            # A role by itself is supported only with ':'; do not eat prose.
            lone = re.match(r"([가-힣·]{2,30})[ \t]*[:：][ \t]*", s[start:])
            if lone and (_classify(lone.group(1)) != "other" or re.fullmatch(_NAME, lone.group(1))):
                candidates.append((marker.start(), start + lone.end(), lone.group(1)))
    # Some sources mix symbol headers and colon-only line headers.
    for m in re.finditer(r"(?m)^[ \t]*([^\n○◯●]{2,60})[:：][ \t]*", s):
        label = _LABEL_RE.fullmatch(m.group(1).strip())
        if label:
            candidates.append((m.start(), m.end(), label.group("label")))
    candidates.sort()
    # De-duplicate overlapping header candidates defensively.
    candidates = [x for i, x in enumerate(candidates) if not i or x[0] >= candidates[i - 1][1]]
    turns = []
    agenda = 0
    for i, (_, a, label) in enumerate(candidates):
        b = candidates[i + 1][0] if i + 1 < len(candidates) else len(s)
        label = re.sub(r"\s+", " ", label).strip()
        role = _classify(label)
        if role == "end":
            break
        raw = s[a:b]
        headings = list(_HEADING.finditer(raw))
        # Text after an agenda heading cannot be attached to the previous speaker.
        segments = [(0, headings[0].start(), role, label)] if headings else [(0, len(raw), role, label)]
        for segment_start, segment_end, segment_role, segment_label in segments:
            body = re.sub(r"[ \t]*\n[ \t]*", " ", raw[segment_start:segment_end]).strip()
            body = re.sub(r"\s*맨위로\s*", " ", body).strip()
            if not body:
                continue
            if segment_role == "chair" and _AGENDA_START.search(body):
                agenda += 1
            turns.append({"idx": len(turns), "label": segment_label, "role": segment_role,
                          "text": body, "agenda": agenda, "act": classify_act(segment_role, segment_label, body),
                          "char_start": a + segment_start, "char_end": a + segment_end,
                          "offset_basis": "html_to_plain_text", "classification": "RULE_BASED_CANDIDATE"})
            if segment_role == "chair" and _AGENDA_CLOSE.search(body):
                agenda += 1
        for j, heading in enumerate(headings):
            agenda += 1
            tail_end = headings[j + 1].start() if j + 1 < len(headings) else len(raw)
            tail = raw[heading.end():tail_end].strip()
            if tail:
                # Preserve unattributed content without guessing who said it.
                turns.append({"idx": len(turns), "label": "발언자 미확인", "role": "other", "text": tail,
                              "agenda": agenda, "act": "other", "char_start": a + heading.end(),
                              "char_end": a + tail_end, "offset_basis": "html_to_plain_text",
                              "classification": "UNATTRIBUTED_AFTER_AGENDA_BOUNDARY"})
    return turns


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+|(?<=습니다)\s+(?=[가-힣A-Za-z0-9“\"(])", text) if p.strip()]


def build_qa_pairs(turns: list[dict], kw: Optional[str] = None) -> list[dict]:
    pairs = []
    for i, question in enumerate(turns):
        if question.get("act") != "question":
            continue
        answers = []
        for j in range(i + 1, len(turns)):
            turn = turns[j]
            if turn.get("agenda", 0) != question.get("agenda", 0):
                break
            if turn.get("act") == "question" and turn.get("role") in ("member", "chair"):
                break
            if turn.get("role") == "chair":
                if _AGENDA_START.search(turn["text"]) or _AGENDA_CLOSE.search(turn["text"]):
                    break
                if _ANSWER_CUE.search(turn["text"]) or len(turn["text"]) < 60:
                    continue
                break
            if turn.get("role") in ("executive", "staff"):
                # A standalone report/review is never promoted to a response.
                if turn.get("act") == "review":
                    continue
                if turn.get("act") == "report" and not _ANSWER_CUE.search(turn["text"]):
                    break
                answers.append(turn)
        if match_text(question["text"] + " ".join(a["text"] for a in answers), kw):
            pairs.append({"q": question, "answers": answers, "kind": speech_context(turns, i),
                          "agenda": question.get("agenda", 0),
                          "answer_status": "ANSWER_CANDIDATES_LINKED" if answers else "NO_LINKED_ANSWER",
                          "link_basis": "SAME_AGENDA_ADJACENCY_HEURISTIC"})
    return pairs


_ANSWER_CUE = re.compile(r"(답변|말씀|설명|대답)")
# Extend maintained rules; all results remain follow-up candidates.
_COMMIT_VERB = re.compile(
    r"(검토|추진|반영|조치|개선|보고|협의|마련|확대|점검|시정|노력|제출|드리|챙기|해결|시행|설치|정비|확보|파악|살펴|추가|보완|강화|진행|수정|정정|확인)"
    r"[가-힣\s]{0,8}(하겠습니다|겠습니다|토록\s*하겠습니다|도록\s*하겠습니다|해\s*보겠습니다|될\s*수\s*있도록)")


def validate_date_range(date_from: Optional[str], date_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    values = []
    for value in (date_from, date_to):
        if value is None or value == "":
            values.append(None); continue
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}", value):
            raise EvidenceInputError("날짜는 YYYY-MM-DD 또는 YYYYMMDD로 입력하세요.")
        compact = value.replace("-", "")
        try:
            dt.datetime.strptime(compact, "%Y%m%d")
        except ValueError as exc:
            raise EvidenceInputError("존재하지 않는 날짜입니다.") from exc
        values.append(compact)
    if values[0] and values[1] and values[0] > values[1]:
        raise EvidenceInputError("시작일이 종료일보다 늦습니다.")
    return values[0], values[1]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _position(value: Any, name: str, maximum: int = 100_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise EvidenceInputError(f"{name}은 0~{maximum} 정수여야 합니다.")
    return value


def encode_cursor(position: int, parameters: dict, snapshot_id: Optional[str] = None) -> str:
    _position(position, "position")
    payload = {"v": 2, "p": position, "q": _digest(parameters), "s": snapshot_id}
    return "e2." + base64.urlsafe_b64encode(_json(payload).encode()).decode().rstrip("=")


def decode_cursor(cursor: Optional[str], parameters: dict, snapshot_id: Optional[str] = None) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or len(cursor) > 2048 or not re.fullmatch(r"e2\.[A-Za-z0-9_-]+", cursor):
        raise EvidenceInputError("유효하지 않은 이어검색 cursor입니다.")
    try:
        value = json.loads(base64.b64decode(cursor[3:] + "=" * (-len(cursor[3:]) % 4), altchars=b"-_", validate=True))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceInputError("cursor를 해석할 수 없습니다.") from exc
    if not isinstance(value, dict) or set(value) != {"v", "p", "q", "s"} or type(value["v"]) is not int or value["v"] != 2:
        raise EvidenceInputError("지원되지 않는 cursor 버전 또는 형식입니다.")
    if value["q"] != _digest(parameters):
        raise EvidenceInputError("검색 조건이 변경되었습니다. 기존 cursor를 재사용할 수 없습니다.")
    if value["s"] != snapshot_id:
        raise EvidenceInputError("근거 snapshot이 변경되었습니다.")
    return _position(value["p"], "cursor.position")


def read_page(turns: list[dict], *, start_turn: int = 0, start_char: int = 0,
              max_turns: int = 30, max_chars: int = 12000, selected_indices: Optional[list[int]] = None) -> dict:
    """Return lossless sequential pieces; next pointer can stay on the same turn."""
    _position(start_turn, "start_turn", len(turns))
    _position(start_char, "start_char")
    _position(max_turns, "max_turns", 80)
    _position(max_chars, "max_chars", 100000)
    if not max_turns or not max_chars:
        raise EvidenceInputError("max_turns와 max_chars는 1 이상이어야 합니다.")
    chosen = list(range(len(turns))) if selected_indices is None else sorted(set(selected_indices))
    for index in chosen:
        _position(index, "selected_indices", max(0, len(turns) - 1))
    if chosen and not turns:
        raise EvidenceInputError("존재하지 않는 발언 번호입니다.")
    if start_char and (start_turn not in chosen or start_turn == len(turns)):
        raise EvidenceInputError("start_char는 선택된 start_turn의 문자 위치여야 합니다.")
    if start_turn < len(turns) and start_char > len(turns[start_turn]["text"]):
        raise EvidenceInputError("start_char가 발언 길이를 초과했습니다.")
    remaining = [index for index in chosen if index >= start_turn]
    pieces, budget = [], max_chars
    next_turn, next_char = None, None
    for offset, index in enumerate(remaining):
        if len(pieces) >= max_turns or budget == 0:
            next_turn, next_char = index, 0; break
        turn = turns[index]
        begin = start_char if index == start_turn else 0
        end = min(len(turn["text"]), begin + budget)
        piece = copy.deepcopy(turn)
        piece.update({"text": turn["text"][begin:end], "source_char_start": begin, "source_char_end": end,
                      "source_char_total": len(turn["text"]), "is_fragment": begin > 0 or end < len(turn["text"])})
        pieces.append(piece)
        budget -= end - begin
        if end < len(turn["text"]):
            next_turn, next_char = index, end; break
    return {"status": "PARTIAL" if next_turn is not None else ("COMPLETE" if pieces else "EMPTY"),
            "turns": pieces, "next_start_turn": next_turn, "next_start_char": next_char,
            "coverage": {"all_turns": len(turns), "selected_turns": len(chosen), "returned_pieces": len(pieces),
                         "returned_chars": max_chars - budget, "complete_selected_range": next_turn is None,
                         "offset_basis": "parsed_turn_unicode_characters"}}

_META_KEYS = {
    "council_id": ("council_id", "RASMBLY_ID"),
    "council_name": ("council_name", "council", "RASMBLY_NM"),
    "term": ("term", "RASMBLY_NUMPR"),
    "session": ("session", "RASMBLY_SESN"),
    "sitting": ("sitting", "MINTS_ODR"),
    "meeting_date": ("meeting_date", "date", "MTG_DE"),
    "meeting_name": ("meeting_name", "title", "MTGNM"),
    "committee": ("committee", "PRMPST_CMIT_NM"),
    "agenda_title": ("agenda_title", "MTR_SJ"),
}


def canonical_metadata(meta: dict) -> dict:
    out = {}
    for key, alternatives in _META_KEYS.items():
        out[key] = next((str(meta[name]).strip() for name in alternatives if meta.get(name) not in (None, "")), None)
    # Never derive the accounting year from meeting date or current calendar year.
    fiscal = meta.get("fiscal_year")
    if isinstance(fiscal, bool) or (fiscal is not None and not re.fullmatch(r"\d{4}", str(fiscal))):
        raise EvidenceInputError("fiscal_year는 원문에서 확인한 4자리 연도 또는 null이어야 합니다.")
    out["fiscal_year"] = int(fiscal) if fiscal is not None else None
    return out


def parsed_body_hash(turns: list[dict]) -> str:
    return _digest([{"label": normalize_match(t.get("label", "")), "text": normalize_match(t.get("text", "")),
                     "agenda": t.get("agenda", 0)} for t in turns])


def _safe_reference(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if not isinstance(url, str) or len(url) > 8192 or re.search(r"[\x00-\x20\x7f]", url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            return None
        _ = parsed.port
        sensitive = {"apikey", "api_key", "authkey", "servicekey", "access_token", "token", "signature", "x-amz-signature"}
        for name, _value in parse_qsl(parsed.query, keep_blank_values=True):
            if name.lower() in sensitive or (name.lower() == "key" and parsed.hostname == "clik.nanet.go.kr" and parsed.path.startswith("/openapi/")):
                return None  # Credentialed request URLs must never become citations.
    except ValueError:
        return None
    return url


def make_record(meta: dict, turns: list[dict], *, source: str,
                source_kind: str = "OFFICIAL_FETCHED", source_url: Optional[str] = None,
                body_url: Optional[str] = None, source_url_verified: bool = False,
                body_url_verified: bool = False) -> dict:
    """Create an immutable-by-convention evidence record from fetched inputs.

    The caller must supply source_kind truthfully; a user-supplied URL alone is
    never proof the contents were fetched there. Derived viewers remain separate.
    """
    allowed_kinds = {"OFFICIAL_FETCHED", "PUBLIC_API", "OFFICIAL_SITE", "USER_PROVIDED", "SYNTHETIC", "LOCAL_ARCHIVE"}
    if source_kind not in allowed_kinds:
        raise EvidenceInputError("지원되지 않는 source_kind입니다.")
    metadata = canonical_metadata(meta)
    docid = str(meta.get("DOCID") or meta.get("docid") or meta.get("key") or "") or None
    body_sha256 = parsed_body_hash(turns)
    origin = _safe_reference(source_url or meta.get("ORGINL_FILE_URL"))
    fetched = _safe_reference(body_url)
    official = source_kind in {"OFFICIAL_FETCHED", "PUBLIC_API", "OFFICIAL_SITE"}
    provenance = {"source": source, "source_kind": source_kind, "source_url": origin, "body_url": fetched,
                  "source_url_status": "FETCHED" if origin and source_url_verified and official else ("PROVIDED_NOT_FETCHED" if origin else "NOT_AVAILABLE"),
                  "body_url_status": "FETCHED" if fetched and body_url_verified and official else ("PROVIDED_NOT_FETCHED" if fetched else "NOT_AVAILABLE"),
                  "body_sha256": body_sha256, "body_hash_basis": "complete_normalized_parsed_turns",
                  "parser_version": SCHEMA_VERSION, "source_verified": bool(official and body_url_verified and fetched),
                  "limitations": ["발언번호·문자위치는 파싱한 본문 기준이며 원본 PDF 쪽수나 HTML 바이트 위치가 아닙니다.",
                                  "원본 첨부 URL 제공은 해당 첨부의 실제 열람·검증을 의미하지 않습니다."]}
    record_id = "rec_" + _digest({"meta": metadata, "body": body_sha256, "kind": source_kind, "source": source, "docid": docid})[:24]
    return {"record_id": record_id, "docid": docid, "metadata": metadata, "turns": copy.deepcopy(turns),
            "source": source, "source_kind": source_kind, "provenance": provenance, "body_sha256": body_sha256,
            "aliases": [], "parse_status": "PARSED" if turns else "NO_PARSED_TURNS"}


def _meeting_identity(record: dict) -> Optional[tuple]:
    meta = canonical_metadata(record.get("metadata", record.get("meta", {})))
    council = meta.get("council_id") or meta.get("council_name")
    values = [council, meta.get("term"), meta.get("session"), meta.get("sitting"),
              meta.get("meeting_date"), meta.get("meeting_name")]
    if any(v is None or not str(v).strip() for v in values):
        return None
    # Conservative: differing committee / explicit fiscal-year metadata is retained.
    values.extend([meta.get("committee") or "", str(meta.get("fiscal_year") or "")])
    return tuple(normalize_match(v) for v in values)


def dedup_records(records: list[dict]) -> list[dict]:
    """Coalesce only matching complete metadata AND full parsed body.

    Incomplete meeting metadata and differing source kinds cannot be silently
    merged. Every merged identifier/provenance survives in aliases.
    """
    out, lookup = [], {}
    for source_record in records:
        record = copy.deepcopy(source_record)
        turns = record.get("turns", [])
        identity = _meeting_identity(record)
        key = (identity, parsed_body_hash(turns), record.get("source_kind")) if identity and turns else None
        if key is None or key not in lookup:
            record.setdefault("aliases", [])
            out.append(record)
            if key is not None:
                lookup[key] = record
        else:
            canonical = lookup[key]
            aliases = [{"record_id": record.get("record_id"), "docid": record.get("docid"),
                        "source": record.get("source"), "provenance": record.get("provenance", {})}] + record.get("aliases", [])
            existing = {_json(a) for a in canonical["aliases"]}
            for alias in aliases:
                if _json(alias) not in existing:
                    canonical["aliases"].append(alias); existing.add(_json(alias))
            canonical["dedup_basis"] = "COMPLETE_MEETING_METADATA_AND_COMPLETE_PARSED_BODY"
    return out


def turn_evidence(record: dict, turn: dict) -> dict:
    provenance = record.get("provenance", {})
    citation = {"record_id": record["record_id"], "docid": record.get("docid"), "turn_index": turn["idx"],
                "source_url": provenance.get("source_url"), "body_url": provenance.get("body_url"),
                "source_kind": record.get("source_kind"), "body_sha256": record.get("body_sha256"),
                "turn_sha256": _digest({"label": turn["label"], "text": turn["text"]}),
                "locator": "parsed_turn", "char_start": 0, "char_end": len(turn["text"]),
                "fiscal_year": record.get("metadata", {}).get("fiscal_year"),
                "source_url_status": provenance.get("source_url_status"), "body_url_status": provenance.get("body_url_status")}
    return {"turn_index": turn["idx"], "label": turn["label"], "role": turn["role"], "text": turn["text"],
            "agenda": turn.get("agenda", 0), "act": turn.get("act", "other"), "citation": citation}


MODE_ALIASES = {"질의답변": "질의답변", "qa": "질의답변", "발언": "발언", "speech": "발언",
                "약속": "약속", "후속조치": "약속", "commitments": "약속", "5분자유발언": "5분자유발언", "five_minute": "5분자유발언"}


def record_events(record: dict, keyword: str = "", mode: str = "질의답변", answerer: Optional[str] = None) -> list[dict]:
    """Same four search modes regardless of upstream source.

    Outputs preserve verbatim parsed quotes; no factual answer is synthesized.
    Follow-up promises require a linked answer, and never imply implementation.
    """
    if mode not in MODE_ALIASES:
        raise EvidenceInputError("mode는 질의답변·발언·약속·5분자유발언 중 하나여야 합니다.")
    mode = MODE_ALIASES[mode]
    turns = record.get("turns", [])
    events = []
    def append_event(kind, *, q=None, answers=None, speech=None, commitment=None, linkage=None):
        event = {"kind": kind, "record_id": record["record_id"], "docid": record.get("docid"),
                 "metadata": copy.deepcopy(record.get("metadata", {})),
                 "question": turn_evidence(record, q) if q else None,
                 "answers": [turn_evidence(record, a) for a in (answers or [])],
                 "speech": turn_evidence(record, speech) if speech else None, "commitment": commitment,
                 "source_kind": record.get("source_kind"), "provenance": copy.deepcopy(record.get("provenance", {})),
                 "coverage_note": "확인한 본문 범위의 규칙 기반 후보입니다. 전체 의회 자료의 전수 결과나 이행 확인이 아닙니다.",
                 "linkage": linkage}
        event["event_id"] = "evt_" + _digest({"record": record["record_id"], "kind": kind,
                                                "q": q["idx"] if q else None,
                                                "a": [a["idx"] for a in (answers or [])],
                                                "s": speech["idx"] if speech else None,
                                                "c": commitment})[:24]
        events.append(event)
    if mode in ("발언", "5분자유발언"):
        for i, turn in enumerate(turns):
            if not match_text(turn["text"], keyword) or not dept_match(answerer, turn["label"]):
                continue
            if mode == "5분자유발언" and not (turn["role"] == "member" and speech_context(turns, i) == "5분자유발언"):
                continue
            append_event(mode, speech=turn)
        return events
    for pair in build_qa_pairs(turns, keyword):
        if pair["kind"] == "5분자유발언":
            continue
        answers = [a for a in pair["answers"] if dept_match(answerer, a["label"])]
        if answerer and not answers:
            continue
        if mode == "질의답변":
            append_event("질의답변", q=pair["q"], answers=answers,
                         linkage={"status": pair["answer_status"], "basis": pair["link_basis"]})
        else:
            for answer in answers:
                offset = 0
                for sentence in split_sentences(answer["text"]):
                    pos = answer["text"].find(sentence, offset)
                    offset = pos + len(sentence)
                    info = classify_commitment(sentence)
                    if not info:
                        continue
                    info = dict(info, status="EVIDENCE_NOT_VERIFIED", excerpt=sentence, turn_index=answer["idx"],
                                char_start=pos, char_end=offset)
                    append_event("후속조치 후보", q=pair["q"], answers=[answer], commitment=info,
                                 linkage={"status": "CANDIDATE_ONLY", "basis": pair["link_basis"]})
    return events


def evidence_status(*, items: int, attempted: int, succeeded: int, errors: Optional[list] = None,
                    limited: bool = False, body_unavailable: int = 0, parse_failed: int = 0) -> dict:
    """Separate no matches from failed/incomplete acquisition explicitly."""
    for name, value in (("items", items), ("attempted", attempted), ("succeeded", succeeded),
                        ("body_unavailable", body_unavailable), ("parse_failed", parse_failed)):
        _position(value, name)
    if succeeded > attempted or body_unavailable + parse_failed > attempted:
        raise EvidenceInputError("조회 범위 집계가 서로 일치하지 않습니다.")
    errors = errors or []
    unresolved = bool(errors or body_unavailable or parse_failed or succeeded < attempted)
    if unresolved and succeeded == 0:
        status = "ERROR"
    elif unresolved or limited:
        status = "PARTIAL"
    else:
        status = "COMPLETE" if items else "EMPTY"
    return {"status": status,
            "coverage": {"documents_attempted": attempted, "documents_succeeded": succeeded,
                         "body_unavailable": body_unavailable, "parse_failed": parse_failed,
                         "matched_items": items, "limited": bool(limited), "complete_requested_scope": not unresolved and not limited,
                         "is_exhaustive_council_archive": False},
            "errors": copy.deepcopy(errors),
            "interpretation": "미발견은 확인한 범위에 한정되며 조회 실패·본문 미제공은 미발견으로 간주하지 않습니다."}
