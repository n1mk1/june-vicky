"""Custom column mapping (step 02): the founder names a field the standard list lacks; it reaches every table,
the metrics engine (as a labelled series) and the confirmed knowledge base note."""

import pytest

from vik import db
from vik.kb import truthnote
from vik.services import engagements

pytestmark = pytest.mark.db


async def _login(c):
    await c.post("/auth/access", json={"code": "vik-demo"})


async def test_a_custom_field_is_saved_offered_and_computed(api_client):
    await _login(api_client)
    csv = b"Month,Revenue,Pilots live\n2025-01,100,2\n2025-02,120,3\n2025-03,130,5\n"
    r = await api_client.post("/uploads", files={"file": ("custom_map.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    eng = r.json()
    try:
        ds = eng["datasets"][0]
        m = (await api_client.get(f"/datasets/{ds['id']}/mapping")).json()
        rows = [
            {**c, "canonical_field": "custom.", "label": "Active pilots", "unit": "count"}
            if c["source_column"] == "Pilots live"
            else c
            for c in m["proposed"]
        ]
        put = await api_client.put(f"/datasets/{ds['id']}/mapping", json={"mapping": rows})
        assert put.status_code == 200, put.text
        saved = next(c for c in put.json()["confirmed"] if c["source_column"] == "Pilots live")
        assert saved["canonical_field"] == "custom.active_pilots" and saved["label"] == "Active pilots"
        assert saved["unit"] == "count"
        # Every table of the engagement is offered the custom field.
        targets = {t["id"]: t for t in put.json()["targets"]}
        assert targets["custom.active_pilots"]["label"] == "Active pilots"
        # The engine keeps it as one labelled series.
        ctx = await engagements.context(eng["id"])
        assert ctx.model.raw["custom.active_pilots"] == {"2025-01": 2.0, "2025-02": 3.0, "2025-03": 5.0}
        assert ctx.model.raw_label["custom.active_pilots"] == "Active pilots"

        bad = [{**c, "canonical_field": "custom.Bad Id!"} for c in rows]
        assert (
            await api_client.put(f"/datasets/{ds['id']}/mapping", json={"mapping": bad})
        ).status_code == 422

        # The confirmed-knowledge note says how the column is read, and repeats no figure.
        nid = await truthnote.write(eng["id"])
        content = await db.fetchval("select content from kb_notes where id = $1::uuid", nid)
        assert "“Pilots live” is read as Active pilots (a custom field)" in content
        assert "130" not in content
    finally:
        await db.execute("delete from kb_notes where meta->>'generated' = 'confirmed_kb'")
        await db.execute("delete from engagements where id::text = $1", eng["id"])
