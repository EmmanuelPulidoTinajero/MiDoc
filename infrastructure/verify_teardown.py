"""Inventario de sólo lectura para verificar el retiro de MiDoc en Learner Lab.

Ejemplo: python infrastructure/verify_teardown.py --account 647018795197
No elimina recursos, no muestra valores secretos ni modifica Terraform.
"""
import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--project", default="midoc")
    parser.add_argument("--rds-secret-arn", help="ARN exacto del secreto administrado de la instancia retirada")
    parser.add_argument("--report", type=Path, default=Path("docs/evidencia-destruccion-aws.json"))
    args = parser.parse_args()
    prefix = args.project

    def aws(*command):
        result = subprocess.run(["aws", *command, "--region", args.region, "--output", "json"],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{' '.join(command[:2])}: {result.stderr.strip()}")
        return json.loads(result.stdout or "{}")

    identity = aws("sts", "get-caller-identity")
    if identity["Account"] != args.account:
        parser.error("La cuenta activa no coincide con --account")
    commands = {
        "lambda": ("lambda", "list-functions"),
        "apiGateway": ("apigatewayv2", "get-apis"),
        "rds": ("rds", "describe-db-instances"),
        "snapshots": ("rds", "describe-db-snapshots"),
        "dynamodb": ("dynamodb", "list-tables"),
        "s3": ("s3api", "list-buckets"),
        "secrets": ("secretsmanager", "list-secrets", "--include-planned-deletion"),
        "logs": ("logs", "describe-log-groups", "--log-group-name-prefix", f"/aws/lambda/{prefix}"),
        "eventbridge": ("events", "list-rules", "--name-prefix", prefix),
        "securityGroups": ("ec2", "describe-security-groups", "--filters", f"Name=group-name,Values={prefix}-*"),
        "vpcEndpoints": ("ec2", "describe-vpc-endpoints", "--filters",
                         "Name=vpc-endpoint-id,Values=vpce-0837c4d5a8bee3a0c,vpce-0b9612efe07baa831,vpce-0e353534555e89254"),
        "networkInterfaces": ("ec2", "describe-network-interfaces", "--filters",
                              "Name=group-id,Values=sg-0cc5831717592d5d5,sg-05d7f9cceaf511ed6"),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(aws, *command) for name, command in commands.items()}
        data = {name: future.result() for name, future in futures.items()}
    remaining = {
        "lambda": [v["FunctionName"] for v in data["lambda"].get("Functions", []) if v["FunctionName"].startswith(prefix)],
        "apiGateway": [v["ApiId"] for v in data["apiGateway"].get("Items", []) if v["Name"].startswith(prefix)],
        "rds": [v["DBInstanceIdentifier"] for v in data["rds"].get("DBInstances", []) if v["DBInstanceIdentifier"].startswith(prefix)],
        "snapshots": [v["DBSnapshotIdentifier"] for v in data["snapshots"].get("DBSnapshots", []) if v["DBInstanceIdentifier"].startswith(prefix)],
        "dynamodb": [v for v in data["dynamodb"].get("TableNames", []) if v.startswith(prefix)],
        "s3": [v["Name"] for v in data["s3"].get("Buckets", []) if v["Name"].startswith(prefix)],
        "secrets": [v["Name"] for v in data["secrets"].get("SecretList", []) if v["Name"].startswith(prefix)
                    or (args.rds_secret_arn and v["ARN"] == args.rds_secret_arn)],
        "logs": [v["logGroupName"] for v in data["logs"].get("logGroups", [])],
        "eventbridge": [v["Name"] for v in data["eventbridge"].get("Rules", [])],
        "securityGroups": [v["GroupId"] for v in data["securityGroups"].get("SecurityGroups", [])],
        "vpcEndpoints": [v["VpcEndpointId"] for v in data["vpcEndpoints"].get("VpcEndpoints", []) if v["State"] != "deleted"],
        "networkInterfaces": [v["NetworkInterfaceId"] for v in data["networkInterfaces"].get("NetworkInterfaces", [])],
    }
    role = aws("iam", "get-role", "--role-name", "LabRole")["Role"]["RoleName"]
    state_path = Path(__file__).resolve().parent / "terraform.tfstate"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        managed = [v["type"] + "." + v["name"] for v in state.get("resources", []) if v["mode"] == "managed"]
    except OSError:
        # Windows puede mantener el estado bloqueado mientras termina apply.
        managed = ["Estado no disponible; repetir al finalizar terraform apply"]
    passed = not any(remaining.values()) and not managed
    report = {"verifiedAt": datetime.now(timezone.utc).isoformat(), "account": args.account,
              "region": args.region, "project": prefix, "result": "PASS" if passed else "PENDING",
              "remaining": remaining, "terraformManagedResources": managed, "preservedRole": role,
              "scope": "Recursos MiDoc en us-east-1; se conservan LabRole, VPC/subnets predeterminadas y recursos ajenos.",
              "note": "Los IDs de endpoints y security groups corresponden al despliegue validado del 16/10/2026."}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "remainingCounts": {k: len(v) for k, v in remaining.items()},
                      "terraformManaged": len(managed), "preservedRole": role}, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
