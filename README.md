# docu

Agente autónomo de documentación técnica: **agnóstico**, **verificable** e **incremental**.
Se invoca una vez y entrega documentación en cuatro niveles; después se mantiene solo y
aprende de cada instalación.

> Estado: **siete fases cerradas** (F0, F1, F2, F4, F5, F6, F7) + **perfil conectado**, **Nivel 2** y
> **diagramas como código** (F3 parcial: falta la capa de prosa con LLM, que es opcional). El agente se
> documenta a sí mismo: 550 afirmaciones, 0 sin cita, compuerta en verde y **auditoría determinista
> 100/100** sin ningún modelo. El servidor MCP sirve **varios repositorios** y expone **`search_code`**
> con la recuperación híbrida (1.000 de recall con identificadores, 0.850 en español).
> **432 tests** en verde. Ver [`Plan.md`](Plan.md).

## Principios que el código hace cumplir

| Principio | Dónde se garantiza |
|---|---|
| Sin evidencia no hay afirmación | `Claim.verified`, `ContentNode.is_publishable()`, `Fact.citation` |
| Publicar es una decisión auditada | `GatePolicy.evaluate()` → `PUBLISH` / `REVIEW` / `ABORT` |
| Idempotencia | `index/freshness.py::is_idempotent`, hash de 6 componentes, salida byte a byte |
| Agnosticismo | `core/ports.py` (9 puertos), `adapters/langs/registry.py`; `core/` no importa `adapters/` |
| Autonomía con presupuesto | `Budget.spend()` lanza `BudgetExhausted` en lugar de degradar salida |
| Fuente volátil no citable sin snapshot | `Artifact.__post_init__` |

## Lenguajes soportados

| Lenguaje | Adaptador | Extrae |
|---|---|---|
| Java | `adapters/langs/java.py` | tipos, miembros, anotaciones, imports, rutas Spring |
| Python | `adapters/langs/python.py` (sobre `ast`) | clases, funciones, decoradores, `async`, rutas FastAPI/Flask |
| TypeScript/JS | `adapters/langs/typescript.py` | clases, interfaces, enums, decoradores NestJS, rutas, arrow functions |

La **suite de conformidad** ([tests/test_conformance.py](tests/test_conformance.py)) exige las 12
construcciones en los tres lenguajes sin tocar `core/`. Añadir un lenguaje = un paquete nuevo.

## Uso

```bash
python -m docu.delivery.cli --help          # sin instalar nada (stdlib)
python -m unittest discover -s tests -t .   # suite del núcleo y del arnés

# evaluación de recuperación (necesita .models/multilingual-minilm para el modo híbrido)
python eval/harness.py --golden eval/golden/backend-security-starter.json --index auto --query-field question --expand
```

Con dependencias opcionales:

```bash
pip install -e ".[langs,index,docs,generate,eval]"
docu init                                     # detecta el stack y propone el perfil
docu gen                                      # niveles del perfil, con citas y diagramas
docu gen --level l1 --level l2 --level l4     # manual + operación + onboarding
docu status --root .                          # frescura: fresh / stale / expired
docu gen --dry-run                            # simula: no escribe nada (ni manifest ni ledger)
docu gen --incremental                        # regenera solo lo desactualizado
docu audit --report out/auditoria.md          # 5 comprobaciones deterministas, sin modelos
docu site --out out/site                      # web con divulgación progresiva (sin CDN ni JS obligatorio)
docu pdf                                      # extrae texto de los PDFs y reporta qué se pudo leer
docu web --fetch                              # congela las URLs del perfil (snapshot citable)
docu web --check                              # compara el snapshot con la web actual
docu ci check                                 # validación rápida para PR (sin modelo)
docu ci regen --out docs/generated            # regenera lo stale y escribe .docu/pr-body.md
docu drift --bootstrap                        # foto inicial del modelo arquitectónico
docu drift                                    # deriva entre lo declarado y el código real
docu serve --mcp --out docs/generated         # servidor MCP de solo lectura
docu learn                                    # resumen del ledger y candidatos
docu learn --promote                          # instala el patrón si supera la compuerta
docu learn --federate --dry-run               # muestra el payload anonimizado (no envía)
```

## Primera instalación

**El stack no se declara: se detecta.** `docu init` inspecciona el repositorio (extensiones, artefactos
de build y **paquetes**: `__init__.py`, sentencia `package`, barril `index.ts`), elige los niveles (L3
solo si hay rutas HTTP), siembra el glosario cuando reconoce el framework y escribe
`docu.profile.yaml` con exclusiones razonables. Después, `docu gen` **obedece el perfil**: niveles,
carpeta de salida, exclusiones, umbrales de la compuerta, TTL y glosario.

**Reejecutar `init` no es destructivo.** Si el perfil ya existe, produce una **orden de cambio**:

```
orden de cambio propuesta para demo-cambio:
  1. output.levels: ('l1', 'l4') → ('l1', 'l3', 'l4') (se detectaron rutas HTTP: habilita la guía de uso)
  · conservado: thresholds — valor humano: la detección no lo redefine

informe: .docu/init-change-order.md
no se escribió nada. Aplica con `docu init --apply`.
```

Códigos: `0` aplicado · `10` sin cambios · `20` orden de cambio pendiente de aprobación · `60` perfil
inválido. La detección solo puede **añadir** estructura; nunca reescribe modo, umbrales, TTL ni el
glosario que escribió una persona.

Lo que el perfil **sí** tiene que decidir un humano, porque no es inferible:

| Decisión | Por qué no se detecta |
|---|---|
| `glossary` | la jerga del dominio («cadena de filtros» → `securityFilterChain`) no está en el código |
| `sources.git.exclude` | qué es producto y qué es herramienta del equipo |
| `acceptance.thresholds` | cuánta calidad exige este proyecto |
| `sources.web.allowlist` | a qué dominios puede consultar |

## Servidor MCP

Cualquier agente compatible (Claude Code, Cursor) consulta la misma documentación que los humanos:

```json
{
  "mcpServers": {
    "docu": {
      "command": "docu",
      "args": ["serve", "--mcp", "--root", ".", "--out", "docs/generated"]
    }
  }
}
```

Herramientas de **solo lectura**: `list_projects`, **`search_code`**, `search_docs`, `get_module`,
`get_symbol_doc`, `list_gaps`, `get_architecture`, `get_freshness`. Todas las respuestas incluyen
citas `archivo#L`.

`search_code` es la vía recomendada para preguntas técnicas: usa la **recuperación híbrida** del
producto ([`retrieve/hybrid.py`](src/docu/retrieve/hybrid.py) — léxico + símbolo exacto + denso
multilingüe, con el glosario del perfil). `search_docs` busca en la documentación ya redactada.

### Transporte

- **stdio** (por defecto): el que usan Claude Code, Cursor y el resto de clientes MCP.
- **HTTP** (`--port`): puente JSON-RPC para consultar desde otro proceso o máquina.

```bash
docu serve --mcp --port 8791 --workspace /ruta/a/mis-proyectos
curl -s localhost:8791/health
curl -s -X POST localhost:8791/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"search_code","arguments":{"query":"dónde se valida el refresh token","project":"Backend-Security-Starter"}}}'
```

> El transporte HTTP implementa JSON-RPC por `POST /mcp` (más `GET /health` y `GET /projects`). **No**
> implementa el transporte «Streamable HTTP» del estándar MCP, que exige SSE para mensajes
> servidor→cliente: es un puente para scripts, integraciones y equipos, no un sustituto del stdio.

**Un servidor, varios repositorios.** Con `--workspace` sirve todos los proyectos documentados de una
carpeta; el agente elige con el parámetro `project`:

```json
{
  "mcpServers": {
    "docu-workspace": {
      "command": "docu",
      "args": ["serve", "--mcp", "--workspace", "/ruta/a/mis-proyectos", "--root", "/ruta/a/mis-proyectos/docu"]
    }
  }
}
```

```
list_projects                       → {"projects": [{"name":"Docu",…},{"name":"Backend-Security-Starter",…}]}
search_docs(query, project="Docu")  → secciones de ese repositorio, con citas
search_docs(query)                  → error accionable: «hay varios proyectos: indica 'project' (…)»
```

## Estructura

```
src/docu/core/       contratos, puertos, política, perfil   (stdlib puro, hoja del grafo)
src/docu/index/      chunker sintáctico, metadatos, frescura, paquetes
src/docu/retrieve/   glosario de dominio, híbrido y enrutado
src/docu/generate/   hechos, diagramas Mermaid, cuatro niveles, operación
src/docu/audit/      auditoría determinista (citas, duplicados, coherencia, cobertura, frescura)
src/docu/conformance/ arquitectura prescriptiva vs. real
src/docu/learn/      ledger, patrones, promoción, federación
src/docu/delivery/   CLI, entrada de CI, propuesta de perfil, servidor MCP (solo lectura)
src/docu/adapters/   implementaciones de cada puerto (langs, embedders, stores…)
eval/                golden set, arnés de evaluación, informes
tests/               suite del núcleo + conformidad de lenguajes (432 pruebas)
.models/             modelo ONNX multilingüe (ignorado en git)
```

## Niveles y diagramas

| Nivel | Documento | Para quién |
|---|---|---|
| L1 | manual técnico | ingeniería: arquitectura, diagramas, API, configuración, símbolos |
| L2 | operación y despliegue | quien monta el sistema: entorno, puertos, artefactos, comandos, CI |
| L3 | guía de uso | negocio: qué se puede hacer, sin jerga |
| L4 | README de onboarding | quien llega nuevo |

Los diagramas se generan como **Mermaid** a partir de evidencia y se embeben en el L1
(`docs/generated/diagrams/*.mmd`): dependencias entre paquetes derivadas de los `import` reales,
clases por paquete con su herencia declarada, flujo de la API y modelo de datos (ERD). **No** se
generan diagramas de secuencia: el grafo de llamadas no resuelve despacho dinámico y el documento lo
declara como hueco.

## Publicación web

`docu site` convierte lo mismo en una web navegable donde **la profundidad la elige quien lee**:

| Escalón | Qué muestra |
|---|---|
| 1. Resumen | la fila: qué es y de qué tipo |
| 2. Detalle | firma, anotaciones, valor declarado |
| 3. Prueba | la cita y el **fragmento real** del archivo, con números de línea |

Sin dependencias, sin CDN y sin JavaScript obligatorio: el tercer escalón es un `<details>` nativo, así
que funciona abriendo `index.html` desde el disco. El JS sólo añade buscar y «expandir todo». La
arquitectura se dibuja como **SVG propio** generado del mismo grafo.

## Documentación del proyecto

- [`Guia-v2.md`](Guia-v2.md) — guía de arquitectura corregida (14 correcciones sobre v1, decisiones cerradas).
- [`Plan.md`](Plan.md) — plan de construcción: KPIs, fases F0–F7, cronograma, riesgos, coste.
- [`Guia.txt`](Guia.txt) — documento original, conservado como referencia.

## Licencia

MIT (motor). La federación entre instalaciones es opt-in y nunca envía código ni texto.

## Probar sin tocar el proyecto

`docu` escribe en `docs/generated/` y en `.docu/`; nunca en la documentación existente. Para una
prueba sobre un repositorio ajeno, sin dejar rastro:

```bash
docu gen --root /ruta/al/proyecto --out /fuera/de/el/repo --dry-run      # simula, no escribe nada
docu gen --root /ruta/al/proyecto --out /fuera/de/el/repo \
         --manifest /fuera/de/el/repo/.docu/manifest.json                # manifest y ledger fuera
docu audit --root /ruta/al/proyecto --out /fuera/de/el/repo
```

El recetario completo, con el prompt para pedírselo a un agente y la verificación de que no se pisó
nada, está en [`PROBAR-CON-OTRO-AGENTE.md`](PROBAR-CON-OTRO-AGENTE.md).

## Próximos features

Ver [`Plan.md`](Plan.md) §14. En orden de retorno esperado: indexar PDFs y snapshots web en el buscador,
prosa con LLM (opcional y marcada como tal), IaC, diagramas de secuencia y paginación de índices.
