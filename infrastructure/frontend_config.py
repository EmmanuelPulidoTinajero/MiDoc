"""Publica config.json con la URL de la API en el bucket del frontend (lo usa frontend_config.tf)."""
import json
import os
import subprocess

bucket = os.environ["MIDOC_FRONTEND_BUCKET"]
contenido = json.dumps({"apiUrl": os.environ["MIDOC_API_URL"]})
subprocess.run(
    ["aws", "s3", "cp", "-", f"s3://{bucket}/config.json", "--content-type", "application/json",
     "--cache-control", "no-cache"],
    input=contenido.encode(),
    check=True,
)
print(f"config.json publicado en s3://{bucket}")
