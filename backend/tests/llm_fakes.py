"""Recorded Anthropic API responses for the LLM-path tests. No network: a real `AsyncAnthropic`
client runs over an `httpx2.MockTransport`, so the SDK's request building, beta headers, response
parsing and `messages.parse()` validation are all exercised against canned JSON.
"""

import inspect
import json
from collections.abc import Callable
from typing import Any

import httpx2
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from vicky.llm.client import LLM

USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def text_block(text: str, citations: list[dict] | None = None) -> dict:
    return {"type": "text", "text": text, "citations": citations}


def message(content: list[dict], *, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5",
            usage: dict | None = None, stop_details: dict | None = None) -> dict:
    return {"id": "msg_recorded", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "stop_details": stop_details, "usage": usage or USAGE}


def json_reply(obj: Any, **kw: Any) -> dict:
    return message([text_block(json.dumps(obj))], **kw)


def text_reply(text: str, **kw: Any) -> dict:
    return message([text_block(text)], **kw)


def tool_use_reply(name: str, tool_input: dict, tool_id: str = "toolu_1", **kw: Any) -> dict:
    return message([{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}], stop_reason="tool_use", **kw)


def page_cite(text: str, page: int, title: str = "doc.pdf") -> dict:
    return {"type": "page_location", "cited_text": text, "document_index": 0, "document_title": title,
            "start_page_number": page, "end_page_number": page + 1}


def char_cite(text: str, start: int, title: str = "doc.docx") -> dict:
    return {"type": "char_location", "cited_text": text, "document_index": 0, "document_title": title,
            "start_char_index": start, "end_char_index": start + len(text)}


FILE_META = {"id": "file_recorded", "type": "file", "filename": "doc.pdf", "mime_type": "application/pdf",
             "size_bytes": 10, "created_at": "2026-10-01T00:00:00Z", "downloadable": False}


class Recorder:
    """Answers each request with `responder(call)`; keeps every call for assertions.

    `responder` gets a dict {method, path, body, headers, task} and returns a response body (dict),
    or a `(status, body)` tuple, or an awaitable of either (to simulate a slow API). `task` is a short tag for which agent prompt the call carries.
    """

    def __init__(self, responder: Callable[[dict], Any]):
        self.responder = responder
        self.calls: list[dict] = []

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        raw = request.content
        try:
            body = json.loads(raw) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None  # multipart (Files API upload)
        call = {"method": request.method, "path": request.url.path, "body": body, "headers": dict(request.headers),
                "task": task_of(body), "raw": raw}
        self.calls.append(call)
        out = self.responder(call)
        if inspect.isawaitable(out):
            out = await out
        status, payload = out if isinstance(out, tuple) else (200, out)
        return httpx2.Response(status, json=payload)

    def tasks(self) -> list[str]:
        return [c["task"] for c in self.calls]


def queue(*responses: Any) -> Callable[[dict], Any]:
    items = list(responses)

    def respond(_call: dict) -> Any:
        if not items:
            raise AssertionError("unexpected extra API call")
        return items.pop(0)

    return respond


TASK_MARKERS = [("memo", "pre-meeting memo"), ("speak", "say your next line"), ("bid", "update your confidence"),
                ("chair", "chairing the panel"), ("judge", "score the founder's answer"), ("claims", "quantitative claim"),
                ("mapper", "map the columns"), ("doc_parse", "cited fact list"), ("doc_facts", "extract facts"),
                ("persona", "investor persona card"), ("review", "review the investor's draft line"),
                ("probes", "draft recall questions"), ("ask_knowledge", "ask the founder to recall"),
                ("verify", "verify the founder's recall")]


def task_of(body: Any) -> str:
    if not isinstance(body, dict):
        return "file"
    system = body.get("system") or ""
    text = " ".join(b.get("text", "") for b in system) if isinstance(system, list) else str(system)
    for tag, marker in TASK_MARKERS:
        if marker in text.lower():
            return tag
    return "other"


def make_llm(recorder: Recorder) -> LLM:
    client = AsyncAnthropic(api_key="test-key", max_retries=0, base_url="https://api.anthropic.test",
                            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder.handler)))
    return LLM(client)


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal text PDF (Helvetica, one line per string) that pypdf can read back."""
    objects: dict[int, bytes] = {}
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, lines in enumerate(pages):
        ops = ["BT", "/F1 11 Tf", "14 TL", "72 720 Td"]
        for ln in lines:
            ops.append("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects[page_ids[i]] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R "
                                f">> >> /Contents {page_ids[i] + 1} 0 R >>").encode()
        objects[page_ids[i] + 1] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    out = b"%PDF-1.4\n"
    offsets = {}
    for k in sorted(objects):
        offsets[k] = len(out)
        out += f"{k} 0 obj\n".encode() + objects[k] + b"\nendobj\n"
    xref = len(out)
    n = max(objects) + 1
    out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
    for k in range(1, n):
        out += f"{offsets[k]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
