"""Inventario de sólo lectura para verificar el retiro total de MiDoc en AWS.

Ejemplo: python infrastructure/verify_teardown.py --project-name midoc
No elimina recursos, no muestra valores secretos ni modifica Terraform.
"""
import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def _has_project_tag(tags: list[dict] | None, prefix: str) -> bool:
    for tag in tags or []:
        key = tag.get("Key")
        value = tag.get("Value") or ""
        if key == "Project" and value == prefix:
            return True
        if key == "Name" and value.startswith(prefix):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="ID de cuenta AWS esperada (opcional; se autodetecta vía STS si se omite)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--project",
        "--project-name",
        dest="project",
        default=os.environ.get("TF_VAR_project_name", "midoc"),
        help="Prefijo / etiqueta Project de MiDoc (por defecto TF_VAR_project_name o 'midoc')",
    )
    parser.add_argument("--rds-secret-arn", help="ARN exacto del secreto administrado de la instancia retirada")
    parser.add_argument(
        "--extra-bucket",
        action="append",
        default=[],
        help="Nombre adicional de bucket S3 a vigilar (p. ej. frontend_bucket_name personalizado)",
    )
    parser.add_argument("--report", type=Path, default=Path("docs/evidencia-destruccion-aws.json"))
    args = parser.parse_args()
    prefix = args.project
    extra_buckets = set(args.extra_bucket)

    def aws(*command):
        result = subprocess.run(
            ["aws", *command, "--region", args.region, "--output", "json"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(f"{' '.join(command[:2])}: {result.stderr.strip()}")
        return json.loads(result.stdout or "{}")

    identity = aws("sts", "get-caller-identity")
    account_id = identity["Account"]
    if args.account and account_id != args.account:
        parser.error(f"La cuenta activa ({account_id}) no coincide con --account ({args.account})")

    commands = {
        "securityGroups": ("ec2", "describe-security-groups"),
        "subnets": ("ec2", "describe-subnets"),
        "routeTables": ("ec2", "describe-route-tables"),
        "natGateways": ("ec2", "describe-nat-gateways"),
        "eips": ("ec2", "describe-addresses"),
        "networkInterfaces": ("ec2", "describe-network-interfaces"),
        "vpcEndpoints": ("ec2", "describe-vpc-endpoints"),
        "rds": ("rds", "describe-db-instances"),
        "snapshots": ("rds", "describe-db-snapshots"),
        "dbSubnetGroups": ("rds", "describe-db-subnet-groups"),
        "lambda": ("lambda", "list-functions"),
        "apiGateway": ("apigatewayv2", "get-apis"),
        "dynamodb": ("dynamodb", "list-tables"),
        "s3": ("s3api", "list-buckets"),
        "secrets": ("secretsmanager", "list-secrets", "--include-planned-deletion"),
        "eventbridge": ("events", "list-rules", "--name-prefix", prefix),
        "logs": ("logs", "describe-log-groups"),
        "alarms": ("cloudwatch", "describe-alarms"),
        "dashboards": ("cloudwatch", "list-dashboards", "--dashboard-name-prefix", prefix),
        "queryDefinitions": ("logs", "describe-query-definitions", "--query-definition-name-prefix", prefix),
        "sns": ("sns", "list-topics"),
    }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {name: pool.submit(aws, *command) for name, command in commands.items()}
        data = {name: future.result() for name, future in futures.items()}

    matched_sgs = [
        sg
        for sg in data["securityGroups"].get("SecurityGroups", [])
        if sg.get("GroupName") != "default"
        and (sg.get("GroupName", "").startswith(prefix) or _has_project_tag(sg.get("Tags"), prefix))
    ]
    found_sg_ids = {sg["GroupId"] for sg in matched_sgs}

    matched_subnets = [
        subnet
        for subnet in data["subnets"].get("Subnets", [])
        if not subnet.get("DefaultForAz", False) and _has_project_tag(subnet.get("Tags"), prefix)
    ]
    found_subnet_ids = {subnet["SubnetId"] for subnet in matched_subnets}

    matched_rts = [
        rt
        for rt in data["routeTables"].get("RouteTables", [])
        if not any(assoc.get("Main") for assoc in rt.get("Associations", []))
        and _has_project_tag(rt.get("Tags"), prefix)
    ]
    found_rt_ids = {rt["RouteTableId"] for rt in matched_rts}

    matched_ngws = [
        ngw
        for ngw in data["natGateways"].get("NatGateways", [])
        if ngw.get("State") != "deleted"
        and (_has_project_tag(ngw.get("Tags"), prefix) or ngw.get("SubnetId") in found_subnet_ids)
    ]
    found_nat_eip_allocs = {
        addr.get("AllocationId")
        for ngw in matched_ngws
        for addr in ngw.get("NatGatewayAddresses", [])
        if addr.get("AllocationId")
    }

    matched_enis = []
    for eni in data["networkInterfaces"].get("NetworkInterfaces", []):
        groups = eni.get("Groups", [])
        desc = (eni.get("Description") or "").lower()
        if (
            any(g.get("GroupId") in found_sg_ids or (g.get("GroupName") or "").startswith(prefix) for g in groups)
            or eni.get("SubnetId") in found_subnet_ids
            or _has_project_tag(eni.get("TagSet"), prefix)
            or desc.startswith(f"{prefix}-")
            or f" {prefix}-" in desc
        ):
            matched_enis.append(eni)
    found_eni_ids = {eni["NetworkInterfaceId"] for eni in matched_enis}

    matched_eips = [
        addr
        for addr in data["eips"].get("Addresses", [])
        if _has_project_tag(addr.get("Tags"), prefix)
        or addr.get("AllocationId") in found_nat_eip_allocs
        or addr.get("NetworkInterfaceId") in found_eni_ids
    ]

    matched_vpces = [
        vpce
        for vpce in data["vpcEndpoints"].get("VpcEndpoints", [])
        if vpce.get("State") != "deleted"
        and (
            _has_project_tag(vpce.get("Tags"), prefix)
            or any(g.get("GroupId") in found_sg_ids for g in vpce.get("Groups", []))
            or any(sid in found_subnet_ids for sid in vpce.get("SubnetIds", []))
            or any(rtid in found_rt_ids for rtid in vpce.get("RouteTableIds", []))
        )
    ]

    log_prefixes = (
        f"/aws/lambda/{prefix}",
        f"/aws/apigateway/{prefix}",
        f"/aws/api-gateway/{prefix}",
        f"/{prefix}/",
    )
    matched_logs = [
        lg["logGroupName"]
        for lg in data["logs"].get("logGroups", [])
        if lg["logGroupName"].startswith(log_prefixes) or f"/{prefix}-" in lg["logGroupName"]
    ]

    matched_alarms = [
        a["AlarmName"]
        for a in data["alarms"].get("MetricAlarms", []) + data["alarms"].get("CompositeAlarms", [])
        if a["AlarmName"].startswith(prefix)
    ]

    remaining = {
        "lambda": [v["FunctionName"] for v in data["lambda"].get("Functions", []) if v["FunctionName"].startswith(prefix)],
        "apiGateway": [v["ApiId"] for v in data["apiGateway"].get("Items", []) if v["Name"].startswith(prefix)],
        "rds": [
            v["DBInstanceIdentifier"]
            for v in data["rds"].get("DBInstances", [])
            if v["DBInstanceIdentifier"].startswith(prefix) or _has_project_tag(v.get("TagList"), prefix)
        ],
        "snapshots": [
            v["DBSnapshotIdentifier"]
            for v in data["snapshots"].get("DBSnapshots", [])
            if v.get("DBInstanceIdentifier", "").startswith(prefix)
            or v.get("DBSnapshotIdentifier", "").startswith(prefix)
        ],
        "dbSubnetGroups": [
            v["DBSubnetGroupName"]
            for v in data["dbSubnetGroups"].get("DBSubnetGroups", [])
            if v["DBSubnetGroupName"].startswith(prefix)
        ],
        "dynamodb": [v for v in data["dynamodb"].get("TableNames", []) if v.startswith(prefix)],
        "s3": [
            v["Name"]
            for v in data["s3"].get("Buckets", [])
            if v["Name"].startswith(prefix) or v["Name"] in extra_buckets
        ],
        "secrets": [
            v["Name"]
            for v in data["secrets"].get("SecretList", [])
            if v["Name"].startswith(prefix)
            or _has_project_tag(v.get("Tags"), prefix)
            or (args.rds_secret_arn and v["ARN"] == args.rds_secret_arn)
        ],
        "eventbridge": [v["Name"] for v in data["eventbridge"].get("Rules", [])],
        "logs": matched_logs,
        "alarms": matched_alarms,
        "dashboards": [v["DashboardName"] for v in data["dashboards"].get("DashboardEntries", [])],
        "queryDefinitions": [v["name"] for v in data["queryDefinitions"].get("queryDefinitions", [])],
        "sns": [
            v["TopicArn"]
            for v in data["sns"].get("Topics", [])
            if v["TopicArn"].rsplit(":", 1)[-1].startswith(prefix)
        ],
        "securityGroups": [sg["GroupId"] for sg in matched_sgs],
        "subnets": [s["SubnetId"] for s in matched_subnets],
        "routeTables": [rt["RouteTableId"] for rt in matched_rts],
        "natGateways": [ngw["NatGatewayId"] for ngw in matched_ngws],
        "eips": [addr.get("AllocationId") or addr.get("PublicIp") for addr in matched_eips],
        "vpcEndpoints": [vpce["VpcEndpointId"] for vpce in matched_vpces],
        "networkInterfaces": [eni["NetworkInterfaceId"] for eni in matched_enis],
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
    report = {
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "account": account_id,
        "region": args.region,
        "project": prefix,
        "result": "PASS" if passed else "PENDING",
        "remaining": remaining,
        "terraformManagedResources": managed,
        "preservedRole": role,
        "scope": f"Recursos '{prefix}' en {args.region}; se conservan LabRole, VPC/subnets/RT predeterminadas y recursos ajenos.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "result": report["result"],
                "remainingCounts": {k: len(v) for k, v in remaining.items()},
                "terraformManaged": len(managed),
                "preservedRole": role,
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
