"""Real Chromium checks for the approved customer artifact laws."""
from __future__ import annotations

import base64
import json
import os
import pathlib
import signal
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import urllib.request
from urllib.parse import urlparse

from tests import test_verify_render as fixtures


CHROME = pathlib.Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
PDFTOTEXT = pathlib.Path("/opt/homebrew/bin/pdftotext")


def customer_page() -> str:
    checks = [
        fixtures.accepted_check(1, "confirmed", severity="high"),
        fixtures.accepted_check(2, "confirmed", severity="low"),
        fixtures.accepted_check(3, "contradicted"),
        fixtures.accepted_check(4, "not_checkable"),
    ]
    raw = fixtures.raw_for(checks)
    raw["source"]["period_label"] = "Week ending April 4, 2026"
    artifact = fixtures.render.artifact_from_findings(
        raw,
        run_id="browser-laws",
        generated_at="2026-08-25T13:10:00Z",
        layer2=checks,
        guidance=fixtures.guidance_for(checks),
    )
    return fixtures.render.html_of(artifact)


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("DevTools WebSocket closed early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class DevTools:
    def __init__(self, websocket_url: str):
        parsed = urlparse(websocket_url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Origin: http://localhost\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError(response.decode(errors="replace"))
        self.next_id = 0

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length < 65536:
            header = bytes((0x80 | opcode, 0xFE)) + struct.pack(">H", length)
        else:
            header = bytes((0x80 | opcode, 0xFF)) + struct.pack(">Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _message(self) -> str:
        parts: list[bytes] = []
        while True:
            first, second = _read_exact(self.sock, 2)
            finished = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", _read_exact(self.sock, 2))[0]
            elif length == 127:
                length = struct.unpack(">Q", _read_exact(self.sock, 8))[0]
            mask = _read_exact(self.sock, 4) if second & 0x80 else None
            payload = _read_exact(self.sock, length)
            if mask:
                payload = bytes(
                    value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 8:
                raise ConnectionError("DevTools WebSocket closed")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode in {0, 1}:
                parts.append(payload)
            if finished and parts:
                return b"".join(parts).decode()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        call_id = self.next_id
        self._send_frame(json.dumps({
            "id": call_id, "method": method, "params": params or {},
        }).encode())
        while True:
            response = json.loads(self._message())
            if response.get("id") != call_id:
                continue
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result") or {}

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=8)
        finally:
            self.sock.close()


class ChromeSession:
    def __init__(self, root: pathlib.Path, page_uri: str):
        self.root = root
        self.port = _free_port()
        self.stdout = (root / "chrome.stdout").open("wb")
        self.stderr = (root / "chrome.stderr").open("wb")
        self.process = subprocess.Popen([
            str(CHROME),
            "--headless=new",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-gpu",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={root / 'profile'}",
            page_uri,
        ], stdout=self.stdout, stderr=self.stderr, start_new_session=True)
        self.devtools: DevTools | None = None
        try:
            target = self._target()
            self.devtools = DevTools(target["webSocketDebuggerUrl"])
            self.devtools.call("Page.enable")
        except Exception:
            self.close()
            raise

    def _target(self) -> dict:
        deadline = time.monotonic() + 20
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json", timeout=1
                ) as response:
                    targets = json.load(response)
                pages = [row for row in targets if row.get("type") == "page"]
                if pages:
                    return pages[0]
            except Exception as exc:  # the local debug port may not be ready yet
                last_error = exc
            time.sleep(0.1)
        raise TimeoutError(f"Chrome DevTools did not start: {last_error}")

    def close(self) -> None:
        if self.devtools is not None:
            self.devtools.close()
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
        self.stdout.close()
        self.stderr.close()


@unittest.skipUnless(CHROME.is_file(), "Google Chrome is required")
class BrowserCustomerLawTests(unittest.TestCase):
    def test_host_selected_confirmation_is_visible_before_technical_detail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            page_path = root / "grade-artifact.html"
            page_path.write_text(customer_page())
            browser = ChromeSession(root, page_path.as_uri())
            try:
                result = browser.devtools.call("Runtime.evaluate", {
                    "expression": """
(() => {
  const details = document.querySelector('details.technical-detail');
  const selected = document.querySelector('[data-card-id="C1"]');
  const deferred = document.querySelector('[data-card-id="C2"]');
  return {
    selectedBeforeDetails: !!selected && !!details &&
      (selected.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    deferredInsideDetails: !!deferred && !!details && details.contains(deferred),
    notCheckableReceiptInsideDetails: !!details && details.contains(
      document.querySelector('[data-card-id="C4"]')
    ),
    compactNotCheckableVisible: !!document.querySelector(
      '[data-outcome-section="not_checkable"] .not-checkable-item'
    ),
    confirmedSectionVisible: !!document.querySelector(
      '[data-outcome-section="confirmed"] [data-card-id="C1"]'
    )
  };
})()
""",
                    "returnByValue": True,
                })["result"]["value"]
                self.assertTrue(result["selectedBeforeDetails"], result)
                self.assertTrue(result["deferredInsideDetails"], result)
                self.assertTrue(result["notCheckableReceiptInsideDetails"], result)
                self.assertTrue(result["compactNotCheckableVisible"], result)
                self.assertTrue(result["confirmedSectionVisible"], result)
            finally:
                browser.close()

    def test_long_receipt_page_has_no_390px_horizontal_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            page_path = root / "grade-artifact.html"
            page_path.write_text(customer_page())
            browser = ChromeSession(root, page_path.as_uri())
            try:
                browser.devtools.call("Emulation.setDeviceMetricsOverride", {
                    "width": 390, "height": 844, "deviceScaleFactor": 1,
                    "mobile": True,
                })
                browser.devtools.call("Page.navigate", {"url": page_path.as_uri()})
                time.sleep(0.2)
                expression = """
(() => {
  document.querySelectorAll('details').forEach((row) => { row.open = true; });
  const width = document.documentElement.clientWidth;
  const nodes = [...document.querySelectorAll(
    '.material-card,.operand,.card-source,.receipt-row,.receipt-math'
  )];
  return {
    clientWidth: width,
    scrollWidth: document.documentElement.scrollWidth,
    rows: nodes.map((node) => {
      const rect = node.getBoundingClientRect();
      return {cls: node.className, left: rect.left, right: rect.right,
        within: rect.left >= -0.5 && rect.right <= width + 0.5};
    }),
    operands: [...document.querySelectorAll('.operand')].map((node) => ({
      columns: getComputedStyle(node).gridTemplateColumns,
      wrap: getComputedStyle(node.querySelector('.location')).overflowWrap,
      operandWidth: node.getBoundingClientRect().width,
      locationWidth: node.querySelector('.location').getBoundingClientRect().width
    }))
  };
})()
"""
                result = browser.devtools.call("Runtime.evaluate", {
                    "expression": expression, "returnByValue": True,
                })
                metrics = result["result"]["value"]
                self.assertEqual(metrics["clientWidth"], 390)
                self.assertLessEqual(metrics["scrollWidth"], metrics["clientWidth"])
                self.assertTrue(metrics["rows"])
                self.assertTrue(all(row["within"] for row in metrics["rows"]), metrics)
                self.assertTrue(metrics["operands"])
                for operand in metrics["operands"]:
                    self.assertEqual(len(operand["columns"].split()), 1, operand)
                    self.assertIn(operand["wrap"], {"anywhere", "break-word"})
                    self.assertAlmostEqual(
                        operand["locationWidth"], operand["operandWidth"], delta=1.0,
                        msg=operand,
                    )
                shot = browser.devtools.call("Page.captureScreenshot", {
                    "format": "png", "captureBeyondViewport": False,
                })
                screenshot = base64.b64decode(shot["data"])
                self.assertEqual(screenshot[:8], b"\x89PNG\r\n\x1a\n")
                width, height = struct.unpack(">II", screenshot[16:24])
                self.assertEqual((width, height), (390, 844))
            finally:
                browser.close()

    def test_mobile_locations_are_full_width(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            page_path = root / "grade-artifact.html"
            page_path.write_text(customer_page())
            browser = ChromeSession(root, page_path.as_uri())
            try:
                browser.devtools.call("Emulation.setDeviceMetricsOverride", {
                    "width": 390, "height": 844, "deviceScaleFactor": 1,
                    "mobile": True,
                })
                browser.devtools.call("Page.navigate", {"url": page_path.as_uri()})
                time.sleep(0.2)
                rows = browser.devtools.call("Runtime.evaluate", {
                    "expression": """
(() => [...document.querySelectorAll('.operand')].map((operand) => {
  const location = operand.querySelector('.location');
  return {
    columns: getComputedStyle(operand).gridTemplateColumns,
    operandWidth: operand.getBoundingClientRect().width,
    locationWidth: location.getBoundingClientRect().width
  };
}))()
""",
                    "returnByValue": True,
                })["result"]["value"]
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(len(row["columns"].split()), 1, row)
                    self.assertAlmostEqual(
                        row["locationWidth"], row["operandWidth"], delta=1.0,
                        msg=row,
                    )
            finally:
                browser.close()

    @unittest.skipUnless(PDFTOTEXT.is_file(), "pdftotext is required")
    def test_desktop_and_print_use_customer_copy_without_duplicate_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            page_path = root / "grade-artifact.html"
            page_path.write_text(customer_page())
            browser = ChromeSession(root, page_path.as_uri())
            try:
                desktop = browser.devtools.call("Runtime.evaluate", {
                    "expression": """
(() => ({
  visible: document.body.innerText,
  sources: document.querySelectorAll('.material-card .card-source').length,
  pageSources: document.querySelectorAll('.sources').length,
  nextBlocks: document.querySelectorAll('.next').length
}))()
""",
                    "returnByValue": True,
                })["result"]["value"]
                for label in (
                    "Fix 1 error before you share this report.",
                    "Confirmed", "Contradicted",
                    "Not checkable", "Supplied file",
                ):
                    self.assertIn(label, desktop["visible"])
                for token in (
                    "safe_to_share", "fix_first", "not_checkable",
                    "supplied_file", "not_run",
                ):
                    self.assertNotIn(token, desktop["visible"])
                self.assertEqual(desktop["sources"], 3)
                self.assertEqual(desktop["pageSources"], 0)
                self.assertEqual(desktop["nextBlocks"], 1)
                browser.devtools.call(
                    "Emulation.setEmulatedMedia", {"media": "print"})
                styles = browser.devtools.call("Runtime.evaluate", {
                    "expression": """
(() => {
  document.querySelectorAll('details').forEach((row) => { row.open = true; });
  return {
    card: getComputedStyle(document.querySelector('.material-card')).breakInside,
    stats: getComputedStyle(document.querySelector('.stats')).breakInside,
    scope: getComputedStyle(document.querySelector('.technical-scope')).breakInside,
    operand: getComputedStyle(document.querySelector('.operand')).breakInside,
    detailHeading: getComputedStyle(
      document.querySelector('details.technical-detail > summary')
    ).display
  };
})()
""",
                    "returnByValue": True,
                })["result"]["value"]
                self.assertEqual(styles, {
                    "card": "avoid", "stats": "avoid", "scope": "avoid",
                    "operand": "avoid", "detailHeading": "block",
                })
                pdf_result = browser.devtools.call("Page.printToPDF", {
                    "printBackground": True,
                    "preferCSSPageSize": True,
                    "displayHeaderFooter": False,
                })
                pdf = root / "grade-artifact.pdf"
                pdf.write_bytes(base64.b64decode(pdf_result["data"]))
            finally:
                browser.close()
            self.assertGreater(pdf.stat().st_size, 1000)
            text_path = root / "print.txt"
            extracted = subprocess.run(
                [str(PDFTOTEXT), str(pdf), str(text_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            printed = text_path.read_text()
            for index in range(1, 5):
                self.assertIn(f"Visible report claim {index}.", printed)
            self.assertIn("Technical detail", printed)
            self.assertLess(
                printed.index("Technical detail"),
                printed.index("Visible report claim 2."),
            )
            pages = [page for page in printed.split("\f") if page.strip()]
            self.assertLessEqual(len(pages), 4, pages)
            scope_pages = [page for page in pages if "Technical scope" in page]
            self.assertEqual(len(scope_pages), 1, pages)
            for text in (
                "Material outcomes", "Retained sources", "Live source",
                "Did not run", "Report format", "md",
            ):
                self.assertIn(text, scope_pages[0])


if __name__ == "__main__":
    unittest.main()
