"""Run bounded, sequential MCP minimum calls using actual prior response values.

The output separates valid transport, explicit support/source states, and
semantic assertions. A 40-tool minimum call is not a national accuracy audit.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def data_of(result):
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    for block in result.content:
        if getattr(block, "type", None) == "text":
            try:
                value = json.loads(block.text)
                if isinstance(value, dict):
                    return value
            except (ValueError, TypeError):
                pass
    return {}


def lookup(value, path):
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    if value is None or value == "":
        raise KeyError(path)
    return value


def condition_value(value, condition):
    """Honor an explicitly documented optional field without inventing IDs.

    Some response fields (for example an article's excerpt marker) are absent
    for a complete item. Only a condition declaring missing_value can accept
    that absence. A missing list item, malformed parent, or explicit null is
    never converted to the default.
    """
    try:
        for key in condition["path"].split("."):
            value = value[int(key)] if isinstance(value, list) else value[key]
    except KeyError:
        if "missing_value" in condition:
            return condition["missing_value"]
        raise
    return value


def substitute(value, variables):
    if isinstance(value, str) and value.startswith("@"):
        return variables[value[1:]]
    if isinstance(value, dict):
        return {key: substitute(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, variables) for item in value]
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def classify(result, data):
    status = str(data.get("status", ""))
    if status in {"INVALID_INPUT", "INVALID_INPUT_OR_PROCESSING_ERROR"}:
        return "INVALID_TEST_INPUT"
    if result.isError:
        if status in {"NOT_CONFIGURED", "NEEDS_CONTEXT", "UNSUPPORTED", "NOT_SUPPORTED"}:
            return "EXPLICIT_SUPPORT_LIMITATION"
        return "TOOL_ERROR"
    return "RETURNED_WITH_SCOPE" if status in {"PARTIAL", "EMPTY", "NEEDS_CONTEXT", "PLAN_ONLY",
                                                "METADATA_REVIEW_ONLY"} else "RETURNED"


async def verify(args):
    parsed = urlsplit(args.url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTPS MCP endpoint without credentials or query parameters")
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    calls = inventory["calls"] if isinstance(inventory, dict) else inventory
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records, variables, responses = [], {}, {}
    report = {"endpoint": args.url, "authentication": "none", "transport": "MCP_SDK_STREAMABLE_HTTP",
              "checked_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(),
              "scope": "One bounded minimum input per public tool, plus stated dependencies; no load test.",
              "records": records, "checks": {}}
    async with streamablehttp_client(args.url, timeout=75) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            listing = await session.list_tools()
            schemas = {tool.name: tool.inputSchema for tool in listing.tools}
            write_json(output / "initialize.json", init.model_dump(mode="json"))
            write_json(output / "tools-list.json", listing.model_dump(mode="json"))
            report["protocol_version"] = init.protocolVersion
            report["tool_count"] = len(schemas)
            report["checks"]["forty_advertised_tools"] = len(schemas) == 40
            report["checks"]["finance_search_terms_exposed"] = "search_terms" in schemas["council_finance_context"]["properties"]
            report["checks"]["background_default_off"] = all(
                schemas["council_context_pack"]["properties"].get(key, {}).get("default") is False
                for key in ("include_member_records", "include_policy_background"))
            report["checks"]["compare_pagination_exposed"] = all(
                key in schemas["ordinance_compare"]["properties"]
                for key in ("offset", "limit", "max_chars", "expected_hashes"))
            for index, case in enumerate(calls, 1):
                call_id = case.get("id") or f"call-{index:02d}"
                if not re.fullmatch(r"[A-Za-z0-9_-]+", call_id):
                    raise ValueError("Unsafe call id")
                name = case.get("name") or case["tool"]
                row = {"id": call_id, "tool": name, "purpose": case.get("purpose", "")}
                try:
                    for condition in case.get("preconditions", []):
                        if "placeholder" in condition:
                            observed = variables[condition["placeholder"]]
                        else:
                            observed = condition_value(responses[condition["source"]][-1], condition)
                        if "equals" in condition and observed != condition["equals"]:
                            raise ValueError("A prerequisite value does not match")
                        if "must_not_equal" in condition and observed == condition["must_not_equal"]:
                            raise ValueError("A prerequisite indicates incomplete source text")
                    arguments = substitute(case.get("arguments", {}), variables)
                    if name not in schemas:
                        raise ValueError("Tool is not advertised")
                    unexpected = set(arguments) - set(schemas[name].get("properties", {}))
                    if unexpected:
                        raise ValueError("Undeclared argument fields: " + ", ".join(sorted(unexpected)))
                    Draft202012Validator(schemas[name]).validate(arguments)
                except Exception as exc:
                    row.update(classification="UNEXECUTED_INPUT_OR_DEPENDENCY", error_type=type(exc).__name__,
                               reason=str(exc)[:600])
                    records.append(row)
                    write_json(output / "summary.json", report)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    continue
                started = time.monotonic()
                try:
                    result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=85)
                    data = data_of(result)
                    row.update(seconds=round(time.monotonic() - started, 2), isError=bool(result.isError),
                               status=data.get("status"), code=data.get("code"),
                               classification=classify(result, data),
                               receipt=data.get("mcp_receipt"), arguments=arguments,
                               response_file=f"calls/{call_id}.json")
                    responses.setdefault(name, []).append(data)
                    write_json(output / row["response_file"], {"call": row, "result": result.model_dump(mode="json")})
                    extraction_allowed = True
                    for condition in case.get("preconditions_for_extraction", []):
                        try:
                            observed = condition_value(data, condition)
                            passed = (("equals" not in condition or observed == condition["equals"]) and
                                      ("must_not_equal" not in condition or observed != condition["must_not_equal"]))
                        except (KeyError, IndexError, TypeError, ValueError):
                            passed = False
                        if not passed:
                            extraction_allowed = False
                            row.setdefault("failed_extraction_preconditions", []).append(condition["path"])
                    for variable, path in (case.get("extract", {}) if extraction_allowed else {}).items():
                        try:
                            variables[variable.lstrip("@")] = lookup(data, path)
                        except (KeyError, IndexError, TypeError, ValueError):
                            row.setdefault("unavailable_extractions", []).append({"variable": variable, "path": path})
                    if case.get("expected"):
                        row["expected_checks"] = {}
                        for path, expected in case["expected"].items():
                            try:
                                row["expected_checks"][path] = lookup(data, path) == expected
                            except (KeyError, IndexError, TypeError, ValueError):
                                row["expected_checks"][path] = False
                    records.append(row)
                except Exception as exc:
                    row.update(seconds=round(time.monotonic() - started, 2), classification="TRANSPORT_OR_SDK_ERROR",
                               error_type=type(exc).__name__)
                    records.append(row)
                write_json(output / "summary.json", report)
                print(json.dumps({key: row.get(key) for key in
                                  ("id", "tool", "status", "classification", "seconds", "unavailable_extractions")},
                                 ensure_ascii=False), flush=True)
    # A separate real SDK session verifies reconnection, independently of the
    # session that carries source IDs and snapshots above.
    async with streamablehttp_client(args.url, timeout=75) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing2 = await session.list_tools()
            calc = await session.call_tool("budget_calculate", {"operation": "change",
                "arguments": {"before": "0", "after": "120", "unit": "천원"}})
            calc_data = data_of(calc)
            write_json(output / "sdk-reconnect.json", {"tool_count": len(listing2.tools),
                "result": calc.model_dump(mode="json")})
            report["checks"]["sdk_reconnect_and_zero_base"] = len(listing2.tools) == 40 and not calc.isError \
                and calc_data.get("rate_pct") is None and calc_data.get("rate_status") == "ZERO_BASE_NOT_COMPUTABLE"
    returned = {r["tool"] for r in records if r.get("response_file")}
    report["unique_tools_returned"] = len(returned)
    report["checks"]["all_advertised_tools_returned"] = returned == set(schemas)
    report["checks"]["inputs_and_transport_valid"] = all(r["classification"] not in {
        "UNEXECUTED_INPUT_OR_DEPENDENCY", "TRANSPORT_OR_SDK_ERROR", "INVALID_TEST_INPUT"} for r in records)
    report["checks"]["declared_case_expectations"] = all(all(r.get("expected_checks", {}).values()) for r in records)
    report["classifications"] = dict(Counter(r["classification"] for r in records))
    report["tool_errors_require_review"] = [r["id"] for r in records if r["classification"] == "TOOL_ERROR"]
    status = next(iter(responses.get("council_status", [])), {})
    report["observed_version"] = status.get("version")
    report["observed_commit"] = status.get("deployment_commit")
    report["checks"]["release_manifest_matches"] = status.get("release_verification", {}).get("status") == "MATCH"
    if args.expect_version:
        report["checks"]["expected_version"] = status.get("version") == args.expect_version
    if args.expect_commit:
        report["checks"]["expected_commit"] = status.get("deployment_commit") == args.expect_commit
    comparison_pages = responses.get("ordinance_compare", [])
    if any(case.get("id") == "dependency_compare_next_page" for case in calls):
        first = comparison_pages[0] if comparison_pages else {}
        second = comparison_pages[1] if len(comparison_pages)>1 else {}
        first_coverage, second_coverage = first.get("coverage", {}), second.get("coverage", {})
        report["checks"]["comparison_continuation_preserves_source"] = bool(
            first_coverage.get("returned_alignments", 0) > 0 and
            second_coverage.get("returned_alignments", 0) > 0 and
            first_coverage.get("next_offset") == second_coverage.get("offset") and
            first_coverage.get("source_content_hashes") == second_coverage.get("source_content_hashes") and
            (first.get("continuation") or {}).get("arguments", {}).get("expected_hashes") == second_coverage.get("source_content_hashes") and
            first.get("legal_approval") is False and second.get("legal_approval") is False)
    contexts = responses.get("council_context_pack", [])
    if contexts:
        context = contexts[-1]
        review = context.get("linked_review", {})
        report["checks"]["followup_candidates_not_empty"] = all(
            review.get(domain, {}).get("status") == "PARTIAL" and
            review.get(domain, {}).get("candidate_status") == "CANDIDATES_FOUND" and
            review.get(domain, {}).get("discovered_candidates", 0) > 0
            for domain in ("budget", "ordinance"))
        trace_statuses = {row.get("stage"): row.get("status") for row in context.get("execution_trace", {}).get("stages", [])}
        report["checks"]["default_background_skipped"] = all(context.get(layer, {}).get("status", trace_statuses.get(layer)) == "SKIPPED"
            for layer in ("member_record_discovery", "policy_background"))
        report["checks"]["relationships_not_certified"] = review.get("same_project_verified") is False and \
            review.get("budget", {}).get("amounts_verified") is False and \
            review.get("ordinance", {}).get("applicability_verified") is False and context.get("ready_for_submission") is False
    report["status"] = "PASS" if all(report["checks"].values()) and not report["tool_errors_require_review"] else "REVIEW_REQUIRED"
    write_json(output / "summary.json", report)
    print(json.dumps({key: report.get(key) for key in ("status", "unique_tools_returned", "classifications", "checks")},
                     ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expect-version")
    parser.add_argument("--expect-commit")
    args = parser.parse_args()
    report = asyncio.run(verify(args))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
