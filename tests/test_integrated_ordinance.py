import asyncio
import pytest
import integrated_ordinance as mod
from jachi.models import Document, Article, DocumentRef, ReviewInput, ChangeOperation
from jachi.analysis import evidence_index

class Registry:
    def __init__(self): self.tools={}
    def tool(self,**metadata):
        def decorator(fn): self.tools[metadata['name']]=fn; return fn
        return decorator

@pytest.fixture
def functions():
    server=Registry();mod.register(server);return server.tools

@pytest.fixture
def document():
    return Document(kind='ordinance',document_id='123',title='시험 조례',jurisdiction='가상시',
        source_state='fixture',version_scope='current',effective_date='20250101',
        articles=[Article(key=str(i),label=f'제{i}조',text=f'지원 {i}') for i in range(1,12)])

@pytest.fixture
def mock_client(monkeypatch,document):
    class Client:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get_document(self,ref): return document
    monkeypatch.setattr(mod,'LawClient',Client)

@pytest.mark.anyio
async def test_paging_preserves_original_evidence_identity(functions,mock_client,document):
    result=await functions['ordinance_get_document'](DocumentRef(document_id='123'),offset=2,limit=2)
    assert result['coverage']['next_offset']==4
    assert result['summary']['content_hash']==document.content_hash
    assert len(result['evidence'])==2
    all_evidence=evidence_index([document])
    assert all(all_evidence[k]==v for k,v in result['evidence'].items())

@pytest.mark.anyio
async def test_timeout_is_unavailable(monkeypatch,mock_client):
    monkeypatch.setattr(mod,'TIMEOUT_SECONDS',.01)
    async def stalled(c): await asyncio.sleep(1)
    result=await mod._run(stalled)
    assert result['status']=='unavailable' and result['code']=='deadline_exceeded'
    assert 'results' not in result

@pytest.mark.anyio
async def test_exception_does_not_leak_secret(mock_client):
    async def broken(c): raise ValueError('secret-auth-value')
    result=await mod._run(broken)
    assert 'secret-auth-value' not in str(result)

@pytest.mark.anyio
async def test_external_llm_request_rejected(functions,mock_client):
    params=ReviewInput(project='조례 검토',jurisdiction='가상시',reasoning='gemini',allow_external_llm=True)
    result=await functions['ordinance_review_project'](params)
    assert result['status']=='unavailable'

@pytest.mark.anyio
async def test_drafting_hash_mismatch_blocks(functions,mock_client):
    result=await functions['ordinance_draft_amendment'](DocumentRef(document_id='123'),
        [ChangeOperation(operation='replace_article',article='제1조',expected_text='지원 1',new_text='지원 2',reason='검토')],
        expected_hash='wrong')
    assert result['status'] != 'completed'
    assert '일부개정조례안' not in str(result)

def test_all_tools_registered(functions):
    assert set(functions)==set(mod.TOOL_NAMES)

@pytest.fixture
def anyio_backend(): return "asyncio"

@pytest.mark.anyio
async def test_search_can_continue_without_losing_scanned_matches(functions,monkeypatch):
    class Client:
        def __init__(self,*a,**kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def search(self,*a,**kw): return {'results':[{'document_id':str(i)} for i in range(23)],'coverage':{'next_page':2}}
    monkeypatch.setattr(mod,'LawClient',Client)
    first=await functions['ordinance_search']('시험',limit=10)
    second=await functions['ordinance_search']('시험',limit=10,offset=first['next_offset'])
    third=await functions['ordinance_search']('시험',limit=10,offset=second['next_offset'])
    assert len(first['results']+second['results']+third['results'])==23
    assert third['next_offset'] is None and third['coverage']['next_page']==2

@pytest.mark.anyio
async def test_different_identity_version_comparison_refused(functions,monkeypatch,document):
    class Client:
        def __init__(self,*a,**kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def get_document(self,ref): return document.model_copy(update={'document_id':ref.document_id})
    monkeypatch.setattr(mod,'LawClient',Client)
    result=await functions['ordinance_diff_versions'](DocumentRef(document_id='123'),DocumentRef(document_id='456'))
    assert result['status']=='unavailable' and result['code']=='invalid_input'

@pytest.mark.anyio
async def test_comparison_law_as_ordinance_refused(functions,mock_client):
    result=await functions['ordinance_compare'](DocumentRef(kind='law',document_id='123'),[DocumentRef(document_id='456')])
    assert result['status']=='unavailable'

@pytest.mark.anyio
async def test_provided_document_official_url_does_not_make_official(functions):
    from jachi.models import UserText
    params=ReviewInput(project='지원 사업 검토',jurisdiction='가상시',auto_search=False,
        provided_documents=[UserText(title='가상 지원 조례안',text='제1조 지원할 수 있다.',jurisdiction='가상시',source_url='https://www.law.go.kr')])
    result=await functions['ordinance_review_project'](params)
    assert result['privacy']['external_llm_requested'] is False
    assert result['usage']['llm_calls']==0
    assert all(d['source_state']=='user_provided' for d in result['documents'])
    assert result['coverage']['baseline_confirmed'] is False
