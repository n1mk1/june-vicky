"""Any file enters the knowledge base: the formats beyond the Office/PDF/text set (docs/07-KNOWLEDGE-BASE.md)."""

import io
import zipfile
from email.message import EmailMessage

from vik.kb import convert

ODF_HEAD = (
    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"><office:body>'
)
ODF_TAIL = "</office:body></office:document-content>"


def _odf(inner: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("content.xml", ODF_HEAD + inner + ODF_TAIL)
    return b.getvalue()


def test_rtf_keeps_paragraphs_and_escapes():
    uni = "\\" + "u8364?"  # an RTF unicode escape (the euro sign) with its ANSI fallback
    rtf = (
        r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\*\generator x;}\f0 Hiring plan\par Caf\'e9 team of five\par "
        + uni
        + " budget}"
    ).encode("ascii")
    (d,) = convert.convert("plan.rtf", rtf)
    assert "Hiring plan" in d.content and "Café team of five" in d.content and "€ budget" in d.content
    assert "Arial" not in d.content and "generator" not in d.content


def test_odt_headings_paragraphs_and_tables():
    inner = (
        "<office:text><text:h text:outline-level='1'>Market</text:h><text:p>We sell to clinics.</text:p>"
        "<table:table><table:table-row><table:table-cell><text:p>Region</text:p></table:table-cell>"
        "<table:table-cell><text:p>Clinics</text:p></table:table-cell></table:table-row></table:table></office:text>"
    )
    (d,) = convert.convert("memo.odt", _odf(inner))
    assert (
        "## Market" in d.content
        and "We sell to clinics." in d.content
        and "| Region | Clinics |" in d.content
    )


def test_ods_sheets_become_csv_and_odp_slides_get_headings():
    sheet = (
        "<office:spreadsheet><table:table table:name='KPIs'><table:table-row>"
        "<table:table-cell><text:p>month</text:p></table:table-cell><table:table-cell><text:p>mrr</text:p></table:table-cell>"
        "</table:table-row><table:table-row><table:table-cell><text:p>2025-01</text:p></table:table-cell>"
        "<table:table-cell office:value-type='float' office:value='1200.5' "
        "xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'><text:p>1,200.50</text:p></table:table-cell>"
        "</table:table-row></table:table></office:spreadsheet>"
    )
    (t,) = convert.convert("kpis.ods", _odf(sheet))
    assert t.format == "csv" and t.content.splitlines() == ["month,mrr", "2025-01,1200.5"]
    deck = (
        "<office:presentation><draw:page draw:name='Traction'><text:p>Pilots live</text:p></draw:page>"
        "<draw:page draw:name='page2'><text:p>Ask</text:p></draw:page></office:presentation>"
    )
    (p,) = convert.convert("deck.odp", _odf(deck))
    assert "## Slide 1: Traction" in p.content and "## Slide 2\n" in p.content and "Pilots live" in p.content


def test_eml_body_and_attachments_are_notes():
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@x.io", "b@x.io", "Board update"
    m.set_content("Churn fell after the onboarding change.")
    m.add_attachment(b"month,mrr\n2025-01,100\n", maintype="text", subtype="csv", filename="mrr.csv")
    drafts = convert.convert("update.eml", m.as_bytes())
    assert drafts[0].title == "Board update" and "Churn fell" in drafts[0].content
    assert "mrr.csv" in drafts[0].content
    assert any(d.format == "csv" and "2025-01,100" in d.content for d in drafts[1:])


def test_legacy_office_text_runs_are_recovered():
    blob = (
        b"\xd0\xcf\x11\xe0" + bytes(64) + "Quarterly board memo for investors".encode("utf-16-le") + bytes(32)
    )
    (d,) = convert.convert("memo.doc", blob)
    assert "Quarterly board memo for investors" in d.content and d.meta["legacy"]


def test_media_without_a_voice_key_is_a_stub(monkeypatch):
    monkeypatch.setattr(convert.get_settings(), "elevenlabs_api_key", None)
    (d,) = convert.convert("call.mp3", b"ID3" + bytes(400))
    assert d.meta["stub"] and "ELEVENLABS_API_KEY" in d.meta["reason"]


def test_media_is_transcribed_with_speakers(monkeypatch):
    monkeypatch.setattr(convert.get_settings(), "elevenlabs_api_key", "k")
    words = [
        {"text": "We", "type": "word", "start": 0.0, "speaker_id": "speaker_0"},
        {"text": " ", "type": "spacing", "speaker_id": "speaker_0"},
        {"text": "launched.", "type": "word", "start": 0.4, "speaker_id": "speaker_0"},
        {"text": "When?", "type": "word", "start": 61.0, "speaker_id": "speaker_1"},
    ]
    monkeypatch.setattr(
        convert,
        "transcribe",
        lambda data, name: {"text": "We launched. When?", "words": words, "model": "scribe_v2"},
    )
    (d,) = convert.convert("call.m4a", b"\x00" * 100)
    assert "**speaker_0** [0:00] We launched." in d.content and "**speaker_1** [1:01] When?" in d.content
    assert d.meta["transcript"]


def test_autofill_places_the_company_from_how_often_documents_name_it():
    from vik.kb.autofill import place_in

    found = place_in(
        [
            {
                "path": "a.md",
                "content": "We are based in Toronto, Ontario.\nCanadian credits apply.\nOne US pilot.",
            }
        ]
    )
    assert found["country"][0] == "CA" and found["city"][0] == "Toronto" and "[[a.md]]" in found["country"][1]
    assert place_in([{"path": "a.md", "content": "Sold once in London."}]) == {}  # one mention isn't enough


async def test_a_long_text_is_read_in_parts_and_an_overflowing_part_is_halved(monkeypatch):
    from vik.llm import docs
    from vik.llm.client import LLMError
    from vik.llm.schemas import DocFactList

    calls = []

    class Fake:
        async def parse(self, route, schema, *, system, messages):
            n = messages[0]["content"][0]["text"].count("customers")  # one fact per paragraph
            calls.append(n)
            if n > 3:
                raise LLMError("response hit max_tokens")
            return DocFactList(facts=[])

        async def delete_file(self, name):
            pass

    monkeypatch.setattr(docs, "get_llm", lambda: Fake())
    monkeypatch.setattr(docs, "TEXT_PART_CHARS", 2000)
    text = "\n\n".join(f"We have {i} customers. " + "More of the operating report. " * 8 for i in range(10))
    out = await docs.extract_facts(text.encode(), "pack.md", "md", upload_id="u", currency="usd")
    assert out == {"facts": [], "dropped": 0, "lines": 0}
    assert len([c for c in calls if c > 3]) >= 1  # a part overflowed and was halved
    assert sum(c for c in calls if c <= 3) == 10  # every paragraph read exactly once
