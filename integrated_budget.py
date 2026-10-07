"""Stateless budget adapters registered on the shared council MCP transport."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import Any, Literal

import anyio
from mcp.types import ToolAnnotations
from budget_mcp.api import redact
from budget_mcp.extended import IntegratedService
from budget_mcp.extra_tools import available_tools
from budget_mcp.money import BudgetError
from budget_mcp.tools import validate_schema

REGISTRY = {t['name']: t for t in available_tools(True)}
OPERATIONS = ('cost', 'settlement', 'change', 'matching_funds', 'lifecycle_cost',
              'variance_drivers', 'calculate_unit_cost', 'adjust_inflation', 'execution_plan')
Operation = Literal['cost', 'settlement', 'change', 'matching_funds', 'lifecycle_cost',
                    'variance_drivers', 'calculate_unit_cost', 'adjust_inflation', 'execution_plan']
TOOL_NAMES = (
    "budget_api_catalog", "budget_api_status", "budget_fetch_api",
    "budget_search_similar_projects", "budget_calculation_schema", "budget_calculate",
    "budget_review_project", "budget_checklist",
)
MAX_OUTPUT_BYTES = 100_000

@lru_cache(maxsize=1)
def service():
    # Public mode never creates Store, datasets, or filesystem workspaces.
    return IntegratedService(public=True)


def invoke(name: str, arguments: dict[str, Any]) -> dict:
    spec = REGISTRY.get(name)
    if spec is None:
        return {'status': 'INVALID_INPUT', 'message': '공개 예산 도구가 아닙니다.'}
    try:
        validate_schema(arguments, spec['inputSchema'])
        result = redact(getattr(service(), spec['method'])(**arguments))
        if name == 'budget_api_status':
            checks = result.get('last_checks') or {}
            result['check_state'] = 'CHECKS_RECORDED' if checks else 'NO_CHECK_SINCE_RESTART'
            result['check_state_note'] = '점검 기록 없음은 연결 실패가 아닙니다. 설정과 실제 조회를 구분합니다.'
        if result.get('api_id') == 'lofin_projects':
            from budget_evidence import fiscal_basis
            params = result.get('public_params', {})
            result['budget_basis'] = fiscal_basis('current', str(params.get('exe_ymd', '')))
            result['answer_guidance'] = ['예산현액·지출액을 본예산·예산안·확정 결산으로 표시하지 마세요.',
                '일반 사업 검색은 council_finance_context로 날짜·사업명 변형을 보정하세요.',
                '수치 뒤에 공식 자료 확인 링크와 실제 조회조건을 표시하세요.']
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_OUTPUT_BYTES:
            return {'status': 'OUTPUT_LIMIT', 'message': '응답이 큽니다. 페이지 크기나 대상 수를 줄이세요.',
                    'note': '반환되지 않은 항목은 확인되지 않았습니다.'}
        return result
    except BudgetError as exc:
        return {'status': 'INVALID_INPUT_OR_PROCESSING_ERROR', 'message': redact(str(exc)),
                'note': '오류를 자료 없음이나 0원으로 해석하지 마세요.'}
    except Exception:
        return {'status': 'ERROR', 'message': '예산 처리 실패. 자료 없음이나 0원으로 해석하지 마세요.'}


async def call(name, arguments):
    try:
        with anyio.fail_after(25):
            return await anyio.to_thread.run_sync(lambda: invoke(name, arguments), abandon_on_cancel=True)
    except TimeoutError:
        return {"status": "TIMEOUT", "message": "예산 조회 제한시간 초과. 자료 없음으로 해석하지 마세요."}


def register(mcp):
    local = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    remote = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

    @mcp.tool(annotations=local)
    async def budget_api_catalog(query: str = '') -> dict:
        """공식 재정·조달·통계 API의 ID, 필수 변수, 단위·출처를 조회. 외부 조회 전 필요 API만 검색."""
        return await call('budget_api_catalog', {'query': query})

    @mcp.tool(annotations=local)
    async def budget_api_status() -> dict:
        """예산 API 키 설정 여부와 실제 응답 확인 상태. 키 존재는 연결 성공을 뜻하지 않음."""
        return await call('budget_api_status', {})

    @mcp.tool(annotations=remote)
    async def budget_fetch_api(api_id: str, params: dict[str, Any], page: int = 1, page_size: int = 20) -> dict:
        """카탈로그의 공식 API 한 페이지 조회. ERROR/EMPTY/PAGE_ONLY 구분; 연도·단위·조회범위 보존."""
        return await call('budget_fetch_api', dict(api_id=api_id, params=params, page=page, page_size=page_size, use_sample=False))

    @mcp.tool(annotations=remote)
    async def budget_search_similar_projects(query: str, fiscal_year: int, execution_date: str,
                                             local_gov_code: str = '', region_code: str = '',
                                             page: int = 1, page_size: int = 20) -> dict:
        """지방재정365 사업명 후보 조회. 회계연도와 집행기준일 YYYYMMDD 필수. 명칭 일치만으로 동일사업 확정 금지."""
        return await call('budget_search_similar_projects', dict(query=query, fiscal_year=fiscal_year,
                          execution_date=execution_date, local_gov_code=local_gov_code, region_code=region_code,
                          page=page, page_size=page_size, use_sample=False))

    @mcp.tool(annotations=local)
    async def budget_calculation_schema(operation: Operation) -> dict:
        """선택한 예산 계산의 정확한 입력항목 확인. 금액은 숫자 문자열, 단위·산출근거를 명시."""
        if operation not in OPERATIONS:
            return {'status': 'INVALID_INPUT', 'operations': list(OPERATIONS)}
        spec = REGISTRY['budget_' + operation]
        return {'operation': operation, 'description': spec['description'], 'arguments_schema': copy.deepcopy(spec['inputSchema'])}

    @mcp.tool(annotations=local)
    async def budget_calculate(operation: Operation, arguments: dict[str, Any]) -> dict:
        """산출·결산·증감·재원분담·다년도비용·단가비교·물가환산·집행계획 검산. schema로 입력 확인; 공란≠0."""
        if operation not in OPERATIONS:
            return {'status': 'INVALID_INPUT', 'operations': list(OPERATIONS)}
        return await call('budget_' + operation, arguments)

    @mcp.tool(annotations=local)
    async def budget_review_project(title: str, year: int, components: list[dict[str, Any]],
                                    topic: str = '일반', unit: str = '원', context: dict[str, Any] | None = None) -> dict:
        """신규사업 산출안 검산. components: name,basis,unit_price,quantity[,count,periods]. 규칙 기반 검토이며 승인 아님."""
        arguments = dict(title=title, year=year, components=components, topic=topic, unit=unit)
        if context is not None:
            arguments['context'] = context
        return await call('budget_review_project', arguments)

    @mcp.tool(annotations=local)
    async def budget_checklist(topic: str, year: int) -> dict:
        """예산 사전절차 확인질문. topic=일반/보조금/시설/위탁/인건비/행사/기금. 법률상 의무 확정 아님."""
        return await call('budget_checklist', {'topic': topic, 'year': year})
