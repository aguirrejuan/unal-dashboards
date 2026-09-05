# PIC — de documentos a datos

Veintitrés documentos del Plan Integral de Cobertura —en Word, Excel y PDF
escaneado— convertidos en una base de datos consultable en la que **cada cifra
conserva el documento y la celda de la que salió**.

El tablero público muestra la cadena de procedencia: se elige una cifra y
aparece la tabla original con la celda citada resaltada. No un enlace al
archivo: la fila que produjo el número.

## Cómo funciona

```
extracted/PIC-Información/**     el corpus, sin modificar
        │
        │  pic-etl extract       ocasional · revisado por una persona
        ▼
extractions/*.yaml               versionado y diferenciable
        │
        │  pic-etl build         determinista · sin red
        ▼
build/pic.sqlite                 795 filas
        │
        │  pic-etl publish
        ▼
site/                            → GitHub Pages
```

La separación importa. Todo lo que está por encima de los archivos YAML es un
mejor esfuerzo y lo revisa una persona; todo lo que está por debajo es puro y
repetible. Es lo que permitirá que un modelo ayude a leer los seis escaneos sin
que la carga deje de ser determinista.

## Comandos

```bash
uv sync --extra dev
uv run pic-etl extract     # documentos  → extractions/*.yaml  (revisar antes de confirmar)
uv run pic-etl build       # extractions → build/pic.sqlite
uv run pic-etl verify      # invariantes + re-transcripción contra las fuentes
uv run pic-etl publish     # vistas      → site/
uv run pytest
```

`verify` vuelve a abrir el `.docx` y el `.xlsx` y comprueba que cada cifra sigue
coincidiendo con su celda. El despliegue está condicionado a que pase.

## Alcance

De los 23 documentos hay **2 procesados** (Anexo 1 y Anexo 2), que aportan 242
cifras rastreables. Faltan 12 acuerdos con capa de texto, 6 escaneos que
requieren visión y 2 informes. El propio tablero lo declara en lugar de esperar
a que alguien pregunte.

## Documentación

- [`docs/pic-data-model-v2.md`](docs/pic-data-model-v2.md) — el esquema y el
  registro de 38 inconsistencias
- [`docs/pic-etl-design.md`](docs/pic-etl-design.md) — el diseño del proceso de
  extracción y carga, y los cinco defectos que la implementación encontró en el
  esquema
