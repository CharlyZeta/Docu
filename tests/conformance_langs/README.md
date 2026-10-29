# Suite de conformidad de lenguajes

Implementada en [`tests/test_conformance.py`](../test_conformance.py). Todo `LangAdapter` debe
pasarla **sin modificar una sola línea de `src/docu/core/`**. Si un adaptador nuevo obliga a tocar
el núcleo, hay acoplamiento oculto y el cambio se rechaza.

Estado actual: **Java**, **Python** y **TypeScript** conformes.

Registro: [`src/docu/adapters/langs/registry.py`](../../src/docu/adapters/langs/registry.py) resuelve
el adaptador por extensión; el pipeline de generación no conoce ningún lenguaje concreto.

## Fixtures obligatorias

Cada lenguaje aporta un archivo en `fixtures/<lang>/` que contiene las 12 construcciones:

| # | Construcción | Qué se verifica |
|---|---|---|
| 1 | Clase con métodos | `enclosing_symbol` correcto, `line_start`/`line_end` exactos |
| 2 | Método estático y de instancia | `symbol_kind` distinto, firma capturada |
| 3 | Interfaz / trait / protocolo | relación de implementación |
| 4 | Anotaciones o decoradores | se preservan (clave para Spring y FastAPI) |
| 5 | Genéricos / tipos parametrizados | no rompen el parseo ni el rango |
| 6 | Función asíncrona | `async` reconocido |
| 7 | Import relativo y absoluto | arista en el grafo de dependencias |
| 8 | Export / visibilidad | `public`/`private` no altera el nombre calificado |
| 9 | Función anidada o lambda | se atribuye al símbolo contenedor |
| 10 | Herencia y composición | arista `extends`/`implements` |
| 11 | Enum | `symbol_kind = ENUM` |
| 12 | Ruta HTTP (framework) | `symbol_kind = HTTP_ROUTE` + verbo y path |

## Casos negativos

- Archivo con error de sintaxis: el adaptador **no revienta**; devuelve lo que pudo parsear y
  registra el tramo ilegible.
- Archivo vacío o solo comentarios: cero símbolos, sin excepción.
- Codificación no UTF-8: se detecta y se reporta, no se indexa texto corrupto.

## Regla de confianza

Las aristas de llamada que dependen de despacho dinámico (DI, interfaces, reflexión) **no se
inventan**: se omiten o se marcan con confianza baja y el renderizador de diagramas solo dibuja
las verificables estáticamente.
