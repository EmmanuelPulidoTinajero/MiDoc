import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ESQUEMA = BACKEND / "src" / "schema.sql"
MIGRACIONES = BACKEND / "migrations"

TABLA = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)", re.IGNORECASE)
INDICE = re.compile(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", re.IGNORECASE)
COLUMNA = re.compile(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", re.IGNORECASE)


def _leer(paths):
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


class MigracionesTests(unittest.TestCase):
    """Las migraciones son el camino reproducible: deben cubrir todo lo que aplica schema.sql."""

    def setUp(self):
        self.esquema = ESQUEMA.read_text(encoding="utf-8")
        self.migraciones = _leer(sorted(MIGRACIONES.glob("*.sql")))

    def test_las_migraciones_crean_las_tablas_del_esquema(self):
        faltantes = sorted(set(TABLA.findall(self.esquema)) - set(TABLA.findall(self.migraciones)))
        self.assertEqual(faltantes, [], f"Tablas de schema.sql sin migración: {faltantes}")

    def test_las_migraciones_crean_los_indices_del_esquema(self):
        faltantes = sorted(set(INDICE.findall(self.esquema)) - set(INDICE.findall(self.migraciones)))
        self.assertEqual(faltantes, [], f"Índices de schema.sql sin migración: {faltantes}")

    def test_las_migraciones_agregan_las_columnas_del_esquema(self):
        faltantes = sorted(set(COLUMNA.findall(self.esquema)) - set(COLUMNA.findall(self.migraciones)))
        self.assertEqual(faltantes, [], f"Columnas de schema.sql sin migración: {faltantes}")


if __name__ == "__main__":
    unittest.main()
