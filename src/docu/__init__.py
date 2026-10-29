"""docu — agente autonomo de documentacion tecnica.

El paquete `core` no importa nada de `adapters`: esa es la garantia de agnosticismo
(ver Plan.md §2, "test de agnosticismo").
"""

from docu.core.contracts import SCHEMA_VERSION

__version__ = "0.1.0"
__all__ = ["SCHEMA_VERSION", "__version__"]
