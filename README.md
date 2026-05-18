# Agris CV Scanner

CV review agent built with [Strands Agents SDK](https://strandsagents.com/) + [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/agentcore/). Reads a PDF CV from S3, compares it against a job description, and returns a structured score with pros/cons.

## Architecture

```
User Request → AgentCore Runtime → Strands Agent → S3 (read PDF) → Bedrock Model → JSON Assessment
```

## Input Schema

```json
{
  "s3_bucket": "my-cv-bucket",
  "s3_key": "cvs/candidate-resume.pdf",
  "job_description": "We are looking for a Senior Python Developer with 5+ years...",
  "model_config": {
    "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
    "temperature": 0.3,
    "max_tokens": 4096,
    "region": "us-east-1"
  }
}
```

| Field | Required | Description |
|---|---|---|
| `s3_bucket` | Yes | S3 bucket containing the CV PDF |
| `s3_key` | Yes | S3 object key to the PDF file |
| `job_description` | Yes | Full text of the job description to match against |
| `model_config` | No | Override default model settings |
| `model_config.model_id` | No | Bedrock model ID (default: `anthropic.claude-sonnet-4-20250514-v1:0`) |
| `model_config.temperature` | No | Sampling temperature 0-1 (default: `0.3`) |
| `model_config.max_tokens` | No | Max output tokens (default: `4096`) |
| `model_config.region` | No | AWS region (default: `us-east-1`) |

## Output Schema

```json
{
  "result": {
    "candidate_name": "Nguyen Van A",
    "overall_score": 82,
    "category_scores": {
      "technical_skills": 90,
      "experience_relevance": 80,
      "education": 85,
      "soft_skills": 75,
      "cultural_fit": 78
    },
    "pros": [
      "5+ years Python with Django and FastAPI",
      "AWS certified, strong cloud infrastructure experience",
      "Led team of 6 engineers in previous role"
    ],
    "cons": [
      "No Docker/containerization experience mentioned",
      "Limited PostgreSQL — mostly used MongoDB",
      "No CI/CD pipeline experience listed"
    ],
    "summary": "Strong Python developer with solid AWS background. Good leadership indicators but gaps in containerization and relational databases.",
    "recommendation": "STRONG_MATCH"
  }
}
```

## Setup

### Prerequisites

- Python 3.10+
- AWS CLI configured with profile `account_test`
- S3 bucket with CV PDFs (same account as AgentCore)
- Bedrock model access enabled

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your settings
```

## Usage

### Local Test

```bash
# Set your test CV location
export AWS_PROFILE=account_test
export TEST_S3_BUCKET=your-cv-bucket
export TEST_S3_KEY=cvs/sample-cv.pdf

python scripts/test-local.py
```

### Deploy to AgentCore

```bash
# Set the IAM role ARN with ECR + Bedrock permissions
export AGENTCORE_ROLE_ARN=arn:aws:iam::123456789012:role/AgentCoreRole
export AWS_PROFILE=account_test

python scripts/deploy-to-agentcore.py
```

### Invoke Deployed Agent

```bash
export AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agris-cv-scanner-xxx
export TEST_S3_BUCKET=your-cv-bucket
export TEST_S3_KEY=cvs/sample-cv.pdf

python scripts/invoke-agentcore.py
```

### Invoke via curl (local)

```bash
python agent.py  # starts on port 8080

curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "s3_bucket": "your-cv-bucket",
    "s3_key": "cvs/sample-cv.pdf",
    "job_description": "Senior Python Developer, 5+ years, AWS, Docker, PostgreSQL",
    "model_config": {
      "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
      "temperature": 0.3
    }
  }'
```

## Project Structure

```
hangzhou/
├── agent.py                          # Main agent + AgentCore entrypoint
├── tools/
│   └── s3_pdf_reader.py              # Custom tool: read PDF from S3
├── prompts/
│   └── cv_review_system_prompt.py    # System prompt for CV analysis
├── scripts/
│   ├── test-local.py                 # Local testing without AgentCore
│   ├── deploy-to-agentcore.py        # Build, push, deploy to AgentCore
│   └── invoke-agentcore.py           # Invoke deployed agent
├── requirements.txt
├── pyproject.toml
├── Dockerfile
└── .env.example
```

## IAM Role Requirements

The AgentCore execution role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::your-cv-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"],
      "Resource": "*"
    }
  ]
}
```
