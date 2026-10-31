# docu

[![CI](https://github.com/CharlyZeta/Docu/actions/workflows/docu.yml/badge.svg)](https://github.com/CharlyZeta/Docu/actions/workflows/docu.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white)
![Licencia](https://img.shields.io/badge/licencia-MIT-green)
![Dependencias](https://img.shields.io/badge/dependencias-0-blue)
![Sin LLM](https://img.shields.io/badge/LLM-no%20requerido-purple)
![Auditoría](https://img.shields.io/badge/auditor%C3%ADa-determinista-brightgreen)
![Tests](https://img.shields.io/badge/tests-588-brightgreen)

**Documentación técnica que se puede verificar.** Cada afirmación del documento cita el archivo y la
línea del código que la sostiene. Si una cita no se puede abrir y confirmar, la afirmación no entra.

---

## El problema, en dos frases

La documentación de un proyecto se desactualiza más rápido de lo que se escribe, y cuando alguien
nuevo la lee no sabe si sigue siendo cierta. `docu` la genera desde el código, cita cada dato y avisa
cuando quedó vieja.

## Qué obtenés

- **Un manual que no miente**: 100 % de las filas con cita a `archivo#línea`. Lo que no tiene evidencia
  aparece declarado como *hueco*, no rellenado con texto plausible.
- **Cuatro documentos distintos**, no cuatro copias: manual técnico, operación, guía sin jerga y
  onboarding.
- **Diagramas** de arquitectura, clases, API y modelo de datos, generados del mismo código.
- **Una web** donde cada fila se puede abrir hasta el fragmento real del archivo.
- **Un servidor MCP** para que tu agente consulte el código y la documentación con citas.
- **Mantenimiento**: cuando cambia el código, la documentación se marca vieja y el CI puede abrir un PR
  con la actualización.
- **Prosa delegada (opcional)**: si querés una introducción redactada, docu le pasa los hechos a *tu*
  agente y **valida** lo que devuelve: cada frase tiene que citar hechos existentes y ninguna puede
  aportar cifras nuevas. Sin claves, sin coste y sin que el modelo decida qué es verdad.

## Cómo funciona

```
   repositorio            hechos con cita           documentos            consulta
 ┌──────────────┐      ┌──────────────────┐     ┌───────────────┐    ┌──────────────┐
 │ Java · Python│  ──► │ ruta#L10-L42     │ ──► │ L1 · L2 · L3  │───►│ archivos .md │
 │ TypeScript   │      │ sin cita → hueco │     │ L4 · diagramas│    │ web · MCP    │
 │ + PDF/web    │      └──────────────────┘     └───────────────┘    └──────────────┘
 └──────────────┘            ▲                        ▲
                      auditoría determinista     compuerta de calidad
```

**No usa ningún modelo de lenguaje.** Es determinista: mismo código, mismo documento, byte a byte.
Cuesta 0 USD y funciona sin conexión.

## Empezar en tres comandos

```bash
docu init --root . --apply    # detecta el stack y escribe el perfil
docu gen --root .             # genera los niveles con sus citas
docu audit --root .           # cinco comprobaciones, nota ponderada
```

Instalación: `uv tool install git+https://github.com/CharlyZeta/Docu` (o `pipx`, o `pip install -e .`).
Sólo requiere Python 3.11+; el núcleo no tiene dependencias.

## Lo que lo hace distinto

| | Un LLM escribiendo docs | **docu** |
|---|---|---|
| De dónde sale el texto | del modelo | del repositorio |
| ¿Se puede comprobar? | hay que confiar | abrís la línea citada |
| ¿Se inventa lo que falta? | sí, con seguridad | declara el hueco |
| Coste y repetibilidad | variable | 0 USD, idéntico siempre |
| ¿Sabe cuándo quedó viejo? | no | hash de seis entradas |

## Los cuatro niveles

| Nivel | Documento | Para quién |
|---|---|---|
| L1 | manual técnico | ingeniería: arquitectura, diagramas, API, configuración, modelo de datos |
| L2 | operación y despliegue | quien monta el sistema: entorno, puertos, artefactos, CI |
| L3 | guía de uso | negocio: qué se puede hacer, sin jerga (hay un test que prohíbe el vocabulario técnico) |
| L4 | onboarding | quien llega nuevo |

El manual de este mismo repositorio es el ejemplo más honesto:
[`docs/generated/l1-manual-tecnico.md`](docs/generated/l1-manual-tecnico.md). Ahí están las cifras
reales, con su cita, en lugar de un número en un README.

## Diagramas y web

Los diagramas (arquitectura de paquetes, clases, flujo de API y ERD) se generan desde evidencia y se
embeben en el L1. El ERD se recorta a las entidades con más relaciones **y lo declara**: un diagrama
que omite en silencio miente igual que una tabla vieja.

`docu site` publica lo mismo en tres escalones —resumen, detalle y **prueba** (la cita y el fragmento
real del archivo)— sin CDN y sin JavaScript obligatorio: funciona abriendo `index.html` desde el disco.

## Servidor MCP

Agentes compatibles (Claude Code, Cursor, etc.) consultan la misma documentación, en **sólo lectura**:

```json
{"mcpServers": {"docu": {"command": "docu",
  "args": ["serve", "--mcp", "--root", ".", "--out", "docs/generated"]}}}
```

Herramientas: `list_projects`, `search_code`, `search_docs`, `get_module`, `get_symbol_doc`,
`list_gaps`, `list_unsupported`, `get_architecture`, `get_freshness`, `verify_citation`, `get_diagram`.
Todas las respuestas incluyen citas, y `verify_citation` devuelve las líneas citadas para comprobarlas.

## Higiene del corpus

Se respeta el `.gitignore` del proyecto (negación, directorios, anclaje y `**`) más un piso de
exclusiones (`node_modules`, `target`, `dist`, `coverage`, `build`, `out`, `__pycache__`…). Lo que el
proyecto declara que no es fuente, no se documenta ni se cuenta.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | ok |
| 10 | sin cambios (`gen --incremental`, `pdf` sin PDFs) |
| 20 | revisión: compuerta en `REVIEW`, páginas stale o hallazgos de auditoría |
| 30 | presupuesto agotado |
| 40 | fuente no citable (nada documentable, ningún PDF usable) |
| 50 | no implementado |
| 60 | perfil inválido |
| 70 | error interno |

`docu status --why` nombra los archivos que invalidaron la frescura.

## Volver a cero

`ash
docu clean                 # lista lo que borraría (simulación)
docu clean --force         # borra documentos, diagramas, web, PDFs y el estado
docu clean --docs-only     # deja el manifest: la próxima generación es incremental
docu clean --ledger        # borra también el historial de aprendizaje
`

Sólo borra lo que generó docu: los documentos con su nombre (l1-manual-tecnico.md, l2-operacion.md,
l3-guia-de-uso.md, l4-readme.md), sus carpetas de artefactos (diagrams/, web/, pdf/, site/)
y su estado (.docu/manifest.json, web.json, prose.json). **No toca** la documentación escrita a
mano —aunque comparta carpeta—, el perfil ni el ledger (salvo --ledger).

## Probar sin tocar tu proyecto

```bash
docu gen --root /ruta/al/proyecto --out /fuera/del/repo --dry-run   # no escribe nada
docu gen --root /ruta/al/proyecto --out /fuera/del/repo \
         --manifest /fuera/del/repo/.docu/manifest.json             # ni manifest ni ledger dentro
```

Recetario completo para pedírselo a un agente: [`PROBAR-CON-OTRO-AGENTE.md`](PROBAR-CON-OTRO-AGENTE.md).

## Límites declarados

- **No redacta prosa**: el documento son tablas de hechos.
- **No lee PDFs escaneados, cifrados ni codificaciones sin `ToUnicode`**; cuando no puede, lo dice.
- **No ejecuta JavaScript**: una SPA servida vacía se declara «sin texto útil».
- **No inventa claves foráneas**: el ERD relaciona por tipo de campo declarado.
- **No cubre IaC** (Terraform/CloudFormation) ni diagramas de secuencia.
- **Tres lenguajes**: Java, Python y TypeScript/JS; el resto se declara como no soportado.

## Lenguajes soportados

| Lenguaje | Extrae |
|---|---|
| Java | tipos, miembros, campos, anotaciones, imports, rutas Spring |
| Python | clases, funciones, atributos anotados, decoradores, rutas FastAPI/Flask |
| TypeScript/JS | clases, interfaces, enums, propiedades, decoradores NestJS, rutas, `.mjs`/`.cjs` |

La [suite de conformidad](tests/test_conformance.py) exige las mismas 12 construcciones en los tres
lenguajes sin tocar `core/`.

## Regla de este repositorio

**El README se actualiza en el mismo commit que cambia capacidades, comandos o números.** No es una
promesa: [`tests/test_readme.py`](tests/test_readme.py) falla si el README menciona un comando que no
existe, una herramienta MCP que el servidor no expone, un código de salida inventado o un número de
tests que no coincide.

## Estructura

```
src/docu/core/        contratos, puertos, política, perfil   (stdlib puro, hoja del grafo)
src/docu/index/       chunker, frescura, paquetes, .gitignore, PDFs y snapshots web
src/docu/retrieve/    glosario de dominio, híbrido y enrutado
src/docu/generate/    hechos, diagramas, cuatro niveles, operación
src/docu/audit/       auditoría determinista
src/docu/publish/     web con divulgación progresiva y SVG propio
src/docu/conformance/ arquitectura prescriptiva vs. real
src/docu/learn/       ledger, patrones, promoción, federación
src/docu/delivery/    CLI, CI, propuesta de perfil, servidor MCP
src/docu/adapters/    lenguajes, embedders, fuentes (PDF, web)
eval/                 golden set, arnés de evaluación, informes
tests/                conformidad, núcleo y guardia del README
```

## Documentación del proyecto

- [`Plan.md`](Plan.md) — fases F0–F7, entregas posteriores, próximos features y feedback externo.
- [`Guia-v2.md`](Guia-v2.md) — arquitectura corregida (14 correcciones sobre la guía original).
- [`EVALUACION.md`](EVALUACION.md) — nota ponderada contra la idea inicial y qué la mueve.
- [`eval/README.md`](eval/README.md) — mediciones de recuperación.

## Próximos features

Usar la documentación existente del repo como evidencia citada · indexar PDFs y snapshots web en el
buscador · prosa con LLM (opcional) · IaC · diagramas de secuencia · paginación de índices grandes.
Detalle y coste en [`Plan.md`](Plan.md) §14.

## Licencia

MIT. La federación entre instalaciones es opt-in y nunca envía código ni texto: sólo huellas de
patrones y métricas.
