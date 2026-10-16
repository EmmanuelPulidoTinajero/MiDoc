"""Crea el bucket privado de expedientes con AWS CLI (sin permisos de Object Lock)."""
import json
import os
import subprocess


bucket = os.environ["MIDOC_DOCUMENTS_BUCKET"]
region = os.environ.get("AWS_REGION", "us-east-1")
frontend_bucket = os.environ["MIDOC_FRONTEND_BUCKET"]


def aws(*args: str) -> None:
    subprocess.run(["aws", *args], check=True)


def exists() -> bool:
    return subprocess.run(["aws", "s3api", "head-bucket", "--bucket", bucket],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def create() -> None:
    if not exists():
        args = ["s3api", "create-bucket", "--bucket", bucket, "--region", region]
        if region != "us-east-1":
            args.extend(["--create-bucket-configuration", f"LocationConstraint={region}"])
        aws(*args)
    aws("s3api", "put-public-access-block", "--bucket", bucket,
        "--public-access-block-configuration",
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")
    aws("s3api", "put-bucket-ownership-controls", "--bucket", bucket,
        "--ownership-controls", "Rules=[{ObjectOwnership=BucketOwnerEnforced}]")
    aws("s3api", "put-bucket-encryption", "--bucket", bucket,
        "--server-side-encryption-configuration",
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}')
    origins = ["http://localhost:4200", "http://127.0.0.1:4200",
               f"https://{frontend_bucket}.s3.{region}.amazonaws.com",
               f"http://{frontend_bucket}.s3-website-{region}.amazonaws.com"]
    cors = {"CORSRules": [{"AllowedOrigins": origins, "AllowedMethods": ["POST", "GET"],
                           "AllowedHeaders": ["content-type", "x-amz-meta-file-name"],
                           "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 3000}]}
    aws("s3api", "put-bucket-cors", "--bucket", bucket, "--cors-configuration", json.dumps(cors))
    print(f"Bucket privado de documentos configurado: {bucket}")


if __name__ == "__main__":
    create()
