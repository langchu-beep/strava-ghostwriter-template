import ssl
ssl._create_default_https_context = ssl._create_unverified_context
from strava_service import StravaClient

sc = StravaClient()
aid = 10697270389
act = sc.get(f"/activities/{aid}")
title = act.get('name', '')
if '|' in title:
    new_title = title.split('|', 1)[1].strip()
    sc.put(f"/activities/{aid}", {"name": new_title})
    print("New title:", new_title)
else:
    print("No prefix found.")
