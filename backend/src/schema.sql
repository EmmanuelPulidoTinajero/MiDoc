CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS usuario (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(150) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  rol VARCHAR(20) NOT NULL CHECK (rol IN ('PACIENTE', 'DOCTOR', 'CLINICA')),
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS perfil_doctor (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL UNIQUE REFERENCES usuario(id),
  nombre_completo VARCHAR(150) NOT NULL,
  especialidad VARCHAR(100) NOT NULL,
  ubicacion VARCHAR(255) NOT NULL,
  precio_consulta NUMERIC(10,2) NOT NULL CHECK (precio_consulta >= 0)
);
CREATE TABLE IF NOT EXISTS cita (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paciente_id UUID NOT NULL REFERENCES usuario(id),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id),
  fecha_hora TIMESTAMPTZ NOT NULL,
  estado VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE', 'CONFIRMADA', 'CANCELADA', 'COMPLETADA'))
);
CREATE TABLE IF NOT EXISTS consentimiento_expediente (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paciente_id UUID NOT NULL REFERENCES usuario(id),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id),
  estado_acceso BOOLEAN NOT NULL,
  fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (paciente_id, doctor_id)
);
CREATE TABLE IF NOT EXISTS expediente (
  paciente_id UUID PRIMARY KEY REFERENCES usuario(id),
  alergias TEXT[] NOT NULL DEFAULT '{}',
  notas TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS consulta (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cita_id UUID NOT NULL REFERENCES cita(id),
  paciente_id UUID NOT NULL REFERENCES usuario(id),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id),
  diagnostico TEXT NOT NULL,
  tratamiento TEXT NOT NULL DEFAULT '',
  creada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS receta (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cita_id UUID NOT NULL REFERENCES cita(id),
  diagnostico TEXT NOT NULL,
  tratamiento TEXT NOT NULL,
  documento_url VARCHAR(500)
);
CREATE TABLE IF NOT EXISTS suscripcion (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id),
  estado VARCHAR(20) NOT NULL CHECK (estado IN ('ACTIVA', 'INACTIVA', 'PENDIENTE')),
  monto NUMERIC(10,2) NOT NULL DEFAULT 20.00,
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS bitacora_acceso_expediente (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paciente_id UUID NOT NULL REFERENCES usuario(id),
  actor_id UUID NOT NULL REFERENCES usuario(id),
  consultado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Funcionalidades de gestión del doctor y avisos de producto del Reporte de Fase 1.
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

-- Ampliación de los 3 flujos de la fase 1 (ver migrations/002_ampliacion_flujos.sql)

-- Flujo 1: nombre del usuario, datos públicos del doctor y horario semanal
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS nombre VARCHAR(150);
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS telefono VARCHAR(20);
ALTER TABLE perfil_doctor ADD COLUMN IF NOT EXISTS ciudad VARCHAR(100);
ALTER TABLE perfil_doctor ADD COLUMN IF NOT EXISTS descripcion TEXT;
ALTER TABLE perfil_doctor ADD COLUMN IF NOT EXISTS duracion_cita_min SMALLINT NOT NULL DEFAULT 30;
ALTER TABLE cita ADD COLUMN IF NOT EXISTS motivo VARCHAR(500);

-- dia_semana sigue ISO 8601: 1 = lunes ... 7 = domingo (hora de Ciudad de México)
CREATE TABLE IF NOT EXISTS disponibilidad (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES perfil_doctor(id) ON DELETE CASCADE,
  dia_semana SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
  hora_inicio TIME NOT NULL,
  hora_fin TIME NOT NULL CHECK (hora_fin > hora_inicio)
);

-- Dos pacientes no pueden tomar el mismo horario aunque reserven al mismo tiempo
CREATE UNIQUE INDEX IF NOT EXISTS ux_cita_doctor_horario ON cita (doctor_id, fecha_hora) WHERE estado <> 'CANCELADA';

-- Flujo 2: expediente completo
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE;
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS sexo VARCHAR(10);
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS tipo_sangre VARCHAR(3);
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS padecimientos_cronicos TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS medicamentos_actuales TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE expediente ADD COLUMN IF NOT EXISTS fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT now();


-- Flujo 3: notas de la consulta, receta ligada a la consulta y datos del pago simulado
ALTER TABLE consulta ADD COLUMN IF NOT EXISTS notas TEXT;
ALTER TABLE receta ADD COLUMN IF NOT EXISTS consulta_id UUID REFERENCES consulta(id);
ALTER TABLE receta ADD COLUMN IF NOT EXISTS fecha_emision TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS referencia_pago VARCHAR(40);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS tarjeta_marca VARCHAR(12);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS tarjeta_ultimos4 CHAR(4);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS fecha_pago TIMESTAMPTZ;

-- Migración 004: Stripe real (Checkout Sessions + webhook), biografía de perfil,
-- control de intentos de login e idempotencia (ver migrations/004_stripe_suscripcion_y_perfil.sql)
ALTER TABLE perfil_doctor ADD COLUMN IF NOT EXISTS biografia TEXT;

ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS modo_pago VARCHAR(10) NOT NULL DEFAULT 'test';
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS stripe_session_id VARCHAR(255);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS stripe_payment_intent_id VARCHAR(255);
ALTER TABLE suscripcion ALTER COLUMN referencia_pago TYPE VARCHAR(255);
ALTER TABLE suscripcion ALTER COLUMN tarjeta_marca TYPE VARCHAR(32);

CREATE UNIQUE INDEX IF NOT EXISTS ux_suscripcion_stripe_session_id
  ON suscripcion (stripe_session_id) WHERE stripe_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_suscripcion_doctor_estado
  ON suscripcion (doctor_id, estado, fecha_fin DESC);

CREATE TABLE IF NOT EXISTS intento_login (
  clave VARCHAR(255) PRIMARY KEY,
  intentos INTEGER NOT NULL DEFAULT 0,
  ventana_inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
  bloqueado_hasta TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS clave_idempotencia (
  clave VARCHAR(160) NOT NULL,
  usuario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  ruta VARCHAR(120) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status_code SMALLINT NOT NULL,
  respuesta_json TEXT NOT NULL,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (usuario_id, clave)
);
CREATE INDEX IF NOT EXISTS ix_clave_idempotencia_creado_en ON clave_idempotencia (creado_en);
