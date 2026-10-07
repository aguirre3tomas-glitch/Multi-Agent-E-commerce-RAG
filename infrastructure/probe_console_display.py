"""Create a throwaway KB with indexArn so the console display can be checked.

The three real KBs were created with indexName, and the console renders their
"S3 vector index" as an empty dash. This probe is identical except it passes
indexArn, so opening it in the console answers whether recreating the real ones
would make the index visible.
"""
import pathlib
import sys
import time

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402

BUCKET = config.VECTOR_STORE_BUCKET_ARN
PROBE = "tmp-index-display-probe"

ba = boto3.client("bedrock-agent", region_name=config.AWS_REGION)

# remove a leftover probe from an earlier run
for k in ba.list_knowledge_bases().get("knowledgeBaseSummaries", []):
    if k["name"] == PROBE:
        print("deleting leftover probe", k["knowledgeBaseId"])
        ba.delete_knowledge_base(knowledgeBaseId=k["knowledgeBaseId"])
        time.sleep(20)

created = ba.create_knowledge_base(
    name=PROBE,
    description="throwaway probe: created with indexArn instead of indexName",
    roleArn=f"arn:aws:iam::{config.ACCOUNT_ID}:role/{config.PROJECT_NAME}-kb-role",
    knowledgeBaseConfiguration={
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
            "embeddingModelArn": ("arn:aws:bedrock:us-east-1::foundation-model/"
                                  "amazon.titan-embed-text-v2:0"),
        },
    },
    storageConfiguration={
        "type": "S3_VECTORS",
        "s3VectorsConfiguration": {
            "vectorBucketArn": BUCKET,
            "indexArn": f"{BUCKET}/index/returns-policy-index",
        },
    },
)["knowledgeBase"]

kb_id = created["knowledgeBaseId"]
print(f"probe created: {PROBE}   id={kb_id}")

for _ in range(25):
    d = ba.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
    if d["status"] != "CREATING":
        break
    time.sleep(6)

print("status:", d["status"])
print("console URL to open:")
print(f"  https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1"
      f"#/knowledge-bases/{kb_id}")
print()
print("what to look for: the 'Vector store' section -> 'S3 vector index'")
print("  if it shows 'returns-policy-index' -> recreating fixes it")
print("  if it still shows a dash          -> recreating does NOT fix it")