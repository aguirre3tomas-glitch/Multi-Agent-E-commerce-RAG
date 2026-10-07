"""Create the three Bedrock Knowledge Bases backed by S3 Vectors.

Phase 3 of the project asks for these to be created in the AWS Console; this
script does the same thing through the API so the whole environment can be built
without the console. Each KB points at one S3 prefix and one vector index that
the CloudFormation stack already created.

Run from the project root:  ./venv/Scripts/python.exe infrastructure/create_kbs.py
"""
import json
import os
import pathlib
import sys
import time

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402

REGION = config.AWS_REGION
ACCT = config.ACCOUNT_ID
BUCKET = config.POLICY_BUCKET
ROLE = f"arn:aws:iam::{ACCT}:role/{config.PROJECT_NAME}-kb-role"

ba = boto3.client("bedrock-agent", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
ba_admin = boto3.client("bedrock-agent", region_name=REGION)

EMBED_ARN = f"arn:aws:bedrock:{REGION}::foundation-model/amazon.titan-embed-text-v2:0"

DOMAINS = [
    ("Returns", "novamart-returns-policy-kb", "policies/returns/", config.RETURNS_VECTOR_INDEX),
    ("Shipping", "novamart-shipping-policy-kb", "policies/shipping/", config.SHIPPING_VECTOR_INDEX),
    ("Warranty", "novamart-warranty-policy-kb", "policies/warranty/", config.WARRANTY_VECTOR_INDEX),
]


def say(text=""):
    print(text, flush=True)


# ── the KB execution role ────────────────────────────────────────────────────
def ensure_role():
    trust = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })
    try:
        iam.create_role(RoleName=config.PROJECT_NAME + "-kb-role", AssumeRolePolicyDocument=trust)
        say(f"role created: {ROLE}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        say(f"role exists: {ROLE}")

    iam.put_role_policy(
        RoleName=config.PROJECT_NAME + "-kb-role",
        PolicyName="KbAccess",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
                 "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"]},
                {"Effect": "Allow", "Action": ["bedrock:InvokeModel"], "Resource": [EMBED_ARN]},
                {"Effect": "Allow", "Action": ["s3vectors:*"],
                 "Resource": f"arn:aws:s3vectors:{REGION}:{ACCT}:*"},
            ],
        }),
    )
    say("  policy attached (s3, bedrock:InvokeModel, s3vectors)")


def existing_kb(name):
    for kb in ba.list_knowledge_bases().get("knowledgeBaseSummaries", []):
        if kb["name"] == name:
            return kb["knowledgeBaseId"]
    return None


def create_one(domain, name, prefix, index):
    say(f"\n=== {domain} KB ({name})")
    kb_id = existing_kb(name)
    if kb_id:
        say(f"  reusing {kb_id}")
    else:
        kb = ba.create_knowledge_base(
            name=name,
            description=f"NovaMart {domain.lower()} policy documents",
            roleArn=ROLE,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": EMBED_ARN,
                },
            },
            storageConfiguration={
                "type": "S3_VECTORS",
                "s3VectorsConfiguration": {
                    # the API takes the bucket ARN (not its name) plus the index name
                    "vectorBucketArn": config.VECTOR_STORE_BUCKET_ARN,
                    # indexArn, not indexName: the console renders the index from
                    # the ARN, and shows an empty dash when only the name is set.
                    "indexArn": f"{config.VECTOR_STORE_BUCKET_ARN}/index/{index}",
                },
            },
        )["knowledgeBase"]
        kb_id = kb["knowledgeBaseId"]
        say(f"  created {kb_id}")

    # wait for ACTIVE
    status = None
    for _ in range(60):
        status = ba.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]["status"]
        if status in ("ACTIVE", "FAILED"):
            break
        time.sleep(10)
    say(f"  status: {status}")
    if status == "FAILED":
        say(f"  reasons: {ba.get_knowledge_base(knowledgeBaseId=kb_id)['knowledgeBase'].get('failureReasons')}")
        return None

    # data source on the domain's prefix
    ds_ids = [d["dataSourceId"] for d in
              ba.list_data_sources(knowledgeBaseId=kb_id).get("dataSourceSummaries", [])]
    if ds_ids:
        ds_id = ds_ids[0]
        say(f"  data source reused: {ds_id}")
    else:
        ds = ba.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"{domain.lower()}-policies-s3",
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{BUCKET}",
                    "inclusionPrefixes": [prefix],
                },
            },
        )["dataSource"]
        ds_id = ds["dataSourceId"]
        say(f"  data source created: {ds_id} (prefix {prefix})")

    # sync
    job = ba.start_ingestion_job(
        knowledgeBaseId=kb_id, dataSourceId=ds_id,
        description=f"seed sync {domain}",
    )["ingestionJob"]
    job_id = job["ingestionJobId"]
    for i in range(90):
        st = ba.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id,
                                  ingestionJobId=job_id)["ingestionJob"]
        stats = st.get("statistics", {})
        if st["status"] in ("COMPLETE", "FAILED"):
            break
        time.sleep(10)
    say(f"  ingestion {job_id}: {st['status']} "
        f"scanned={stats.get('documentsScanned')} indexed={stats.get('documentsIndexed')} "
        f"failed={stats.get('documentsFailed')}")
    return kb_id, ds_id


say("=" * 70)
say("KNOWLEDGE BASES")
say("=" * 70)
say(f"bucket  : {BUCKET}")
say(f"vectors : {config.VECTOR_STORE_BUCKET}")

ensure_role()
time.sleep(20)  # let IAM settle before Bedrock tries to assume it

result = {}
for domain, name, prefix, index in DOMAINS:
    out = create_one(domain, name, prefix, index)
    if out:
        result[domain] = out[0]

say("\n" + "=" * 70)
say("RESULT")
say("=" * 70)
for domain, _, _, _ in DOMAINS:
    say(f"  {domain:<10} {result.get(domain, 'FAILED')}")

# write .env
env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
existing = {}
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
existing["RETURNS_KB_ID"] = result.get("Returns", "")
existing["SHIPPING_KB_ID"] = result.get("Shipping", "")
existing["WARRANTY_KB_ID"] = result.get("Warranty", "")
existing.setdefault("AWS_REGION", REGION)
existing.setdefault("PROJECT_NAME", config.PROJECT_NAME)
env_path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8")
say(f"\n.env written: {env_path}")