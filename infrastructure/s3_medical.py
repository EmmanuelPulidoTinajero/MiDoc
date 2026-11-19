"""Crea y destruye el bucket privado de expedientes con AWS CLI (sin permisos de Object Lock)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


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


def exists(bucket: str, region: str) -> bool:
    return (
        subprocess.run(
            ["aws", "s3api", "head-bucket", "--bucket", bucket, "--region", region],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


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
    bucket = os.environ["MIDOC_DOCUMENTS_BUCKET"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    frontend_bucket = os.environ["MIDOC_FRONTEND_BUCKET"]

    if not exists(bucket, region):
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
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
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
    origins = [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        f"https://{frontend_bucket}.s3.{region}.amazonaws.com",
        f"http://{frontend_bucket}.s3-website-{region}.amazonaws.com",
    ]
    cors = {
        "CORSRules": [
            {
                "AllowedOrigins": origins,
                "AllowedMethods": ["POST", "GET"],
                "AllowedHeaders": ["content-type", "x-amz-meta-file-name"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3000,
            }
        ]
    }
    aws(region, "s3api", "put-bucket-cors", "--bucket", bucket, "--cors-configuration", json.dumps(cors))
    print(f"Bucket privado de documentos configurado: {bucket}")


def destroy() -> None:
    bucket = os.environ["MIDOC_DOCUMENTS_BUCKET"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    if os.environ.get("MIDOC_DELETE_MEDICAL_ON_DESTROY", "true").strip().lower() == "false":
        print(f"Conservando bucket de documentos por configuración: {bucket}")
        return
    if not exists(bucket, region):
        return
    _empty_bucket(bucket, region)
    aws(region, "s3api", "delete-bucket", "--bucket", bucket)
    print(f"Bucket privado de documentos eliminado: {bucket}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "destroy"}:
        raise SystemExit("Usage: python s3_medical.py create|destroy")
    create() if sys.argv[1] == "create" else destroy()
