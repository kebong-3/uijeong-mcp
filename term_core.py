"""Existing v2.3.1 Korean term extraction, isolated for offline testing."""
import re

_JOSA = sorted(["으로부터", "에서부터", "이라든지", "에서는", "으로는", "에게는", "까지는", "부터는", "이라는", "라는", "에서",
                "으로", "에게", "께서", "까지", "부터", "보다", "처럼", "마다", "이나", "이랑", "하고", "과는", "와는", "에는",
                "에도", "만큼", "은", "는", "이", "가", "을", "를", "에", "의", "로", "와", "과", "도", "만", "들"], key=len, reverse=True)
_STOP = set("""의원 위원 위원님 의원님 위원장 위원장님 의장 의장님 구청장 구청장님 과장 과장님 국장 국장님 실장 팀장 동장 집행부
말씀 부분 생각 저희 우리 지금 관련 그런 이런 저런 그거 이거 저거 그래서 그리고 그러면 그런데 하지만 그러니까 때문 정도
경우 문제 내용 사항 사업 계획 추진 진행 현재 올해 작년 내년 확인 필요 검토 답변 질의 질문 요청 부탁 감사 수고 여러분
어떻게 어떤 무엇 얼마 이렇게 그렇게 저렇게 다시 계속 조금 많이 너무 아주 정말 혹시 일단 먼저 다음 이상 이하 대해 대한
통해 위해 따라 관해 등등 함께 모두 각각 전체 일부 역시 또한 특히 바로 가장 매우 여기 거기 저기 자료 보고 설명 방안 부서 담당 행정 서구 전남광주통합특별시 광주광역시 광주 제가
했는데 하는데 있는데 없는데 거든요 있습니다 없습니다 합니다 됩니다 같습니다 드립니다 바랍니다 하겠습니다 주시기 해주시기
그게 이게 저게 것이 것을 것은 거는 거를 건데 뭐냐 그러 이제 좀 네 예 아니 아니요 위원회 회의 안건 의사일정""".split())
_VERB_END = re.compile(r"(습니다|십니까|니까|니다|는데|세요|어요|아요|해서|하고|했고|하며|하면|하는|했던|되는|되어|된다|한다|했다|이다|였다|지만|는지|거든|잖아|네요|시오|십시오|주고|봐|줘|죠|까|요|다|게|며|고|서|면|던|인|한|된|할|될|있는|없는|같은)$")


def extract_terms(text: str) -> list[str]:
    out = []
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        if tok.isdigit() or (_VERB_END.search(tok) and len(tok) >= 3):
            continue
        for _ in range(2):
            for j in _JOSA:
                if tok.endswith(j) and len(tok) - len(j) >= 2:
                    tok = tok[: -len(j)]
                    break
        if _VERB_END.search(tok) and len(tok) >= 3:
            continue
        if len(tok) < 2 or tok in _STOP or re.fullmatch(r"\d+[가-힣]?", tok):
            continue
        out.append(tok)
    return out

