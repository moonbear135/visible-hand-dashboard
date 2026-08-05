import json
import os
from collector_kospi200 import enrich_quant_metrics

base_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(base_dir, "data", "kospi200_pegy_latest.json")

with open(json_path, "r", encoding="utf-8") as f:
    payload = json.load(f)

stocks = payload.get("stocks", [])
test_raw = [s for s in stocks if s["code"] in ["005930", "000660"]]

enriched = enrich_quant_metrics(test_raw)

for e in enriched:
    for s in stocks:
        if s["code"] == e["code"]:
            s["t_pbr"] = e.get("t_pbr")
            s["ev_ebitda"] = e.get("ev_ebitda")

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("Updated kospi200_pegy_latest.json with PBR and EV/EBITDA for Samsung and SK Hynix.")
