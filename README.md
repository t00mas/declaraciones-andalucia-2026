# Declaraciones de candidatos · Andalucía 2026

Explorador de las declaraciones de actividades, bienes e intereses presentadas por los candidatos a las elecciones al Parlamento de Andalucía del 17 de mayo de 2026.

**Fuente:** [Boletín Oficial de la Junta de Andalucía, núm. 79 C1, 27 de abril de 2026](https://www.juntadeandalucia.es/eboja)

## Qué incluye

- **1.127 candidatos** de 8 circunscripciones y más de 10 partidos
- Actividades declaradas: cargos públicos, empleo público, empleo privado
- Bienes declarados: inmuebles (valor catastral), saldo bancario, acciones y fondos, vehículos, seguros de vida, créditos y deudas

## Sitio web

`index.html` es una aplicación de una sola página sin dependencias de servidor ni paso de compilación. Carga `candidates.json` directamente en el navegador.

**Tabs:**
- **Candidatos** — tabla completa con búsqueda, filtros por partido y circunscripción, ordenación por cualquier columna. Clic en cualquier fila para ver la declaración completa.
- **Por partido** — mediana de patrimonio neto por partido, con tabla de estadísticas comparativas.
- **Señales de alerta** — seis paneles con candidatos que presentan patrones destacables (patrimonio negativo, sin ingresos declarados con activos significativos, vehículo de lujo con saldo bajo, cargo público con grandes inversiones, deuda sin respaldo inmobiliario, cinco o más inmuebles).
- **Distribución** — diagrama de dispersión con todos los candidatos ordenados por patrimonio, coloreados por partido, y tabla de percentiles por partido.

## Despliegue local

```bash
python3 -m http.server
# abre http://localhost:8000
```

## Despliegue en GitHub Pages

Activa GitHub Pages sobre la rama `main` en la raíz del repositorio. No requiere ningún paso de compilación.

## Generar candidates.json desde el PDF

Requiere `poppler` (`brew install poppler` en macOS).

```bash
python3 parse_pdf.py
```

El script extrae el texto del PDF con `pdftotext`, limpia las cabeceras del BOJA y parsea cada declaración en un objeto JSON estructurado con campos numéricos calculados (`patrimonio_neto`, `total_activos`, etc.).

## Estructura de datos

Cada candidato en `candidates.json`:

```json
{
  "nombre": "APELLIDO APELLIDO, NOMBRE",
  "apellidos": "Apellido Apellido",
  "nombre_pila": "Nombre",
  "partido": "nombre completo del partido",
  "circunscripcion": "ALMERÍA",
  "saldo_bancario": 1234.56,
  "valor_inmuebles": 95000.0,
  "total_acciones": null,
  "total_vehiculos": 8000.0,
  "total_seguros": null,
  "total_deudas": 60000.0,
  "total_activos": 104234.56,
  "patrimonio_neto": 44234.56,
  "cargos_publicos": [...],
  "actividades_publicas": [...],
  "actividades_privadas": [...],
  "bienes_inmuebles": [...],
  "acciones_valores": [...],
  "vehiculos_otros": [...],
  "seguros_vida": [...],
  "creditos_deudas": [...]
}
```

## Notas metodológicas

- El **valor catastral** de los inmuebles es el declarado por el candidato; suele ser inferior al valor de mercado.
- Los campos `null` indican que el candidato no declaró nada en esa categoría, no necesariamente que el valor sea cero.
- Las **señales de alerta** son indicadores analíticos, no acusaciones. Pueden tener explicaciones legítimas (herencias, jubilaciones, propiedad compartida al 50 %).
- El campo `patrimonio_neto` es `total_activos − total_deudas`. Solo se calcula cuando hay al menos un activo declarado.

## Licencia

Los datos son públicos (BOJA). El código es MIT.
