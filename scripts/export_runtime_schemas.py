#!/usr/bin/env python3
"""Run only with the real installed mcp SDK. No API calls. Current profile only."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uijeong_mcp as U

async def main():
    tools=await U.mcp.list_tools()
    data={'generation_method':'ACTUAL_INSTALLED_MCP_SDK','version':U.SERVER_VERSION,'profile':U.PROFILE,
          'tool_count':len(tools),'tools':[t.model_dump(mode='json') for t in sorted(tools,key=lambda x:x.name)]}
    print(json.dumps(data,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
