# Evaluación del proyecto frente a la idea inicial

**Fecha:** cierre de esta etapa · **Base:** código en este repo, 369 tests, 3 repositorios medidos.

## Método

Comparo lo construido con la guía original (`Guia.txt`) por dimensiones ponderadas según el peso que
la propia guía les da. Cada nota se sostiene en evidencia ejecutable, no en la intención.

| # | Dimensión | Peso | Nota | Evidencia | Brecha principal |
|---|---|---|---|---|---|
| 1 | Ingesta y cobertura de fuentes | 12 | **72** | Código Java/Python/TS, `pom`, `pyproject`, `package.json`, YAML, OpenAPI, **PDF** (CMap por fuente, cita por página) y **web** (snapshot congelado con allowlist) | Sin IaC (Terraform/CloudFormation) y sin ejecutar JavaScript de SPA |
| 2 | Estructura y trazabilidad | 13 | **94** | Chunks sintácticos, prefijo de metadatos, paquetes, citas `archivo#L`, conformidad de 3 lenguajes | Parsers propios (no tree-sitter) y sin ERD/diccionario de datos |
| 3 | Recuperación | 12 | **82** | recall@10 **1.000** (identificadores) y **0.850** (español), híbrido de 3 canales con glosario | MRR 0.562 < 0.60 (falta cross-encoder) |
| 4 | Generación documental | 18 | **72** | L1/L2/L3/L4 con 0 afirmaciones sin cita, diagramas Mermaid embebidos, idempotencia byte a byte, 0 USD | Sigue siendo **extractiva**: sin prosa explicativa |
| 5 | Perfil y gobernanza por proyecto | 8 | **80** | Esquema validado, `init` con orden de cambio, umbrales/exclusiones/TTL efectivos | Rúbrica `required_modules` no se aplica aún |
| 6 | Evaluación y auditoría de calidad | 10 | **75** | `docu audit`: 5 comprobaciones deterministas (citas, duplicados, coherencia entre niveles, cobertura, frescura) + arnés de recuperación | Sin juez LLM para claridad/utilidad (opcional por diseño) |
| 7 | Frescura y mantenimiento | 12 | **95** | Hash de 6 entradas, `fresh/stale/expired`, incremental, PR automático, TTL | Sin `pre-commit` (decisión deliberada: valida el CI) |
| 8 | Multicapa y visualización | 8 | **88** | L1/L2/L3/L4 + diagramas (arquitectura, clases, flujo de API, ERD) + **web con divulgación progresiva** hasta el fragmento de código | Sin diagramas de secuencia (el grafo no resuelve despacho dinámico) |
| 9 | Interoperabilidad (MCP) | 7 | **88** | 8 herramientas read-only, multi-repo, `search_code` híbrido, puente HTTP | HTTP no es Streamable HTTP/SSE |

### Nota ponderada: **82 / 100** como herramienta de documentación utilizable hoy

### Fidelidad a la visión completa de la guía: **≈ 65 / 100**

La diferencia entre ambas cifras ya no son los diagramas ni el Nivel 2 —implementados— sino la capa de
prosa con LLM, el juez automático que aquí se sustituyó a propósito por verificación determinista, y las
fuentes que no son código (PDF, web, IaC).

## Prueba ciega sobre código no visto

`ZyrconPay` (232 archivos, nunca analizado) en la primera pasada:

- 253 afirmaciones, **0 sin cita**, completitud 8/10 → compuerta `REVIEW`
- **0 rutas HTTP** declaradas por un proyecto con 8 controladores Spring

Diagnóstico: dos defectos reales del adaptador Java.

1. Los parámetros con anotaciones (`@RequestHeader(value = "X", required = false)`) rompían el
   patrón de firma: se perdían el método **y su ruta**.
2. Las llaves dentro de anotaciones (`@ApiResponses(value = { ... })`) desalineaban el conteo de
   bloques: todo lo posterior quedaba «dentro» de la anotación.

Corregidos (parentesis balanceados + neutralización de llaves en anotaciones + bloque de anotaciones
por tramo), el mismo repo da ahora:

- 264 afirmaciones, **10/10**, compuerta `PUBLISH`
- **5 rutas** con su cita exacta: `POST /api/v1/payments/intents`,
  `POST /api/v1/gateways/payway/webhooks`, `GET /api/v1/payments/{id}/status`,
  `GET /api/v1/payments/{id}/status-stream`, `POST /api/v1/payments/{id}/authorize`

Los 369 tests siguen en verde y el piloto Java no regresó (220 afirmaciones, 10/10).

## Qué puedes esperar al probarla

| Repo | Resultado medido |
|---|---|
| Java/Spring (≈100 archivos) | ~220 afirmaciones, 0 sin cita, 10/10, 7 rutas, 4 módulos, 8 paquetes, 0.6 s |
| Python (este repo) | 517 afirmaciones, 10/10, 12 paquetes, 51 claves de configuración, 0.7 s |
| Java multi-módulo ajeno | 264 afirmaciones, 10/10, 5 rutas, 4 módulos, 12 paquetes, 2.6 s |

**Lo que sí obtienes:** manual técnico y onboarding con cada fila citada a `archivo#L`, inventario de
paquetes/módulos, dependencias con versión y scope, rutas HTTP, claves de configuración, índice de
tipos y métodos, manifest de frescura, regeneración incremental, PR automático, conformidad
arquitectónica (`drift`) y consulta por MCP desde otro repo.

**Lo que no obtienes todavía:** explicaciones en prosa (son tablas), diagramas de secuencia/clases,
Nivel 2 de operación/despliegue, ingestión de PDFs o web, ERD/diccionario de datos y generación de
OpenAPI.

> **Sobre el evaluador:** no requiere ninguna IA. `docu audit` verifica las cinco propiedades
> objetivas (cita abrible y con su sujeto dentro del rango, duplicados, coherencia entre niveles,
> cobertura de secciones aplicables y frescura) con código reproducible y coste cero. Un juez LLM
> solo añadiría la parte subjetiva —claridad y utilidad didáctica— y debería ser **asesor, nunca
> compuerta**: si el verificador es otro modelo, el producto pierde la garantía que promete.

## Ruta a 90+ (estimación)

| Trabajo | Días | Impacto |
|---|---|---|
| Diagramas como código (secuencia desde grafo de llamadas, clases desde tipos) | 3–4 | +10 en dimensión 8 |
| Ingesta PDF (layout-aware) y web con snapshot | 2–3 | +10 en dimensión 1 |
| Capa LLM sobre los hechos + juez calibrado + `docu audit` | 5–7 | +20 en dimensiones 4 y 6 |
| Nivel 2 (operación/despliegue) | 2 | +5 en dimensión 8 |
| Cross-encoder de re-ranking | 1–2 | +3 en dimensión 3 |

Total ≈ 3 semanas de trabajo para pasar de **69** a **~90**.

## Riesgos al probarla en un repo desconocido

1. **Parsers propios, no tree-sitter.** Sintaxis poco común (Kotlin/Scala en el repo, Java con
   procesadores de anotaciones exóticos, TypeScript con decoradores de parámetro) puede degradar el
   parseo. En TypeScript ya sé que `@Body() dto` rompe la firma: es la misma clase de fallo que acabo
   de corregir en Java.
2. **Rutas no extractables.** Django (`urls.py`), Express (`app.get`), rutas declaradas en XML o
   config no se detectan. Si el proyecto declara un framework web y no hay rutas, la compuerta
   devuelve `REVIEW` a propósito: prefiere avisar a mentir.
3. **Repos grandes.** El índice de métodos se corta a 200 filas; el documento de un monorepo puede
   pesar varios MB. El rendimiento es bueno (2.6 s para 232 archivos), el tamaño no está paginado.
4. **Sin juez automático.** Las métricas del documento (exactitud, completitud) las calcula el propio
   generador. Es una compuerta honesta, pero no una auditoría independiente.

## Recomendación de prueba

1. `docu init` en un repo de tamaño medio (100–500 archivos), idealmente Java/Spring o Python.
2. Revisar la sección «Alcance y límites» del manual generado y **muestrear 10 citas**: abrir el
   archivo y la línea indicada.
3. `docu drift --bootstrap` y revisar el modelo de 20–50 componentes.
4. `docu gen --incremental` dos veces: la segunda debe decir «sin cambios» (exit 10).
5. Probar `search_code` por MCP con una pregunta real del equipo.
6. Medir lo que de verdad importa: ¿cuánto tardaría un nuevo integrante en entender el proyecto con
   este documento frente a sin él?
