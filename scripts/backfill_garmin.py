import sys, os, json, time
from datetime import date, timedelta
import boto3
from garminconnect import Garmin

# SET THESE VARIABLES OR EXPORT THEM IN YOUR TERMINAL
BUCKET = os.getenv("S3_HISTORY_BUCKET", "your-bucket-name")
SECRET_ID = os.getenv("SECRET_NAME", "StravaGhostwriterSecrets")
KB_ID = os.getenv("BEDROCK_KB_ID", "your-knowledge-base-id")
DS_ID = os.getenv("BEDROCK_DS_ID", "your-data-source-id")
DAYS_TO_BACKFILL = 90

secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')

def get_secrets():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ID)
    return json.loads(resp['SecretString'])

def main():
    print(f"Backfilling {DAYS_TO_BACKFILL} days of Garmin data to {BUCKET}...")
    secrets = get_secrets()
    email = secrets.get('GARMIN_EMAIL')
    password = secrets.get('GARMIN_PASSWORD')
    tokens = secrets.get('GARMIN_TOKENS')
    
    token_dir = '/tmp/garmin_tokens'
    os.makedirs(token_dir, exist_ok=True)
    
    if tokens:
        tokens_dict = json.loads(tokens)
        for k, v in tokens_dict.items():
            with open(os.path.join(token_dir, k), 'w') as f: json.dump(v, f)
    
    client = Garmin(email, password)
    client.login(token_dir)
    print("Garmin Logged in successfully!")
    
    today = date.today()
    
    for i in range(1, DAYS_TO_BACKFILL + 1):
        d = (today - timedelta(days=i)).isoformat()
        try:
            stats = client.get_stats(d) or {}
            sleep = client.get_sleep_data(d) or {}
            hrv = client.get_hrv_data(d) or {}
            
            sleep_score = sleep.get('dailySleepDTO', {}).get('sleepScores', {}).get('overall', {}).get('value', 'N/A')
            sleep_time_seconds = sleep.get('dailySleepDTO', {}).get('sleepTimeSeconds', 0)
            sleep_hours = round(sleep_time_seconds / 3600, 1) if sleep_time_seconds else 'N/A'
            
            hrv_status = hrv.get('hrvSummary', {}).get('status', 'N/A')
            hrv_value = hrv.get('hrvSummary', {}).get('weeklyAvg', 'N/A')
            
            body_battery = stats.get('bodyBatteryHighestValue', 'N/A')
            resting_hr = stats.get('restingHeartRate', 'N/A')
            
            summary = f"GARMIN HEALTH SYNC ({d})\nSleep: {sleep_hours} hours (Score: {sleep_score})\nHRV Status: {hrv_status} (Weekly Avg: {hrv_value})\nResting Heart Rate: {resting_hr} bpm\nBody Battery (High): {body_battery}/100\n"
            
            key = f"memory/garmin_{d}.txt"
            s3_client.put_object(Bucket=BUCKET, Key=key, Body=summary)
            print(f"[{i}/{DAYS_TO_BACKFILL}] Saved {key}")
            
            time.sleep(2)
        except Exception as e:
            print(f"[{i}/{DAYS_TO_BACKFILL}] Error fetching {d}: {e}")
            time.sleep(5)

    if KB_ID != "your-knowledge-base-id":
        print("\nTriggering Vector DB ingestion...")
        bedrock = boto3.client('bedrock-agent', region_name='us-east-1')
        bedrock.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
        print("Ingestion Job Triggered.")
    else:
        print("\nBedrock KB ID not set, skipping Vector DB sync.")

if __name__ == '__main__':
    main()
