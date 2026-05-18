"""CV Scanner Agent — reviews CVs against job descriptions using Strands SDK + AgentCore."""

import json
import logging
import os

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from prompts.cv_review_system_prompt import SYSTEM_PROMPT
from tools.s3_pdf_reader import read_pdf_from_s3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


def build_agent(model_config: dict) -> Agent:
    """Build a Strands agent with the given model configuration."""
    model_id = model_config.get("model_id", os.getenv("DEFAULT_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"))
    temperature = model_config.get("temperature", float(os.getenv("DEFAULT_TEMPERATURE", "0.3")))
    max_tokens = model_config.get("max_tokens", int(os.getenv("DEFAULT_MAX_TOKENS", "4096")))
    region = model_config.get("region", os.getenv("AWS_REGION", "us-east-1"))

    boto_session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE"),
        region_name=region,
    )

    bedrock_model = BedrockModel(
        model_id=model_id,
        boto_session=boto_session,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=False,
    )

    return Agent(
        model=bedrock_model,
        tools=[read_pdf_from_s3],
        system_prompt=SYSTEM_PROMPT,
    )


@app.entrypoint
def invoke(payload: dict) -> dict:
    """Process a CV review request.

    Expected payload:
    {
        "s3_bucket": "my-cv-bucket",
        "s3_key": "cvs/candidate-resume.pdf",
        "job_description": "We are looking for a Senior Python Developer...",
        "model_config": {             // optional
            "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
            "temperature": 0.3,
            "max_tokens": 4096,
            "region": "us-east-1"
        }
    }
    """
    s3_bucket = payload.get("s3_bucket")
    s3_key = payload.get("s3_key")
    job_description = payload.get("job_description", "")
    model_config = payload.get("model_config", {})

    if not s3_bucket or not s3_key:
        return {"error": "Missing required fields: s3_bucket and s3_key"}

    if not job_description:
        return {"error": "Missing required field: job_description"}

    agent = build_agent(model_config)

    prompt = (
        f"Review the following CV against the job description.\n\n"
        f"## Job Description\n{job_description}\n\n"
        f"## CV Location\n"
        f"S3 Bucket: {s3_bucket}\n"
        f"S3 Key: {s3_key}\n\n"
        f"Please read the CV from S3 using the read_pdf_from_s3 tool, "
        f"then analyze it against the job description and return your structured JSON assessment."
    )

    logger.info("Processing CV review: s3://%s/%s", s3_bucket, s3_key)
    result = agent(prompt)

    # result.message can be dict or str depending on Strands version
    message = result.message
    if isinstance(message, dict):
        content = message.get("content", [])
        response_text = ""
        for block in content:
            if isinstance(block, dict) and "text" in block:
                response_text += block["text"]
            elif isinstance(block, str):
                response_text += block
        if not response_text:
            response_text = json.dumps(message)
    else:
        response_text = str(message)

    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        assessment = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        assessment = {"raw_response": response_text}

    return {"result": assessment}


if __name__ == "__main__":
    app.run()
