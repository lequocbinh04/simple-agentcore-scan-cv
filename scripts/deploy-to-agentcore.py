"""Deploy the CV Scanner agent to Amazon Bedrock AgentCore Runtime."""

import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

# AgentCore names: [a-zA-Z][a-zA-Z0-9_]{0,47} — no hyphens allowed
AGENT_NAME = "agris_cv_scanner"
ECR_REPO_NAME = "agris-cv-scanner"
REGION = os.getenv("AWS_REGION", "us-east-1")
PROFILE = os.getenv("AWS_PROFILE", "account_test")
ROLE_NAME = "AgrisCVScannerAgentCoreRole"


def get_account_id(session: boto3.Session) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def ensure_execution_role(session: boto3.Session) -> str:
    """Create or get the AgentCore execution role with required permissions."""
    iam = session.client("iam")
    account_id = get_account_id(session)

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:*"
                    },
                },
            }
        ],
    }

    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        arn = role["Role"]["Arn"]
        print(f"Role exists: {arn}")
        return arn
    except iam.exceptions.NoSuchEntityException:
        pass

    print(f"Creating IAM role: {ROLE_NAME}")
    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="Execution role for Agris CV Scanner on AgentCore",
    )
    arn = role["Role"]["Arn"]

    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": "arn:aws:s3:::*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
        ],
    }

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="AgrisCVScannerPolicy",
        PolicyDocument=json.dumps(inline_policy),
    )

    print(f"Created role: {arn}")
    print("Waiting 10s for IAM propagation...")
    time.sleep(10)
    return arn


def create_ecr_repo(session: boto3.Session) -> str:
    ecr = session.client("ecr", region_name=REGION)
    try:
        response = ecr.create_repository(
            repositoryName=ECR_REPO_NAME,
            imageScanningConfiguration={"scanOnPush": True},
        )
        uri = response["repository"]["repositoryUri"]
        print(f"Created ECR repo: {uri}")
        return uri
    except ecr.exceptions.RepositoryAlreadyExistsException:
        response = ecr.describe_repositories(repositoryNames=[ECR_REPO_NAME])
        uri = response["repositories"][0]["repositoryUri"]
        print(f"ECR repo exists: {uri}")
        return uri


def build_and_push_image(session: boto3.Session, ecr_uri: str):
    account_id = get_account_id(session)
    registry = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com"

    print("\n--- Building Docker image (arm64) ---")
    os.system(f"docker buildx build --platform linux/arm64 -t {ecr_uri}:latest --load .")

    print("\n--- Logging in to ECR ---")
    os.system(
        f"aws ecr get-login-password --region {REGION} --profile {PROFILE} "
        f"| docker login --username AWS --password-stdin {registry}"
    )

    print("\n--- Pushing image to ECR ---")
    os.system(f"docker push {ecr_uri}:latest")
    print(f"Image pushed: {ecr_uri}:latest")


def create_agent_runtime(session: boto3.Session, ecr_uri: str, role_arn: str) -> str:
    client = session.client("bedrock-agentcore-control", region_name=REGION)

    print(f"\n--- Creating AgentCore Runtime: {AGENT_NAME} ---")
    try:
        response = client.create_agent_runtime(
            agentRuntimeName=AGENT_NAME,
            agentRuntimeArtifact={
                "containerConfiguration": {
                    "containerUri": f"{ecr_uri}:latest",
                }
            },
            networkConfiguration={"networkMode": "PUBLIC"},
            roleArn=role_arn,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        print(f"ERROR {code}: {msg}")
        if code == "AccessDeniedException":
            if "iam:PassRole" in msg:
                print(f"  -> User needs iam:PassRole for: {role_arn}")
            elif "assume" in msg.lower():
                print(f"  -> Role trust policy must allow bedrock-agentcore.amazonaws.com for region {REGION}")
            else:
                print("  -> Check IAM permissions: BedrockAgentCoreFullAccess")
        elif code == "ConflictException":
            print(f"  -> Runtime '{AGENT_NAME}' already exists. Updating...")
            return update_agent_runtime(client, ecr_uri)
        raise

    arn = response["agentRuntimeArn"]
    print(f"Agent Runtime ARN: {arn}")
    return wait_for_active(client, arn)


def update_agent_runtime(client, ecr_uri: str) -> str:
    """Update existing runtime with new image."""
    runtimes = client.list_agent_runtimes(maxResults=50)
    for rt in runtimes.get("agentRuntimeSummaries", []):
        if rt["agentRuntimeName"] == AGENT_NAME:
            arn = rt["agentRuntimeArn"]
            client.update_agent_runtime(
                agentRuntimeId=arn.split("/")[-1],
                agentRuntimeArtifact={
                    "containerConfiguration": {
                        "containerUri": f"{ecr_uri}:latest",
                    }
                },
            )
            print(f"Updated runtime: {arn}")
            return wait_for_active(client, arn)
    raise RuntimeError(f"Runtime '{AGENT_NAME}' not found for update")


def wait_for_active(client, arn: str) -> str:
    runtime_id = arn.split("/")[-1]
    print("Waiting for runtime to become ACTIVE...")
    for _ in range(30):
        time.sleep(10)
        desc = client.get_agent_runtime(agentRuntimeId=runtime_id)
        status = desc["status"]
        print(f"  Status: {status}")
        if status == "ACTIVE":
            print(f"Runtime is ACTIVE: {arn}")
            return arn
        if status == "FAILED":
            print(f"ERROR: Runtime creation FAILED")
            print(f"  Reason: {desc.get('statusReasons', 'unknown')}")
            sys.exit(1)
    print("ERROR: Timed out waiting for ACTIVE status")
    sys.exit(1)


def main():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    account_id = get_account_id(session)
    print(f"Account: {account_id} | Region: {REGION} | Profile: {PROFILE}")

    role_arn = os.getenv("AGENTCORE_ROLE_ARN")
    if not role_arn:
        print("\nNo AGENTCORE_ROLE_ARN set — creating/reusing execution role...")
        role_arn = ensure_execution_role(session)
    print(f"Role: {role_arn}")

    ecr_uri = create_ecr_repo(session)
    build_and_push_image(session, ecr_uri)
    arn = create_agent_runtime(session, ecr_uri, role_arn)

    print(f"\n=== Deployment Complete ===")
    print(f"Agent Runtime ARN: {arn}")
    print(f"\nTo invoke:")
    print(f"  AGENT_RUNTIME_ARN='{arn}' python scripts/invoke-agentcore.py")


if __name__ == "__main__":
    main()
