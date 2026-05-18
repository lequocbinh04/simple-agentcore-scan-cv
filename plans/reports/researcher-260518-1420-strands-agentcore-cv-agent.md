# Research Report: Strands SDK + AgentCore + CV Processing Agent

**Date:** 2026-05-18 | **Scope:** Implementation research for PDF CV analysis agent on Amazon Bedrock AgentCore

---

## 1. Strands Agents SDK (Python)

### Installation

```bash
pip install strands-agents strands-agents-tools bedrock-agentcore
```

Python 3.10+ required. `strands-agents-tools` is a separate package for built-in tools.

### Core Concepts

**Agent creation:**
```python
from strands import Agent, tool
from strands.models import BedrockModel

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    temperature=0.3,
    max_tokens=4096,
    streaming=True,
)
agent = Agent(model=model, tools=[my_tool])
result = agent("analyze this text")
```

**Custom tool with decorator:**
```python
@tool
def my_tool(param: str) -> str:
    """Tool description — the LLM uses this docstring to know when to call the tool."""
    return do_something(param)
```

Type hints + docstring are mandatory: Strands converts them into a tool spec for the model.

### BedrockModel Parameters

| Parameter | Type | Notes |
|---|---|---|
| `model_id` | str | Required. Use cross-region prefix: `us.anthropic.claude-*` |
| `temperature` | float | 0–1. Lower = more deterministic |
| `max_tokens` | int | Max generation length |
| `streaming` | bool | Default: True |
| `top_p` | float | Nucleus sampling |
| `boto_session` | Session | Custom boto3 session for credentials |
| `region_name` | str | Falls back to env `AWS_REGION`, then `us-west-2` |
| `cache_config` | dict | Prompt caching (reduces cost; expires after 5 min) |
| `guardrail_id` | str | Content guardrails |

**Common model IDs:**
- `us.anthropic.claude-sonnet-4-20250514-v1:0` — recommended, strong reasoning
- `us.amazon.nova-pro-v1:0` — lower cost
- `us.amazon.nova-premier-v1:0` — highest capability Amazon model

### Structured Output (critical for CV scoring)

```python
from pydantic import BaseModel, Field
from strands import Agent

class CVAnalysis(BaseModel):
    score: int = Field(description="Score from 0-100")
    pros: list[str] = Field(description="List of strengths")
    cons: list[str] = Field(description="List of weaknesses")
    summary: str = Field(description="Brief assessment")

agent = Agent(model=model)
result = agent(
    "Analyze this CV: ...",
    structured_output_model=CVAnalysis
)
analysis: CVAnalysis = result.structured_output
```

Works via tool-use internally — compatible with all Strands model providers.

**Note:** Known issue [#1239](https://github.com/strands-agents/sdk-python/issues/1239): `structured_output_model` does not force JSON mode at the model level; it uses tool-calling to coerce output. Works reliably in practice but may fail on edge-case LLM refusals.

### Built-in Tools (strands-agents-tools)

| Tool | Purpose |
|---|---|
| `use_aws` | Generic boto3 wrapper — any AWS service |
| `file_read` | Read local files (PDF, CSV, DOCX, XLSX) |
| `python_repl` | Execute Python code |
| `http_request` | HTTP calls |
| `shell` | Shell commands |

`file_read` can parse PDFs directly (uses underlying libraries). `use_aws` can do S3 `get_object` but returns raw bytes — not ideal for PDF parsing.

---

## 2. Custom S3 + PDF Tool (Recommended Pattern)

The `use_aws` tool is a generic bridge; for PDF-from-S3, a custom `@tool` is cleaner and gives the LLM a precise interface:

```python
import boto3
import pypdf
import io
from strands import tool

@tool
def read_pdf_from_s3(bucket: str, key: str) -> str:
    """
    Read a PDF file from S3 and return its text content.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key (path to the PDF file)
    
    Returns:
        Extracted text content from the PDF
    """
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = response["Body"].read()
    
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    
    return text.strip()
```

**Dependencies to add:** `pypdf>=4.0.0` (pure Python, no system deps). Alternative: `pdfplumber` for better table extraction.

---

## 3. Amazon Bedrock AgentCore

### What It Is

Managed serverless runtime for AI agents. GA since October 2025.
- Runs agent code in isolated microVMs (per-session)
- Handles scaling, auth, observability, versioning
- Supports HTTP, MCP, A2A, WebSocket protocols
- Sessions last up to 8h; idle timeout 15 min
- 100MB payload limit

### Architecture

```
Client → InvokeAgentRuntime (boto3) → AgentCore Runtime Endpoint → microVM (agent code)
                                              ↑
                                    ECR image or CodeZip artifact
```

Each Runtime has:
- **Versions** — immutable snapshots on each deploy
- **Endpoints** — named access points (DEFAULT auto-created, custom for dev/prod)

### Two Deployment Paths

| Path | Tool | Best For |
|---|---|---|
| **AgentCore CLI** (recommended) | `npm install -g @aws/agentcore` | New projects, fastest |
| **Starter Toolkit** (legacy) | `pip install bedrock-agentcore-starter-toolkit` | Existing scripts |

The new CLI (`@aws/agentcore`) uses CDK under the hood, supports CodeZip (no Docker) or Container build, and includes a local dev server with hot reload (`agentcore dev`).

---

## 4. Deploying a Strands Agent to AgentCore

### Option A: AgentCore CLI (Recommended)

**Install:**
```bash
npm install -g @aws/agentcore
```

**Scaffold:**
```bash
agentcore create \
  --name CVAnalyzerAgent \
  --framework Strands \
  --model-provider Bedrock \
  --memory none \
  --build CodeZip
```

This generates:
```
CVAnalyzerAgent/
├── agentcore/
│   ├── agentcore.json
│   └── aws-targets.json
└── app/
    └── CVAnalyzerAgent/
        ├── main.py          ← edit this
        └── pyproject.toml   ← add dependencies here
```

**main.py pattern:**
```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):
    bucket = payload.get("bucket")
    key = payload.get("key")
    
    model = BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        temperature=0.2,
    )
    agent = Agent(model=model, tools=[read_pdf_from_s3])
    
    result = agent(
        f"Read the PDF from S3 bucket '{bucket}' key '{key}', then analyze it as a CV. "
        "Score from 0-100, list pros and cons.",
        structured_output_model=CVAnalysis
    )
    
    analysis = result.structured_output
    return {
        "score": analysis.score,
        "pros": analysis.pros,
        "cons": analysis.cons,
        "summary": analysis.summary
    }

if __name__ == "__main__":
    app.run()
```

**Local test:**
```bash
cd CVAnalyzerAgent
agentcore dev
# Opens browser inspector at localhost:8080
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"bucket": "my-bucket", "key": "resumes/john.pdf"}'
```

**Deploy:**
```bash
agentcore deploy
agentcore status
agentcore invoke --prompt '{"bucket":"my-bucket","key":"resumes/john.pdf"}'
```

### Option B: BedrockAgentCoreApp (Starter Toolkit, simpler for existing code)

```python
# agent.py
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel
import boto3, pypdf, io
from pydantic import BaseModel, Field

app = BedrockAgentCoreApp()

@tool
def read_pdf_from_s3(bucket: str, key: str) -> str:
    """Read PDF from S3 and return text content."""
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    reader = pypdf.PdfReader(io.BytesIO(body))
    return "\n".join(p.extract_text() for p in reader.pages)

class CVAnalysis(BaseModel):
    score: int = Field(description="0-100 score")
    pros: list[str] = Field(description="Strengths")
    cons: list[str] = Field(description="Weaknesses")
    summary: str = Field(description="Brief assessment")

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    temperature=0.2,
)
agent = Agent(model=model, tools=[read_pdf_from_s3])

@app.entrypoint
def invoke(payload: dict) -> dict:
    bucket = payload["bucket"]
    key = payload["key"]
    
    result = agent(
        f"Read the PDF at s3://{bucket}/{key} and analyze it as a CV. "
        "Provide score (0-100), pros, cons, and summary.",
        structured_output_model=CVAnalysis
    )
    
    cv = result.structured_output
    return {"score": cv.score, "pros": cv.pros, "cons": cv.cons, "summary": cv.summary}

if __name__ == "__main__":
    app.run()
```

**requirements.txt:**
```
strands-agents
bedrock-agentcore
pypdf>=4.0.0
boto3
```

**Deploy with legacy toolkit:**
```bash
pip install bedrock-agentcore-starter-toolkit
agentcore configure --entrypoint agent.py
agentcore launch
```

---

## 5. Invoking the Deployed Agent

```python
import boto3
import json
import uuid

client = boto3.client("bedrock-agentcore", region_name="us-west-2")

agent_arn = "arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/your-runtime-id"
session_id = str(uuid.uuid4())

payload = json.dumps({
    "bucket": "my-resume-bucket",
    "key": "candidates/john-doe.pdf"
}).encode()

response = client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=session_id,
    payload=payload,
)

# Handle streaming response
content = []
for chunk in response.get("response", []):
    content.append(chunk.decode("utf-8"))

result = json.loads("".join(content))
print(f"Score: {result['score']}")
print(f"Pros: {result['pros']}")
print(f"Cons: {result['cons']}")
```

**IAM permissions needed:**
- Caller: `bedrock-agentcore:InvokeAgentRuntime`
- Agent execution role: `s3:GetObject` on resume bucket, `bedrock:InvokeModel` on the model

---

## 6. Trade-off Matrix

| Concern | Strands SDK | LangChain | Raw boto3 + Bedrock |
|---|---|---|---|
| Simplicity | High — decorator-based | Medium — verbose | Low — manual |
| Structured output | Native via Pydantic | Via `.with_structured_output()` | Manual JSON parsing |
| AgentCore integration | First-class (docs + samples) | Supported | Manual HTTP wiring |
| Tool definition | Minimal boilerplate | Moderate | N/A |
| Maturity | New (May 2025), GA | Mature (2022) | Stable |
| Community | Small but AWS-backed | Very large | N/A |

| Deployment Path | Setup Time | Docker Required | Hot Reload | Recommended |
|---|---|---|---|---|
| AgentCore CLI (`@aws/agentcore`) | 5 min | No (CodeZip) | Yes | Yes — new projects |
| Starter Toolkit (legacy) | 10 min | Optional | No | For existing scripts |
| Raw AWS SDK (`create_agent_runtime`) | 30+ min | Yes (ECR) | No | Avoid unless full control needed |

---

## 7. Adoption Risk

**Strands SDK:** Released May 2025, GA. AWS-maintained, open source (Apache 2.0). 484 stars on the starter toolkit. Small community vs LangChain but growing. No significant breaking-change history yet (still pre-1.0 in some sub-packages — pin versions). Risk: **Low-Medium** — AWS has strong incentive to maintain.

**AgentCore Runtime:** GA October 2025. AWS managed service — no abandonment risk. Breaking changes follow AWS service lifecycle (years of notice). Risk: **Low**.

**Known gaps:**
- Structured output has a reported bug (#1239) — does not force JSON mode. Works via tool-calling workaround but test thoroughly.
- Starter toolkit marked legacy; migrate to `@aws/agentcore` CLI for new work.
- `agentcore dev` requires Node.js 20+ (non-obvious for Python-only teams).

---

## 8. Concrete Recommendation (Ranked)

**For this CV agent project:**

1. **Use Strands SDK** with a custom `@tool` for S3+PDF reading (cleaner than `use_aws` generic wrapper). Add `pypdf` for PDF parsing.
2. **Use `agent.structured_output`** with a Pydantic model for score/pros/cons — avoids manual JSON parsing.
3. **Deploy via `@aws/agentcore` CLI** (CodeZip, no Docker) — fastest path, best tooling (hot reload, inspector).
4. **Invoke via boto3** `invoke_agent_runtime` from the calling service.

**Stack:**
```
pypdf + boto3 (S3 read) → Strands @tool → Agent + BedrockModel (Claude Sonnet 4)
→ structured_output (Pydantic) → BedrockAgentCoreApp @entrypoint → AgentCore Runtime
```

---

## Unresolved Questions

1. **PDF quality** — `pypdf` struggles with scanned/image PDFs (no OCR). If CVs are image-based, need Amazon Textract instead of `pypdf`. Confirm PDF source format.
2. **Agent execution role** — exact IAM policy for S3 bucket access needs to be specified (bucket ARN, prefix). Does the bucket have KMS encryption?
3. **Region** — AgentCore defaults to `us-west-2`. Is that acceptable, or is a different region required?
4. **Response latency** — CV analysis may take 10–30s. Does the caller support async/streaming, or need synchronous response? (AgentCore supports both.)
5. **Multi-page PDF limit** — 100MB payload cap applies to the `invoke_agent_runtime` call, not to internal S3 reads. No issue for CVs, but confirm if CVs can be portfolios (50+ pages).
6. **Cost model** — AgentCore charges per microVM compute time, not just token count. For batch CV processing, Lambda + Bedrock direct-call may be cheaper. Validate workload pattern.

---

## Sources

- [Strands Agents SDK GitHub](https://github.com/strands-agents/sdk-python)
- [Strands Bedrock Model Docs](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/)
- [Strands Structured Output Docs](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/)
- [Strands Deploy to AgentCore (Python)](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/)
- [AgentCore Get Started with CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-cli.html)
- [AgentCore Runtime How It Works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [AgentCore Invoke Agent API](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)
- [AgentCore Starter Toolkit GitHub](https://github.com/aws/bedrock-agentcore-starter-toolkit)
- [Bedrock AgentCore SDK Python](https://github.com/aws/bedrock-agentcore-sdk-python)
- [DEV.to: AgentCore Runtime Part 2 (Strands + Starter Toolkit)](https://dev.to/aws-heroes/amazon-bedrock-agentcore-runtime-part-2-deploy-the-agent-with-the-agentcore-runtime-starter-3706)
- [DEV.to: AgentCore Runtime Part 4 (Custom Agent)](https://dev.to/aws-heroes/amazon-bedrock-agentcore-runtime-part-4-using-custom-agent-with-strands-agents-sdk-201o)
- [strands-agents-tools PyPI](https://pypi.org/project/strands-agents-tools/)
- [AWS Blog: AgentCore GA Announcement](https://aws.amazon.com/blogs/aws/introducing-amazon-bedrock-agentcore-securely-deploy-and-operate-ai-agents-at-any-scale/)
