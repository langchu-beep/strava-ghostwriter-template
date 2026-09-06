import os, boto3, json, ssl
ssl._create_default_https_context = ssl._create_unverified_context

sm = boto3.client('secretsmanager', region_name='us-east-1')
secrets = json.loads(sm.get_secret_value(SecretId='StravaJarvisSecrets')['SecretString'])
os.environ['STRAVA_CLIENT_ID'] = secrets['STRAVA_CLIENT_ID']
os.environ['STRAVA_CLIENT_SECRET'] = secrets['STRAVA_CLIENT_SECRET']
os.environ['STRAVA_REFRESH_TOKEN'] = secrets['STRAVA_REFRESH_TOKEN']

from strava_service import StravaClient
sc = StravaClient()
activities = sc.get("/athlete/activities?per_page=10")

latest_walk = next((a for a in activities if a['type'] == 'Walk'), None)
if latest_walk:
    aid = latest_walk['id']
    title = latest_walk['name']
    print(f"Latest Walk ID: {aid}")
    print(f"Current Title: {title}")
    
    if '|' in title:
        new_title = title.split('|', 1)[1].strip()
        print(f"Resetting to: {new_title}")
        sc.put(f"/activities/{aid}", {"name": new_title})
    else:
        print("No prefix found.")
    
    with open('latest_walk_payload.json', 'w') as f:
        json.dump({
            "Records": [
                {
                    "body": json.dumps({
                        "object_id": aid,
                        "aspect_type": "update",
                        "object_type": "activity"
                    })
                }
            ]
        }, f)
else:
    print("No walk found in the last 10 activities.")
