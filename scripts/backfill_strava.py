import sys, os, json, time
import urllib3
import boto3

# SET THESE VARIABLES
BUCKET = os.getenv("S3_HISTORY_BUCKET", "your-bucket-name")
SECRET_ID = os.getenv("SECRET_NAME", "StravaGhostwriterSecrets")

secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')
http = urllib3.PoolManager()

def get_strava_token():
    resp = secrets_client.get_secret_value(SecretId=SECRET_ID)
    secrets = json.loads(resp['SecretString'])
    
    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": secrets['STRAVA_CLIENT_ID'],
        "client_secret": secrets['STRAVA_CLIENT_SECRET'],
        "refresh_token": secrets['STRAVA_REFRESH_TOKEN'],
        "grant_type": "refresh_token"
    }
    r = http.request('POST', url, fields=payload)
    data = json.loads(r.data.decode('utf-8'))
    return data['access_token']

def main():
    print(f"Backfilling Strava Activities to {BUCKET}...")
    token = get_strava_token()
    
    # Fetch last 30 activities
    r = http.request('GET', 'https://www.strava.com/api/v3/athlete/activities?per_page=30', headers={"Authorization": f"Bearer {token}"})
    activities = json.loads(r.data.decode('utf-8'))
    
    print(f"Found {len(activities)} activities.")
    
    for act in activities:
        act_id = act['id']
        key = f"activities/{act_id}.json"
        
        # Get detailed activity to include descriptions
        r_det = http.request('GET', f'https://www.strava.com/api/v3/activities/{act_id}', headers={"Authorization": f"Bearer {token}"})
        detailed = json.loads(r_det.data.decode('utf-8'))
        
        s3_client.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(detailed),
            ContentType="application/json"
        )
        print(f"Saved {act['name']} (ID: {act_id}) to S3")
        time.sleep(1)

    print("\nStrava backfill complete. Run backfill_garmin.py to sync Garmin data and trigger Bedrock ingestion.")

if __name__ == '__main__':
    main()
