import os
import subprocess
import sys


bucket = os.environ["MIDOC_FRONTEND_BUCKET"]
region = os.environ.get("AWS_REGION", "us-east-1")
dist = os.path.abspath(os.environ.get("MIDOC_FRONTEND_DIST", "frontend/dist/midoc-frontend"))
publish_dir = os.path.join(dist, "browser") if os.path.isdir(os.path.join(dist, "browser")) else dist


def aws(*args: str) -> None:
    subprocess.run(["aws", *args], check=True)


def bucket_exists() -> bool:
    result = subprocess.run(
        ["aws", "s3api", "head-bucket", "--bucket", bucket],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def create() -> None:
    if not bucket_exists():
        args = ["s3api", "create-bucket", "--bucket", bucket, "--region", region]
        if region != "us-east-1":
            args.extend(["--create-bucket-configuration", f"LocationConstraint={region}"])
        aws(*args)

    aws(
        "s3api",
        "put-public-access-block",
        "--bucket",
        bucket,
        "--public-access-block-configuration",
        "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false",
    )
    aws("s3api", "put-bucket-ownership-controls", "--bucket", bucket, "--ownership-controls", "Rules=[{ObjectOwnership=BucketOwnerEnforced}]")
    aws("s3api", "put-bucket-encryption", "--bucket", bucket, "--server-side-encryption-configuration", '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}')
    aws("s3api", "put-bucket-website", "--bucket", bucket, "--website-configuration", '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}')
    policy = f'{{"Version":"2012-10-17","Statement":[{{"Sid":"PublicReadFrontend","Effect":"Allow","Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::{bucket}/*"}}]}}'
    aws("s3api", "put-bucket-policy", "--bucket", bucket, "--policy", policy)
    if os.path.isdir(publish_dir):
        aws("s3", "sync", publish_dir, f"s3://{bucket}", "--delete", "--cache-control", "max-age=60")
    else:
        print(f"Frontend build not found at {dist}; bucket configured without uploaded files.", file=sys.stderr)


def destroy() -> None:
    if bucket_exists():
        subprocess.run(["aws", "s3", "rb", f"s3://{bucket}", "--force"], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "destroy"}:
        raise SystemExit("Usage: python s3_frontend.py create|destroy")
    create() if sys.argv[1] == "create" else destroy()
