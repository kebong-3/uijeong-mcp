"""Explicit flat CSV/XLSX import; no fuzzy auto-mapping, macros, or formulas.
The small stdlib OOXML reader only imports literal flat tables. It does not edit
workbooks or execute formulas. File parsing limits are deliberately conservative.
"""
from pathlib import Path, PurePosixPath
import csv, io, hashlib, json, re, zipfile
import xml.etree.ElementTree as ET
from datetime import date
from .money import BudgetError, won, UNITS

MAX_FILE = 20 * 1024 * 1024
MAX_UNCOMPRESSED = 80 * 1024 * 1024
MAX_ROWS, MAX_COLS, MAX_CELL = 30000, 100, 2000
TEXT_FIELDS = ['project_id','project_name','department','account','budget_code','line_id','row_type']
MONEY_FIELDS = ['budget_amount','available_budget','expenditure','committed_unpaid','carryover_next',
                'subsidy_return','unspent_declared','national','balanced','fund_national','provincial',
                'municipal','other','assessed','collected','writeoffs','unpaid_declared']
REQUIRED_TEXT = ['project_id','project_name','department','account','budget_code']
HEADERS_KO = dict(zip(TEXT_FIELDS + MONEY_FIELDS, [
 '사업코드','사업명','부서','회계','통계목코드','세부행코드','행구분',
 '예산액','예산현액','지출액','미지급지출원인행위액','다음연도이월액','보조금반납금','집행잔액',
 '국고보조금','균특보조금','기금보조금','시도비','시군구비','기타재원',
 '징수결정액','실제수납액','정리보류액','미수납액']))
STAGES = ['본예산','1회추경','2회추경','3회추경','최종예산','결산','집행현황','요구안']
N = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
     'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

def safe_file(root, name):
    root = Path(root).resolve()
    p = Path(name)
    if p.is_absolute() or '..' in p.parts:
        raise BudgetError('허용된 inputs 폴더 아래의 상대경로만 사용하세요.')
    full = (root / p).resolve()
    if not full.is_relative_to(root) or not full.is_file():
        raise BudgetError('허용 입력파일을 찾지 못했습니다.')
    if full.stat().st_size > MAX_FILE:
        raise BudgetError('파일은 20MB 이하여야 합니다.')
    return full

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise BudgetError('외부 엔티티/DTD는 허용하지 않습니다.')
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise BudgetError('XLSX XML 형식 오류') from e

def column_index(cell):
    letters = re.match(r'^([A-Z]+)[1-9]\d*$', cell)
    if not letters:
        raise BudgetError('잘못된 셀 좌표')
    result = 0
    for c in letters.group(1):
        result = result*26+ord(c)-64
    if result > MAX_COLS:
        raise BudgetError('100열 초과: 필요한 표만 별도 저장하세요.')
    return result-1

def read_xlsx(data, sheet_name):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise BudgetError('손상된 XLSX') from e
    with z:
        entries = z.infolist()
        if len(entries)>3000 or sum(e.file_size for e in entries)>MAX_UNCOMPRESSED:
            raise BudgetError('압축 해제 용량/파일 개수 제한 초과')
        for e in entries:
            if '..' in PurePosixPath(e.filename).parts or e.filename.startswith('/'):
                raise BudgetError('잘못된 XLSX 내부 경로')
            if any(x in e.filename.lower() for x in ('vbaproject','externallink')):
                raise BudgetError('매크로/외부연결 포함 파일은 값만 저장한 XLSX를 사용하세요.')
        if len(set(z.namelist())) != len(entries):
            raise BudgetError('중복된 XLSX 내부 파일명')
        wb = xml(z.read('xl/workbook.xml'))
        rel = xml(z.read('xl/_rels/workbook.xml.rels'))
        targets = {x.attrib.get('Id'): x.attrib.get('Target') for x in rel}
        sheets = []
        target = None
        for s in wb.findall('s:sheets/s:sheet', N):
            sheets.append(s.attrib['name'])
            if s.attrib['name'] == sheet_name:
                if s.attrib.get('state', 'visible') != 'visible':
                    raise BudgetError('숨김 시트는 읽지 않습니다.')
                target = targets.get(s.attrib.get('{'+N['r']+'}id'))
        if not target:
            raise BudgetError('시트명을 정확하게 지정하세요: '+', '.join(sheets))
        target = target.lstrip('/') if target.startswith('/') else 'xl/'+target
        if '..' in PurePosixPath(target).parts or not target.startswith('xl/'):
            raise BudgetError('외부 시트 대상은 허용하지 않습니다.')
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(x.itertext()) for x in xml(z.read('xl/sharedStrings.xml')).findall('s:si', N)]
        ws = xml(z.read(target))
        if ws.find('s:mergeCells',N) is not None:
            raise BudgetError('병합된 시트는 행별 정형표로 정리한 뒤 가져오세요.')
        if any(c.attrib.get('hidden')=='1' for c in ws.findall('s:cols/s:col',N)):
            raise BudgetError('숨김 열 포함: 숨김을 해제하거나 해당 표를 별도 저장하세요.')
        rows=[];seen_row_nums=set()
        for rn, row in enumerate(ws.findall('s:sheetData/s:row',N),1):
            row_num=int(row.attrib.get('r',rn))
            if row_num < 1 or row_num in seen_row_nums:
                raise BudgetError('중복/잘못된 XLSX 행번호')
            seen_row_nums.add(row_num)
            if row_num>MAX_ROWS+100 or len(rows)>MAX_ROWS+100:
                raise BudgetError('행수 제한 초과')
            if row.attrib.get('hidden')=='1':
                raise BudgetError('숨김 행은 묵시적으로 포함/제외하지 않습니다.')
            cells={}
            for c in row.findall('s:c',N):
                idx=column_index(c.attrib['r'])
                if idx in cells or int(re.search(r'\d+$',c.attrib['r']).group()) != row_num:
                    raise BudgetError('중복 셀 또는 행·셀 좌표 불일치')
                if c.find('s:f',N) is not None:
                    raise BudgetError('수식 발견 '+c.attrib['r']+': 재계산 후 값만 붙여넣은 사본을 사용하세요.')
                typ=c.attrib.get('t','n')
                if typ=='e':
                    raise BudgetError('엑셀 오류 셀: '+c.attrib['r'])
                v=c.findtext('s:v',None,N)
                if typ=='s':
                    try: v=strings[int(v)]
                    except (ValueError,IndexError,TypeError) as e: raise BudgetError('문자열 인덱스 오류') from e
                elif typ=='inlineStr':
                    v=''.join(c.find('s:is',N).itertext()) if c.find('s:is',N) is not None else ''
                elif typ=='b':
                    v='TRUE' if v=='1' else 'FALSE'
                if v is not None and len(v)>MAX_CELL:
                    raise BudgetError('셀 문자열 길이 초과')
                cells[idx]=v
            if cells:
                vals=[cells.get(i) for i in range(max(cells)+1)]
                rows.append((row_num,vals))
        return rows

def read_table(path, sheet_name='데이터', encoding='utf-8-sig'):
    path=Path(path)
    if path.stat().st_size>MAX_FILE:
        raise BudgetError('파일 크기 제한 초과')
    data=path.read_bytes()
    if path.suffix.lower()=='.xlsx':
        rows=read_xlsx(data,sheet_name)
    elif path.suffix.lower()=='.csv':
        if encoding not in ['utf-8-sig','cp949']:
            raise BudgetError('지원 인코딩: utf-8-sig, cp949')
        try: text=data.decode(encoding)
        except UnicodeError as e: raise BudgetError('인코딩을 확인하세요.') from e
        rows=[]
        try:
            for i,row in enumerate(csv.reader(io.StringIO(text)),1):
                if i>MAX_ROWS+100 or len(row)>MAX_COLS or any(len(c)>MAX_CELL for c in row):
                    raise BudgetError('행/열/셀 길이 제한 초과')
                rows.append((i,row))
        except csv.Error as e:
            raise BudgetError('CSV 형식 오류') from e
    else:
        raise BudgetError('초기판은 정형 CSV/XLSX만 지원합니다. PDF/HWP/HWPX 자동추출은 미구현입니다.')
    return rows,hashlib.sha256(data).hexdigest()

def validate_spec(spec):
    required=['name','authority','year','stage','basis','unit','kind','coverage','as_of']
    if any(k not in spec for k in required):
        raise BudgetError('필수 자료정보: '+', '.join(required))
    if not isinstance(spec['year'],int) or isinstance(spec['year'],bool) or not 1990<=spec['year']<=2100:
        raise BudgetError('회계연도 오류')
    if spec['stage'] not in STAGES or spec['basis'] not in ('누계','증감'):
        raise BudgetError('편성단계/누계·증감 기준 오류')
    if spec['unit'] not in UNITS or spec['kind'] not in ('세입','세출') or spec['coverage'] not in ('전체','부분'):
        raise BudgetError('단위/세입세출/조회범위 오류')
    try: date.fromisoformat(spec['as_of'])
    except (ValueError,TypeError) as e: raise BudgetError('자료기준일은 YYYY-MM-DD') from e
    for k in ('name','authority'):
        if not isinstance(spec[k],str) or not spec[k].strip() or len(spec[k])>200:
            raise BudgetError(k+' 값 오류')
    if not isinstance(spec.get('header_row',1),int) or isinstance(spec.get('header_row',1),bool) or not 1<=spec.get('header_row',1)<=100:
        raise BudgetError('머리글 행은 1~100')
    mapping=spec.get('mapping')
    if mapping is not None:
        if not isinstance(mapping,dict) or any(k not in TEXT_FIELDS+MONEY_FIELDS for k in mapping):
            raise BudgetError('mapping은 표준필드:실제열제목의 객체입니다.')
        if any(not isinstance(v,str) or not v.strip() or len(v)>MAX_CELL for v in mapping.values()):
            raise BudgetError('매핑 열제목은 비어있지 않은 문자열이어야 합니다.')
        if len(set(mapping.values()))!=len(mapping.values()):
            raise BudgetError('같은 열을 둘 이상의 표준필드로 중복 연결할 수 없습니다.')
    return spec

def key(row):
    return (row['account'],row['project_id'],row['budget_code'],row.get('line_id',''))

def load_dataset(path,spec):
    validate_spec(spec)
    sheet=spec.get('sheet','데이터')
    records,digest=read_table(path,sheet,spec.get('encoding','utf-8-sig'))
    hrow=spec.get('header_row',1)
    headers=next((r for n,r in records if n==hrow),None)
    if headers is None:
        raise BudgetError('머리글 행 없음')
    headers=[str(h).strip() if h is not None else '' for h in headers]
    named=[h for h in headers if h]
    if len(named)!=len(set(named)):
        raise BudgetError('중복 열 제목: 명시적으로 구분하세요.')
    mapping=spec.get('mapping') or {f:f for f in TEXT_FIELDS+MONEY_FIELDS if f in headers}
    if any(f not in mapping for f in REQUIRED_TEXT):
        raise BudgetError('사업코드·사업명·부서·회계·통계목코드 매핑이 필요합니다.')
    if any(h not in headers for h in mapping.values()):
        raise BudgetError('매핑한 열을 찾지 못했습니다.')
    positions={f:headers.index(h) for f,h in mapping.items()}
    rows=[]; seen=set(); totals=0
    for rn,vals in records:
        if rn<=hrow or all(v in ('',None) for v in vals):
            continue
        if len(rows)>=MAX_ROWS:
            raise BudgetError('가져올 수 있는 행수 초과')
        raw={f:vals[i] if i<len(vals) else None for f,i in positions.items()}
        row={f:str(raw.get(f) or '').strip() for f in TEXT_FIELDS}
        row['row_type']=row['row_type'] or 'detail'
        if row['row_type'] not in ('detail','total','subtotal'):
            raise BudgetError(f'{rn}행: 행구분은 detail/total/subtotal')
        for f in MONEY_FIELDS:
            try: row[f]=won(raw.get(f),spec['unit'])
            except BudgetError as e: raise BudgetError(f'{rn}행 {f}: {e}') from e
        if row['row_type']=='detail':
            if any(not row[f] for f in REQUIRED_TEXT):
                raise BudgetError(f'{rn}행: 사업·회계·부서·통계목 식별값 누락')
            if key(row) in seen:
                raise BudgetError(f'{rn}행: 동일 사업/회계/통계목/세부행 중복. 세부행코드를 지정하세요.')
            seen.add(key(row))
        if row['row_type']=='total': totals+=1
        if totals>1:
            raise BudgetError('총계는 1개만 허용합니다. 여러 표는 별도 자료로 나누세요.')
        row['source']={'file':Path(path).name,'sheet':sheet if Path(path).suffix.lower()=='.xlsx' else 'CSV',
                       'row':rn,'sha256':digest,'column_mapping':mapping.copy(), 'input_unit':spec['unit']}
        rows.append(row)
    if not any(r['row_type']=='detail' for r in rows):
        raise BudgetError('세부행이 없습니다.')
    clean_spec={k:v for k,v in spec.items() if k not in ('mapping',)}
    clean_spec['mapping']=mapping
    ident=hashlib.sha256((digest+json.dumps(clean_spec,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()[:24]
    return {'dataset_id':ident,'meta':clean_spec,'file_sha256':digest,'rows':rows,
            'input_source':'USER_FILE','external_upload':False,
            'warnings':['행구분 subtotal은 합산에서 제외하며 하위 계층 검산은 초기판에서 하지 않습니다.'] if any(r['row_type']=='subtotal' for r in rows) else []}

