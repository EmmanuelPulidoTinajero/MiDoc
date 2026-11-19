-- Migración 004: Stripe real (Checkout Sessions + webhook), biografía de perfil,
-- control de intentos de login e idempotencia.

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
