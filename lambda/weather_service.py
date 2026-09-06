import os, json, urllib.request, urllib.parse, logging
from datetime import datetime, timezone

OWM_KEY = os.getenv("OWM_API_KEY")
_log = logging.getLogger(__name__)

def get_weather(lat: float, lon: float) -> str:
    """Return 'clear 29 °C' string or empty if API/key missing."""
    if not OWM_KEY or lat is None or lon is None:
        return ""

    url = ("https://api.openweathermap.org/data/3.0/onecall?"
           f"lat={lat}&lon={lon}&exclude=minutely,hourly,daily,alerts&units=metric&appid={OWM_KEY}")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            w = json.load(r)["current"]
            desc = w["weather"][0]["description"]    # e.g. light rain
            temp = round(w["temp"])
            return f"{desc} {temp} °C"
    except Exception as exc:
        _log.warning("Weather API failed: %s", exc)
        return ""
