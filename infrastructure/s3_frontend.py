import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _config() -> tuple[str, str, str, str]:
    bucket = os.environ["MIDOC_FRONTEND_BUCKET"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    dist = os.path.abspath(os.environ.get("MIDOC_FRONTEND_DIST", "frontend/dist/midoc-frontend"))
    publish_dir = os.path.join(dist, "browser") if os.path.isdir(os.path.join(dist, "browser")) else dist
    return bucket, region, dist, publish_dir


def aws(region: str, *args: str) -> None:
    subprocess.run(["aws", *args, "--region", region], check=True)


def aws_json(region: str, *args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--region", region, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout or "{}")


def bucket_exists(bucket: str, region: str) -> bool:
    result = subprocess.run(
        ["aws", "s3api", "head-bucket", "--bucket", bucket, "--region", region],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _delete_objects_batch(bucket: str, region: str, objects: list[dict]) -> None:
    for idx in range(0, len(objects), 1000):
        batch = objects[idx : idx + 1000]
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"Objects": batch, "Quiet": True}, handle)
            file_uri = f"file://{Path(tmp_path).resolve().as_posix()}"
            aws(region, "s3api", "delete-objects", "--bucket", bucket, "--delete", file_uri)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _abort_multipart_uploads(bucket: str, region: str) -> None:
    key_marker = None
    upload_id_marker = None
    while True:
        cmd = ["s3api", "list-multipart-uploads", "--bucket", bucket]
        if key_marker:
            cmd.extend(["--key-marker", key_marker])
        if upload_id_marker:
            cmd.extend(["--upload-id-marker", upload_id_marker])
        resp = aws_json(region, *cmd)
        for upload in resp.get("Uploads", []):
            aws(
                region,
                "s3api",
                "abort-multipart-upload",
                "--bucket",
                bucket,
                "--key",
                upload["Key"],
                "--upload-id",
                upload["UploadId"],
            )
        if not resp.get("IsTruncated"):
            break
        key_marker = resp.get("NextKeyMarker")
        upload_id_marker = resp.get("NextUploadIdMarker")


def _empty_bucket(bucket: str, region: str) -> None:
    _abort_multipart_uploads(bucket, region)

    key_marker = None
    version_id_marker = None
    while True:
        cmd = ["s3api", "list-object-versions", "--bucket", bucket]
        if key_marker:
            cmd.extend(["--key-marker", key_marker])
        if version_id_marker:
            cmd.extend(["--version-id-marker", version_id_marker])
        resp = aws_json(region, *cmd)
        to_delete = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in resp.get("Versions", []) + resp.get("DeleteMarkers", [])
        ]
        if to_delete:
            _delete_objects_batch(bucket, region, to_delete)
        if not resp.get("IsTruncated"):
            break
        key_marker = resp.get("NextKeyMarker")
        version_id_marker = resp.get("NextVersionIdMarker")

    continuation_token = None
    while True:
        cmd = ["s3api", "list-objects-v2", "--bucket", bucket]
        if continuation_token:
            cmd.extend(["--continuation-token", continuation_token])
        resp = aws_json(region, *cmd)
        to_delete = [{"Key": item["Key"]} for item in resp.get("Contents", [])]
        if to_delete:
            _delete_objects_batch(bucket, region, to_delete)
        if not resp.get("IsTruncated"):
            break
        continuation_token = resp.get("NextContinuationToken")


def create() -> None:
    bucket, region, dist, publish_dir = _config()
    if not bucket_exists(bucket, region):
        args = ["s3api", "create-bucket", "--bucket", bucket]
        if region != "us-east-1":
            args.extend(["--create-bucket-configuration", f"LocationConstraint={region}"])
        aws(region, *args)

    aws(
        region,
        "s3api",
        "put-public-access-block",
        "--bucket",
        bucket,
        "--public-access-block-configuration",
        "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false",
    )
    aws(
        region,
        "s3api",
        "put-bucket-ownership-controls",
        "--bucket",
        bucket,
        "--ownership-controls",
        "Rules=[{ObjectOwnership=BucketOwnerEnforced}]",
    )
    aws(
        region,
        "s3api",
        "put-bucket-encryption",
        "--bucket",
        bucket,
        "--server-side-encryption-configuration",
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}',
    )
    aws(
        region,
        "s3api",
        "put-bucket-website",
        "--bucket",
        bucket,
        "--website-configuration",
        '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}',
    )
    policy = (
        f'{{"Version":"2012-10-17","Statement":[{{"Sid":"PublicReadFrontend","Effect":"Allow",'
        f'"Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::{bucket}/*"}}]}}'
    )
    aws(region, "s3api", "put-bucket-policy", "--bucket", bucket, "--policy", policy)
    if os.path.isdir(publish_dir):
        aws(region, "s3", "sync", publish_dir, f"s3://{bucket}", "--delete", "--cache-control", "max-age=60")
    else:
        print(f"Frontend build not found at {dist}; bucket configured without uploaded files.", file=sys.stderr)


def destroy() -> None:
    bucket = os.environ["MIDOC_FRONTEND_BUCKET"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    if not bucket_exists(bucket, region):
        return
    _empty_bucket(bucket, region)
    aws(region, "s3api", "delete-bucket", "--bucket", bucket)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "destroy"}:
        raise SystemExit("Usage: python s3_frontend.py create|destroy")
    create() if sys.argv[1] == "create" else destroy()
