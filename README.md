# docu

**Documentación técnica autogenerada y verificable.** Cada afirmación del documento cita
`archivo#línea`; si una cita no se puede abrir y confirmar, la afirmación no entra.

Motor **determinista**: no usa ningún modelo de lenguaje, cuesta 0 USD y da el mismo resultado siempre.
Agnóstico de lenguaje, incremental y con compuerta de calidad antes de publicar.

> **Estado:** núcleo completo (F0–F7), Nivel 2, diagramas como código, diccionario de datos/ERD,
> auditoría determinista, publicación web, ingesta de PDF y de fuentes web con snapshot.
> El agente se documenta a sí mismo: **1043 afirmaciones, 0 sin cita, 100.00/100** en su propia
> auditoría. **535 tests** en verde. 55 módulos · 10.605 líneas.
> Pendiente: prosa con LLM (opcional) e IaC — ver [Próximos features](#próximos-features).

---

## Qué hace

1. **Extrae** hechos del repositorio: tipos, miembros, campos, rutas HTTP, dependencias, configuración,
   artefactos de despliegue y PDFs.
2. **Cita** cada hecho con `ruta#L inicio-L fin`. Si no hay evidencia, la sección se declara como hueco
   en vez de rellenarse con prosa plausible.
3. **Mantiene** lo generado: hash de seis entradas, regeneración incremental, conformidad
   arquitectónica y PR automático cuando algo quedó desactualizado.

## Instalación

```bash
uv tool install git+https://github.com/CharlyZeta/Docu   # o: pipx install / pip install -e .
docu --help
```

El núcleo no tiene dependencias: Python 3.11+ y biblioteca estándar. Las dependencias opcionales
(`.[langs,index,docs,generate,eval]`) sólo añaden el modelo de embeddings y utilidades de evaluación.

## Inicio rápido

```bash
docu init --root .            # detecta el stack y PROPONE un perfil (no escribe nada por defecto)
docu init --root . --apply    # lo escribe: docu.profile.yaml
docu gen --root .             # genera los niveles del perfil, con citas y diagramas
docu audit --root .           # 5 comprobaciones deterministas + nota ponderada
docu status --root .          # frescura: fresh / stale / expired
```

Salida real de este repositorio:

```
docu: 1043 afirmaciones · sin cita: 0 · completitud de compuerta 10.0/10 · 1.6s
  frescura: l1=fresh, l2=fresh, l4=fresh
```

## Los cuatro niveles

| Nivel | Documento | Para quién |
|---|---|---|
| L1 | manual técnico | ingeniería: arquitectura, diagramas, API, configuración, modelo de datos, símbolos |
| L2 | operación y despliegue | quien monta el sistema: entorno, puertos, artefactos, comandos, CI |
| L3 | guía de uso | negocio: qué se puede hacer, sin jerga (con test que prohíbe el vocabulario técnico) |
| L4 | README de onboarding | quien llega nuevo |

El Nivel 2 **nunca** documenta valores de secretos: de `.env.example` toma los nombres de las variables,
y un `.env` real no se abre. Hay un test que verifica que un valor del archivo de ejemplo no aparece en
el documento generado.

## Diagramas como código

Se generan desde evidencia y se embeben en el L1 (`docs/generated/diagrams/*.mmd`):

| Diagrama | De dónde sale |
|---|---|
| arquitectura de paquetes | los `import` reales, resueltos a paquete |
| clases por paquete | tipos, métodos y herencia declarada en la firma |
| flujo de API | ruta → controlador |
| modelo de datos (ERD) | campos y relaciones derivadas del **tipo** del campo |

El ERD se recorta a las 24 entidades con más relaciones y lo declara (`%% recorte: 24 de 94`): un
diagrama que omite en silencio miente igual que una tabla vieja.

**No** se generan diagramas de secuencia: el grafo de llamadas no resuelve despacho dinámico y el
documento lo declara como hueco.

## Publicación web

`docu site` publica lo mismo en tres escalones, donde **la profundidad la elige quien lee**:

| Escalón | Qué muestra |
|---|---|
| 1. Resumen | la fila: qué es y de qué tipo |
| 2. Detalle | firma, anotaciones, valor declarado |
| 3. Prueba | la cita y el **fragmento real** del archivo, con números de línea |

Sin CDN y sin JavaScript obligatorio: el tercer escalón es un `<details>` nativo, así que funciona
abriendo `index.html` desde el disco. Hay un test que verifica que no existe ninguna referencia externa.
Arquitectura, ERD y flujo de API se dibujan como **SVG propio**; el resto queda como Mermaid copiable.

## Servidor MCP

Cualquier agente compatible consulta la misma documentación que los humanos, **sólo lectura**:

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

| Herramienta | Para qué |
|---|---|
| `list_projects` | proyectos servidos y si tienen documentación |
| `search_code` | recuperación híbrida sobre el **código** (léxico + símbolo exacto + denso) |
| `search_docs` | búsqueda sobre el **manual** generado, por nivel |
| `get_module` · `get_symbol_doc` | sección o símbolo concretos |
| `list_gaps` · `list_unsupported` | qué falta: huecos, lenguajes y fuentes no cubiertas |
| `get_architecture` · `get_freshness` | modelo declarado y estado de frescura |
| `verify_citation` | comprueba una cita y devuelve las líneas citadas |
| `get_diagram` | entrega un `.mmd` generado |

Todas las respuestas incluyen citas `archivo#L`. `search_code` publica `files_indexed` y
`files_documented`, y si el canal denso está apagado explica por qué (`dense_reason`).

**Transporte:** stdio (por defecto) y un puente HTTP (`--port`) con `POST /mcp`, `GET /health` y
`GET /projects`. El puente **no** implementa el transporte «Streamable HTTP» del estándar: es para
scripts e integraciones, no un sustituto del stdio.

**Un servidor, varios repositorios:** con `--workspace` sirve todos los proyectos documentados de una
carpeta y el agente elige con el parámetro `project`.

## Perfil: qué decide una persona

`docu init` detecta el stack (extensiones, artefactos de build, paquetes por `__init__.py`, `package` o
barril `index.ts`), propone niveles y exclusiones, y siembra el glosario sólo cuando reconoce el
framework. Reejecutarlo **no es destructivo**: produce una orden de cambio y sólo puede **añadir**
estructura.

Lo que el perfil tiene que decidir un humano, porque no es inferible:

| Decisión | Por qué no se detecta |
|---|---|
| `glossary` | la jerga del dominio («copia de seguridad» → `backup`) no está en el código |
| `sources.git.exclude` | qué es producto y qué es herramienta del equipo |
| `acceptance.thresholds` | cuánta calidad exige este proyecto |
| `sources.web.allowlist` · `urls` | a qué dominios puede consultar y qué páginas capturar |

## Higiene del corpus

Se respeta el `.gitignore` del proyecto, con la semántica de git en lo que importa (negación, patrones
de directorio, anclaje, `**`, última regla gana) y un piso de exclusiones por defecto
(`node_modules`, `target`, `dist`, `coverage`, `build`, `out`, `__pycache__`…). Lo que el proyecto
declara que no es fuente, no se documenta ni se cuenta.

## Cita, auditoría y códigos de salida

`docu audit` corre cinco comprobaciones **sin modelos**: cita abrible y con su sujeto dentro del rango,
duplicados (sujeto + cita), coherencia de rutas entre niveles, cobertura de secciones aplicables y
frescura. Nota ponderada.

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

`docu status --why` nombra los archivos que invalidaron la frescura; sin eso, «stale» es una acusación
sin nombre.

## Probar sin tocar el proyecto

`docu` escribe en `docs/generated/` y en `.docu/`; nunca en la documentación existente.

```bash
docu gen --root /ruta/al/proyecto --out /fuera/de/el/repo --dry-run    # simula: no escribe nada
docu gen --root /ruta/al/proyecto --out /fuera/de/el/repo \
         --manifest /fuera/de/el/repo/.docu/manifest.json              # manifest y ledger fuera
```

El recetario completo, con el prompt para pedírselo a un agente, está en
[`PROBAR-CON-OTRO-AGENTE.md`](PROBAR-CON-OTRO-AGENTE.md).

## Límites declarados

Lo que **no** hace, dicho en voz alta:

- **No redacta prosa**: el documento son tablas de hechos. Una introducción explicativa es la siguiente
  pieza, y sería la única que puede degradar la trazabilidad.
- **No lee PDFs escaneados, cifrados ni codificaciones sin `ToUnicode`**; cuando no puede, lo dice y
  `docu pdf` devuelve exit 40.
- **No ejecuta JavaScript**: una SPA servida vacía se declara «sin texto útil».
- **No inventa claves foráneas**: el ERD relaciona por tipo de campo declarado.
- **No cubre infraestructura provisionada** (Terraform/CloudFormation) ni diagramas de secuencia.
- **Tres lenguajes**: Java, Python y TypeScript/JS; el resto se declara como no soportado.

## Lenguajes soportados

| Lenguaje | Adaptador | Extrae |
|---|---|---|
| Java | `adapters/langs/java.py` | tipos, miembros, campos, anotaciones, imports, rutas Spring |
| Python | `adapters/langs/python.py` (sobre `ast`) | clases, funciones, atributos anotados, decoradores, rutas FastAPI/Flask |
| TypeScript/JS | `adapters/langs/typescript.py` | clases, interfaces, enums, propiedades, decoradores NestJS, rutas, `.mjs`/`.cjs` |

La **suite de conformidad** ([tests/test_conformance.py](tests/test_conformance.py)) exige las 12
construcciones en los tres lenguajes sin tocar `core/`. Añadir un lenguaje = un paquete nuevo.

## Estructura

```
src/docu/core/        contratos, puertos, política, perfil   (stdlib puro, hoja del grafo)
src/docu/index/       chunker, frescura, paquetes, .gitignore, PDFs y snapshots web
src/docu/retrieve/    glosario de dominio, híbrido y enrutado
src/docu/generate/    hechos, diagramas, cuatro niveles, operación
src/docu/audit/       auditoría determinista (citas, duplicados, coherencia, cobertura, frescura)
src/docu/publish/     web con divulgación progresiva y SVG propio
src/docu/conformance/ arquitectura prescriptiva vs. real
src/docu/learn/       ledger, patrones, promoción, federación
src/docu/delivery/    CLI, CI, propuesta de perfil, servidor MCP
src/docu/adapters/    lenguajes, embedders, fuentes (PDF, web)
eval/                 golden set, arnés de evaluación, informes
tests/                27 archivos · 535 pruebas
.models/              modelo ONNX multilingüe (ignorado en git)
```

## Documentación del proyecto

- [`docs/generated/l1-manual-tecnico.md`](docs/generated/l1-manual-tecnico.md) — el manual de este
  repositorio, generado por sí mismo: 1043 afirmaciones con cita.
- [`Guia-v2.md`](Guia-v2.md) — arquitectura corregida (14 correcciones sobre la guía original).
- [`Plan.md`](Plan.md) — fases F0–F7, §13 entregas posteriores, §14 próximos features, §15 feedback externo.
- [`EVALUACION.md`](EVALUACION.md) — nota ponderada contra la idea inicial y qué la mueve.
- [`eval/README.md`](eval/README.md) — mediciones de recuperación y hallazgos.
- [`PROBAR-CON-OTRO-AGENTE.md`](PROBAR-CON-OTRO-AGENTE.md) — probar sin pisar nada.

## Próximos features

Ver [`Plan.md`](Plan.md) §14. Por retorno esperado: usar la documentación existente del repo como
evidencia citada, indexar PDFs y snapshots web en el buscador, prosa con LLM (opcional), IaC,
diagramas de secuencia y paginación de índices grandes.

## Licencia

MIT. La federación entre instalaciones es opt-in y nunca envía código ni texto: sólo huellas de
patrones y métricas.
