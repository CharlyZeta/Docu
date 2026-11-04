# docu — Operación y despliegue (Nivel 2)

Generado por `docu 0.1.0` · fuente `sha256:cbbe2` · archivos analizados: 66 · afirmaciones: 1213 · sin cita: 0

> Documento **extractivo**: cada fila procede de un archivo y un rango de líneas del repositorio. No hay texto generado sin evidencia.

## 1. Entorno requerido

> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos con prosa plausible.

## 2. Puertos y servicios

> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos con prosa plausible.

## 3. Artefactos de infraestructura

> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos con prosa plausible.

## 4. Procedimientos

| Comando | Qué ejecuta | Cita |
|---|---|---|
| `docu` | `python -m docu.delivery.cli · docu.delivery.cli:main` | `pyproject.toml#L28-L28` |

## 5. Integración continua

| Workflow | Archivo | Cita |
|---|---|---|
| `docu` | .github/workflows/docu.yml | `.github/workflows/docu.yml#L1-L1` |
| `pages` | .github/workflows/pages.yml | `.github/workflows/pages.yml#L1-L1` |

| Disparador | Workflow | Cita |
|---|---|---|
| `pull_request` | dispara docu | `.github/workflows/docu.yml#L4-L4` |
| `push` | dispara docu | `.github/workflows/docu.yml#L6-L6` |
| `workflow_dispatch` | dispara docu | `.github/workflows/docu.yml#L8-L8` |
| `push` | dispara pages | `.github/workflows/pages.yml#L7-L7` |
| `workflow_dispatch` | dispara pages | `.github/workflows/pages.yml#L9-L9` |

| Job | Workflow | Cita |
|---|---|---|
| `check` | job de docu | `.github/workflows/docu.yml#L21-L21` |
| `regen` | job de docu | `.github/workflows/docu.yml#L42-L42` |
| `build` | job de pages | `.github/workflows/pages.yml#L21-L21` |
| `deploy` | job de pages | `.github/workflows/pages.yml#L52-L52` |

## 6. Alcance y límites

- Afirmaciones documentadas: **1213** · entorno 0, puertos 0, servicios 0, comandos 1, jobs de CI 4
- **No** se documentan valores de secretos ni el contenido de un `.env` real.
- **No** se describe infraestructura provisionada que no esté declarada en el repositorio: Terraform y CloudFormation aún no se leen.
