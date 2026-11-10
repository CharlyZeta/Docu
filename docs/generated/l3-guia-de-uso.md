# docu — Guía de uso (Nivel 3)

Generado por `docu 0.1.0` a partir de las acciones y la configuración vigentes.

> Cada dato de esta guía indica de dónde sale. Lo que no está declarado no se inventa.

## Qué puedes hacer

> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos con prosa plausible.

## Valores que puedes ajustar

| Ajuste | Valor actual | Cita |
|---|---|---|
| `schema_version` | `1.0` | `docu.profile.yaml#L3-L3` |
| `project` | `docu` | `docu.profile.yaml#L5-L5` |
| `mode` | `apply` | `docu.profile.yaml#L6-L6` |
| `sources.git.ref` | `HEAD` | `docu.profile.yaml#L10-L10` |
| `sources.pdf` | `[]` | `docu.profile.yaml#L31-L31` |
| `sources.web.allowlist` | `["docs.spring.io", "docs.python.org", "developer.mozilla.org"]` | `docu.profile.yaml#L33-L33` |
| `sources.contracts` | `[]` | `docu.profile.yaml#L34-L34` |
| `output.dir` | `docs/generated` | `docu.profile.yaml#L37-L37` |
| `output.language` | `es` | `docu.profile.yaml#L38-L38` |
| `output.levels.l1` | `true` | `docu.profile.yaml#L40-L40` |
| `output.levels.l2` | `true` | `docu.profile.yaml#L41-L41` |
| `output.levels.l3` | `true` | `docu.profile.yaml#L42-L42` |
| `output.levels.l4` | `true` | `docu.profile.yaml#L43-L43` |
| `output.notation.diagrams` | `mermaid` | `docu.profile.yaml#L45-L45` |
| `output.notation.architecture` | `c4` | `docu.profile.yaml#L46-L46` |
| `output.notation.api` | `openapi3.1` | `docu.profile.yaml#L47-L47` |
| `acceptance.thresholds.accuracy` | `8.5` | `docu.profile.yaml#L51-L51` |
| `acceptance.thresholds.completeness` | `9.0` | `docu.profile.yaml#L52-L52` |
| `acceptance.thresholds.attribution` | `9.5` | `docu.profile.yaml#L53-L53` |
| `acceptance.thresholds.conciseness` | `7.5` | `docu.profile.yaml#L54-L54` |
| `freshness.ttl_days` | `90` | `docu.profile.yaml#L57-L57` |
| `learn.promotion_delta` | `0.05` | `docu.profile.yaml#L60-L60` |
| `learn.rollback_drop` | `0.05` | `docu.profile.yaml#L61-L61` |
| `learn.federate` | `false` | `docu.profile.yaml#L62-L62` |

## Preguntas frecuentes

> El proyecto **ya documenta** esto. Se cita para no duplicarlo ni contradecirlo.

- **What you get** — - **A manual that cannot lie silently**: 100 % of rows carry a `file#line` citation. Whatever has no evidence is declared as a *gap* instead of being filled with plausible text. - **Four different documents**, not four copies: technical manual, operations, a no-jargon guide, and onboarding. - **Diag [`README.md#L34-L49`]

- **How it works** — repository            cited facts             documents            query ┌──────────────┐      ┌──────────────────┐     ┌───────────────┐    ┌──────────────┐ │ Java · Python│  ──► │ path#L10-L42     │ ──► │ L1 · L2 · L3  │───►│ .md files    │ │ TypeScript   │      │ no citation→gap  │     │ L4 · dia [`README.md#L49-L64`]

## Aviso

Esta guía se construye a partir de lo que el sistema expone hoy y de su configuración actual. No sustituye la validación con el equipo responsable del negocio: si una acción no aparece aquí, es que no está declarada en el sistema, no que no exista.
