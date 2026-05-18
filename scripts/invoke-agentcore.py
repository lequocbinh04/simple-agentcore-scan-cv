"""Invoke the deployed CV Scanner agent on AgentCore Runtime."""

import json
import os
import sys
import uuid

import boto3


REGION = os.getenv("AWS_REGION", "us-east-1")
PROFILE = os.getenv("AWS_PROFILE", "account_test")


def main():
    agent_arn = os.getenv("AGENT_RUNTIME_ARN")
    if not agent_arn:
        print("ERROR: Set AGENT_RUNTIME_ARN environment variable")
        sys.exit(1)

    s3_bucket = os.getenv("TEST_S3_BUCKET")
    s3_key = os.getenv("TEST_S3_KEY")
    if not s3_bucket or not s3_key:
        print("ERROR: Set TEST_S3_BUCKET and TEST_S3_KEY environment variables")
        sys.exit(1)

    job_description = os.getenv("TEST_JD", (
        "We are looking for a Senior Python Developer with 5+ years of experience. "
        "Required skills: Python, AWS, Docker, REST APIs, PostgreSQL. "
        "Nice to have: Machine Learning, Terraform, CI/CD pipelines."
    ))

    payload = {
        "s3_bucket": s3_bucket,
        "s3_key": s3_key,
        "job_description": job_description,
        "model_config": {
            "model_id": os.getenv("DEFAULT_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"),
            "temperature": 0.3,
            "max_tokens": 4096,
        },
    }

    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    client = session.client("bedrock-agentcore", region_name=REGION)

    session_id = str(uuid.uuid4())
    print(f"=== Invoking CV Scanner on AgentCore ===")
    print(f"ARN: {agent_arn}")
    print(f"CV:  s3://{s3_bucket}/{s3_key}")
    print(f"Session: {session_id}")
    print("Processing...\n")

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=json.dumps(payload),
        qualifier="DEFAULT",
    )

    response_body = response["response"].read()
    result = json.loads(response_body)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
