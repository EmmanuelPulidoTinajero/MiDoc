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
