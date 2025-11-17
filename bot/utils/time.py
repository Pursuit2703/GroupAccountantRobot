
from datetime import datetime, timedelta, timezone
from bot.config import DB_TIMEZONE_OFFSET

def get_now_in_configured_timezone() -> datetime:
    """
    Parses the DB_TIMEZONE_OFFSET string and returns the current time
    in that timezone.
    """
    try:
        parts = DB_TIMEZONE_OFFSET.split()
        offset_val = int(parts[0])
        offset_unit = parts[1]

        if 'hour' in offset_unit:
            td = timedelta(hours=offset_val)
        elif 'minute' in offset_unit:
            td = timedelta(minutes=offset_val)
        else:
            # Default to UTC if the unit is not recognized
            td = timedelta(hours=0)
        
        tz = timezone(td)
        return datetime.now(tz)
    except Exception:
        # Default to UTC on any parsing error
        return datetime.now(timezone.utc)
