"""Comprueba una invocación programada real y restaura la cadencia original."""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--region", "us-east-1", "--output", "json"], text=True))


def main():
    rule = aws("events", "describe-rule", "--name", "midoc-reminders")
    start = int(time.time() * 1000)
    try:
        aws("events", "put-rule", "--name", rule["Name"], "--schedule-expression", "rate(1 minute)",
            "--state", "ENABLED", "--description", rule.get("Description", "MiDoc reminders"))
        print("Esperando una invocación automática real de EventBridge (hasta 150 segundos).", flush=True)
        deadline = time.monotonic() + 150
        events = []
        while time.monotonic() < deadline:
            result = aws("logs", "filter-log-events", "--log-group-name", "/aws/lambda/midoc-api",
                         "--start-time", str(start), "--filter-pattern", '{ $.job = "reminders" }')
            events = result.get("events", [])
            if events:
                break
            time.sleep(10)
        assert events, "No se observó ejecución programada dentro del plazo"
    finally:
        aws("events", "put-rule", "--name", rule["Name"], "--schedule-expression", rule["ScheduleExpression"],
            "--state", rule["State"], "--description", rule.get("Description", "MiDoc reminders"))
    report = {"testedAt": datetime.now(timezone.utc).isoformat(), "result": "PASS",
              "rule": rule["Name"], "restoredSchedule": rule["ScheduleExpression"],
              "automaticInvocations": [{"timestamp": event["timestamp"], "result": json.loads(event["message"])}
                                       for event in events]}
    path = Path(__file__).resolve().parents[2] / "docs/evidencia-recordatorios.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: ejecución programada en CloudWatch y cadencia original restaurada.", flush=True)


if __name__ == "__main__":
    main()
