# Probar `docu` desde otro proyecto, por MCP, sin pisar su documentación

Guía para pedirle a un agente que instale el servidor MCP y documente un proyecto **sin tocar** lo que
ya está escrito. Pensada para copiar y pegar.

## Regla de oro

`docu` **nunca** escribe en la carpeta de documentación existente del proyecto. Escribe en
`docs/generated/` (o donde diga `--out`) y su memoria de estado en `.docu/`. Si querés cero rastros,
hay dos banderas: `--dry-run` y `--manifest` fuera del proyecto.

## Qué pedirle al agente (prompt listo)

```text
Tarea: instalar el servidor MCP de "docu" y usarlo para documentar este proyecto,
sin modificar ni sobrescribir la documentación existente.

Reglas estrictas:
1. NO edites, muevas ni borres ningún archivo del repositorio. Sólo lees.
2. NO escribas dentro de `docs/` ni en ninguna carpeta de documentación existente.
3. Todo lo que genere docu va a una carpeta externa al repo:
   E:/Propios/Docu/out/<nombre-del-proyecto>/
4. Primero ejecutá una simulación y mostrame el resultado antes de escribir nada:
   docu gen --root . --out E:/Propios/Docu/out/<proyecto> --dry-run
5. Si la simulación no falla, recién entonces generá de verdad:
   docu gen --root . --out E:/Propios/Docu/out/<proyecto> --manifest E:/Propios/Docu/out/<proyecto>/.docu/manifest.json
6. Para el MCP, configurá exactamente:
   command: docu
   args: serve --mcp --root <ruta absoluta del proyecto> --out E:/Propios/Docu/out/<proyecto>
7. Al terminar, mostrame: la salida de `docu audit` del proyecto, y `git status` del repo
   (debe estar limpio: ninguna modificación).

No instales dependencias del proyecto ni ejecutes sus tests.
```

## Qué hace cada bandera

| Bandera | Efecto | Rastro que deja |
|---|---|---|
| `--dry-run` | calcula hechos, métricas y compuerta; **no escribe nada** | ninguno |
| `--out <fuera del repo>` | documentos y diagramas fuera del proyecto | sólo el directorio de salida |
| `--manifest <fuera del repo>` | manifest **y ledger** junto al manifest | ninguno dentro del repo |
| `docu init` | crea `docu.profile.yaml` en la raíz | un archivo nuevo, nunca sobrescribe documentación |
| `docu web --fetch` | escribe `docs/generated/web/*.txt` y `.docu/web.json` | snapshot + índice |

**Sin `--manifest`,** `docu` deja `.docu/manifest.json` y `.docu/ledger.jsonl` en el proyecto. No son
documentación, son su memoria de frescura; si no querés ni eso, usá `--manifest` externo.

## Verificación de que no pisó nada

```bash
git status --short          # debe estar vacío
git diff --stat             # sin cambios
ls docs/                    # intacto
```

Si el repo no está en git, comparar el conteo de archivos antes y después (mi prueba: 788 → 788).

## Consultas MCP que conviene probar

| Herramienta | Para qué |
|---|---|
| `list_projects` | confirmar que el servidor ve el proyecto |
| `search_code("dónde se valida el token")` | recuperación híbrida sobre el código |
| `search_docs("cómo se despliega")` | búsqueda sobre el manual generado |
| `get_module("src/pagos")` | documento de una unidad |
| `get_symbol_doc("Clase.metodo")` | ficha de un símbolo |
| `list_gaps` | qué quedó declarado como hueco |
| `get_freshness` | si la documentación está al día |

Todas son **de sólo lectura**: ninguna escribe.

## Qué mirar en el resultado

1. **«sin cita: 0»** — no hay afirmaciones sin evidencia.
2. **Completitud** — si es < 9, la compuerta dice `REVIEW` y el motivo (suele ser un framework cuyas
   rutas no se pueden extraer).
3. **Aviso de lenguajes no soportados** — lo que el agente no documenta, dicho en voz alta.
4. **Muestreo de 5 citas** — abrir el archivo y la línea; si no coinciden, hay un bug que reportar.

## Lo que este proyecto aún no cubre

Ver [`Plan.md`](Plan.md) §14: indexar PDFs y web en el buscador (P1), prosa con LLM (P2), IaC (P3),
diagramas de secuencia (P4) y paginación de índices grandes (P5).
