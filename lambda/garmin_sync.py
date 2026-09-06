import json, logging, os, boto3
from datetime import datetime, date
from garminconnect import Garmin

log = logging.getLogger()
log.setLevel(logging.INFO)

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

def get_secrets():
    secret_id = os.environ.get('SECRET_ID', 'StravaJarvisSecrets')
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_id)
        return json.loads(resp['SecretString'])
    except Exception as e:
        log.error(f"Failed to get secrets: {e}")
        return {}

def start_ingestion_job(kb_id, ds_id):
    try:
        bedrock_agent = boto3.client('bedrock-agent', region_name='us-east-1')
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        log.info(f"Started ingestion for KB {kb_id}, DS {ds_id}")
    except Exception as e:
        log.error(f"Failed to start ingestion job: {e}")

def handler(event, context):
    secrets = get_secrets()
    email = secrets.get('GARMIN_EMAIL')
    password = secrets.get('GARMIN_PASSWORD')
    
    if not email or not password:
        log.error("Garmin credentials not found in Secrets Manager")
        return {"statusCode": 500, "body": "Missing credentials"}
        
    history_bucket = os.environ.get('HISTORY_BUCKET')
    kb_id = os.environ.get('KNOWLEDGE_BASE_ID')
    ds_id = os.environ.get('DATA_SOURCE_MEMORY_ID')
    
    try:
        log.info("Setting up Garmin tokens...")
        token_dir = '/tmp/garmin_tokens'
        os.makedirs(token_dir, exist_ok=True)
        
        tokens = secrets.get('GARMIN_TOKENS')
        if tokens:
            tokens_dict = json.loads(tokens)
            for k, v in tokens_dict.items():
                with open(os.path.join(token_dir, k), 'w') as f:
                    json.dump(v, f)
        
        log.info("Logging into Garmin Connect...")
        client = Garmin(email, password)
        client.login(token_dir)
        
        today = date.today().isoformat()
        
        # Fetch stats
        log.info(f"Fetching stats for {today}")
        stats = client.get_stats(today)
        sleep = client.get_sleep_data(today)
        hrv = client.get_hrv_data(today)
        
        # Build text summary
        sleep_score = sleep.get('dailySleepDTO', {}).get('sleepScores', {}).get('overall', {}).get('value', 'N/A')
        sleep_time_seconds = sleep.get('dailySleepDTO', {}).get('sleepTimeSeconds', 0)
        sleep_hours = round(sleep_time_seconds / 3600, 1)
        
        hrv_status = hrv.get('hrvSummary', {}).get('status', 'N/A')
        hrv_value = hrv.get('hrvSummary', {}).get('weeklyAvg', 'N/A')
        
        body_battery = stats.get('bodyBatteryHighestValue', 'N/A')
        resting_hr = stats.get('restingHeartRate', 'N/A')
        
        summary = f"""GARMIN HEALTH SYNC ({today})
Sleep: {sleep_hours} hours (Score: {sleep_score})
HRV Status: {hrv_status} (Weekly Avg: {hrv_value})
Resting Heart Rate: {resting_hr} bpm
Body Battery (High): {body_battery}/100
"""
        
        log.info(f"Generated Summary: \n{summary}")
        
        if history_bucket:
            key = f"memory/garmin_{today}.txt"
            s3_client.put_object(Bucket=history_bucket, Key=key, Body=summary)
            log.info(f"Saved to {key}")
            
            if kb_id and ds_id:
                start_ingestion_job(kb_id, ds_id)
                
        return {"statusCode": 200, "body": summary}
        
    except Exception as e:
        log.error(f"Failed to sync Garmin data: {e}")
        return {"statusCode": 500, "body": str(e)}
