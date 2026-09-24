"""Configuration scaffold for 지방재정365 context.

The public dataset page exposes the service-key application but the concrete
request endpoint/parameter contract can vary by approved OpenAPI. We therefore
register the credential/endpoint slots now and refuse to guess request
parameters. After the operator receives the approved endpoint, the adapter can
be activated without changing the public MCP surface.
"""
from __future__ import annotations

import os
from typing import Any

DATASET_URL = "https://www.data.go.kr/data/15138857/openapi.do"
KEY_ENV = "FINANCE365_SERVICE_KEY"
URL_ENV = "FINANCE365_API_URL"


def configuration() -> dict[str, Any]:
    key = os.environ.get(KEY_ENV, "").strip()
    url = os.environ.get(URL_ENV, "").strip()
    return {
        "configured": bool(key and url),
        "service_key_configured": bool(key),
        "api_url_configured": bool(url),
        "env": {
            "service_key": KEY_ENV,
            "api_url": URL_ENV,
        },
        "dataset_url": DATASET_URL,
        "note": (
            "공공데이터포털에서 '행정안전부_지방재정365_세부사업별 세출현황' 활용신청 후 "
            "발급된 서비스키와 승인 화면의 실제 요청 URL을 입력합니다."
        ),
    }


async def context(topic: str, council: str = "", fiscal_year: int | None = None,
                  limit: int = 20) -> dict[str, Any]:
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
        return {"status":"INVALID_INPUT","message":"topic은 1~200자 문자열이어야 합니다."}
    cfg = configuration()
    if not cfg["configured"]:
        return {
            "status":"NOT_CONFIGURED",
            "message":"지방재정365 API는 Render 환경변수만 미리 준비되어 있고 아직 인증값/요청 URL이 설정되지 않았습니다.",
            "configuration":cfg,
            "query":{"topic":topic,"council":council or None,"fiscal_year":fiscal_year,"limit":limit},
            "items":[],
            "limitations":[
                "재정 API가 미설정이어도 CLIK·법령·조례 검색은 정상 작동합니다.",
                "API 상세 계약을 추측해 호출하지 않습니다. 활용신청 후 실제 요청 URL을 확인한 뒤 활성화해야 합니다.",
            ],
        }
    return {
        "status":"PENDING_ENDPOINT_CONTRACT",
        "message":"서비스키와 URL은 설정됐지만, 승인받은 API의 실제 요청변수 계약을 확인하기 전에는 자동 호출하지 않습니다.",
        "configuration":cfg,
        "query":{"topic":topic,"council":council or None,"fiscal_year":fiscal_year,"limit":limit},
        "items":[],
        "next_step":"승인 화면의 요청변수/샘플 URL을 확인해 Finance365Adapter 매핑을 확정하세요.",
    }
