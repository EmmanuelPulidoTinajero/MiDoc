"""Publica un build existente sin recrear el bucket ni borrar config.json."""
import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def terraform_output(name):
    return subprocess.check_output(
        ["terraform", f"-chdir={ROOT / 'infrastructure'}", "output", "-raw", name], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", help="Por defecto usa frontend_bucket_name de Terraform")
    parser.add_argument("--api-url", help="Por defecto usa api_url de Terraform")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dist", type=Path, default=ROOT / "frontend/dist/midoc-frontend")
    args = parser.parse_args()
    dist = args.dist / "browser" if (args.dist / "browser").is_dir() else args.dist
    if not (dist / "index.html").is_file():
        parser.error(f"Falta index.html en {dist}. Ejecuta primero npm run build --prefix frontend")
    bucket = args.bucket or terraform_output("frontend_bucket_name")
    api_url = (args.api_url or terraform_output("api_url")).rstrip("/")
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        parser.error("La API debe usar una URL HTTPS válida")
    subprocess.run(["aws", "s3", "sync", str(dist), f"s3://{bucket}", "--delete",
                    "--exclude", "config.json", "--cache-control", "max-age=60",
                    "--region", args.region], check=True)
    subprocess.run(["aws", "s3", "cp", "-", f"s3://{bucket}/config.json", "--content-type",
                    "application/json", "--cache-control", "no-cache", "--region", args.region],
                   input=json.dumps({"apiUrl": api_url}).encode(), check=True)
    print(f"Frontend publicado desde {dist}; config.json actualizado.")


if __name__ == "__main__":
    main()
