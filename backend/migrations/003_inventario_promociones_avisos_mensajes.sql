-- Migración 003: funcionalidades de gestión del doctor y avisos de producto.
-- Completa lo que ya vivía en src/schema.sql pero faltaba en las migraciones:
-- inventario, promociones, avisos y mensajería. Cambios aditivos e idempotentes.

CREATE TABLE IF NOT EXISTS inventario_insumo (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id) ON DELETE CASCADE,
  nombre VARCHAR(120) NOT NULL,
  cantidad NUMERIC(12,2) NOT NULL CHECK (cantidad >= 0),
  unidad VARCHAR(30) NOT NULL,
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventario_doctor_nombre_ci ON inventario_insumo (doctor_id, lower(nombre));

CREATE TABLE IF NOT EXISTS promocion (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id) ON DELETE CASCADE,
  titulo VARCHAR(120) NOT NULL,
  descripcion VARCHAR(500) NOT NULL DEFAULT '',
  descuento_porcentaje SMALLINT NOT NULL CHECK (descuento_porcentaje BETWEEN 1 AND 90),
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL CHECK (fecha_fin >= fecha_inicio),
  activa BOOLEAN NOT NULL DEFAULT true,
  creada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notificacion (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  tipo VARCHAR(40) NOT NULL,
  titulo VARCHAR(120) NOT NULL,
  mensaje VARCHAR(500) NOT NULL,
  referencia VARCHAR(120),
  creada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  leida_en TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_notificacion_usuario_fecha ON notificacion (usuario_id, creada_en DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_notificacion_dedupe ON notificacion (usuario_id, tipo, referencia) WHERE referencia IS NOT NULL;

CREATE TABLE IF NOT EXISTS mensaje_usuario (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  remitente_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  destinatario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  contenido VARCHAR(2000) NOT NULL,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  leido_en TIMESTAMPTZ,
  CHECK (remitente_id <> destinatario_id)
);
CREATE INDEX IF NOT EXISTS ix_mensaje_conversacion_fecha ON mensaje_usuario (remitente_id, destinatario_id, creado_en);
CREATE INDEX IF NOT EXISTS ix_mensaje_destinatario_fecha ON mensaje_usuario (destinatario_id, creado_en DESC);
