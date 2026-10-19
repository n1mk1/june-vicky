"""Recorded Gemini API responses for the LLM-path tests. No network: a real `google.genai.Client` runs over an
`httpx.MockTransport`, so the SDK's request building, response parsing and error mapping are all exercised
against canned JSON.

Each request is kept twice: as sent (`raw_body`, Gemini's wire format) and as a neutral view (`body`):
`model`, `system` (one string), `messages` (`role` user / assistant; `content` a string when every part is text,
else blocks: `tool_use` {name, input}, `tool_result` {name, content (JSON)}, `document` {mime_type, data}), `tools`
({name, description, input_schema}), `thinking_level`, `max_tokens` and `response_schema`.
"""

import base64
import inspect
import json
from collections.abc import Callable
from typing import Any

import httpx
from google import genai
from google.genai import types

from vik.llm.client import LLM

USAGE = {"promptTokenCount": 1000, "candidatesTokenCount": 200}

FINISH = {
    "end_turn": "STOP",
    "tool_use": "STOP",
    "max_tokens": "MAX_TOKENS",
    "refusal": "SAFETY",
}


def text_block(text: str) -> dict:
    return {"text": text}


def message(
    parts: list[dict],
    *,
    stop_reason: str = "end_turn",
    model: str = "gemini-3.8-flash",
    usage: dict | None = None,
    blocked: str | None = None,
) -> dict:
    """A `generateContent` response. `stop_reason` takes the old names too (end_turn, tool_use, max_tokens,
    refusal) or a Gemini finish reason; `blocked` makes it a blocked prompt (no candidates)."""
    if blocked:
        return {
            "promptFeedback": {"blockReason": blocked},
            "usageMetadata": usage or USAGE,
            "modelVersion": model,
        }
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": FINISH.get(stop_reason, stop_reason),
            }
        ],
        "usageMetadata": usage or USAGE,
        "modelVersion": model,
    }


def json_reply(obj: Any, **kw: Any) -> dict:
    return message([text_block(json.dumps(obj))], **kw)


def text_reply(text: str, **kw: Any) -> dict:
    return message([text_block(text)], **kw)


def tool_use_reply(name: str, tool_input: dict, **kw: Any) -> dict:
    return message([{"functionCall": {"name": name, "args": tool_input}, "thoughtSignature": "c2ln"}], **kw)


def api_error(status: int, message_: str = "error") -> tuple[int, dict]:
    names = {400: "INVALID_ARGUMENT", 403: "PERMISSION_DENIED", 429: "RESOURCE_EXHAUSTED", 503: "UNAVAILABLE"}
    return status, {"error": {"code": status, "message": message_, "status": names.get(status, "INTERNAL")}}


def _b64(data: str) -> bytes:
    """Inline data as the SDK sends it (URL-safe base64, padding optional)."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _blocks(parts: list[dict]) -> str | list[dict]:
    if all("text" in p for p in parts):
        return "".join(p["text"] for p in parts)
    out: list[dict] = []
    for p in parts:
        if "text" in p:
            out.append({"type": "text", "text": p["text"]})
        elif "functionCall" in p:
            fc = p["functionCall"]
            out.append({"type": "tool_use", "name": fc.get("name"), "input": fc.get("args") or {}})
        elif "functionResponse" in p:
            fr = p["functionResponse"]
            out.append(
                {"type": "tool_result", "name": fr.get("name"), "content": json.dumps(fr.get("response"))}
            )
        elif "inlineData" in p:
            d = p["inlineData"]
            out.append(
                {
                    "type": "document",
                    "mime_type": d.get("mimeType") or d.get("mime_type"),
                    "data": _b64(d.get("data", "")),
                }
            )
        elif "fileData" in p:
            out.append({"type": "file", "uri": p["fileData"].get("fileUri")})
    return out


def view(path: str, body: Any) -> dict | None:
    """The neutral view of a `generateContent` request (None for anything else)."""
    if not isinstance(body, dict) or ":generateContent" not in path:
        return None
    gen = body.get("generationConfig") or {}
    thinking = gen.get("thinkingConfig") or {}
    level = thinking.get("thinking_level") or thinking.get("thinkingLevel")
    return {
        "model": path.rsplit("/models/", 1)[-1].split(":", 1)[0],
        "system": "".join(p.get("text", "") for p in (body.get("systemInstruction") or {}).get("parts", [])),
        "messages": [
            {
                "role": "assistant" if c.get("role") == "model" else "user",
                "content": _blocks(c.get("parts", [])),
            }
            for c in body.get("contents", [])
        ],
        "tools": [
            {
                "name": d.get("name"),
                "description": d.get("description"),
                "input_schema": d.get("parameters_json_schema") or d.get("parametersJsonSchema"),
            }
            for t in body.get("tools", [])
            for d in t.get("functionDeclarations", [])
        ],
        "thinking_level": str(level).lower() if level else None,
        "max_tokens": gen.get("maxOutputTokens"),
        "response_schema": gen.get("responseJsonSchema"),
    }


class Recorder:
    """Answers each request with `responder(call)`; keeps every call for assertions.

    `responder` gets a dict {method, path, body, raw_body, headers, task} and returns a response body (dict),
    or a `(status, body)` tuple, or an awaitable of either (to simulate a slow API). `task` is a short tag for
    which agent prompt the call carries.
    """

    def __init__(self, responder: Callable[[dict], Any]):
        self.responder = responder
        self.calls: list[dict] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        raw = request.content
        try:
            body = json.loads(raw) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None
        neutral = view(request.url.path, body)
        call = {
            "method": request.method,
            "path": request.url.path,
            "body": neutral,
            "raw_body": body,
            "headers": dict(request.headers),
            "task": task_of(neutral),
            "raw": raw,
        }
        self.calls.append(call)
        out = self.responder(call)
        if inspect.isawaitable(out):
            out = await out
        status, payload = out if isinstance(out, tuple) else (200, out)
        return httpx.Response(status, json=payload)

    def tasks(self) -> list[str]:
        return [c["task"] for c in self.calls]


def queue(*responses: Any) -> Callable[[dict], Any]:
    items = list(responses)

    def respond(_call: dict) -> Any:
        if not items:
            raise AssertionError("unexpected extra API call")
        return items.pop(0)

    return respond


TASK_MARKERS = [
    ("memo", "pre-meeting memo"),
    ("speak", "say your next line"),
    ("bid", "update your confidence"),
    ("chair", "chairing the panel"),
    ("judge", "score the founder's answer"),
    ("claims", "quantitative claim"),
    ("mapper", "map the columns"),
    ("doc_facts", "extract facts"),
    ("persona", "investor persona card"),
    ("review", "review the investor's draft line"),
    ("probes", "draft recall questions"),
    ("ask_knowledge", "ask the founder to recall"),
    ("verify", "verify the founder's recall"),
]


def task_of(body: Any) -> str:
    if not isinstance(body, dict):
        return "file"
    text = str(body.get("system") or "").lower()
    for tag, marker in TASK_MARKERS:
        if marker in text:
            return tag
    return "other"


def make_llm(recorder: Recorder) -> LLM:
    client = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(
            base_url="https://gemini.test",
            httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return LLM(client)


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal text PDF (Helvetica, one line per string) that pypdf can read back."""
    objects: dict[int, bytes] = {}
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>".encode()
    )
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, lines in enumerate(pages):
        ops = ["BT", "/F1 11 Tf", "14 TL", "72 720 Td"]
        for ln in lines:
            ops.append("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects[page_ids[i]] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R "
            f">> >> /Contents {page_ids[i] + 1} 0 R >>"
        ).encode()
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
