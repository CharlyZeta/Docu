"""Suite de conformidad de lenguajes (Plan.md §2).

Cada adaptador debe pasar las mismas 12 construcciones sin que se toque una linea de `core/`.
Si un adaptador nuevo obliga a modificar el nucleo, hay acoplamiento oculto.
"""

from __future__ import annotations

import unittest

from docu.adapters.langs.java import JavaLangAdapter
from docu.adapters.langs.python import PythonLangAdapter
from docu.adapters.langs.registry import adapter_for, supported_languages
from docu.adapters.langs.typescript import TypeScriptLangAdapter
from docu.core.contracts import SymbolKind

JAVA = '''package com.example;

import java.util.List;

@Service
public class OrderService {
    private final Repo repo;

    @PostMapping("/orders")
    public List<String> create(String id, int qty) {
        return helper(id);
    }

    private String helper(String id) {
        if (id == null) { return ""; }
        return id;
    }

    private static class Inner { }
}

interface Repo<T> {
    T find(String id);
}

enum Status { NEW, DONE }
'''

PYTHON = '''from dataclasses import dataclass
import json


@dataclass
class Order:
    id: str


class OrderService:
    def create(self, order_id: str, qty: int = 1) -> list[str]:
        return self._helper(order_id)

    async def fetch(self, order_id: str) -> dict:
        return {"id": order_id}

    def _helper(self, order_id: str) -> list[str]:
        return [order_id]


def module_entry(order_id: str) -> str:
    service = OrderService()
    return service.create(order_id)


app = None


@bp.post("/orders")
def create_order(order_id: str) -> str:
    return module_entry(order_id)
'''

TYPESCRIPT = '''import { Repository } from './repository';

@Controller('/api/orders')
export class OrdersController {
  constructor(private readonly repo: Repository) {}

  @Get('/:id')
  async findOne(id: string): Promise<Order> {
    return this.repo.find(id);
  }

  @Post()
  create(name: string): void {
    this.save(name);
  }

  private save(name: string): void {
    console.log(name);
  }
}

export interface Order<T> {
  id: string;
}

export enum Status {
  New,
  Done,
}

export function buildOrder(id: string): Order<string> {
  return { id } as Order<string>;
}

const handler = async (id: string) => id;
'''


def names(adapter, path: str, source: str) -> set[str]:
    """Nombres calificados, incluidos los miembros de cada tipo."""
    found: set[str] = set()
    for symbol in adapter.symbols(path, source):
        found.add(symbol.qualname)
        found.update(child.qualname for child in symbol.children)
    return found


def kinds(adapter, path: str, source: str) -> set[SymbolKind]:
    return {symbol.kind for symbol in adapter.symbols(path, source)}


class RegistryTests(unittest.TestCase):
    def test_three_languages_are_registered(self) -> None:
        self.assertEqual(set(supported_languages()), {"java", "python", "typescript"})

    def test_dispatch_by_extension(self) -> None:
        self.assertIsInstance(adapter_for("A.java"), JavaLangAdapter)
        self.assertIsInstance(adapter_for("a.py"), PythonLangAdapter)
        self.assertIsInstance(adapter_for("a.tsx"), TypeScriptLangAdapter)
        self.assertIsNone(adapter_for("notes.md"))


class JavaConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = JavaLangAdapter()
        self.symbols = self.adapter.symbols("OrderService.java", JAVA)
        self.found = names(self.adapter, "OrderService.java", JAVA)

    def test_1_class(self) -> None:
        self.assertIn("OrderService", self.found)

    def test_2_method_with_signature(self) -> None:
        method = next(s for s in self.symbols[0].children if s.name == "create")
        self.assertIn("create(String id, int qty)", method.signature)

    def test_3_interface(self) -> None:
        self.assertIn(SymbolKind.INTERFACE, kinds(self.adapter, "OrderService.java", JAVA))

    def test_4_annotations(self) -> None:
        self.assertIn("@Service", self.symbols[0].annotations)

    def test_5_generics_do_not_break_parsing(self) -> None:
        self.assertIn("Repo", self.found)

    def test_7_imports(self) -> None:
        self.assertIn("java.util.List", self.adapter.imports("OrderService.java", JAVA))

    def test_9_nested_members_are_not_mistaken_for_top_level(self) -> None:
        self.assertEqual(sum(1 for s in self.symbols if s.name == "Inner"), 0)

    def test_10_inheritance_in_signature(self) -> None:
        self.assertTrue(any("class OrderService" in (s.signature or "") for s in self.symbols))

    def test_11_enum(self) -> None:
        self.assertIn(SymbolKind.ENUM, kinds(self.adapter, "OrderService.java", JAVA))

    def test_12_http_route(self) -> None:
        routes = [s.name for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE]
        self.assertIn("POST /orders", routes)

    def test_calls_are_limited_to_declared_methods(self) -> None:
        self.assertIn(("OrderService", "helper"), self.adapter.calls("OrderService.java", JAVA))


class PythonConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PythonLangAdapter()
        self.symbols = self.adapter.symbols("orders.py", PYTHON)
        self.found = names(self.adapter, "orders.py", PYTHON)

    def test_1_class(self) -> None:
        self.assertIn("OrderService", self.found)
        self.assertIn("Order", self.found)

    def test_2_methods_and_module_functions(self) -> None:
        self.assertIn("OrderService.create", self.found)
        self.assertIn("module_entry", self.found)

    def test_4_decorators(self) -> None:
        order = next(s for s in self.symbols if s.name == "Order")
        self.assertIn("@dataclass", order.annotations)

    def test_5_generics_in_annotations(self) -> None:
        method = next(c for s in self.symbols for c in s.children if c.name == "create")
        self.assertIn("list[str]", method.signature)

    def test_6_async_is_recognised(self) -> None:
        method = next(c for s in self.symbols for c in s.children if c.name == "fetch")
        self.assertIn("async def", method.signature)

    def test_7_imports(self) -> None:
        imports = self.adapter.imports("orders.py", PYTHON)
        self.assertIn("json", imports)
        self.assertIn("dataclasses", imports)

    def test_9_nested_calls_are_attributed_to_the_innermost_function(self) -> None:
        calls = self.adapter.calls("orders.py", PYTHON)
        # El llamado se resuelve a su nombre calificado: `self._helper` es `OrderService._helper`.
        self.assertIn(("OrderService.create", "OrderService._helper"), calls)
        self.assertIn(("module_entry", "OrderService.create"), calls)

    def test_10_inheritance_in_class_signature(self) -> None:
        symbols = PythonLangAdapter().symbols("x.py", "class Child(Base):\n    pass\n")
        self.assertIn("Base", symbols[0].signature)

    def test_12_http_route_from_decorator(self) -> None:
        routes = [s.name for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE]
        self.assertIn("POST /orders", routes)

    def test_syntax_error_does_not_raise(self) -> None:
        self.assertEqual(self.adapter.symbols("broken.py", "def (:\n    pass\n"), ())

    def test_empty_file(self) -> None:
        self.assertEqual(self.adapter.symbols("empty.py", ""), ())


class TypeScriptConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = TypeScriptLangAdapter()
        self.symbols = self.adapter.symbols("orders.ts", TYPESCRIPT)
        self.found = names(self.adapter, "orders.ts", TYPESCRIPT)

    def test_1_class(self) -> None:
        self.assertIn("OrdersController", self.found)

    def test_2_methods_with_signatures(self) -> None:
        controller = next(s for s in self.symbols if s.name == "OrdersController")
        self.assertEqual({c.name for c in controller.children}, {"findOne", "create", "save"})

    def test_3_interface(self) -> None:
        self.assertIn(SymbolKind.INTERFACE, kinds(self.adapter, "orders.ts", TYPESCRIPT))

    def test_4_decorators(self) -> None:
        controller = next(s for s in self.symbols if s.name == "OrdersController")
        self.assertIn("@Controller('/api/orders')", controller.annotations)

    def test_5_generics_do_not_break_parsing(self) -> None:
        self.assertIn("Order", self.found)

    def test_6_async_method(self) -> None:
        controller = next(s for s in self.symbols if s.name == "OrdersController")
        find_one = next(c for c in controller.children if c.name == "findOne")
        self.assertIn("async", find_one.signature)

    def test_7_imports(self) -> None:
        self.assertIn("./repository", self.adapter.imports("orders.ts", TYPESCRIPT))

    def test_8_exported_function(self) -> None:
        self.assertIn("buildOrder", self.found)

    def test_9_arrow_function_property(self) -> None:
        self.assertIn("handler", self.found)

    def test_11_enum(self) -> None:
        self.assertIn(SymbolKind.ENUM, kinds(self.adapter, "orders.ts", TYPESCRIPT))

    def test_12_http_routes_with_class_prefix(self) -> None:
        routes = {s.name for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE}
        self.assertIn("GET /api/orders/:id", routes)
        self.assertIn("POST /api/orders", routes)

    def test_template_literal_braces_do_not_break_parsing(self) -> None:
        source = "class A {\n  m() {\n    const t = `${x} { falso }`;\n  }\n}\n"
        symbols = self.adapter.symbols("a.ts", source)
        self.assertEqual(symbols[0].name, "A")
        self.assertEqual([c.name for c in symbols[0].children], ["m"])

    def test_empty_file(self) -> None:
        self.assertEqual(self.adapter.symbols("empty.ts", ""), ())


class CrossLanguageConsistencyTests(unittest.TestCase):
    """La promesa del producto: los tres adaptadores producen el mismo contrato."""

    def test_all_adapters_return_symbols_with_citations(self) -> None:
        table = [
            (JavaLangAdapter(), "OrderService.java", JAVA),
            (PythonLangAdapter(), "orders.py", PYTHON),
            (TypeScriptLangAdapter(), "orders.ts", TYPESCRIPT),
        ]
        for adapter, path, source in table:
            with self.subTest(language=adapter.language):
                symbols = adapter.symbols(path, source)
                self.assertTrue(symbols)
                for symbol in symbols:
                    self.assertEqual(symbol.path, path)
                    self.assertGreaterEqual(symbol.line_start, 1)
                    self.assertLessEqual(symbol.line_start, symbol.line_end)

    def test_all_adapters_detect_at_least_one_route(self) -> None:
        table = [
            (JavaLangAdapter(), "OrderService.java", JAVA),
            (PythonLangAdapter(), "orders.py", PYTHON),
            (TypeScriptLangAdapter(), "orders.ts", TYPESCRIPT),
        ]
        for adapter, path, source in table:
            with self.subTest(language=adapter.language):
                routes = [s for s in adapter.symbols(path, source) if s.kind is SymbolKind.HTTP_ROUTE]
                self.assertTrue(routes, msg="ningun adaptador debe perder las rutas")


if __name__ == "__main__":
    unittest.main()
