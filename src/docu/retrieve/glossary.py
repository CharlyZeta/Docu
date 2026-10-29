"""Glosario del dominio y expansion de consulta.

Hallazgo medido en F2, y el mas importante para el producto: **el glosario es la palanca
principal**, no las embeddings. Sin glosario, el indice hibrido con embeddings multilingues
obtiene 0.450 de recall@10 en preguntas en espanol; con glosario, 0.825-0.850. Las embeddings
solas no puentean "cadena de filtros" -> `securityFilterChain`.

Regla de diseno: el glosario es **dato del perfil**, no logica compilada. Cada proyecto declara
sus propios terminos y `docu` los aplica antes de recuperar, en ambos canales.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Sequence

#: Glosario v0, calibrado contra el piloto `Backend-Security-Starter`.
#: frase en espanol (plegada, minusculas) -> terminos que aparecen en el codigo
DEFAULT_GLOSSARY: dict[str, tuple[str, ...]] = {
    "cadena de filtros": ("securityfilterchain", "filter", "chain", "addfilterbefore"),
    "filtro": ("filter", "onceperrequestfilter"),
    "sesion sin estado": ("stateless", "sessioncreationpolicy"),
    "sin estado": ("stateless", "sessioncreationpolicy"),
    "rutas permitidas": ("permitall", "requestmatchers", "authorizehttprequests"),
    "csrf": ("csrf", "disable"),
    "secreto": ("secret", "hs256"),
    "expiracion": ("expiration", "expire"),
    "token de refresco": ("refreshtoken", "refresh", "rotation"),
    "refresco": ("refresh", "refreshtoken"),
    "rotacion": ("rotation", "deletebytoken"),
    "anotacion": ("annotation", "mapping"),
    "autoconfiguracion": ("autoconfiguration", "imports", "metainf"),
    "modulo": ("module", "parent", "pom"),
    "dependencia": ("dependency", "dependencymanagement", "pom"),
    "version": ("version", "springboot", "jjwt"),
    "puerto": ("port", "server"),
    "hilos virtuales": ("virtual", "threads", "enabled"),
    "cache": ("cache", "enabled", "configurationproperties"),
    "cors": ("cors", "allowedorigins", "allowcredentials"),
    "endpoint": ("endpoint", "mapping", "postmapping", "getmapping"),
    "autoridad": ("authority", "role", "hasauthority"),
    "administracion": ("management", "bss", "admin"),
    "cuerpo json": ("json", "body", "writer", "error"),
    "errores de seguridad": ("error", "entrypoint", "accessdeniedhandler", "writer"),
    "limpieza": ("cleanup", "scheduled", "expired"),
    "tarea programada": ("scheduled", "enablescheduling", "task"),
    "interfaz": ("interface", "repository"),
    "implementacion por defecto": ("default", "inmemory", "bean", "conditional"),
    "bean": ("bean", "conditionalonmissingbean"),
    "condicional": ("conditional", "conditionalonmissingbean"),
    "cliente": ("client", "starter", "dependency", "pom"),
    "usuario": ("user", "userdetails", "username"),
    "contrasena": ("password", "bcrypt", "passwordencoder"),
    "login": ("login", "authentication"),
    "permisos": ("authorize", "roles", "authorities"),
    "configuracion": ("configuration", "properties", "yml"),
    "aplicacion de ejemplo": ("sample", "application", "yml"),
}


def fold(text: str) -> str:
    """Sin diacriticos: `expiracion` y `expiración` son el mismo termino."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def merge(*glossaries: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    """Combina el glosario por defecto con el del perfil, sin perder terminos."""
    merged: dict[str, tuple[str, ...]] = {}
    for glossary in glossaries:
        for phrase, terms in glossary.items():
            existing = merged.get(phrase, ())
            merged[phrase] = tuple(dict.fromkeys((*existing, *terms)))
    return merged


def expand(
    query: str, glossary: Mapping[str, Sequence[str]] | None = None
) -> str:
    """Anade a la consulta los terminos de codigo asociados a sus frases conocidas.

    Coincidencia por frase completa con limites de palabra: `cors` no debe expandir dentro de
    `corsario`. Si no hay coincidencias, devuelve la consulta intacta (y el coste es un scan).
    """
    table = DEFAULT_GLOSSARY if glossary is None else glossary
    folded = fold(query).lower()
    extras: list[str] = []
    for phrase, terms in table.items():
        pattern = r"(?<![\w])" + re.escape(phrase) + r"(?![\w])"
        if re.search(pattern, folded):
            extras.extend(terms)
    if not extras:
        return query
    return query + " " + " ".join(dict.fromkeys(extras))
