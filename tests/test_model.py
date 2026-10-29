"""Campos declarados: diccionario de datos y ERD derivados del tipo, no de una convención."""

from __future__ import annotations

import unittest

from docu.adapters.langs.java import JavaLangAdapter
from docu.adapters.langs.python import PythonLangAdapter
from docu.adapters.langs.typescript import TypeScriptLangAdapter
from docu.core.contracts import SymbolKind
from docu.generate.diagrams import erd_diagram
from docu.generate.facts import Fact, symbol_facts
from docu.generate.markdown import render_l1

JAVA = """package com.example;

@Entity
public class Pedido {
    private final String id;
    @Column(name = "total")
    private BigDecimal total = BigDecimal.ZERO;
    private List<Cliente> clientes = new ArrayList<>();

    public record Linea(@JsonProperty("sku") String sku, int cantidad) {}

    public BigDecimal total() { return total; }
}
"""

PYTHON = '''
from dataclasses import dataclass
from typing import List


@dataclass
class Pedido:
    id: str
    total: float
    lineas: List["Linea"]


class Linea:
    sku: str
'''

TS = """
export interface Linea {
  sku: string;
  cantidad: number;
  precio?: number;
}

export class Pedido {
  private readonly id: string;
  total: number = 0;
  lineas: Linea[] = [];
}
"""


def children_of(symbols, kind):
    """Todos los hijos de ese tipo, incluidos los de tipos anidados."""
    found = []

    def visit(symbol):
        for child in symbol.children:
            if child.kind is kind:
                found.append(child)
            visit(child)

    for symbol in symbols:
        visit(symbol)
    return found


class JavaFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.symbols = JavaLangAdapter().symbols("Pedido.java", JAVA)
        self.fields = {field.name: field for field in children_of(self.symbols, SymbolKind.FIELD)}

    def test_fields_with_generics_and_initializers(self) -> None:
        self.assertEqual(set(self.fields), {"id", "total", "clientes", "sku", "cantidad"})

    def test_type_is_the_declared_one(self) -> None:
        self.assertEqual(self.fields["clientes"].signature, "List<Cliente>")
        self.assertEqual(self.fields["total"].signature, "BigDecimal")

    def test_field_annotations_are_kept(self) -> None:
        self.assertIn("@Column", self.fields["total"].annotations)

    def test_record_components_are_fields(self) -> None:
        self.assertEqual(self.fields["sku"].qualname.split(".")[-2], "Linea")

    def test_fields_are_not_methods(self) -> None:
        methods = [child.name for child in children_of(self.symbols, SymbolKind.METHOD)]
        self.assertNotIn("id", methods)


class PythonFieldTests(unittest.TestCase):
    def test_annotated_and_plain_attributes(self) -> None:
        fields = children_of(PythonLangAdapter().symbols("x.py", PYTHON), SymbolKind.FIELD)
        names = {field.name for field in fields}
        self.assertEqual(names, {"id", "total", "lineas", "sku"})

    def test_annotation_is_preserved(self) -> None:
        fields = {field.name: field for field in children_of(PythonLangAdapter().symbols("x.py", PYTHON), SymbolKind.FIELD)}
        self.assertEqual(fields["lineas"].signature, "List['Linea']")


class TypeScriptFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        fields = children_of(TypeScriptLangAdapter().symbols("x.ts", TS), SymbolKind.FIELD)
        self.fields = {field.name: field for field in fields}

    def test_interface_and_class_properties(self) -> None:
        self.assertEqual(set(self.fields), {"sku", "cantidad", "precio", "id", "total", "lineas"})

    def test_optional_property_is_marked(self) -> None:
        self.assertIn("ausente", self.fields["precio"].signature)


class FactTests(unittest.TestCase):
    def test_fields_become_field_facts_with_owner(self) -> None:
        facts = symbol_facts(JavaLangAdapter().symbols("Pedido.java", JAVA))
        fields = {fact.subject: fact for fact in facts if fact.kind == "field"}
        self.assertIn("Pedido.clientes", fields)
        self.assertEqual(fields["Pedido.clientes"].attributes["owner"], "Pedido")
        self.assertEqual(fields["Pedido.clientes"].detail, "List<Cliente>")


class DictionaryTests(unittest.TestCase):
    def test_section_lists_entities_and_types(self) -> None:
        facts = symbol_facts(JavaLangAdapter().symbols("Pedido.java", JAVA))
        document = render_l1("demo", facts, {}, {})
        self.assertIn("## 8. Diccionario de datos", document)
        self.assertIn("| `Pedido` | `clientes` | `List<Cliente>` |", document)

    def test_without_fields_the_gap_is_declared(self) -> None:
        document = render_l1("demo", [], {}, {})
        self.assertIn("## 8. Diccionario de datos", document)
        self.assertIn("Sin evidencia", document)


class ErdTests(unittest.TestCase):
    def setUp(self) -> None:
        facts = symbol_facts(JavaLangAdapter().symbols("Pedido.java", JAVA)) + [
            Fact("field", "Cliente.id", "String", "Cliente.java#L1-L1", {"owner": "Cliente"}),
        ]
        self.diagram = erd_diagram(facts)

    def test_entities_and_relations(self) -> None:
        assert self.diagram is not None
        self.assertIn("erDiagram", self.diagram.mermaid)
        self.assertIn("Pedido {", self.diagram.mermaid)
        # colección → muchos; tipo simple → uno
        self.assertIn('Pedido }o--o{ Cliente : "clientes"', self.diagram.mermaid)

    def test_single_valued_relation_is_one_to_one(self) -> None:
        facts = [
            Fact("field", "A.id", "String", "a#L1-L1", {"owner": "A"}),
            Fact("field", "A.b", "B", "a#L2-L2", {"owner": "A"}),
            Fact("field", "B.id", "String", "b#L1-L1", {"owner": "B"}),
        ]
        diagram = erd_diagram(facts)
        assert diagram is not None
        self.assertIn('A }o--|| B : "b"', diagram.mermaid)

    def test_self_reference_is_ignored(self) -> None:
        facts = [
            Fact("field", "A.id", "String", "a#L1-L1", {"owner": "A"}),
            Fact("field", "A.parent", "A", "a#L2-L2", {"owner": "A"}),
        ]
        diagram = erd_diagram(facts)
        assert diagram is not None
        self.assertNotIn("-->", diagram.mermaid)
        self.assertNotIn("A }o--", diagram.mermaid)

    def test_without_fields_there_is_no_erd(self) -> None:
        self.assertIsNone(erd_diagram([]))


if __name__ == "__main__":
    unittest.main()
