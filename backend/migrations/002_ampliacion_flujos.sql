-- Ampliación de los 3 flujos de la fase 1 (cambios aditivos e idempotentes).
-- También está al final de src/schema.sql, que el backend aplica al arrancar.

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
