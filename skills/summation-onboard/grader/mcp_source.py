"""Direct, read-only MCP execution with first-hand source receipts."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


MAX_RESPONSE_BYTES = 1_000_000


class McpSourceError(RuntimeError):
    """A direct MCP source could not be inspected or queried safely."""


def resolve_mcpc(explicit: str | None = None) -> Path:
    candidate = explicit or shutil.which("mcpc")
    if not candidate:
        raise McpSourceError("mcpc is required for direct MCP source checks")
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise McpSourceError(f"mcpc was not found at {path}")
    return path


def _json_command(command: list[str], *, timeout: int = 120):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise McpSourceError(f"MCP command timed out after {timeout}s") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise McpSourceError(detail or f"MCP command exited {result.returncode}")
    if len(result.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise McpSourceError(
            f"MCP response exceeded the {MAX_RESPONSE_BYTES}-byte receipt limit")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise McpSourceError("MCP command returned invalid JSON") from error


def session_identity(mcpc: Path, session: str) -> dict:
    document = _json_command([str(mcpc), "--json"])
    matches = [item for item in document.get("sessions") or []
               if item.get("name") == session]
    if len(matches) != 1:
        raise McpSourceError(f"MCP session {session} is not connected")
    item = matches[0]
    if item.get("status") != "live":
        raise McpSourceError(
            f"MCP session {session} is {item.get('status') or 'not live'}")
    server = item.get("server") or {}
    info = item.get("serverInfo") or {}
    return {
        "session": session,
        "server_url": str(server.get("url") or "stdio"),
        "server_name": str(info.get("title") or info.get("name") or session),
        "server_version": info.get("version"),
        "protocol_version": item.get("protocolVersion"),
    }


def approved_tools(mcpc: Path, session: str,
                   approved_names: list[str]) -> dict[str, dict]:
    if not approved_names:
        raise McpSourceError("at least one approved MCP tool is required")
    payload = _json_command(
        [str(mcpc), "--json", session, "tools-list", "--full"])
    if not isinstance(payload, list):
        raise McpSourceError("MCP tools-list did not return an array")
    by_name = {str(item.get("name")): item for item in payload
               if item.get("name")}
    selected = {}
    for name in dict.fromkeys(approved_names):
        tool = by_name.get(name)
        if not tool:
            raise McpSourceError(f"approved MCP tool {name!r} is not available")
        annotations = tool.get("annotations") or {}
        if annotations.get("readOnlyHint") is not True:
            raise McpSourceError(
                f"approved MCP tool {name!r} is not declared read-only")
        if annotations.get("destructiveHint") is True:
            raise McpSourceError(
                f"approved MCP tool {name!r} is declared destructive")
        selected[name] = {
            "name": name,
            "title": tool.get("title"),
            "description": tool.get("description"),
            "inputSchema": tool.get("inputSchema") or {"type": "object"},
            "outputSchema": tool.get("outputSchema"),
            "annotations": annotations,
        }
    return selected


def call_tool(mcpc: Path, session: str, tool: str,
              arguments: dict, *, timeout: int = 120) -> dict:
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    response = _json_command(
        [str(mcpc), "--json", session, "tools-call", tool, encoded],
        timeout=timeout)
    if not isinstance(response, dict):
        raise McpSourceError("MCP tool call did not return an object")
    if response.get("isError"):
        raise McpSourceError("MCP tool returned an error result")
    return response


def normalized_payload(response: dict):
    structured = response.get("structuredContent")
    if structured is not None:
        return structured
    texts = [str(item.get("text")) for item in response.get("content") or []
             if item.get("type") == "text" and item.get("text") is not None]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            xml_payload = _embedded_xml(texts[0])
            return {"text": texts[0], "xml": xml_payload} if xml_payload else {"text": texts[0]}
    parsed = []
    for text in texts:
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append(text)
    return {"content": parsed}


def _xml_element(element: ET.Element) -> dict:
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": (element.text or "").strip() or None,
        "children": [_xml_element(child) for child in element],
    }


def _embedded_xml(text: str) -> dict | None:
    """Parse one XML data block embedded after an MCP safety preamble."""
    starts = [match.start() for match in re.finditer(r"<[A-Za-z][^>]*>", text)]
    for start in starts:
        candidate = text[start:].strip()
        try:
            return _xml_element(ET.fromstring(candidate))
        except ET.ParseError:
            continue
    return None


def response_sha256(response: dict) -> str:
    canonical = json.dumps(
        response, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def resolve_json_pointer(document, pointer: str):
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise McpSourceError(f"invalid JSON pointer {pointer!r}")
    current = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as error:
                raise McpSourceError(
                    f"JSON pointer {pointer!r} did not resolve") from error
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise McpSourceError(f"JSON pointer {pointer!r} did not resolve")
    return current


def write_raw_receipt(out: Path, check_id: str, response: dict) -> Path:
    receipt_dir = out / "source-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(char for char in check_id if char.isalnum() or char in "_-")
    destination = receipt_dir / f"{safe_id or 'check'}.json"
    destination.write_text(json.dumps(response, indent=2, ensure_ascii=False) + "\n")
    return destination
