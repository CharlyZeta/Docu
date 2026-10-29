"""Adaptador Java: el parser estructural es la base del indice de simbolos de F1."""

from __future__ import annotations

import unittest

from docu.adapters.langs.java import JavaLangAdapter, depth_map, mask_source, matching_brace
from docu.core.contracts import Symbol, SymbolKind


def _method(symbol: Symbol, name: str) -> Symbol:
    return next(
        child
        for child in symbol.children
        if child.name == name and child.kind in (SymbolKind.METHOD, SymbolKind.CONSTRUCTOR)
    )


def _methods(symbol: Symbol) -> list[str]:
    """Nombres de los miembros que son métodos.

    Los campos también son hijos del tipo desde que se extraen para el diccionario de datos y el
    ERD, así que un test sobre métodos debe decir «métodos», no «todos los hijos».
    """
    return [
        child.name
        for child in symbol.children
        if child.kind in (SymbolKind.METHOD, SymbolKind.CONSTRUCTOR)
    ]


def _fields(symbol: Symbol) -> list[str]:
    return [child.name for child in symbol.children if child.kind is SymbolKind.FIELD]

FIXTURE = '''package com.example.demo;

import java.util.Map;
import static org.junit.Assert.assertEquals;
import org.springframework.web.bind.annotation.*;

/**
 * Javadoc con llaves { que no deben confundirse } con bloques reales.
 */
@RestController
@RequestMapping("/api/v1")
public class DemoController {

    private static final String TEMPLATE = "no soy una llave { ni un cierre }";

    @GetMapping("/items")
    public Map<String, Integer> listItems() {
        if (true) {
            for (int i = 0; i < 2; i++) {
                System.out.println(TEMPLATE);
            }
        }
        return Map.of("count", 1);
    }

    @PostMapping("/items")
    public void createItem(String name) {
        helper(name);
    }

    private void helper(String name) {
        assert name != null;
    }
}
'''


def line_of(source: str, needle: str, occurrence: int = 1) -> int:
    position = -1
    for _ in range(occurrence):
        position = source.index(needle, position + 1)
    return source[:position].count("\n") + 1


class MaskTests(unittest.TestCase):
    def test_braces_in_comments_and_strings_are_masked(self) -> None:
        masked = mask_source(FIXTURE)
        self.assertNotIn("{ que no", masked)
        # Solo quedan las llaves reales: se descartan la del javadoc y la del literal.
        self.assertEqual(masked.count("{"), FIXTURE.count("{") - 2)
        self.assertEqual(masked.count("}"), FIXTURE.count("}") - 2)

    def test_newlines_are_preserved(self) -> None:
        self.assertEqual(mask_source(FIXTURE).count("\n"), FIXTURE.count("\n"))

    def test_depth_and_matching_brace(self) -> None:
        masked = mask_source(FIXTURE)
        depth = depth_map(masked)
        opening = masked.find("class DemoController")
        brace = masked.find("{", opening)
        closing = matching_brace(masked, brace)
        self.assertEqual(depth[brace], 0)
        self.assertEqual(closing, len(masked.rstrip()) - 1)


class SymbolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = JavaLangAdapter()
        self.symbols = self.adapter.symbols("DemoController.java", FIXTURE)
        self.types = [s for s in self.symbols if s.kind is SymbolKind.CLASS]
        self.routes = [s for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE]
        self.controller = self.types[0]

    def test_type_is_detected_with_annotations(self) -> None:
        self.assertEqual(len(self.types), 1)
        self.assertEqual(self.controller.name, "DemoController")
        self.assertIn("@RestController", self.controller.annotations)
        self.assertIn("@RequestMapping", self.controller.annotations)

    def test_type_starts_at_its_first_annotation(self) -> None:
        self.assertEqual(self.controller.line_start, line_of(FIXTURE, "@RestController *".replace(" *", "")))
        self.assertEqual(self.controller.line_end, FIXTURE.count("\n"))  # cierre de la clase

    def test_members_exclude_control_flow_blocks(self) -> None:
        self.assertEqual(_methods(self.controller), ["listItems", "createItem", "helper"])

    def test_method_range_covers_body_only(self) -> None:
        method = _method(self.controller, "listItems")
        self.assertEqual(method.line_start, line_of(FIXTURE, "@GetMapping"))
        # El metodo termina en su llave de cierre, no en la del siguiente miembro.
        self.assertEqual(method.line_end, line_of(FIXTURE, "@PostMapping") - 2)
        self.assertIn("Map<String, Integer> listItems()", method.signature)

    def test_method_kind_and_qualname(self) -> None:
        method = _method(self.controller, "createItem")
        self.assertIs(method.kind, SymbolKind.METHOD)
        self.assertEqual(method.qualname, "DemoController.createItem")

    def test_static_field_is_a_field_not_a_method(self) -> None:
        """Un `static final` es un campo: se documenta en el diccionario de datos, no como método."""
        self.assertNotIn("TEMPLATE", _methods(self.controller))
        self.assertIn("TEMPLATE", _fields(self.controller))

    def test_string_with_parentheses_does_not_break_parsing(self) -> None:
        source = FIXTURE.replace('"no soy una llave { ni un cierre }"', '"metodo() falso { }"')
        symbols = self.adapter.symbols("DemoController.java", source)
        self.assertEqual(_methods(symbols[0]), ["listItems", "createItem", "helper"])


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = [
            s for s in JavaLangAdapter().symbols("DemoController.java", FIXTURE) if s.kind is SymbolKind.HTTP_ROUTE
        ]

    def test_class_level_path_is_prefixed(self) -> None:
        names = {route.name for route in self.routes}
        self.assertIn("GET /api/v1/items", names)
        self.assertIn("POST /api/v1/items", names)

    def test_route_keeps_method_qualname(self) -> None:
        route = next(r for r in self.routes if r.name.startswith("POST"))
        self.assertEqual(route.qualname, "DemoController.createItem")

    def test_helpers_without_mapping_are_not_routes(self) -> None:
        self.assertEqual(len(self.routes), 2)


class ImportAndCallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = JavaLangAdapter()

    def test_imports_are_extracted_including_static(self) -> None:
        imports = self.adapter.imports("DemoController.java", FIXTURE)
        self.assertIn("java.util.Map", imports)
        self.assertIn("org.junit.Assert.assertEquals", imports)

    def test_calls_are_limited_to_declared_methods(self) -> None:
        calls = self.adapter.calls("DemoController.java", FIXTURE)
        self.assertIn(("DemoController", "helper"), calls)
        self.assertNotIn(("DemoController", "println"), calls)

    def test_interface_without_bodies_is_parsed(self) -> None:
        source = "public interface Repo<T> {\n    T find(String id);\n    void save(T item);\n}\n"
        symbols = self.adapter.symbols("Repo.java", source)
        self.assertEqual(len(symbols), 1)
        self.assertIs(symbols[0].kind, SymbolKind.INTERFACE)
        self.assertEqual(symbols[0].children, ())

    def test_enum_is_parsed(self) -> None:
        source = "public enum Status {\n    ACTIVE, INACTIVE;\n}\n"
        symbols = self.adapter.symbols("Status.java", source)
        self.assertIs(symbols[0].kind, SymbolKind.ENUM)

    def test_empty_and_comment_only_files_do_not_raise(self) -> None:
        self.assertEqual(self.adapter.symbols("A.java", ""), ())
        self.assertEqual(self.adapter.symbols("A.java", "// solo comentario\n"), ())

    def test_unbalanced_braces_do_not_raise(self) -> None:
        symbols = self.adapter.symbols("A.java", "class A { void x() { if (true) { }\n")
        self.assertEqual(len(symbols), 1)


if __name__ == "__main__":
    unittest.main()
