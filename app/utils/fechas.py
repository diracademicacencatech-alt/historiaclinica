from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

tz_bogota = ZoneInfo("America/Bogota")

def ahora_bogota():
    return datetime.now(tz_bogota)
