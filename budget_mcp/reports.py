"""Auditable value exports; no source overwrite and no CSV formula execution."""
import csv, io, json, html
from .money import display, BudgetError

STYLE='''body{margin:0;background:#f3f5f7;font-family:Arial,"Malgun Gothic",sans-serif;color:#182838}main{max-width:1180px;margin:36px auto;background:white;padding:36px;border-radius:12px}h1{font-size:27px}h2{font-size:20px;margin-top:30px}p{line-height:1.8}.notice{padding:18px;background:#eef4f8;border-left:4px solid #225d86}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#183c55;color:white;padding:12px;text-align:left}td{border-bottom:1px solid #dee5ea;padding:10px;vertical-align:top;word-break:break-word}tr:nth-child(even){background:#f7f9fb}pre{white-space:pre-wrap;word-break:break-word;font-size:12px;background:#f5f7f9;padding:16px}footer{margin-top:30px;color:#526675;font-size:13px}'''

def rendered_cell(key,value,unit,digits):
    if key.endswith('_won') and value is not None and isinstance(value,int):return display(value,unit,digits)
    if value is None:return '미확인'
    if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)

def export_report(store,report_id,fmt='html',unit='백만원',digits=0):
    if fmt not in ('json','csv','html'):raise BudgetError('출력형식은 json/csv/html')
    display(0,unit,digits)
    report=store.get('reports',report_id)
    target=store.outputs/(report_id+'.'+fmt)
    if target.is_symlink():raise BudgetError('출력 경로 오류')
    if fmt=='json':text=json.dumps(report,ensure_ascii=False,indent=2)
    else:
        items=report.get('items',[])
        columns=list(dict.fromkeys(k for row in items for k in row))
        rows=[[rendered_cell(k,r.get(k),unit,digits) for k in columns] for r in items]
        labels=[k.replace('_won','_'+unit) for k in columns]
        if fmt=='csv':
            buf=io.StringIO();w=csv.writer(buf)
            w.writerow(labels)
            for r in rows:
                # Prefix potentially executable text; negative numeric text is also
                # deliberately quoted to prioritize a safe value-only export.
                w.writerow([("'"+x) if x.lstrip().startswith(('=','+','-','@')) or x.startswith(('\t','\r')) else x for x in r])
            text=buf.getvalue()
        else:
            esc=html.escape
            head=''.join('<th>'+esc(k)+'</th>' for k in labels)
            body=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)
            summary={k:v for k,v in report.items() if k not in ('items','excluded')}
            text=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(report['analysis'])}</title><style>{STYLE}</style><main><h1>{esc(report['analysis'])}</h1><p class="notice">독립형 지방예산 MCP / 표시 금액단위: {esc(unit)} · 소수 {digits}자리 / 내부 계산·검산은 원 단위<br>표시금액을 각각 반올림한 합과 원 단위 총계의 반올림값은 다를 수 있습니다.</p><h2>계산기준·확인사항</h2><pre>{esc(json.dumps(summary,ensure_ascii=False,indent=2))}</pre><h2>결과표</h2><div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div><h2>별도 제외·미확인 항목</h2><pre>{esc(json.dumps(report.get('excluded',[]),ensure_ascii=False,indent=2))}</pre><footer>report_id: {esc(report_id)} · 입력자료에 대한 산술·자료 검토 결과이며 지출 적법성 또는 예산 확정을 대신하지 않습니다.</footer></main></html>'''
    with target.open('w',encoding='utf-8-sig' if fmt=='csv' else 'utf-8',newline='') as f:f.write(text)
    return {'relative_path':'outputs/'+target.name,'format':fmt,'display_unit':unit,'digits':digits,
            'rows':len(report.get('items',[])),'source_overwritten':False,'report_id':report_id}

