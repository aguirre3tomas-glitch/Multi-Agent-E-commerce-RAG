"""Test whether passing indexArn makes the API store it (and the console show it).

The existing KBs were created with indexName only, which is why the console
renders "S3 vector index: -". This creates one throwaway KB using indexArn,
checks what the API reports back, then deletes it.
"""
import json
import sys
import pathlib
import time

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402

BUCKET_ARN = config.VECTOR_STORE_BUCKET_ARN
INDEX_ARN = f"{BUCKET_ARN}/index/returns-policy-index"

ba = boto3.client("bedrock-agent", region_name=config.AWS_REGION)

print("bucket arn:", BUCKET_ARN)
print("index  arn:", INDEX_ARN)
print("=" * 74)

# 1. what does an indexArn-created KB report back?
created = ba.create_knowledge_base(
    name="tmp-index-arn-probe",
    description="throwaway probe",
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
            "vectorBucketArn": BUCKET_ARN,
            "indexArn": INDEX_ARN,
        },
    },
)["knowledgeBase"]

kb_id = created["knowledgeBaseId"]
print("created probe KB:", kb_id)

for _ in range(20):
    d = ba.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
    if d["status"] != "CREATING":
        break
    time.sleep(6)

print("status:", d["status"])
print("storageConfiguration as returned:")
print(json.dumps(d.get("storageConfiguration"), indent=2, default=str))
print()
print(">>> indexArn stored? ", "YES" if d.get("storageConfiguration", {})
      .get("s3VectorsConfiguration", {}).get("indexArn") else "NO")

# 2. clean up
ba.delete_knowledge_base(knowledgeBaseId=kb_id)
print("probe KB deleted:", kb_id)