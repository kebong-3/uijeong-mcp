#!/usr/bin/env python3
"""AST source signatures, NOT an executed MCP SDK tools/list export."""
import ast
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def build(root=ROOT):
    funcs={}; names={}; legacy_full_tools=set()
    for filename in ('uijeong_mcp.py','service_v2.py','workbench_tools.py','response_tools.py',
                     'response_guidance.py','council_extensions.py','council_v29.py','v3_reliability.py',
                     'openai_compat.py','integrated_budget.py','integrated_ordinance.py','integrated_workflow.py'):
        tree=ast.parse((root/filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and (node.name.startswith(('council_','seogu_council_','budget_','ordinance_','local_')) or node.name in {'search','fetch'}):
                funcs[node.name]=node
                if filename in ('uijeong_mcp.py','service_v2.py','workbench_tools.py','response_tools.py') and node.name.startswith(('council_','seogu_council_')):
                    legacy_full_tools.add(node.name)
        if filename=='uijeong_mcp.py':
            for node in tree.body:
                if isinstance(node,ast.Assign) and isinstance(node.value,ast.Set):
                    for target in node.targets:
                        if isinstance(target,ast.Name) and target.id.endswith('_TOOLS'):
                            names[target.id]=set(ast.literal_eval(node.value))
    core=names['CORE_TOOLS'];work=core|names['WORKBENCH_TOOLS']|names['DEPARTMENT_TOOLS']
    lite=names['LITE_TOOLS']|work|{'council_period_review','council_data_sources'}
    definitions=[]
    for name,node in sorted(funcs.items()):
        defaults=[None]*(len(node.args.args)-len(node.args.defaults))+list(node.args.defaults)
        props={};required=[]
        for arg,default in zip(node.args.args,defaults):
            props[arg.arg]={'annotation':ast.unparse(arg.annotation) if arg.annotation else 'Any'}
            if default is None:required.append(arg.arg)
            else:
                try:props[arg.arg]['default']=ast.literal_eval(default)
                except (ValueError,TypeError):props[arg.arg]['default_expression']=ast.unparse(default)
        definitions.append({'name':name,'parameters':props,'required':required,
                            'description':ast.get_docstring(node) or ''})
    from public_server import PUBLIC_TOOLS
    return {'generation_method':'AST_SOURCE_NOT_RUNTIME_SDK','version':__import__('release_info').VERSION,
       'note':'SDK가 반환하는 JSON Schema의 실제 형식은 export_runtime_schemas.py 및 CI로 별도 확인.',
       'profiles':{k:sorted(v) for k,v in {'core':core,'work':work,'lite':lite,'full':legacy_full_tools,'public':set(PUBLIC_TOOLS)}.items()},
       'tools':definitions}
if __name__=='__main__':
    target=ROOT/'docs/source-tool-contracts.json'
    target.write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n')
    print(target)
