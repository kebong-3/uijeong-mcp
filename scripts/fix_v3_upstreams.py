"""Apply small fixes based on the 2026-09-28 live API response, not guesses."""
from pathlib import Path
from apply_v3_release import change, apply

root=Path(__file__).resolve().parents[1]
# Live public-data service returned result.data[].dataName/detailPageUrl/organization.
change('public_data_discovery.py',
       '"title", "dataNm", "openApiNm", "apiNm", "datasetNm", "name"',
       '"title", "dataName", "dataNm", "openApiNm", "apiNm", "datasetNm", "name"')
change('public_data_discovery.py',
       '"detailUrl", "dataUrl", "url", "link", "dataDetailUrl"',
       '"detailPageUrl", "detailUrl", "dataUrl", "url", "link", "dataDetailUrl"')
# QWGJK requires the snapshot date; a no-data response is still not data proof.
change('v3_reliability.py',
       'F._request({"fyr":str(today().year), "pSize":1})',
       'F._request({"fyr":str(today().year), "exe_ymd":today().strftime("%Y%m%d"), "pSize":1})')
apply()
