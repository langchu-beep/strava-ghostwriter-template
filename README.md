# 🏃‍♂️ Strava AI Ghostwriter (AWS Serverless Multi-Agent Pipeline)

An AWS-native, multi-agent AI pipeline that automatically fetches your Strava and Garmin data, analyzes your performance against historical data, and writes a highly-contextualized Strava post matching your exact tone and style.

## Architecture Highlights
- **API Gateway + SQS**: Decouples Strava Webhooks to prevent timeouts while LLMs generate text.
- **EventBridge + S3**: Automatically scrapes daily Garmin recovery metrics (Body Battery, Sleep) to inject physiological context.
- **Amazon Bedrock + Pinecone**: Serverless RAG (Retrieval-Augmented Generation) pipeline for infinite memory without the massive costs of OpenSearch.
- **Multi-Agent Bedrock Pipeline**: Data Analyst (Claude Sonnet) -> Strategist (Claude Sonnet) -> Ghostwriter (Claude Opus).

---

## 🛠️ Deployment & Setup Guide

### 1. Prerequisites & Secrets
You must have an AWS account with CDK configured, and Amazon Bedrock access enabled for **Claude Sonnet** and **Claude Opus**.

Create a secret in AWS Secrets Manager named `StravaGhostwriterSecrets` with the following JSON keys:
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`

### 2. SES Email Verification (Required for Feedback Loop)
To allow the AI to email you drafts (Shadow Mode) and to allow you to email the AI (Inbound Life Context), you must configure Amazon Simple Email Service (SES):
1. In the AWS SES Console, verify the sender email address you want to use (e.g., `you@gmail.com`).
2. **For Inbound Email:** You must verify a custom domain (e.g., `jarvis.yourdomain.com`).
3. Add the required **TXT and MX Records** provided by SES to your Route53 (or external DNS) settings to authorize AWS to receive emails on behalf of that domain.
4. Update `app.py` and the Lambda environment variables to point to your verified SES email addresses.

### 3. Deploy the Stack
```bash
npm install -g aws-cdk
pip install -r requirements.txt
cdk bootstrap
cdk deploy
```

### 4. Backfilling Historical Memory (Crucial)
After deploying, your AI will have no memory of your past runs or Garmin stats. You must backfill the data:
1. Navigate to the `/scripts` directory.
2. Run `python backfill_strava.py` to dump your last 30 activities into S3.
3. Run `python backfill_garmin.py` to pull your last 90 days of Sleep/HRV data. This script will automatically trigger the Bedrock Knowledge Base to sync this data into your Pinecone Vector DB.

### 5. Set Your Vibe Profile
Edit `lambda/prompt_rules.txt` to include your exact writing constraints, jokes, and formatting rules. This acts as the final guardrail for the Claude Opus Ghostwriter agent.
