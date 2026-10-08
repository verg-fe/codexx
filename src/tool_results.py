"""Separate tool transport status from diagnostic text and target validation."""
import json
import re


def flatten_output(value, depth=0):
    if depth > 8:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "[{":
            try:
                decoded = json.loads(stripped)
            except (ValueError, TypeError):
                return value
            if isinstance(decoded, (dict, list)):
                return flatten_output(decoded, depth + 1)
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (flatten_output(item, depth + 1) for item in value)))
    if isinstance(value, dict):
        parts = []
        for key in ("text", "input_text", "stdout", "stderr", "message", "content", "output", "result"):
            if key in value:
                part = flatten_output(value[key], depth + 1)
                if part and part not in parts:
                    parts.append(part)
        if parts:
            return "\n".join(parts)
        return json.dumps(value, ensure_ascii=False, default=str)
    return "" if value is None else str(value)


def _walk_errors(value, depth=0):
    if depth > 8:
        return []
    found = []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "[{":
            try:
                decoded = json.loads(stripped)
            except (ValueError, TypeError):
                return []
            return _walk_errors(decoded, depth + 1)
    elif isinstance(value, dict):
        if value.get("isError") is True:
            found.append("MCP tool returned isError=true")
        for key, child in value.items():
            if key in ("content", "output", "result", "structuredContent"):
                found.extend(_walk_errors(child, depth + 1))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_errors(child, depth + 1))
    return found


def classify_output(output):
    text = flatten_output(output)
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    findings = []
    for pattern, code in (
        (r"(?m)^\s*Traceback \(most recent call last\):", "python_traceback"),
        (r"(?m)^\s*ParserError\s*:", "powershell_parser_error"),
        (r"(?im)^\s*FullyQualifiedErrorId\s*:\s*.+", "powershell_error_record"),
        (r"(?im)^\s*The property .+ cannot be found on this object\.", "powershell_property_error"),
        (r"(?im)^.*(?:Exception|Error):\s*[^\n]+", "observed_error_text"),
        (r"(?im)^.*\b(?:crashed|crash|unknown authority)\b[^\n]*", "observed_runtime_error_text"),
        (r"(?im)^.*(?:BUILD FAILED|Build FAILED|Compilation failed).*$", "build_failure_text"),
    ):
        match = re.search(pattern, clean)
        if match:
            findings.append({"code": code, "attribution": "unverified", "excerpt": match.group(0)[:500]})

    transport_errors = _walk_errors(output)
    if transport_errors:
        status = "failed"
        findings.extend({"code": "mcp_reported_error", "attribution": "tool", "excerpt": item}
                        for item in transport_errors if item not in {f.get("excerpt") for f in findings})
    else:
        exit_code = None
        if isinstance(output, dict):
            for key in ("exit_code", "exitCode", "returncode", "return_code"):
                if isinstance(output.get(key), int):
                    exit_code = output[key]
                    break
        code_match = re.search(r"(?:Process exited with code|Exit code:)\s*(-?\d+)\b", clean)
        if exit_code is None and code_match:
            exit_code = int(code_match.group(1))
        if exit_code is not None:
            status = "succeeded" if exit_code == 0 else "failed"
        elif isinstance(output, dict) and output.get("isError") is False:
            status = "succeeded"
        elif clean.startswith("Success. Updated the following files:"):
            status = "succeeded"
        else:
            status = "unknown"

    target = "not_checked"
    evidence = re.search(r"(?im)^.*\b(?:BUILD SUCCESSFUL|Build succeeded|Compilation successful)\b.*$", clean)
    if evidence:
        target = "reported_success"
    elif any(item["code"] == "build_failure_text" for item in findings):
        target = "reported_failure"
    elif re.search(r"(?im)^\s*Success\s*$", clean) and re.search(r"(?i)adb(?:\.exe)?\s+install", clean):
        target = "reported_success"

    evidence = []
    for item in findings:
        excerpt = item.get("excerpt", "")
        location = re.search(r"(?i)(?:^|[\s(])((?:(?:[A-Za-z]:\\|/)[^\s():]+|[\w. -]+\.(?:java|kt|py|cs|cpp|h|xml|gradle)))(?:[:(])(\d+)(?:[:)]|\b)", excerpt)
        if location:
            item["file"] = location.group(1)
            item["line"] = int(location.group(2))
        evidence.append(item)
    return {"execution_status": status, "diagnostic_findings": evidence,
            "target_validation": target, "text": text}
