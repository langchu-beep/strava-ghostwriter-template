# 🏃‍♂️ Strava AI Ghostwriter (Multi-Agent Pipeline)

An AWS-native, multi-agent AI pipeline that automatically fetches your Strava and Garmin data, analyzes your performance, and writes a personalized, highly-contextualized Strava post matching your exact tone and style.

## Architecture
- **API Gateway + Lambda**: Receives webhook events directly from Strava when a new activity is uploaded.
- **S3 & Bedrock Knowledge Bases**: Pulls historical Garmin recovery data (Body Battery, HRV, Sleep) and past running history (Vector DB).
- **Multi-Agent AI Pipeline (Amazon Bedrock)**:
  1. **Data Analyst (Claude Sonnet)**: Crunches the raw metrics and physiological data.
  2. **Strategic Router (Claude Sonnet)**: Classifies the run (e.g., Epic, Survival, Snark) based on effort.
  3. **Ghostwriter (Claude Opus)**: Drafts the final post using a strict user-defined "Vibe Profile".
- **Shadow Mode (AWS SES)**: Emails you the AI drafts for review before automatically posting to your Strava via API.

## Prerequisites
1. An AWS Account with CDK configured.
2. Amazon Bedrock access enabled for **Claude 3.5 Sonnet** and **Claude 3 Opus** (or 4.6+ equivalents).
3. A Strava Developer App (Client ID, Secret, Refresh Token).
4. An AWS SecretsManager secret named `StravaGhostwriterSecrets`.

## Deployment
1. Set up your `.env` variables or export AWS credentials.
2. Run `npm install -g aws-cdk` and `pip install -r requirements.txt`.
3. Run `cdk bootstrap` and `cdk deploy`.
4. Update `lambda/prompt_rules.txt` with your personalized writing constraints.
