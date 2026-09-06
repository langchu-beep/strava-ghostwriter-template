import os
import boto3
import json
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

# 1. Get Secrets to set up Strava Client
print("Fetching secrets...")
sm = boto3.client('secretsmanager', region_name='us-east-1')
secrets = json.loads(sm.get_secret_value(SecretId='StravaJarvisSecrets')['SecretString'])
os.environ['STRAVA_CLIENT_ID'] = secrets['STRAVA_CLIENT_ID']
os.environ['STRAVA_CLIENT_SECRET'] = secrets['STRAVA_CLIENT_SECRET']
os.environ['STRAVA_REFRESH_TOKEN'] = secrets['STRAVA_REFRESH_TOKEN']

# 2. Reset Activity Title
print("Connecting to Strava...")
from strava_service import StravaClient
sc = StravaClient()
aid = 10697270389
act = sc.get(f"/activities/{aid}")
title = act.get('name', '')
print("Current title:", title)

if '|' in title:
    new_title = title.split('|', 1)[1].strip()
    print(f"Resetting title to: {new_title}")
    sc.put(f"/activities/{aid}", {"name": new_title})
    print("Title reset successfully.")
else:
    print("No prefix found, ready to test.")

