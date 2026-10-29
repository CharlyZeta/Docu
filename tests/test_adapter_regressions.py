"""Regresiones descubiertas en la prueba ciega sobre código real (no en los fixtures de juguete).

Cada test aquí corresponde a un patrón que un proyecto real usa y que el adaptador perdía.
"""

from __future__ import annotations

import unittest

from docu.adapters.langs.java import JavaLangAdapter
from docu.adapters.langs.typescript import TypeScriptLangAdapter
from docu.core.contracts import SymbolKind

# Spring real: parámetros anotados y bloque de anotaciones con llaves.
JAVA = '''package com.example;

@RestController
@RequestMapping("/api/v1/payments")
public class PaymentController {

    private final Publisher publisher;

    public PaymentController(Publisher publisher) {
        this.publisher = publisher;
    }

    public record IntentRequest(@JsonProperty("id") String id, double amount) {}

    @PostMapping
    @Operation(summary = "Registrar", description = "Registra una intención")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "202", description = "ok"),
            @ApiResponse(responseCode = "400", description = "mal")
    })
    public Mono<ResponseEntity<Void>> register(
            @RequestHeader(value = "X-Merchant-ID", required = false)
            @Parameter(description = "Comercio") String merchantId,
            @RequestBody IntentRequest request
    ) {
        return Mono.empty();
    }
}
'''

NEST = '''import { Body, Controller, Get, Param, Post } from '@nestjs/common';

@Controller('orders')
export class OrdersController {
  constructor(private readonly service: OrdersService) {}

  @Get(':id')
  async findOne(@Param('id') id: string): Promise<Order> {
    return this.service.find(id);
  }

  @Post()
  create(@Body() dto: CreateOrderDto): Promise<void> {
    return this.service.create(dto);
  }

  private save(name: string): void {
    console.log(name);
  }
}
'''


class JavaRealWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.symbols = JavaLangAdapter().symbols("PaymentController.java", JAVA)
        self.controller = next(s for s in self.symbols if s.kind is SymbolKind.CLASS)

    def test_method_with_annotated_parameters_is_detected(self) -> None:
        names = {child.name for child in self.controller.children}
        self.assertIn("register", names)

    def test_annotated_parameters_do_not_hide_the_route(self) -> None:
        routes = [s.name for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE]
        self.assertIn("POST /api/v1/payments", routes)

    def test_annotation_block_with_braces_does_not_hide_later_members(self) -> None:
        annotations = next(c for c in self.controller.children if c.name == "register").annotations
        self.assertIn("@PostMapping", annotations)
        self.assertIn("@ApiResponses", annotations)

    def test_record_is_not_reported_as_method(self) -> None:
        """El record puede ser hijo (es un tipo anidado), pero nunca un metodo."""
        methods = {c.name for c in self.controller.children if c.kind is SymbolKind.METHOD}
        self.assertNotIn("IntentRequest", methods)
        self.assertIn(SymbolKind.CLASS, {s.kind for s in self.symbols})

    def test_citation_starts_at_the_annotation_not_inside_the_previous_record(self) -> None:
        method = next(c for c in self.controller.children if c.name == "register")
        lines = JAVA.splitlines()
        self.assertTrue(lines[method.line_start - 1].strip().startswith("@PostMapping"))


class TypeScriptNestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.symbols = TypeScriptLangAdapter().symbols("orders.ts", NEST)
        self.controller = next(s for s in self.symbols if s.kind is SymbolKind.CLASS)

    def test_decorated_parameters_are_detected(self) -> None:
        names = {child.name for child in self.controller.children}
        self.assertEqual(names, {"findOne", "create", "save"})

    def test_return_type_annotation_does_not_hide_method(self) -> None:
        create = next(c for c in self.controller.children if c.name == "create")
        self.assertIn("Promise<void>", create.signature)

    def test_routes_are_extracted_with_class_prefix(self) -> None:
        routes = {s.name for s in self.symbols if s.kind is SymbolKind.HTTP_ROUTE}
        self.assertIn("GET /orders/:id", routes)
        self.assertIn("POST /orders", routes)

    def test_constructor_is_not_a_method(self) -> None:
        self.assertNotIn("constructor", {c.name for c in self.controller.children})

    def test_decorator_with_arguments_is_preserved(self) -> None:
        self.assertIn("@Controller('orders')", self.controller.annotations)


if __name__ == "__main__":
    unittest.main()
