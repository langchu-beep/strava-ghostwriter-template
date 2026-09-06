import os, json, logging
from datetime import datetime
import boto3
from strava_service import StravaClient

log = logging.getLogger()
log.setLevel(logging.INFO)

secrets_client = boto3.client('secretsmanager')

def get_secrets():
    secret_id = os.environ.get('SECRET_ID', 'StravaJarvisSecrets')
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_id)
        return json.loads(resp['SecretString'])
    except Exception as e:
        log.error(f"Failed to get secrets: {e}")
        return {}

def handler(event, context):
    try:
        secrets = get_secrets()
        os.environ['STRAVA_CLIENT_ID'] = secrets.get('STRAVA_CLIENT_ID', '')
        os.environ['STRAVA_CLIENT_SECRET'] = secrets.get('STRAVA_CLIENT_SECRET', '')
        os.environ['STRAVA_REFRESH_TOKEN'] = secrets.get('STRAVA_REFRESH_TOKEN', '')
        
        client = StravaClient()
        # Get recent activities (up to 30)
        recent_activities = client.get("/athlete/activities?per_page=30")
        
        report_lines = [
            "STRAVA ENGAGEMENT REPORT (LAST 30 ACTIVITIES)",
            "Here is the data on which titles/captions generated the most engagement (Kudos and Comments).",
            "Learn from this to understand Ashish's audience preferences. Avoid styles that get low engagement.",
            ""
        ]
        
        # Sort by total engagement (comments + kudos)
        activities = []
        for act in recent_activities:
            kudos = act.get("kudos_count", 0)
            comments = act.get("comment_count", 0)
            score = (comments * 2) + kudos # Weight comments slightly more
            activities.append({
                "name": act.get("name", ""),
                "kudos": kudos,
                "comments": comments,
                "score": score
            })
            
        activities.sort(key=lambda x: x["score"], reverse=True)
        
        report_lines.append("TOP 5 MOST ENGAGING RECENT ACTIVITIES:")
        for a in activities[:5]:
            report_lines.append(f"- TITLE: \"{a['name']}\" | KUDOS: {a['kudos']} | COMMENTS: {a['comments']}")
            
        report_lines.append("\nBOTTOM 5 LEAST ENGAGING RECENT ACTIVITIES (Avoid this style):")
        for a in activities[-5:]:
            report_lines.append(f"- TITLE: \"{a['name']}\" | KUDOS: {a['kudos']} | COMMENTS: {a['comments']}")
            
        report_text = "\n".join(report_lines)
        
        # Save to S3
        s3 = boto3.client('s3')
        bucket = os.environ.get("HISTORY_BUCKET")
        key = "memory/engagement_report.txt"
        s3.put_object(Bucket=bucket, Key=key, Body=report_text)
        
        log.info("Engagement report saved to S3.")
        
        # Trigger Ingestion
        kb_id = os.environ.get("KNOWLEDGE_BASE_ID")
        ds_id = os.environ.get("DATA_SOURCE_MEMORY_ID")
        
        if kb_id and ds_id:
            bedrock_agent = boto3.client('bedrock-agent', region_name='us-east-1')
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id
            )
            log.info("Triggered ingestion job for engagement report.")
            
        return {"statusCode": 200, "body": report_text}
        
    except Exception as e:
        log.error(f"Error in engagement sync: {e}")
        return {"statusCode": 500, "body": str(e)}
