from __future__ import annotations
import json, os, time, urllib.request, urllib.parse, logging
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

TZ    = ZoneInfo("America/Chicago")
_log  = logging.getLogger(__name__)

class StravaClient:
    _tok, _exp = None, 0

    # ---------- token ----------------------------------------------------
    def _token(self) -> str:
        if self._tok and self._exp > time.time() + 60:
            return self._tok

        CID   = os.getenv("STRAVA_CLIENT_ID")
        CSEC  = os.getenv("STRAVA_CLIENT_SECRET")
        RTOK  = os.getenv("STRAVA_REFRESH_TOKEN")

        payload = urllib.parse.urlencode(
            dict(client_id=CID, client_secret=CSEC,
                 grant_type="refresh_token", refresh_token=RTOK)
        ).encode()

        resp = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    "https://www.strava.com/oauth/token", data=payload)
            )
        )
        self._tok, self._exp = resp["access_token"], resp["expires_at"]
        _log.debug("Refreshed Strava token exp=%s", self._exp)
        return self._tok

    # ---------- REST wrappers -------------------------------------------
    def _req(self, method: str, endpoint: str, body: dict|None=None):
        url = f"https://www.strava.com/api/v3{endpoint}"
        data = json.dumps(body).encode() if body else None
        hdrs = {"Authorization": f"Bearer {self._token()}"}
        if body: hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def get(self, endpoint: str):            return self._req("GET", endpoint)
    def put(self, endpoint: str, body: dict): return self._req("PUT", endpoint, body)

    # ---------- helpers --------------------------------------------------
    def today_activities(self, local_dt: datetime):
        mid = datetime.combine(local_dt.date(), dtime.min, tzinfo=TZ)
        nxt = mid + timedelta(days=1)
        return self.get(
            f"/athlete/activities?after={int(mid.timestamp())}"
            f"&before={int(nxt.timestamp())}&per_page=200"
        )

    def ordinal_in_day(self, aid: int, local_dt: datetime) -> int:
        todays = sorted(
            self.today_activities(local_dt),
            key=lambda a: a["start_date_local"],
        )
        for i, a in enumerate(todays, start=1):
            if a["id"] == aid:
                return i
        return 1
