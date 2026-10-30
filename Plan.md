# Plan de Construcción — Agente Documentador Autónomo y Agnóstico

> **Producto:** un motor que, invocado una vez, entrega documentación técnica verificable en cuatro
> niveles, se mantiene fresco de forma incremental y aprende de cada instalación.
> **No es:** otro chatbot sobre el repo, ni un generador de README, ni un servicio que hay que operar.
> **Regla de diseño:** si una función obliga al usuario a hacer trabajo recurrente, no entra al producto.

**Estado:** F0 completada (línea base medida) · scaffold de contratos, puertos, política y frescura
operativo con 59 tests · 8 decisiones de arquitectura cerradas en [`Guia-v2.md`](Guia-v2.md) §13.
Siguiente: F1 (adaptador Java + chunker sintáctico).

---

## 1. Definición de éxito

| KPI | Objetivo | Cómo se mide |
|---|---|---|
| Tiempo a primera documentación útil | < 15 min desde `docu init` | Cronómetro en el piloto |
| Cobertura de la rúbrica | ≥ 90 % de módulos obligatorios | Checklist del perfil |
| Fidelidad | **0 claims sin cita** en módulos aprobados | Validador de evidencia |
| Recall@10 del retriever | ≥ 0.85 | Golden set |
| Coste | < 0.05 USD/página | Ledger |
| Frescura | ≥ 95 % páginas `fresh` tras un commit típico | `docu status` |
| Carga humana | ≤ 1 revisión de PR por release, no por commit | Historial de PRs |
| Mejora entre instalaciones | ≥ 5 % de métrica tras 3 proyectos | Informe de `docu learn` |

**No-objetivos (v1):** interfaz web propia, multiusuario con permisos, edición colaborativa en vivo,
sustituir a la documentación humana curada (la complementa y la audita).

---

## 2. Estructura del repositorio

```
docu/                                   # nombre provisional
├── pyproject.toml                      # paquete + entry points de plugins
├── docu.profile.yaml                   # perfil por defecto (ver §4)
├── src/docu/
│   ├── core/
│   │   ├── orchestrator.py             # fases, presupuestos, compuertas, idempotencia
│   │   ├── contracts.py                # Artifact, Chunk, ContentNode, DocState, RunRecord
│   │   ├── ports.py                    # Protocols (8 puertos)
│   │   ├── registry.py                 # descubrimiento vía entry points
│   │   └── policy.py                   # umbrales, modos, límites de coste
│   ├── adapters/
│   │   ├── sources/    git.py pdf.py web.py openapi.py sql.py
│   │   ├── langs/      python.py typescript.py java.py      (+ queries/*.scm)
│   │   ├── stores/     chroma.py pgvector.py
│   │   ├── embedders/  onnx_local.py nvidia_api.py
│   │   ├── rerankers/  cross_encoder.py nvidia_api.py
│   │   ├── render/     markdown.py mermaid.py plantuml.py openapi.py
│   │   └── publish/    git_pr.py wiki.py
│   ├── index/          chunker.py metadata.py graph.py freshness.py
│   ├── retrieve/       hybrid.py rerank.py context.py
│   ├── generate/       evidence.py levels/{l1,l2,l3,l4}.py prompts/*.j2
│   ├── audit/          judge.py metrics.py ragas_bridge.py
│   ├── conformance/    model.py drift.py
│   ├── learn/          ledger.py patterns.py promotion.py federation.py
│   └── delivery/       cli.py ci.py mcp_server.py
├── tests/
│   ├── conformance_langs/              # suite obligatoria por LangAdapter
│   └── fixtures/
├── eval/                               # golden set + arnés + informes
│   ├── golden/                         # casos por proyecto
│   ├── harness.py
│   └── reports/
└── .github/workflows/docu.yml
```

**Test de agnosticismo (CI):** un `LangAdapter` nuevo debe pasar `tests/conformance_langs/` con 12
construcciones (clase, método, interfaz, anotación, genérico, async, import, export, lambda/nested,
herencia, enum, ruta HTTP) **sin modificar ninguna línea de `core/`**. Si lo rompe, hay una fuga de
acoplamiento.

---

## 3. Superficie de producto

### CLI (Typer)
| Comando | Hace | Sale con |
|---|---|---|
| `docu init` | Detecta stack, propone perfil, crea `.docu/` | Perfil + plan de indexación |
| `docu index [--since <ref>]` | Ingesta incremental por `content_hash` | Estadísticas de chunks y coste |
| `docu gen [--level l1..l4] [--mode propose\|apply\|publish]` | Genera y audita | Diff / PR |
| `docu audit` | Métricas por documento y por nivel | Informe + `needs_review` |
| `docu status` | Frescura, cobertura, huecos declarados | Tabla `fresh/stale/expired` |
| `docu drift` | Conformidad prescriptivo vs. real | Discrepancias clasificadas |
| `docu learn [--promote\|--federate]` | Revisa y promueve artefactos aprendidos | Versión de biblioteca |
| `docu serve --mcp` | Servidor MCP **read-only** | stdio/HTTP |

Códigos de salida estables (0 ok · 10 sin cambios · 20 `needs_review` · 30 presupuesto agotado ·
40 fuente no citable) para que el CI reaccione sin parsear texto.

### CI (GitHub Actions)
`pull_request` → valida perfil + frescura (falla rápido, < 2 s) · `push` a main → regenerate `stale` →
abre PR `docs/bot`. Reutilizable como plantilla para cualquier repo (GitLab CI incluido).

### MCP (solo lectura)
`search_docs`, `get_module`, `get_symbol_doc`, `get_architecture`, `list_gaps`, `get_last_audit`.
Sin escritura, sin ledger crudo, alcance por proyecto. Permite que Claude Code/Cursor consulten la
misma documentación que los humanos.

---

## 4. Contratos centrales

**Perfil (`docu.profile.yaml`)** — la única entrada del usuario, autocontenida:

```yaml
project: acme-billing
mode: apply                      # propose | apply | publish
sources:
  git:  {url: ., ref: HEAD, include: ["src/**"], exclude: ["**/test/**"]}
  pdf:  [{path: docs/spec.pdf}]
  web:  {allowlist: ["docs.spring.io"]}
  contracts: ["openapi.yaml", "infra/c4/**/*.yaml"]
index: {embedder: onnx-bge-768, reranker: cross-encoder-mini, store: chroma}
output:
  dir: docs
  levels: {l1: true, l2: true, l3: false, l4: true}
  notation: {diagrams: mermaid, api: openapi3.1}
acceptance:
  required_modules: [c4, erd, data_dictionary, openapi, readme, ops]
  thresholds: {accuracy: 8.5, completeness: 9.0, attribution: 9.5, conciseness: 7.5}
  voice: {l1: reference, l2: tutorial, l4: tutorial}
budgets: {max_cost_usd: 3.0, max_seconds: 900, max_pages: 40}
freshness: {ttl_days: 90}
learn: {federate: false}
```

**Los demás contratos (Chunk, ContentNode, DocState, RunRecord) se especifican en `Guia-v2.md` §3.2,
§7 y §9.** Criterio: todos son serializables a JSON y versionados con `schema_version`.

---

## 5. Plan por fases

Estimación en días-persona de un dev senior con asistencia de LLM.

### F0 — Arnés de evaluación *(3 d)* · **bloqueante** · ✅ **completada**
- Golden set sobre el piloto: **20 casos** verificados a mano contra el repositorio
  (8 código · 5 arquitectura · 4 configuración/operación · 3 API), con dos consultas por caso:
  identificadores y pregunta humana en español.
- `eval/harness.py`: BM25 de referencia en stdlib, mide recall@k, hit@k, MRR, acierto de líneas y
  coste; informes JSON + Markdown en `eval/reports/`.
- **Salida medida:** recall@10 **0.950** con identificadores · **0.300** con preguntas en español.
  Hallazgos y consecuencias en [`eval/README.md`](eval/README.md).

### F1 — Núcleo + código + Nivel 1 *(12 d)* · ✅ **completada en tres lenguajes**
Hecho: contratos, puertos, adaptadores **Java, Python (`ast`) y TypeScript**, registro por extensión,
chunker sintáctico, extractores de hechos (símbolos, YAML, Maven, pyproject, package.json,
requirements), generador **extractivo con citas obligatorias**, render Markdown de N1 y N4, compuerta
de calidad y CLI `docu gen`.
- **Medido:** 205 afirmaciones en el piloto Java (completitud 10/10) y **1034 en `docu` mismo**
  (10/10 sobre secciones aplicables: tipos, configuración y dependencias; `module` y `route` no
  aplican y se declaran como tales). **0 afirmaciones sin cita** en ambos, salida **idempotente
  byte a byte**, 0.3 s por repositorio.
- **Aprendizaje del dogfooding:** documentarse a sí mismo destapó dos defectos reales — no se leían
  `[project.optional-dependencies]` (16 dependencias invisibles) y la completitud exigía secciones
  tipo Maven/HTTP a un CLI en Python. Ambos corregidos; la aplicabilidad ahora se declara en el
  documento para que la métrica no oculte nada.
- **Criterio de agnosticismo cumplido:** la suite de conformidad (`tests/test_conformance.py`) exige
  las 12 construcciones en tres lenguajes sin modificar `core/`.
- **Paquetes como unidad arquitectónica:** se detectan con evidencia citable —`__init__.py` en Python,
  sentencia `package` en Java, barril `index.ts` en TypeScript—. `docu` documenta sus **13 paquetes**
  y el piloto sus **8 paquetes Java**, en lugar de "Módulos: 0". Un paquete cuenta como evidencia de
  estructura para la compuerta, igual que un módulo Maven.
- Pendiente: nivel L2 (operación) y Chroma como almacén persistente.

### F2 — Recuperación híbrida *(6 d)* · 🔶 **parcial: medición cerrada, re-ranker pendiente**
Hecho: embeddings multilingües locales (ONNX, 384 dims), índice híbrido con fusión RRF de tres
canales, enrutado por forma de consulta, glosario de dominio y diversity cap por archivo.
- **Medido (k=10):** `auto` → **1.000** recall con identificadores y **0.850** con preguntas en
  español (era 0.300) · acierto de líneas **0.182 → 0.727** · MRR en español **0.562** (objetivo 0.60,
  no alcanzado).
- **Hallazgo decisivo:** el **glosario de dominio** aporta +0.525 de recall por sí solo; las
  embeddings aportan +0.025. El glosario es dato del perfil (`glossary:`), no código.
- **Pendiente para cerrar F2:** re-ranker cross-encoder para levantar el MRR de 0.562 a ≥0.60.
- Ver [`eval/README.md`](eval/README.md).

### F3 — Perfil, métricas y juez calibrado *(9 d)* · 🔶 **perfil y auditoría hechos; juez LLM opcional**
Hecho: esquema y validación del perfil (`core/profile.py`), `docu init` que **detecta el stack y
propone el perfil** (niveles según rutas, glosario si reconoce el framework, exclusiones razonables)
y `gen`/`status`/`ci`/`serve` que **lo obedecen**: niveles, carpeta, exclusiones, umbrales, TTL y
glosario. **`docu audit`** con cinco comprobaciones deterministas y nota ponderada.
- **Medido:** `docu init` + `docu gen` sin banderas sobre este repo: 1084 afirmaciones, 0 sin cita,
  completitud 10/10, exit 0. Perfil inválido → exit 60. Audit sobre `saleshub`: **100.00/100** con
  402/402 citas verificables por código. 66 tests nuevos entre perfil, orden de cambio, paquetes y
  auditoría.
- **`init` es idempotente y no destructivo:** al reejecutarlo produce una **orden de cambio**
  numerada (qué se añade, qué se conserva y por qué), no escribe nada y sale con 20; `--apply` la
  aplica. La detección solo puede añadir estructura (niveles, exclusiones, glosario si estaba vacío);
  nunca redefine modo, umbrales, TTL ni el glosario escrito por una persona.
- **Pendiente:** juez LLM para claridad/utilidad, como métrica **asesora** calibrada contra humanos
  (nunca como compuerta: la compuerta es determinista, ver `docu audit`).

### F4 — Frescura, idempotencia y CI *(7 d)* · ✅ **completada**
Hecho: manifest `.docu/manifest.json` con hash de **seis** entradas por página, estados
`fresh/stale/expired`, `docu gen --incremental` (regenera solo lo desactualizado), `docu status`
(+`--json`), `docu ci check` (validación rápida sin modelo) y `docu ci regen` (regenera y escribe el
cuerpo del PR), más la acción de GitHub con `create-pull-request`.
- **Medido:** `status` sobre el piloto en **0.2 s** · incremental sin cambios **0.25 s**, exit 10 ·
  segunda generación **idéntica byte a byte** · 27 tests nuevos cubren estados, expiración por TTL,
  cambio de perfil, cambio de embedder y códigos de salida.
- **Regla respetada:** el pre-commit/PR valida; la regeneración ocurre post-merge y siempre como PR.

### F5 — Conformidad AaC *(6 d)* · ✅ **completada**
Hecho: lector de YAML sin dependencias (`core/yamlmini.py`), modelo prescriptivo
(`architecture.yaml`, estilo C4InterFlow), lectura de rutas OpenAPI, extracción de lo descriptivo
(rutas, componentes y dependencias **por imports y llamadas**), comparador con cinco clases de
discrepancia y `docu drift` con `--bootstrap`, `--json` y exit 20.
- **Medido:** `--bootstrap` sobre el piloto genera 29 componentes con sus dependencias reales y el
  round-trip da **0 discrepancias**; con tres derivas inyectadas detecta las tres (2
  `undeclared_route` con cita de código, 1 `missing_implementation`) y sale con 20.
- **Decisión de diseño:** la dependencia arquitectónica se deriva de **imports** además de llamadas;
  el grafo de llamadas solo no alcanza cuando hay despacho dinámico.

### F6 — Grafo de contenido y multicapa *(8 d)* · 🔶 **MCP y Nivel 3 hechos; L2 y grafo pendientes**
Hecho: servidor **MCP de solo lectura** (JSON-RPC 2.0 por stdio) con seis herramientas —
`search_docs`, `get_module`, `get_symbol_doc`, `list_gaps`, `get_architecture`, `get_freshness`—,
buscador BM25 reutilizable sobre los documentos (`retrieve/search.py`) y **Nivel 3** (guía de uso
sin jerga, con verbos traducidos a acciones y aviso de alcance).
- **Medido:** sesión MCP real contra el piloto; `search_docs` devuelve secciones con cita,
  `list_gaps` detecta los huecos declarados (L3 «Preguntas frecuentes»), `get_freshness` responde con
  los estados. Ninguna herramienta escribe: 343 tests, uno de ellos verifica que los `mtime` no cambian.
- **Multi-repositorio:** con `--workspace` el servidor descubre los proyectos documentados de una
  carpeta y los sirve todos; `list_projects` los enumera y las herramientas aceptan `project`. Un
  agente que trabaja en el repo A consulta la documentación del repo B sin reconfigurar nada.
- **`search_code`:** el índice híbrido de F2 vive ahora en el producto
  ([`retrieve/hybrid.py`](src/docu/retrieve/hybrid.py)) y se expone por MCP: léxico + símbolo exacto
  + denso multilingüe, con el glosario del perfil y degradación limpia si falta el modelo. Antes, la
  única vía era el Markdown generado; ahora un agente pregunta al código.
- **Transporte HTTP:** `--port` levanta un puente JSON-RPC (`POST /mcp`, `GET /health`,
  `GET /projects`). Documentado explícitamente como **no** compatible con Streamable HTTP/SSE.
- **Criterio de jerga cumplido:** test que elimina el código entre backticks y falla si aparece un
  término prohibido en la prosa del Nivel 3.
- **Nivel 2 entregado después del plan** (ver §12): operación y despliegue desde `.env.example`,
  Dockerfile, compose, scripts y workflows, sin copiar nunca valores de secretos.
- **Diagramas y publicación web** también posteriores al plan (ver §12).

### F7 — Aprendizaje y federación *(8 d)* · ✅ **completada**
Hecho: **ledger** `.docu/ledger.jsonl` alimentado en cada generación, **biblioteca de patrones** por
stack con historial y reversión, **compuerta de promoción** (mejora mínima / caída que revierte) y
**federación opt-in** con payload anonimizado por huella. CLI `docu learn` (revisar, `--promote`,
`--federate --dry-run`).
- **Medido:** sobre el piloto, `learn` resume 1 corrida con sus medias, propone el candidato y
  `--promote` instala la v1; `--federate --dry-run` emite un payload con **huella** del patrón y sin
  nombre de proyecto, rutas ni código (30 tests nuevos, incluido el que verifica la política).
- **Regla dura respetada:** el agente nunca modifica su código; aprende parámetros y selección, y todo
  candidato pasa por compuerta con reversión automática.

**Total ≈ 59 días-persona ≈ 12 semanas** con holgura para el 20 % de imprevistos.

---

## 6. Cronograma e hitos

| Semana | Trabajo | Hito |
|---|---|---|
| 1 | F0 ✅ | **M0: línea base medida** — recall@10 0.950 (identificadores) / 0.300 (español) |
| 2–4 | F1 | **M1: primer documento L1 con citas verificables** |
| 5 | F2 | **M2: recall mejorado y demostrado** |
| 6–7 | F3 | **M3: auditoría calibrada (kappa alto)** |
| 8–9 | F4 | **M4: PR automático en cada push** |
| 10 | F5 | M5: deriva detectada |
| 11 | F6 | M6: cuatro niveles consistentes |
| 12 | F7 | **M7: primera instalación que mejora a la siguiente** |

Piloto: **`Backend-Security-Starter`** (Java/Maven, 114 archivos) — pequeño, con seguridad, anotaciones
Spring y contratos HTTP: el caso ideal para probar el adaptador Java sin ruido. Segundo piloto (TS):
`portfolio`. Tercero (Python): el propio motor, *dogfooding*.

---

## 7. Retroalimentación entre instalaciones, en concreto

1. Cada corrida escribe un `RunRecord` en `.docu/ledger.jsonl`.
2. Al cerrar una instalación, `docu learn` agrupa records en **candidatos**: patrones de prompt,
   priores de recuperación, defaults de perfil, entradas de taxonomía de fallos.
3. Cada candidato se evalúa **contra el golden set** y se registra `Δ` por métrica.
4. Promoción solo si `Δ` mejora y ninguna métrica cae > 5 %; si cae, rollback automático.
5. Federación: payload = `{stack, métricas, versión, fingerprint de patrón}`. Nunca código, nunca
   texto del documento. `--dry-run` muestra el payload antes de enviarlo.
6. **El agente no modifica su código.** Aprende parámetros, plantillas y pesos de selección.

---

## 8. Riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Circularidad del juez (se autopuntúa bien) | Alta | Crítico | Juez separado + kappa + anclaje de Exactitud en AST |
| `tree-sitter` no resuelve tipos en Java (DI, genéricos) | Alta | Alto | Aceptar límite: documentar lo estático + leer anotaciones; marcar inferencias con confianza |
| El pipeline completo excede el presupuesto de coste | Media | Alto | Presupuestos duros, caché por contexto, refinamiento acotado |
| El PR automático se vuelve ruido para el equipo | Media | Alto | Cambios agrupados, umbral de materialidad, `publish` solo con CI verde |
| Fuga de secretos a la documentación | Media | Crítico | Redacción pre-indexado y pre-generación + test negativo obligatorio |
| Prompt injection desde el repo | Media | Medio | Contenido = dato; sistema lo declara; pruebas adversariales en fixtures |
| Cambio de modelo de embeddings invalida el índice | Media | Medio | `embed_model` en el hash y reindexación explícita, nunca silenciosa |
| Deriva de alcance (querer soportar todo) | Alta | Alto | Test de agnosticismo por adaptador; nada de excepciones en `core/` |

---

## 9. Presupuesto de coste (piloto)

- Indexación inicial del repo Java (~1.500 chunks): **0 USD** con embeddings locales.
- Generación L1+L2 completo (~40 páginas): **1.5–2.5 USD** con caché.
- Mantenimiento mensual (commits típicos): **< 1 USD**.
- Evaluación continua (juez sobre golden set): **0.30 USD por corrida**.
- **Techo operativo:** `max_cost_usd: 3.0` por corrida, con corte limpio y tareas `pending`.

---

## 10. Definición de "terminado" (por feature)

1. Contrato tipado y serializable con `schema_version`.
2. Test unitario + test de integración con fixture real.
3. Entrada en el harness de evaluación (afecta o no afecta métricas, se demuestra).
4. Documentado en `docs/` **por el propio agente** (dogfooding desde F4).
5. Sin fugas de acoplamiento: `core/` no importa nada de `adapters/`.
6. Error path probado: presupuesto agotado, fuente caída, contenido vacío, secreto detectado.

---

## 11. Primeros 10 días (arranque concreto)

| Día | Acción | Entregable |
|---|---|---|
| 1 ✅ | Crear repo, `pyproject.toml`, contratos y puertos | `core/contracts.py`, `core/ports.py`, `core/policy.py` |
| 2 | Adaptador git + tree-sitter Java; chunker sintáctico | Chunks con metadatos completos |
| 3 | Chroma + embedder ONNX; retriever híbrido mínimo | `docu index` funcionando |
| 4 ✅ | `eval/harness.py` + 20 casos del golden set | Línea base medida y documentada |
| 5 | Generador con citas obligatorias + render Markdown | Primer L1 real |
| 6–7 | Adaptadores Python y TS; suite de conformidad | 3 lenguajes pasando |
| 8 | Revisión de calidad de los primeros documentos con criterio humano | Lista de defectos priorizada |
| 9 | Ajuste del chunker/prompt según defectos reales | Versión 0.2 del índice |
| 10 | Congelar F1 y escribir el estado del arte interno | Informe M1 |

**Regla del día 1:** no se escribe ni una línea de generación antes de que exista el arnés de
evaluación. Sin medición previa, cada decisión posterior es opinión.

---

## 12. Decisiones menores pendientes

| ID | Pregunta | Default propuesto |
|---|---|---|
| D9 | Nombre del producto y del paquete | `docu` (provisional) |
| D10 | Licencia | MIT para el motor, perfil de uso para la federación |
| D11 | Idioma de salida de la documentación | Español por defecto, inglés por perfil |
| D12 | Dónde vive `.docu/` | En el repo (versionado) salvo `--local` |
| D13 | Publicación L3 (usuario final) en v1 | No: activable por perfil, no por defecto |

---

## 13. Entregas posteriores al plan

Cinco capacidades que el plan dejaba fuera o pendientes, ya implementadas y medidas. No cambian el
núcleo: se apoyan en los mismos hechos con cita.

### 13.1 Nivel 2 — operación y despliegue
Fuente: `.env.example` y equivalentes (**sólo nombres de variables**), `Dockerfile` (imagen base,
`EXPOSE`, arranque), `docker-compose` (servicios, puertos, `depends_on`), `package.json` scripts,
`pyproject [project.scripts]` y workflows de CI (nombre, disparadores, jobs).
- **Regla dura:** un `.env` real no se abre nunca y hay un test que verifica que un valor secreto del
  archivo de ejemplo **no aparece** en el documento generado.
- Los workflows dejan de contarse como configuración de la aplicación: son CI, no `application.yml`.
- **Medido:** `saleshub` documenta 14 variables de entorno y los scripts de `package.json` con su cita;
  `docu` documenta su CLI desde `pyproject.toml`.

### 13.2 Diagramas como código (Mermaid)
Cuatro familias derivadas de evidencia: arquitectura de paquetes (imports reales), clases por paquete
(con herencia declarada), flujo de API (ruta → controlador) y modelo de datos (ERD desde los tipos de
campo). Se escriben en `<docs>/diagrams/*.mmd` y se embeben en el Nivel 1.
- **No** se generan diagramas de secuencia: el grafo de llamadas no resuelve despacho dinámico y el
  documento lo declara en lugar de inventarlo.
- El primer diagrama de este repositorio destapó un ciclo real (`core → adapters`): se corrigió moviendo
  la detección de stack a `delivery/proposal.py`.

### 13.3 Diccionario de datos y ERD
Los tres adaptadores extraen **campos** (Java, incluidos componentes de `record`; Python con `ast`;
TypeScript en clases e interfaces). Se publica una sección de diccionario (entidad, campo, tipo
declarado, anotaciones, cita) y un ERD cuyas relaciones salen del **tipo del campo**: colección →
muchos, tipo simple → uno.

### 13.4 Auditoría determinista (`docu audit`)
Cinco comprobaciones, sin modelos: citas (archivo existe, rango válido y **el sujeto aparece dentro**),
duplicados (sujeto + cita), coherencia de rutas entre niveles, cobertura de secciones aplicables y
frescura. Nota ponderada con esos pesos.
- **Medido:** `docu` 936/936 citas verificadas y **100.00/100**; `saleshub` 1226/1226 y **100.00/100**.
- Un juez LLM queda como métrica **asesora** para claridad, nunca como compuerta: si el verificador es
  otro modelo, el producto pierde la garantía que promete.

### 13.5 Publicación web con divulgación progresiva
`docu site` publica la misma evidencia en tres escalones: resumen (la fila), detalle (firma,
anotaciones, valor) y **prueba** (cita + fragmento real del archivo con números de línea).
- Sin dependencias, sin CDN y sin JavaScript obligatorio: el tercer escalón es un `<details>` nativo y
  abre desde el disco. El JS sólo añade buscar y «expandir todo».
- Arquitectura, ERD y flujo de API se dibujan como **SVG propio**; el recorte es explícito («se muestran
  16 de 94 entidades · 36 relaciones fuera del recorte»). Las clases quedan como Mermaid copiable.
- `site.json` como índice legible por máquina.
- **Medido:** `saleshub` 1226 afirmaciones en 3 páginas con 1201 pruebas; cero referencias externas
  (test que lo verifica) y test de inyección de HTML.

### 13.6 Estado y pendientes
473 tests en verde. Sigue pendiente: ingesta de PDF y web como fuentes citables, capa de prosa con LLM
(opcional, la única que puede degradar la trazabilidad) y paginación de índices en monorepos grandes.

### 13.7 Ingesta de PDF
Extractor propio sin dependencias: objetos, `FlateDecode`, operadores `Tj`/`TJ`/`'`/`"`, escapes
octales y hexadecimales, **CMap `ToUnicode` por fuente** (un PDF real usa una fuente subset por rol;
aplicar un mapa global produce texto cifrado que parece texto) y posiciones `Td`/`TD`/`Tm`/`T*`.
- La unidad de cita es la **página** (`manual.pdf#p1`): un PDF no tiene líneas estables.
- Los PDFs entran en `sources`, así que uno nuevo o modificado invalida la frescura como el código.
- **Límites declarados**: no se leen PDFs escaneados, cifrados ni con codificación exótica sin
  `ToUnicode`; cuando la extracción no alcanza, el documento lo dice y `docu pdf` devuelve exit 40.
- `docu pdf` escribe el texto extraído en `<docs>/pdf/*.txt` para que sea legible sin herramientas.
- **Medido** sobre seis libros reales de 387–468 páginas: texto legible, ~330 000 caracteres por
  documento. La extracción puede perder espacios entre bloques: sirve para buscar y citar la página,
  no para reconstruir el original.

### 13.8 Ingesta web con snapshot congelado
`docu web --fetch` descarga las URLs declaradas en `sources.web.urls`, extrae el texto y lo **congela**
en `docs/generated/web/*.txt`. La cita apunta al snapshot (`.../web/x.txt#L1-LN`), no a la página viva.
- **Allowlist obligatoria** (`sources.web.allowlist`): sin dominio declarado no se descarga nada, y se
  rechazan otros esquemas (`file://`) y dominios que sólo se parecen.
- **La generación no toca la red**: lee el índice `.docu/web.json`. Refrescar es una decisión
  explícita (`--fetch`) y comparar es otra (`--check`), que reporta `vigente` o `cambió`.
- Topes defensivos (2 MB, 20 s, un reintento) y detección de páginas sin texto: una SPA servida vacía
  se declara como «no tiene texto útil» en vez de documentarse como si no dijera nada.
- **Medido:** `https://docs.python.org/3/library/ast.html` → 2103 líneas congeladas y citadas en el
  Nivel 1. `--check` detecta el cambio de hash.
- **Bug que destapó la prueba end-to-end:** con `--root` apuntando a otro proyecto, el snapshot se
  escribía en el directorio actual porque se usaba `profile.output_dir` en vez de la ruta ya resuelta
  contra la raíz. Corregido en `web`, `pdf` y `site`.

---

## 14. Próximos features (no comprometidos)

Ordenados por retorno esperado, no por facilidad. Ninguno está empezado.

| # | Feature | Por qué | Coste estimado |
|---|---|---|---|
| P1 | **Indexar PDFs y snapshots web en el buscador** | Hoy se citan pero el agente no los consulta: `search_code` sólo recorre código. Cerrar esto es lo que convierte las fuentes externas en conocimiento usable por MCP | 2–3 d |
| P2 | **Capa de prosa con LLM** (opcional, por perfil) | El documento son hechos; una introducción explicativa por sección ayudaría a leerlo. **Riesgo asumido:** es la única pieza que puede degradar la trazabilidad, así que debe ir marcada como prosa y no citarse como hecho | 4–6 d |
| P3 | **IaC: Terraform y CloudFormation** | El Nivel 2 documenta despliegue declarado en el repo; la infraestructura provisionada queda fuera | 3–4 d |
| P4 | **Diagramas de secuencia** | Hoy se declaran imposibles con el grafo actual (despacho dinámico). Requeriría resolución de DI por tipos de campo | 4–5 d |
| P5 | **Paginación de índices en monorepos** | El índice de métodos se corta a 200 filas; con 5 000 métodos el documento pierde detalle | 1–2 d |
| P6 | **Juez LLM asesor** (nunca compuerta) | Métrica de claridad/utilidad calibrada contra humanos. La compuerta seguirá siendo determinista | 3–4 d |
| P7 | **Ejecución de JavaScript para SPA** | Las páginas que sólo renderizan en cliente se declaran hoy como «sin texto útil» | 5–7 d |

**Regla que no cambia:** cualquier feature nuevo se apoya en los hechos con cita; si no puede citar, se
declara como hueco.

---

## 15. Feedback de la prueba en un proyecto ajeno (SalesHub)

18 hallazgos reportados por el agente que probó `docu` sobre un repositorio real. Estado al cerrar:

| ID | Hallazgo | Estado |
|---|---|---|
| F-01 | `.mjs` no se indexaba | **corregido**: `.mjs` y `.cjs` soportados |
| F-02 | `coverage/` indexado pese al `.gitignore` | **corregido**: se lee `.gitignore` y el piso de exclusiones aplica siempre |
| F-03 | El índice de búsqueda y el manual no coincidían (79 vs 95 archivos) | **corregido**: se publican `files_indexed` y `files_documented` |
| F-04 | Mojibake en la query MCP (`dÃ³nde`) | **corregido**: stdin/out en UTF-8; verificado con "dónde" y "ñ" |
| F-05 | `list_projects` devolvía `name: ""` | **corregido**: nombre tomado del manifest |
| F-06 | No usa la documentación existente del repo como evidencia | **pendiente**: P1 de la sección 14 |
| F-07 | Cualquier cambio invalidaba la frescura | **mitigado**: `docu status --why` nombra los archivos responsables |
| F-08 | Paquetes con menos de 3 archivos omitidos en silencio | **corregido**: el umbral se declara en el documento |
| F-09 | Exit code de `status` sin documentar | **corregido**: devuelve 20 (documentado) y `--help` lista el código de cada comando |
| F-10 | Canal denso inactivo sin explicación | **corregido**: `capabilities.dense_reason` |
| F-11 | La fuerza de la cita no se distingue | **parcial**: los paquetes por carpeta citan el archivo completo y se etiquetan `(directorio)` |
| F-12 | Nombre de proyecto inconsistente | **corregido**: `audit` y MCP usan el nombre del manifest |
| F-13 | No advertía aislar la salida de git/Prettier | **corregido**: `gen` imprime las dos líneas para `.gitignore` y `.prettierignore` |
| F-14 | Sin selección de niveles | **corregido**: `--levels l1,l2` |
| F-15 | Faltaban `verify_citation`, `get_diagram`, `list_unsupported` | **corregido**: las tres implementadas y probadas |
| F-16 | "Completitud 10/10" se leía como cobertura real | **corregido**: se muestra como **completitud de compuerta** |
| F-17 | ERD de 25 KB en un archivo | **corregido**: recorte a 24 entidades con comentario de recorte (9 KB) |
| F-18 | Aviso de PHP no configurable | **corregido**: al respetar `.gitignore`, el mirror dejó de contarse |

**Lección de método:** las cuatro pruebas ciegas destaparon 12 defectos que ningún test interno
encontraba, y el más grave (F-02) afectaba a **cualquier** proyecto sin perfil.
