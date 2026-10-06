"""Fetch the real X-Ray service graph and print the node/edge chain.

Used to prove that NovaMart-Orchestrator -> Worker -> KnowledgeBase* traces
actually landed, and to render a faithful service map from real API data.
"""
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402

MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 30

client = boto3.client("xray", region_name=config.AWS_REGION)
end = datetime.now(timezone.utc)
start = end - timedelta(minutes=MINUTES)

graph = client.get_service_graph(
    StartTime=start, EndTime=end, TraceGroupName=None
) if False else client.get_service_graph(StartTime=start, EndTime=end)

services = graph.get("Services", [])
print(f"window: last {MINUTES} min   services: {len(services)}")
print("=" * 72)

# node summary
nodes = {}
for s in services:
    ref = s.get("ReferenceId")
    summ = s.get("SummaryStatistics", {})
    ntype = s.get("Type", "?")
    name = s.get("Name") or (s.get("Names") or ["?"])[0]
    node = {
        "name": name,
        "type": ntype,
        "requests": summ.get("TotalCount", 0),
        "errors": summ.get("ErrorStatistics", {}).get("TotalCount", 0),
        "faults": summ.get("FaultStatistics", {}).get("TotalCount", 0),
        "avg_ms": round(summ.get("TotalResponseTime", 0), 1),
        "edges": [],
    }
    for e in s.get("Edges", []):
        node["edges"].append(e.get("ReferenceId"))
    nodes[ref] = node

for ref, n in nodes.items():
    if n["requests"] or n["type"] == "client":
        print(f"[{n['type']:<12}] {n['name']:<44} req={n['requests']:<4} "
              f"err={n['errors']} fault={n['faults']} avg={n['avg_ms']}ms")

print("=" * 72)
print("EDGES")
for ref, n in nodes.items():
    for target in n["edges"]:
        t = nodes.get(target, {})
        print(f"  {n['name']}  -->  {t.get('name','?')} ({t.get('type','?')})")

# trace summaries (proves individual traces incl. trace ids)
print("=" * 72)
summaries = client.get_trace_summaries(StartTime=start, EndTime=end).get(
    "TraceSummaries", []
)
print(f"traces in window: {len(summaries)}")
for t in sorted(summaries, key=lambda x: x.get("Duration", 0), reverse=True)[:12]:
    names = [s.get("Name") for s in t.get("ServiceIds", [])]
    print(f"  {t['Id']}  {round(t.get('Duration',0),2)}s  "
          f"{t.get('ResponseTime',0):.0f}ms  http={t.get('Http',{}).get('HttpStatus')}  "
          f"services={len(names)}")
    for nm in sorted(set(n for n in names if n)):
        print(f"        - {nm}")

out = pathlib.Path(__file__).resolve().parents[1] / "evidence" / "xray_service_graph.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"nodes": nodes, "services": services}, indent=2, default=str),
               encoding="utf-8")
print("=" * 72)
print(f"saved: {out}")