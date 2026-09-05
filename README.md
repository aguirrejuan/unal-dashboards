# PIC — de documentos a datos

Veintitrés archivos del Plan Integral de Cobertura —en Word, Excel y PDF
escaneado— convertidos en una base consultable en la que **cada cifra conserva
el documento y la celda de la que salió**.

**→ [aguirrejuan.github.io/unal-dashboards](https://aguirrejuan.github.io/unal-dashboards/)**

El tablero no enlaza al archivo: muestra la tabla original con la celda citada
resaltada, al lado de la cifra. 428 cifras, cada una rastreable hasta su
página o su celda.

## Cómo funciona

```
extracted/PIC-Información/**     el corpus, sin modificar
        │
        │  pic-etl extract           determinista, donde el documento se deja
        │  pic-etl transcribe        con visión, donde no  ─┐
        ▼                                                   │ propuesta
extractions/*.yaml               versionado y diferenciable ┘ + revisión
        │
        │  pic-etl build         determinista · sin red
        ▼
build/pic.sqlite                 55 tablas, 16 vistas, 1 630 filas · versionado
        │
        │  pic-etl publish
        ▼
site/                            → GitHub Pages
```

La separación es lo único que importa de este diseño. Todo lo que está **por
encima** de los archivos YAML es un mejor esfuerzo y lo revisa una persona;
todo lo que está **por debajo** es puro y repetible. Por eso un modelo puede
leer los escaneos sin que la carga deje de ser determinista: su salida se
convierte en un artefacto revisado, comprometido y con hash, y el cargador no
sabe que hubo un modelo.

## Comandos

```bash
uv sync --extra dev
uv run pic-etl extract     # corpus      → extractions/*.yaml  (revisar antes de confirmar)
uv run pic-etl build       # extractions → build/pic.sqlite
uv run pic-etl verify      # invariantes I1-I15 + re-transcripción contra las fuentes
uv run pic-etl publish     # vistas      → site/
uv run pytest
```

`verify` vuelve a abrir el `.docx` y el `.xlsx` y comprueba que cada cifra
sigue coincidiendo con su celda. El despliegue está condicionado a que pase.

`build/pic.sqlite` está en el repositorio: se puede clonar y consultar sin
ejecutar nada. La construcción es estable byte a byte —dos construcciones del
mismo corpus dan el mismo archivo—, así que una reconstrucción que no cambia
nada no produce diff. Una prueba lo sostiene.

```bash
sqlite3 build/pic.sqlite "SELECT medida, valor, documento_id, ubicacion
                          FROM v_procedencia ORDER BY valor DESC LIMIT 5"
```

### El paso asistido por modelo

Los cinco escaneos del Ministerio no tienen capa de texto: ningún parser
determinista los alcanza. Ese es el único punto del proceso que necesita un
modelo, y una red.

```bash
uv sync --extra llm
export ANTHROPIC_API_KEY=...

uv run pic-etl transcribe --documento RES_MEN_016202_2023 --paginas 2,3
uv run pic-etl review     RES_MEN_016202_2023      # diff cifra a cifra
uv run pic-etl promote    RES_MEN_016202_2023      # ya lo carga `build`
```

`transcribe` escribe en `extractions/propuestas/`, que `build` **no lee** —su
glob no es recursivo—, junto con un acta: modelo, hash de la instrucción,
páginas, resolución, y las cifras que el modelo vio y decidió no transcribir.
Promover es un acto aparte. Un archivo que aún no esté en el registro entra con
`--archivo RUTA --id ID --tipo TIPO --emisor EMISOR --titulo TITULO
--registrar`.

Sin el extra `llm`, todo lo demás sigue corriendo sin red.

## El tablero

Cinco páginas sobre el mismo `pic.sqlite`, más un visor por documento.

| | |
|---|---|
| **Panorama** | El embudo, el dinero, la cobertura, la línea de tiempo del corpus y el registro de hallazgos. Cada cifra enlaza los documentos que la afirman y explica, al pasar el cursor, a qué ciclo pertenece y qué años cubre. |
| **Proceso** | El circuito del dinero y las diez etapas, con la evidencia documental de cada una. |
| **Procedencia** | Cualquier cifra junto a la tabla original, con la celda resaltada. 32 tablas fuente reproducidas. |
| **Esquema** | Las 55 tablas, sus columnas y sus relaciones, leídas del mismo `MetaData` con que se construye la base. |
| **Consulta** | SQL real contra `pic.sqlite`, ejecutado en el navegador con sql.js. |

Un `.docx` no se abre en un navegador: se descarga. Por eso cada cita apunta al
visor `documento.html`, que incrusta el PDF cuando lo hay y reproduce las
tablas extraídas cuando no.

Ninguna cifra está escrita en las plantillas. Dos pruebas lo sostienen: ningún
guion de página puede traer un literal de cuatro cifras que no sea un año, ni
deletrear una cifra dentro de un texto. Se añadieron después de descubrir que
el embudo tenía sus cinco números escritos a mano y que un pie de tarjeta decía
«20 documentos» donde eran quince.

## Alcance

De los 27 documentos del registro —23 archivos más 4 que sólo se citan—:

- **20 procesados**, que aportan las 428 cifras
- **3 leídos** que no declaran ninguna cifra propia
- **4 citados** que no están en el corpus

Ocho de las diez etapas del proceso tienen respaldo documental. Las dos que no
—revisión en mesa técnica y control— son justamente las que dirimirían las
divergencias, y el tablero lo dice en lugar de dibujar diez cajas seguras.

`rubro_mapping` sigue vacío a propósito: sin puente entre las dos generaciones
de rubros, una consulta que las cruce no devuelve nada, que es la respuesta
correcta.

## Hallazgos

42 entradas en el registro, 39 con una consulta que las demuestra: sumas que no
cuadran con sus partes, cifras que un documento copia mal de otro, una misma
palabra que significa cuatro cosas distintas. No se obtienen retecleando; sólo
aparecen si los documentos se leen y se comparan entre sí.

## Documentación

- [`docs/pic-data-model-v2.md`](docs/pic-data-model-v2.md) — el esquema, los
  invariantes I1-I15 y el registro de inconsistencias
- [`docs/pic-etl-design.md`](docs/pic-etl-design.md) — el diseño de extracción y
  carga, el paso asistido por modelo, y los defectos que la implementación
  encontró en el esquema
