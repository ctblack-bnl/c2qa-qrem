import json

path = "../data/ingested/records.jsonl"  # adjust if running from elsewhere

with open(path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        ext = rec.get("extraction_json") or {}
        samples = ext.get("samples", [])
        for s in samples:
            def val(field):
                v = s.get(field)
                if isinstance(v, dict):
                    return v.get("value")
                return v

            resist = val("resist_strip_chemistry")
            postfab = val("post_fabrication_surface_treatment")
            jvac = val("junction_chamber_vacuum")

            if resist or postfab or jvac:
                print("=" * 60)
                print("filename:", rec.get("filename"))
                print("sample_id:", s.get("sample_id"))
                print("resist_strip_chemistry:", resist)
                print("post_fabrication_surface_treatment:", postfab)
                print("junction_chamber_vacuum:", jvac)