"""Exact, auditable arithmetic. Blank is unknown, never zero."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

UNITS = {'원': Decimal(1), '천원': Decimal(1000), '백만원': Decimal(1000000), '억원': Decimal(100000000)}
MAX_WON = Decimal('10000000000000000')
class BudgetError(ValueError):
    pass

def dec(value, *, required=True):
    if value is None or (isinstance(value, str) and value.strip() in ('', '-', '—', '미확인')):
        if required:
            raise BudgetError('금액/수치 누락: 공란을 0으로 보정하지 않습니다.')
        return None
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        raise BudgetError('숫자 또는 숫자 문자열을 입력하세요.')
    text = str(value).strip()
    if len(text) > 70:
        raise BudgetError('수치가 지나치게 깁니다.')
    if text.startswith(('△', '▲')):
        text = '-' + text[1:].strip()
    elif text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1].strip()
    # Group separators must be valid; never silently turn 1,5 into 15.
    if ',' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?', text):
            raise BudgetError('쉼표 구분 형식 오류: ' + text)
        text = text.replace(',', '')
    if not re.fullmatch(r'[+-]?\d+(\.\d+)?', text):
        raise BudgetError('지원하지 않는 숫자 표기: ' + text)
    try:
        d = Decimal(text)
    except InvalidOperation as e:
        raise BudgetError('숫자 형식 오류') from e
    if not d.is_finite() or abs(d) > MAX_WON:
        raise BudgetError('수치 허용 범위를 벗어났습니다.')
    return d

def won(value, unit='원'):
    if unit not in UNITS:
        raise BudgetError('금액단위를 원/천원/백만원/억원 중 명시하세요.')
    d = dec(value, required=False)
    if d is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        result = d * UNITS[unit]
    if abs(result) > MAX_WON or result != result.to_integral_value():
        raise BudgetError('원 미만 정밀도 또는 허용금액 초과: 명시적 반올림 후 입력하세요.')
    return int(result)

def exact_sum(values):
    values = list(values)
    missing = sum(v is None for v in values)
    known = sum(v for v in values if v is not None)
    return {'value_won': None if missing else known, 'known_subtotal_won': known,
            'missing_count': missing, 'count': len(values)}

def pct(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        return format((Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f')

def variance(before, after):
    if before is None or after is None:
        return {'before_won': before, 'after_won': after, 'delta_won': None,
                'rate_pct': None, 'rate_status': 'MISSING_BASE_OR_CURRENT'}
    rate_status = 'NORMAL'
    rate = pct(after - before, before)
    if before == 0:
        rate_status = 'BOTH_ZERO' if after == 0 else 'ZERO_BASE_NOT_COMPUTABLE'
        rate = None
    elif before < 0 or after < 0:
        rate_status = 'NEGATIVE_OR_SIGN_CHANGE_REVIEW'
        rate = None
    return {'before_won': before, 'after_won': after, 'delta_won': after-before,
            'rate_pct': rate, 'rate_status': rate_status}

def display(value, unit='백만원', digits=0):
    if unit not in UNITS or not isinstance(digits, int) or not 0 <= digits <= 6:
        raise BudgetError('표시 단위/자릿수 오류')
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        d = (Decimal(value) / UNITS[unit]).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return format(d, 'f')

