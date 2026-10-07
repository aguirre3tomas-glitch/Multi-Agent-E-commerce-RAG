"""Delete the three knowledge bases and wait until they are gone.

They must be recreated because they were built with indexName, which the console
renders as an empty "S3 vector index". The replacement is created with indexArn.
"""
import pathlib
import sys
import time

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402

TARGETS = {
    "novamart-returns-policy-kb",
    "novamart-shipping-policy-kb",
    "novamart-warranty-policy-kb",
    "tmp-index-display-probe",
}

ba = boto3.client("bedrock-agent", region_name=config.AWS_REGION)


def current():
    return {k["name"]: k for k in
            ba.list_knowledge_bases().get("knowledgeBaseSummaries", [])}


# 1. delete data sources, then the knowledge base
for name, k in current().items():
    if name not in TARGETS:
        continue
    kid = k["knowledgeBaseId"]
    print(f"deleting {name} ({kid}) status={k['status']}")
    for ds in ba.list_data_sources(knowledgeBaseId=kid).get("dataSourceSummaries", []):
        try:
            ba.delete_data_source(knowledgeBaseId=kid, dataSourceId=ds["dataSourceId"])
            print(f"   data source deleted: {ds['name']}")
        except Exception as e:
            print(f"   data source {ds['name']}: {str(e)[:90]}")
    try:
        ba.delete_knowledge_base(knowledgeBaseId=kid)
        print("   knowledge base deleted")
    except Exception as e:
        print(f"   knowledge base: {str(e)[:120]}")

# 2. wait until the names are free again
print("\nwaiting for deletion to finish ...", flush=True)
deadline = time.time() + 600
while time.time() < deadline:
    left = [n for n in current() if n in TARGETS]
    if not left:
        print("all gone")
        break
    print(f"   still present: {left}", flush=True)
    time.sleep(20)
else:
    print("TIMEOUT: some knowledge bases are still there")
    sys.exit(1)

print("\nremaining knowledge bases:")
for n, k in current().items():
    print(f"   {n}  {k['knowledgeBaseId']}  {k['status']}")
print("\nnow run: python infrastructure/create_kbs.py")