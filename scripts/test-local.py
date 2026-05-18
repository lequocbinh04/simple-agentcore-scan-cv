"""Local testing script — invokes the agent directly without AgentCore."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import invoke


def main():
    payload = {
        "s3_bucket": os.getenv("TEST_S3_BUCKET", "your-cv-bucket"),
        "s3_key": os.getenv("TEST_S3_KEY", "cvs/sample-cv.pdf"),
        "job_description": os.getenv("TEST_JD", (
            "We are looking for a Senior Python Developer with 5+ years of experience. "
            "Required skills: Python, AWS, Docker, REST APIs, PostgreSQL. "
            "Nice to have: Machine Learning, Terraform, CI/CD pipelines. "
            "The candidate should have strong communication skills and experience "
            "working in agile teams."
        )),
        "model_config": {
            "model_id": os.getenv("DEFAULT_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"),
            "temperature": 0.3,
            "max_tokens": 4096,
        },
    }

    print("=== CV Scanner Agent — Local Test ===")
    print(f"S3 Location: s3://{payload['s3_bucket']}/{payload['s3_key']}")
    print(f"Model: {payload['model_config']['model_id']}")
    print("Processing...\n")

    result = invoke(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
