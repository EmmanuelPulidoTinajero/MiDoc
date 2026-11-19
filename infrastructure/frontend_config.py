"""Publica config.json con la URL de la API y modo de pago en el bucket del frontend (lo usa frontend_config.tf)."""
import json
import os
import subprocess

bucket = os.environ["MIDOC_FRONTEND_BUCKET"]
region = os.environ.get("AWS_REGION", "us-east-1")
payment_mode = os.environ.get("MIDOC_PAYMENT_MODE", "test").strip().lower()
if payment_mode not in {"test", "live"}:
    raise SystemExit(f"MIDOC_PAYMENT_MODE inválido: {payment_mode!r}. Use 'test' o 'live'.")

contenido = json.dumps({"apiUrl": os.environ["MIDOC_API_URL"], "paymentMode": payment_mode})
subprocess.run(
    [
        "aws",
        "s3",
        "cp",
        "-",
        f"s3://{bucket}/config.json",
        "--content-type",
        "application/json",
        "--cache-control",
        "no-cache",
        "--region",
        region,
    ],
    input=contenido.encode(),
    check=True,
)
print(f"config.json publicado en s3://{bucket} (paymentMode={payment_mode})")
