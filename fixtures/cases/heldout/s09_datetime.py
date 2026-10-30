from datetime import datetime, timedelta, timezone
import datetime as dt
now = datetime.now(tz=timezone.utc)
later = now + timedelta(days=1, hours=2)
print(later.isoformat(timespec="seconds"), dt.date.today().strftime("%Y"), now.replace(microsecond=0))
print(datetime.strptime("2024-01-01", "%Y-%m-%d").date(), dt.datetime.fromisoformat("2024-01-01T00:00:00"))
