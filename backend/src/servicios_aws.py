"""Adaptadores AWS opcionales usados sólo cuando la API corre en Lambda."""
import os
import re
import uuid
from datetime import datetime, timezone

import metricas

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".dcm": "application/dicom",
    ".dicom": "application/dicom",
}
ALLOWED_DOCUMENT_CONTENT_TYPES = {
    ".pdf": ("application/pdf",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".png": ("image/png",),
    ".dcm": ("application/dicom", "application/octet-stream", ""),
    ".dicom": ("application/dicom", "application/octet-stream", ""),
}


def _audit_table_name() -> str | None:
    return os.environ.get("DYNAMODB_TABLE_NAME") or os.environ.get("DYNAMODB_AUDIT_TABLE")


def registrar_acceso(patient_id: str, actor_id: str) -> None:
    table_name = _audit_table_name()
    if not table_name:
        raise RuntimeError("DYNAMODB_TABLE_NAME no está configurado")
    import boto3

    now = datetime.now(timezone.utc).isoformat()
    boto3.resource("dynamodb").Table(table_name).put_item(Item={
        "pk": f"PACIENTE#{patient_id}",
        "sk": f"ACCESO#{now}#{uuid.uuid4()}",
        "actor_id": actor_id,
        "evento": "LECTURA_EXPEDIENTE",
        "fecha_hora": now,
    })


def listar_accesos(patient_id: str, limit: int = 100) -> list[dict]:
    table_name = _audit_table_name()
    if not table_name:
        return []
    import boto3
    from boto3.dynamodb.conditions import Key

    resp = boto3.resource("dynamodb").Table(table_name).query(
        KeyConditionExpression=Key("pk").eq(f"PACIENTE#{patient_id}") & Key("sk").begins_with("ACCESO#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [
        {
            "actorId": item.get("actor_id"),
            "event": item.get("evento", "LECTURA_EXPEDIENTE"),
            "accessedAt": item.get("fecha_hora"),
        }
        for item in resp.get("Items", [])
    ]


def _bucket_name() -> str | None:
    return os.environ.get("MEDICAL_DOCUMENTS_BUCKET") or os.environ.get("DOCUMENTS_BUCKET")


def _bucket():
    name = _bucket_name()
    if not name:
        raise RuntimeError("MEDICAL_DOCUMENTS_BUCKET no está configurado")
    import boto3

    return boto3.client("s3"), name


def _nombre_seguro(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("El nombre del archivo no es válido")
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^\w. -]", "_", name, flags=re.UNICODE).strip(" .")[:120]
    if not name:
        raise ValueError("El nombre del archivo no es válido")
    return name


def crear_carga(patient_id: str, file_name: str, content_type: str, size: int) -> dict:
    name = _nombre_seguro(file_name)
    if not isinstance(content_type, str):
        raise ValueError("El tipo del archivo no es válido")
    extension = os.path.splitext(name)[1].lower()
    permitidos = ALLOWED_DOCUMENT_CONTENT_TYPES.get(extension)
    if not permitidos or content_type not in permitidos:
        raise ValueError("Usa archivos PDF, JPG, PNG o DICOM con su tipo correcto")
    effective_content_type = content_type or ALLOWED_DOCUMENT_TYPES[extension]
    if not isinstance(size, int) or size < 1 or size > MAX_DOCUMENT_BYTES:
        raise ValueError("El archivo debe pesar entre 1 byte y 10 MB")
    s3, bucket = _bucket()
    document_id = str(uuid.uuid4())
    key = f"records/{patient_id}/{document_id}/{name}"
    try:
        signed = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": effective_content_type, "x-amz-meta-file-name": name},
            Conditions=[
                {"Content-Type": effective_content_type},
                {"x-amz-meta-file-name": name},
                ["content-length-range", 1, MAX_DOCUMENT_BYTES],
            ],
            ExpiresIn=300,
        )
    except Exception:
        metricas.registrar_metrica("DocumentOpsErrors", 1)
        raise
    return {"id": document_id, "name": name, "url": signed["url"], "fields": signed["fields"],
            "expiresIn": 300}


def listar_documentos(patient_id: str) -> list[dict]:
    s3, bucket = _bucket()
    try:
        respuesta = s3.list_objects_v2(Bucket=bucket, Prefix=f"records/{patient_id}/")
        documentos = []
        for objeto in respuesta.get("Contents", []):
            if objeto["Key"].endswith("/"):
                continue
            metadata = s3.head_object(Bucket=bucket, Key=objeto["Key"])
            document_id = objeto["Key"].split("/", 3)[2]
            documentos.append({
                "id": document_id,
                "name": metadata.get("Metadata", {}).get("file-name", "Archivo clínico"),
                "contentType": metadata.get("ContentType", "application/octet-stream"),
                "size": objeto["Size"],
                "lastModified": objeto["LastModified"].isoformat(),
                "downloadUrl": s3.generate_presigned_url(
                    "get_object", Params={"Bucket": bucket, "Key": objeto["Key"],
                                          "ResponseContentDisposition": "attachment"}, ExpiresIn=300),
            })
        return sorted(documentos, key=lambda item: item["lastModified"], reverse=True)
    except Exception:
        metricas.registrar_metrica("DocumentOpsErrors", 1)
        raise


def eliminar_documento(patient_id: str, document_id: str) -> bool:
    s3, bucket = _bucket()
    prefix = f"records/{patient_id}/{document_id}/"
    try:
        respuesta = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objetos = respuesta.get("Contents", [])
        if not objetos:
            return False
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": item["Key"]} for item in objetos]})
        return True
    except Exception:
        metricas.registrar_metrica("DocumentOpsErrors", 1)
        raise


def subir_receta_pdf(receta_id: str, pdf_bytes: bytes) -> str | None:
    bucket = _bucket_name()
    if not bucket:
        if os.environ.get("NODE_ENV") == "production":
            metricas.registrar_metrica("DocumentOpsErrors", 1)
            raise RuntimeError("MEDICAL_DOCUMENTS_BUCKET no está configurado")
        return None
    import boto3

    key = f"recetas/{receta_id}.pdf"
    try:
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
        )
    except Exception:
        metricas.registrar_metrica("DocumentOpsErrors", 1)
        raise
    return key


def url_descarga_receta(key: str | None, receta_id: str = "") -> str | None:
    if not key:
        return None
    bucket = _bucket_name()
    if not bucket:
        if os.environ.get("NODE_ENV") == "production":
            metricas.registrar_metrica("DocumentOpsErrors", 1)
            raise RuntimeError("MEDICAL_DOCUMENTS_BUCKET no está configurado")
        return None
    import boto3

    try:
        return boto3.client("s3").generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="receta-{receta_id or "midoc"}.pdf"',
                "ResponseContentType": "application/pdf",
            },
            ExpiresIn=300,
        )
    except Exception:
        metricas.registrar_metrica("DocumentOpsErrors", 1)
        raise
