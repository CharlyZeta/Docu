# Arnés de evaluación — F0, F1 y F2

## Para qué existe

Sin medición previa, cada decisión de diseño es una opinión. Este arnés mide **el retriever**, no la
prosa: si el agente no trae la evidencia correcta, ninguna métrica de generación posterior significa
nada.

## Protocolo

| Elemento | Definición |
|---|---|
| Golden set | 20 casos verificados a mano contra el repositorio piloto ([`golden/backend-security-starter.json`](golden/backend-security-starter.json)) |
| Distribución | 8 código · 5 arquitectura · 4 configuración/operación · 3 API |
| Evidencia esperada | ruta obligatoria; `lines` y `symbol` cuando el caso lo exige; `optional` para la evidencia secundaria |
| Dos consultas por caso | `query` (identificadores tal como buscaría un ingeniero) y `question` (pregunta humana en español) |
| Índice `windows` | BM25 léxico sobre ventanas de 40 líneas (referencia de F0) |
| Índice `symbols` | Chunks sintácticos + canal de coincidencia exacta de símbolo, fusionados con RRF (F1) |
| Índice `hybrid` | `symbols` + canal denso con embeddings multilingües (F2) |
| Índice `auto` | Enruta por forma de la consulta: código → `symbols`, pregunta → `hybrid` (F2) |
| Expansión | `--expand` aplica el glosario de dominio ([`src/docu/retrieve/glossary.py`](../src/docu/retrieve/glossary.py)) |
| Métricas | `recall@k`, `hit@k`, `MRR`, acierto de rango de líneas |

## Reproducir

```bash
# F0 — línea base léxica
python eval/harness.py --golden eval/golden/backend-security-starter.json --index windows --query-field question --label=_es

# F2 — configuración recomendada (requiere .models/multilingual-minilm)
python eval/harness.py --golden eval/golden/backend-security-starter.json --index auto --query-field question --expand --label=-auto_es
python eval/harness.py --golden eval/golden/backend-security-starter.json --index auto --query-field query --expand --label=-auto_id
```

El modelo ONNX no se versiona (`.models/` está ignorado): se descarga de
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (`onnx/model_quint8_avx2.onnx`,
`tokenizer.json`, `config.json`).

## Resultados (k=10)

| Índice | Consulta | Segmentos | recall@10 | MRR | líneas |
|---|---|---|---|---|---|
| `windows` (F0) | identificadores | 162 | 1.000 | 0.892 | 1.000 |
| `windows` (F0) | español | 162 | 0.300 | 0.128 | 0.182 |
| `windows` + glosario | español | 162 | 0.825 | 0.468 | 0.727 |
| `symbols` (F1) | identificadores | 236 | 1.000 | 0.854 | 1.000 |
| `symbols` (F1) | español | 236 | 0.825 | 0.518 | 0.727 |
| `hybrid` (F2) | identificadores | 236 | 0.950 | 0.738 | 0.909 |
| `hybrid` (F2) | español | 236 | 0.825 | **0.596** | 0.727 |
| `auto` (F2) | identificadores | 236 | **1.000** | 0.829 | **1.000** |
| `auto` (F2) | español | 236 | **0.850** | 0.562 | 0.727 |

Sin glosario, `hybrid` en español obtiene **0.450** de recall y 0.167 de MRR: los embeddings solos no
resuelven el problema.

## Lectura de los resultados

**F1 (símbolos):** no mejora el recall de archivo (saturado con identificadores) y **empeora el MRR
en español** (0.128 → 0.064 sin glosario): un chunk de método es corto, comparte menos términos y cae.
Lo que sí mejora es lo que el producto necesita para citar: **acierto de líneas +50 %** y cada chunk
arrastra `Symbol`, `Route` y anotaciones, que es el material de los documentos y diagramas.

**F2 (híbrido):** con el glosario, el recall en español pasa de 0.300 a **0.825–0.850** y el acierto
de líneas a 0.727. El objetivo de recall se cumple; el de **MRR (≥0.60) queda en 0.562** y es
exactamente lo que debe resolver el re-ranker con cross-encoder, aún pendiente.

## Hallazgos (y qué obligan a cambiar)

**F-01 · El corpus necesita higiene, no solo ingesta.** La primera corrida indexó 219 segmentos con
run-logs de `.sdd/`, contratos del flujo documental e informes de auditoría, que desplazaban al código
fuente. Excluirlos bajó a 162 segmentos y subió el MRR de 0.817 a 0.842.
→ *Consecuencia:* el perfil declara `include`/`exclude` con regla por defecto (`target/`, `.sdd/`,
`.agents/`, `contracts/`, `mcp/`, build, logs).

**F-02 · La brecha de idioma es el problema real del producto.** Con identificadores la tarea está
casi resuelta; con la misma pregunta en español, el recall cae a 0.30.
→ *Consecuencia:* la recuperación multilingüe no es opcional en un producto que se consulta en español.

**F-03 · Umbral medido en el modo equivocado no certifica nada.** `recall@10 ≥ 0.85` lo cumple un
retriever léxico ingenuo si se consulta con identificadores.
→ *Consecuencia:* umbrales **por modo de consulta**; manda la pregunta humana.

**F-04 · Hay preguntas que exigen símbolo, no similitud.** `SecurityErrorWriter` define la clase una
vez y su cuerpo habla de `ObjectMapper` e ISO-8601: BM25 no puede saber que el nombre identifica al
archivo.
→ *Consecuencia:* justifica el canal de coincidencia exacta de F1.

**F-05 · El tokenizador mueve las métricas.** El plegado de acentos llevó el recall en español de
0.100 a 0.300 sin tocar el recuperador.
→ *Consecuencia:* el tokenizador entra en el hash de frescura junto al chunker.

**F-06 · Una consulta de evaluación puede filtrar la respuesta.** La consulta de C-07 nombraba los
handlers que son evidencia *secundaria* del caso, premiándolos sobre el hecho central. Corregido.
→ *Consecuencia:* regla del golden set — **la consulta no puede nombrar símbolos de la evidencia
`optional`**.

**F-07 · El canal exacto inunda si no se acota.** Un tipo con 10 métodos genera 11 chunks que
coinciden con su nombre y desplazaban a `META-INF/...AutoConfiguration.imports`, que responde la
pregunta. Se fusiona con RRF y se limita el canal a 2 chunks por archivo.
→ *Consecuencia:* la fusión de canales es obligatoria; la prioridad absoluta es un antipatrón.

**F-08 · Fragmentar mejora la cita y empeora el ranking.** Ver "Lectura de los resultados".
→ *Consecuencia:* las puertas deben medir recall, MRR y acierto de línea a la vez.

**F-09 · El glosario es la palanca principal, no las embeddings.** `windows` sin símbolos ni denso,
pero **con glosario**, obtiene 0.825 en español: casi todo el resultado final. El denso aporta
+0.025 de recall y +0.09 de MRR; el glosario aporta +0.525 de recall.
→ *Consecuencia de producto:* el glosario es **dato del perfil** (`glossary:`), editable por proyecto
y sin coste de inferencia. Se documenta como el primer ajuste a hacer en una instalación nueva.

**F-10 · Las embeddings no puentean vocabulario de dominio.** Sin glosario, `hybrid` en español se
queda en 0.450. Un modelo multilingüe pequeño captura idioma, no jerga («cadena de filtros» →
`securityFilterChain`).
→ *Consecuencia:* no confiar en el modelo para el vocabulario; eso es trabajo del perfil.

**F-11 · La diversidad por archivo rescata el recall de identificadores.** El índice de símbolos con
cap de 2 chunks por archivo recupera 1.000 (antes 0.950, con un archivo ocupando media lista).
→ *Consecuencia:* la diversity cap de `Guia-v2.md` §3.4 es requisito, no refinamiento.

**F-12 · Enrutar por forma de la consulta supera a cualquier índice único.** `auto` consigue 1.000
con identificadores y 0.850 con preguntas; ningún índice solo logra ambos. Pero la heurística debe ser
estricta: una palabra capitalizada no es un identificador —"Spring Boot" y "CORS" enrutados al índice
de símbolos bajaban el MRR de 0.596 a 0.475.
→ *Consecuencia:* regla explícita (punto entre palabras, `_`, kebab-case o camelCase real) y test que
la fija.

## Cómo añadir casos

1. Verificar la evidencia leyendo el archivo (nunca de memoria ni de la documentación existente).
2. Registrar `path` exacto; `lines` solo si el caso exige precisión de rango.
3. Marcar `optional: true` para la evidencia secundaria: no debe bajar el recall.
4. `query` con los identificadores que un ingeniero teclearía; `question` como lo preguntaría un
   usuario. **Sin fuga**: la consulta no nombra la evidencia `optional` (F-06).
5. Reejecutar los cuatro modos y anotar el delta.
