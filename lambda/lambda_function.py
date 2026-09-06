import json, os, boto3, re, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from strava_service import StravaClient

TZ = ZoneInfo("America/Chicago")
START = datetime(2023, 12, 30).date()
log = logging.getLogger()
log.setLevel(logging.INFO)

sc = StravaClient()
s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime')
agent = boto3.client('bedrock-agent-runtime')
ses = boto3.client('ses')

SHADOW_MODE = True
SHADOW_EMAIL = "ashish.mainali@icloud.com"

def invoke_model(model_id, sys_prompt, user_prompt):
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        })
        resp = bedrock.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body
        )
        return json.loads(resp['body'].read())['content'][0]['text']
    except Exception as e:
        log.error(f"Bedrock Error ({model_id}): {e}")
        return str(e)

def handler(event, context):
    for record in event.get('Records', []):
        body = json.loads(record['body'])
        if body.get('object_type') != 'activity' or body.get('aspect_type') not in ('create', 'update'):
            continue
            
        if body.get("aspect_type") == "update" and "title" in body.get("updates", {}):
            if re.match(r"^Day \d+\s+🔥+\s*\|", body["updates"]["title"].strip()):
                log.info("Already prefixed.")
                continue

        aid = body.get('object_id')
        if not aid: continue
        
        try:
            act = sc.get(f"/activities/{aid}")
        except Exception as e:
            log.error(f"Failed to fetch activity {aid}: {e}")
            continue
            
        orig_title = (act.get("name") or "Untitled Activity").strip()
        start_local = datetime.fromisoformat(act["start_date_local"]).replace(tzinfo=TZ)
        day_num     = (start_local.date() - START).days + 1
        fire        = "🔥" * sc.ordinal_in_day(aid, start_local)
        prefix      = f"Day {day_num} {fire} | "
        
        if orig_title.startswith(prefix):
            continue
            
        # 1. Fetch Garmin & Pinecone Data (Data Grabber)
        today_str = start_local.strftime("%Y-%m-%d")
        yest_str = (start_local - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        bucket = os.environ.get("HISTORY_BUCKET")
        
        garmin_context = ""
        for d in [today_str, yest_str]:
            try:
                garmin_context += s3.get_object(Bucket=bucket, Key=f"memory/garmin_{d}.txt")['Body'].read().decode('utf-8') + "\n"
            except Exception: pass
            
        rag_context = ""
        try:
            resp = agent.retrieve(
                knowledgeBaseId=os.environ.get("KB_ID"),
                retrievalQuery={'text': f"training analysis for {act.get('type')} distance {act.get('distance')} title {orig_title}"},
                retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': 2}}
            )
            for r in resp.get('retrievalResults', []):
                rag_context += r['content']['text'] + "\n"
        except Exception: pass
        
        memory_context = f"GARMIN HEALTH DATA:\n{garmin_context}\n\nPAST HISTORY:\n{rag_context}"
        
        # 2. Analyst Agent (Sonnet 5)
        log.info("Running Analyst Agent...")
        sys_analyst = "You are an elite sports data analyst. Calculate pace deltas, compare HR/effort to past runs, and extract interesting physiological anomalies. Return a concise bulleted list."
        usr_analyst = f"Activity: {json.dumps(act)}\nHistory: {memory_context}"
        analysis = invoke_model("us.anthropic.claude-sonnet-4-6", sys_analyst, usr_analyst)
        
        # 3. Router Agent (Sonnet 5)
        log.info("Running Router Agent...")
        sys_router = "You are a strategist. Read the analysis and choose exactly ONE word: EPIC (for massive PRs/long distance), SURVIVAL (for brutal heat/low sleep), or SNARK (for normal/easy recovery runs)."
        usr_router = f"Analysis: {analysis}\nRoute:"
        route_raw = invoke_model("us.anthropic.claude-sonnet-4-6", sys_router, usr_router).strip().upper()
        route = "EPIC" if "EPIC" in route_raw else "SURVIVAL" if "SURVIVAL" in route_raw else "SNARK"
        
        # 4. Writer Agent (Opus 5)
        log.info(f"Running Writer Agent (Route: {route})...")
        try:
            with open("prompt_rules.txt", "r") as f:
                base_vibe = f.read()
        except:
            base_vibe = "Write a short Strava post."
            
        if route == "EPIC":
            spec_sys = base_vibe + "\n\nSTRATEGY: EPIC. Massive run. Sprinkle in a brief historical fact or savage quote. Compare effort to something grand."
        elif route == "SURVIVAL":
            spec_sys = base_vibe + "\n\nSTRATEGY: SURVIVAL. Run was brutal (heat, low sleep). Roast the terrible conditions and his life choices."
        else:
            spec_sys = base_vibe + "\n\nSTRATEGY: SNARK. Casual/normal run. Provide grounded, dry, self-deprecating snark. Don't overhype it."
            
        usr_writer = f"Activity: {json.dumps(act)}\nAnalyst Report: {analysis}\n\nLine 1: Title Hook. Remaining lines: Body."
        post_raw = invoke_model("us.anthropic.claude-opus-4-6-v1", spec_sys, usr_writer)
        
        # 5. Format Output
        post_raw = post_raw.strip()
        lines = [l for l in post_raw.split('\n') if l.strip()]
        if not lines:
            log.error("AI returned empty string.")
            continue
            
        title_from_ai = lines[0].replace('*', '').replace('#', '').replace('Title:', '').strip()
        new_title = prefix + title_from_ai
        body = '\n\n'.join(lines[1:]).strip()
        full_description = body + "\n\n— Ashish's ghost writer"
        
        # 6. Execute (Shadow Mode vs Live)
        if SHADOW_MODE:
            log.info("SHADOW MODE ON. Sending email instead of updating Strava.")
            email_body = f"--- SHADOW MODE STRAVA POST ---\n\nROUTE CHOSEN: {route}\n\nTITLE: {new_title}\n\nDESCRIPTION:\n{full_description}\n\n--- ANALYST REPORT ---\n{analysis}"
            try:
                ses.send_email(
                    FromEmailAddress="jarvis@lightworkrunclub.com",
                    Destination={'ToAddresses': [SHADOW_EMAIL]},
                    Content={
                        'Simple': {
                            'Subject': {'Data': f"[SHADOW] Strava Ghostwriter: {orig_title}"},
                            'Body': {'Text': {'Data': email_body}}
                        }
                    }
                )
            except Exception as e:
                log.error(f"Failed to send shadow email: {e}")
        else:
            try:
                sc.put(f"/activities/{aid}", {"name": new_title, "description": full_description})
                log.info("Updated %s -> %s", aid, new_title)
            except Exception as e:
                log.error(f"Failed to update Strava {aid}: {e}")
