# docu — Manual técnico (Nivel 1)

Generado por `docu 0.1.0` · fuente `sha256:421cf` · archivos: 49 · afirmaciones: 545 · sin cita: 0

> Documento **extractivo**: cada fila procede de un archivo y un rango de líneas del repositorio. No hay texto generado sin evidencia.

## 1. Resumen

- Módulos de build: **0** · paquetes: **13**
- Dependencias declaradas: **16**
- Rutas HTTP: **0**
- Claves de configuración: **51**
- Tipos: **80** · métodos: **384**

## 2. Arquitectura: módulos y paquetes

| Paquete | Lenguaje | Archivos | Cita |
|---|---|---|---|
| `docu` | python | 44 | `src/docu/__init__.py#L1-L10` |
| `docu.adapters` | python | 9 | `src/docu/adapters/__init__.py#L1-L1` |
| `docu.adapters.embedders` | python | 2 | `src/docu/adapters/embedders/__init__.py#L1-L1` |
| `docu.adapters.langs` | python | 6 | `src/docu/adapters/langs/__init__.py#L1-L1` |
| `docu.audit` | python | 2 | `src/docu/audit/__init__.py#L1-L5` |
| `docu.conformance` | python | 3 | `src/docu/conformance/__init__.py#L1-L5` |
| `docu.core` | python | 6 | `src/docu/core/__init__.py#L1-L5` |
| `docu.delivery` | python | 5 | `src/docu/delivery/__init__.py#L1-L5` |
| `docu.generate` | python | 4 | `src/docu/generate/__init__.py#L1-L5` |
| `docu.index` | python | 5 | `src/docu/index/__init__.py#L1-L5` |
| `docu.learn` | python | 5 | `src/docu/learn/__init__.py#L1-L5` |
| `docu.retrieve` | python | 4 | `src/docu/retrieve/__init__.py#L1-L5` |
| `eval` | python | 2 | `eval/__init__.py#L1-L1` |

### Plataforma

| Elemento | Tipo | Valor | Cita |
|---|---|---|---|
| `requires-python` | propiedad | >=3.11 | `pyproject.toml#L10-L10` |

## 3. Dependencias

| Artefacto | Versión | Scope | Cita |
|---|---|---|---|
| `typer` | >=0.12 | cli | `pyproject.toml#L18-L18` |
| `PyYAML` | >=6.0 | profile | `pyproject.toml#L19-L19` |
| `tree-sitter` | >=0.23 | langs | `pyproject.toml#L20-L20` |
| `tree-sitter-python` | (sin versión fija) | langs | `pyproject.toml#L20-L20` |
| `tree-sitter-typescript` | (sin versión fija) | langs | `pyproject.toml#L20-L20` |
| `tree-sitter-java` | (sin versión fija) | langs | `pyproject.toml#L20-L20` |
| `chromadb` | >=0.5 | index | `pyproject.toml#L21-L21` |
| `onnxruntime` | >=1.18 | index | `pyproject.toml#L21-L21` |
| `tokenizers` | >=0.19 | index | `pyproject.toml#L21-L21` |
| `pdfplumber` | >=0.11 | docs | `pyproject.toml#L22-L22` |
| `markdown-it-py` | >=3.0 | docs | `pyproject.toml#L22-L22` |
| `jinja2` | >=3.1 | generate | `pyproject.toml#L23-L23` |
| `ragas` | >=0.1 | eval | `pyproject.toml#L24-L24` |
| `pytest` | >=8.0 | dev | `pyproject.toml#L25-L25` |
| `ruff` | >=0.6 | dev | `pyproject.toml#L25-L25` |
| `mypy` | >=1.10 | dev | `pyproject.toml#L25-L25` |

## 4. API HTTP

> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos con prosa plausible.

## 5. Configuración

| Clave | Valor | Cita |
|---|---|---|
| `name` | `docu` | `.github/workflows/docu.yml#L1-L1` |
| `on.pull_request.branches` | `[main]` | `.github/workflows/docu.yml#L5-L5` |
| `on.push.branches` | `[main]` | `.github/workflows/docu.yml#L7-L7` |
| `permissions.contents` | `write` | `.github/workflows/docu.yml#L11-L11` |
| `permissions.pull-requests` | `write` | `.github/workflows/docu.yml#L12-L12` |
| `concurrency.group` | `docu-${{ github.ref }}` | `.github/workflows/docu.yml#L15-L15` |
| `concurrency.cancel-in-progress` | `true` | `.github/workflows/docu.yml#L16-L16` |
| `jobs.check.name` | `frescura de la documentación` | `.github/workflows/docu.yml#L22-L22` |
| `jobs.check.if` | `github.event_name == 'pull_request` | `.github/workflows/docu.yml#L23-L23` |
| `jobs.check.runs-on` | `ubuntu-latest` | `.github/workflows/docu.yml#L24-L24` |
| `jobs.check.steps.with.python-version` | `3.12` | `.github/workflows/docu.yml#L29-L29` |
| `jobs.check.steps.run` | `pip install -e .` | `.github/workflows/docu.yml#L31-L31` |
| `jobs.check.steps.run` | `docu ci check --json` | `.github/workflows/docu.yml#L33-L33` |
| `jobs.regen.name` | `proponer documentación actualizada` | `.github/workflows/docu.yml#L39-L39` |
| `jobs.regen.if` | `github.event_name != 'pull_request` | `.github/workflows/docu.yml#L40-L40` |
| `jobs.regen.runs-on` | `ubuntu-latest` | `.github/workflows/docu.yml#L41-L41` |
| `jobs.regen.steps.with.python-version` | `3.12` | `.github/workflows/docu.yml#L46-L46` |
| `jobs.regen.steps.run` | `pip install -e .` | `.github/workflows/docu.yml#L48-L48` |
| `jobs.regen.steps.run` | `docu ci regen --out docs/generated` | `.github/workflows/docu.yml#L50-L50` |
| `jobs.regen.steps.uses` | `peter-evans/create-pull-request@v6` | `.github/workflows/docu.yml#L52-L52` |
| `jobs.regen.steps.with.branch` | `docs/docu-bot` | `.github/workflows/docu.yml#L54-L54` |
| `jobs.regen.steps.with.delete-branch` | `true` | `.github/workflows/docu.yml#L55-L55` |
| `jobs.regen.steps.with.title` | `docs: documentación regenerada por docu` | `.github/workflows/docu.yml#L56-L56` |
| `jobs.regen.steps.with.commit-message` | `docs: regenerar documentación desactualizada` | `.github/workflows/docu.yml#L57-L57` |
| `jobs.regen.steps.with.body-path` | `.docu/pr-body.md` | `.github/workflows/docu.yml#L58-L58` |
| `jobs.regen.steps.with.labels` | `documentation` | `.github/workflows/docu.yml#L59-L59` |
| `jobs.regen.steps.with.add-paths` | `|` | `.github/workflows/docu.yml#L60-L60` |
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
| `output.levels.l2` | `false` | `docu.profile.yaml#L41-L41` |
| `output.levels.l3` | `false` | `docu.profile.yaml#L42-L42` |
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

## 6. Tipos

| Tipo | Nombre | Anotaciones | Cita |
|---|---|---|---|
| class | `Segment` | `@dataclass` | `eval/harness.py#L118-L131` |
| class | `BM25` | `@dataclass` | `eval/harness.py#L262-L304` |
| class | `AutoIndex` | `@dataclass` | `eval/harness.py#L353-L373` |
| class | `HybridIndex` | `@dataclass` | `eval/harness.py#L377-L458` |
| class | `SymbolIndex` | `@dataclass` | `eval/harness.py#L462-L518` |
| class | `Expected` | `@dataclass` | `eval/harness.py#L525-L529` |
| class | `Case` | `@dataclass` | `eval/harness.py#L533-L550` |
| class | `CaseResult` | `@dataclass` | `eval/harness.py#L554-L562` |
| class | `Report` | `@dataclass` | `eval/harness.py#L566-L661` |
| class | `OnnxEmbedder` | `@dataclass` | `src/docu/adapters/embedders/onnx_local.py#L40-L104` |
| class | `Lines` | — | `src/docu/adapters/langs/_braces.py#L233-L250` |
| class | `_Lines` | — | `src/docu/adapters/langs/java.py#L135-L152` |
| class | `JavaLangAdapter` | `@dataclass` | `src/docu/adapters/langs/java.py#L241-L448` |
| class | `PythonLangAdapter` | `@dataclass` | `src/docu/adapters/langs/python.py#L19-L157` |
| class | `TypeScriptLangAdapter` | `@dataclass` | `src/docu/adapters/langs/typescript.py#L80-L394` |
| class | `Check` | `@dataclass` | `src/docu/audit/verify.py#L41-L69` |
| class | `AuditReport` | `@dataclass` | `src/docu/audit/verify.py#L73-L124` |
| class | `Discrepancy` | `@dataclass` | `src/docu/conformance/drift.py#L38-L62` |
| class | `DriftReport` | `@dataclass` | `src/docu/conformance/drift.py#L66-L118` |
| class | `RouteFact` | `@dataclass` | `src/docu/conformance/drift.py#L125-L130` |
| class | `CodeFacts` | `@dataclass` | `src/docu/conformance/drift.py#L134-L137` |
| class | `Route` | `@dataclass` | `src/docu/conformance/model.py#L31-L40` |
| class | `DeclaredComponent` | `@dataclass` | `src/docu/conformance/model.py#L44-L49` |
| class | `ArchitectureModel` | `@dataclass` | `src/docu/conformance/model.py#L53-L79` |
| class | `SourceKind` | — | `src/docu/core/contracts.py#L35-L42` |
| class | `SymbolKind` | — | `src/docu/core/contracts.py#L45-L56` |
| class | `DocState` | — | `src/docu/core/contracts.py#L59-L64` |
| class | `Mode` | — | `src/docu/core/contracts.py#L67-L72` |
| class | `GateOutcome` | — | `src/docu/core/contracts.py#L75-L80` |
| class | `Artifact` | `@dataclass` | `src/docu/core/contracts.py#L87-L110` |
| class | `Symbol` | `@dataclass` | `src/docu/core/contracts.py#L114-L130` |
| class | `Chunk` | `@dataclass` | `src/docu/core/contracts.py#L137-L192` |
| class | `Claim` | `@dataclass` | `src/docu/core/contracts.py#L199-L210` |
| class | `ContentNode` | `@dataclass` | `src/docu/core/contracts.py#L214-L236` |
| class | `Metrics` | `@dataclass` | `src/docu/core/contracts.py#L243-L253` |
| class | `GateDecision` | `@dataclass` | `src/docu/core/contracts.py#L257-L270` |
| class | `RunRecord` | `@dataclass` | `src/docu/core/contracts.py#L277-L321` |
| class | `FreshnessRecord` | `@dataclass` | `src/docu/core/contracts.py#L328-L340` |
| class | `BudgetExhausted` | — | `src/docu/core/policy.py#L15-L16` |
| class | `Thresholds` | `@dataclass` | `src/docu/core/policy.py#L20-L34` |
| class | `Budget` | `@dataclass` | `src/docu/core/policy.py#L38-L72` |
| class | `GatePolicy` | `@dataclass` | `src/docu/core/policy.py#L76-L104` |
| class | `SourceAdapter` | `@runtime_checkable` | `src/docu/core/ports.py#L18-L28` |
| class | `LangAdapter` | `@runtime_checkable` | `src/docu/core/ports.py#L32-L52` |
| class | `Chunker` | `@runtime_checkable` | `src/docu/core/ports.py#L56-L62` |
| class | `Embedder` | `@runtime_checkable` | `src/docu/core/ports.py#L69-L76` |
| class | `VectorStore` | `@runtime_checkable` | `src/docu/core/ports.py#L80-L94` |
| class | `Reranker` | `@runtime_checkable` | `src/docu/core/ports.py#L98-L104` |
| class | `RenderAdapter` | `@runtime_checkable` | `src/docu/core/ports.py#L111-L118` |
| class | `Judge` | `@runtime_checkable` | `src/docu/core/ports.py#L122-L129` |
| class | `Publisher` | `@runtime_checkable` | `src/docu/core/ports.py#L133-L145` |
| class | `ProfileError` | — | `src/docu/core/profile.py#L46-L47` |
| class | `Profile` | `@dataclass` | `src/docu/core/profile.py#L51-L105` |
| class | `Change` | `@dataclass` | `src/docu/core/profile.py#L381-L395` |
| class | `YamlError` | — | `src/docu/core/yamlmini.py#L14-L15` |
| class | `CliError` | — | `src/docu/delivery/cli.py#L157-L162` |
| class | `ResolvedOptions` | `@dataclass` | `src/docu/delivery/cli.py#L166-L177` |
| class | `ExitCode` | — | `src/docu/delivery/exit_codes.py#L8-L16` |
| class | `_Handler` | — | `src/docu/delivery/http_server.py#L26-L89` |
| class | `ProjectRef` | `@dataclass` | `src/docu/delivery/mcp_server.py#L122-L131` |
| class | `ToolError` | — | `src/docu/delivery/mcp_server.py#L134-L135` |
| class | `McpServer` | `@dataclass` | `src/docu/delivery/mcp_server.py#L139-L469` |
| class | `Fact` | `@dataclass` | `src/docu/generate/facts.py#L29-L44` |
| class | `GeneratedDoc` | `@dataclass` | `src/docu/generate/pipeline.py#L70-L73` |
| class | `GenerationResult` | `@dataclass` | `src/docu/generate/pipeline.py#L77-L100` |
| class | `SymbolChunker` | `@dataclass` | `src/docu/index/chunker.py#L46-L211` |
| class | `InputComponents` | `@dataclass` | `src/docu/index/freshness.py#L26-L34` |
| class | `DocEntry` | `@dataclass` | `src/docu/index/manifest.py#L33-L68` |
| class | `Manifest` | `@dataclass` | `src/docu/index/manifest.py#L72-L124` |
| class | `DetectedPackage` | `@dataclass` | `src/docu/index/packages.py#L22-L36` |
| class | `FederationError` | — | `src/docu/learn/federation.py#L28-L29` |
| class | `FederationPayload` | `@dataclass` | `src/docu/learn/federation.py#L33-L37` |
| class | `Pattern` | `@dataclass` | `src/docu/learn/patterns.py#L25-L55` |
| class | `PatternLibrary` | `@dataclass` | `src/docu/learn/patterns.py#L59-L142` |
| class | `Candidate` | `@dataclass` | `src/docu/learn/patterns.py#L156-L164` |
| class | `Decision` | `@dataclass` | `src/docu/learn/promotion.py#L21-L33` |
| class | `CodeChunk` | `@dataclass` | `src/docu/retrieve/hybrid.py#L33-L59` |
| class | `CodeIndex` | `@dataclass` | `src/docu/retrieve/hybrid.py#L113-L249` |
| class | `Section` | `@dataclass` | `src/docu/retrieve/search.py#L65-L86` |
| class | `DocIndex` | `@dataclass` | `src/docu/retrieve/search.py#L123-L193` |

## 7. Índice de métodos

| Símbolo | Firma | Cita |
|---|---|---|
| `_fold` | `def _fold(text: str) -> str` | `eval/harness.py#L83-L90` |
| `tokenize` | `def tokenize(text: str) -> list[str]` | `eval/harness.py#L93-L111` |
| `_matches` | `def _matches(path: str, patterns: Sequence[str]) -> bool` | `eval/harness.py#L134-L136` |
| `discover_files` | `def discover_files(repo: Path, include: Sequence[str], exclude: Sequence[str]) -> list[str` | `eval/harness.py#L139-L148` |
| `_window_segments` | `def _window_segments(repo: Path, rel: str, window: int, overlap: int) -> list[Segment]` | `eval/harness.py#L151-L177` |
| `build_corpus` | `def build_corpus(repo: Path, include: Sequence[str]=..., exclude: Sequence[str]=..., windo` | `eval/harness.py#L180-L190` |
| `_exact_names` | `def _exact_names(qualname: str | None) -> tuple[str, ...]` | `eval/harness.py#L193-L199` |
| `build_symbol_corpus` | `def build_symbol_corpus(repo: Path, exclude: Sequence[str]=..., window: int=..., overlap: ` | `eval/harness.py#L202-L255` |
| `BM25.__post_init__` | `def __post_init__(self) -> None` | `eval/harness.py#L272-L277` |
| `BM25._idf` | `def _idf(self, term: str) -> float` | `eval/harness.py#L279-L282` |
| `BM25.scores` | `def scores(self, query: str) -> list[float]` | `eval/harness.py#L284-L299` |
| `BM25.search` | `def search(self, query: str, k: int=...) -> list[tuple[Segment, float]]` | `eval/harness.py#L301-L304` |
| `_looks_like_identifier` | `def _looks_like_identifier(query: str) -> bool` | `eval/harness.py#L307-L325` |
| `_diversity` | `def _diversity(ordered: Sequence[tuple[tuple[str, int, int], float]], k: int, cap: int, by` | `eval/harness.py#L328-L349` |
| `AutoIndex.__post_init__` | `def __post_init__(self) -> None` | `eval/harness.py#L366-L368` |
| `AutoIndex.search` | `def search(self, query: str, k: int=...) -> list[tuple[Segment, float]]` | `eval/harness.py#L370-L373` |
| `HybridIndex.__post_init__` | `def __post_init__(self) -> None` | `eval/harness.py#L395-L401` |
| `HybridIndex._dense_channel` | `def _dense_channel(self, query: str, limit: int) -> list[Segment]` | `eval/harness.py#L405-L416` |
| `HybridIndex._exact_channel` | `def _exact_channel(self, terms: set[str]) -> list[Segment]` | `eval/harness.py#L418-L430` |
| `HybridIndex._channel_weights` | `def _channel_weights(self, query: str) -> tuple[float, float, float]` | `eval/harness.py#L432-L439` |
| `HybridIndex.search` | `def search(self, query: str, k: int=...) -> list[tuple[Segment, float]]` | `eval/harness.py#L441-L458` |
| `SymbolIndex.__post_init__` | `def __post_init__(self) -> None` | `eval/harness.py#L481-L485` |
| `SymbolIndex._exact_channel` | `def _exact_channel(self, terms: set[str]) -> list[Segment]` | `eval/harness.py#L487-L501` |
| `SymbolIndex.search` | `def search(self, query: str, k: int=...) -> list[tuple[Segment, float]]` | `eval/harness.py#L503-L518` |
| `Case.required_paths` | `def required_paths(self) -> tuple[str, ...]` | `eval/harness.py#L544-L545` |
| `Case.retrieval_query` | `def retrieval_query(self, field: str=...) -> str` | `eval/harness.py#L547-L550` |
| `Report._agg` | `def _agg(self, results: Sequence[CaseResult]) -> dict[str, float]` | `eval/harness.py#L578-L589` |
| `Report.overall` | `def overall(self) -> dict[str, float]` | `eval/harness.py#L592-L593` |
| `Report.by_category` | `def by_category(self) -> dict[str, dict[str, float]]` | `eval/harness.py#L595-L597` |
| `Report.to_dict` | `def to_dict(self) -> dict[str, object]` | `eval/harness.py#L599-L624` |
| `Report.to_markdown` | `def to_markdown(self) -> str` | `eval/harness.py#L626-L661` |
| `_overlaps` | `def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool` | `eval/harness.py#L664-L665` |
| `evaluate` | `def evaluate(cases: Sequence[Case], index: object, k: int=..., query_field: str=..., expan` | `eval/harness.py#L668-L720` |
| `load_golden` | `def load_golden(path: Path) -> tuple[str, str, list[Case]]` | `eval/harness.py#L726-L750` |
| `run` | `def run(golden_path: Path, repo: Path | None, k: int, out_dir: Path, quiet: bool=..., quer` | `eval/harness.py#L756-L824` |
| `main` | `def main(argv: Sequence[str] | None=...) -> int` | `eval/harness.py#L827-L871` |
| `resolve_model_dir` | `def resolve_model_dir(*roots) -> Path | None` | `src/docu/adapters/embedders/onnx_local.py#L20-L36` |
| `OnnxEmbedder.dim` | `def dim(self) -> int` | `src/docu/adapters/embedders/onnx_local.py#L53-L54` |
| `OnnxEmbedder.available` | `def available(self) -> bool` | `src/docu/adapters/embedders/onnx_local.py#L57-L60` |
| `OnnxEmbedder._load` | `def _load(self) -> None` | `src/docu/adapters/embedders/onnx_local.py#L62-L83` |
| `OnnxEmbedder.embed` | `def embed(self, texts: Sequence[str]) -> list[list[float]]` | `src/docu/adapters/embedders/onnx_local.py#L85-L104` |
| `_mean_pool_normalize` | `def _mean_pool_normalize(token_vectors: Sequence[Sequence[float]], mask: Sequence[int]) ->` | `src/docu/adapters/embedders/onnx_local.py#L107-L122` |
| `cosine` | `def cosine(left: Sequence[float], right: Sequence[float]) -> float` | `src/docu/adapters/embedders/onnx_local.py#L125-L129` |
| `mask_source` | `def mask_source(source: str) -> str` | `src/docu/adapters/langs/_braces.py#L12-L68` |
| `depth_map` | `def depth_map(masked: str) -> list[int]` | `src/docu/adapters/langs/_braces.py#L71-L81` |
| `matching_brace` | `def matching_brace(masked: str, open_index: int) -> int` | `src/docu/adapters/langs/_braces.py#L84-L95` |
| `mask_annotation_braces` | `def mask_annotation_braces(masked: str) -> str` | `src/docu/adapters/langs/_braces.py#L98-L124` |
| `matching_paren` | `def matching_paren(masked: str, open_index: int) -> int` | `src/docu/adapters/langs/_braces.py#L127-L138` |
| `iter_callables` | `def iter_callables(masked: str, depth: list[int], level: int, start: int, end: int, skip: ` | `src/docu/adapters/langs/_braces.py#L141-L201` |
| `annotations_before` | `def annotations_before(source: str, name_start: int) -> str` | `src/docu/adapters/langs/_braces.py#L204-L230` |
| `Lines.__init__` | `def __init__(self, source: str) -> None` | `src/docu/adapters/langs/_braces.py#L236-L240` |
| `Lines.line_of` | `def line_of(self, offset: int) -> int` | `src/docu/adapters/langs/_braces.py#L242-L250` |
| `skip_whitespace` | `def skip_whitespace(text: str, start: int, limit: int) -> int` | `src/docu/adapters/langs/_braces.py#L253-L258` |
| `declaration_start` | `def declaration_start(masked: str, depth: list[int], offset: int, floor: int, level: int) ` | `src/docu/adapters/langs/_braces.py#L261-L278` |
| `strip_comment_args` | `def strip_comment_args(text: str) -> str` | `src/docu/adapters/langs/_braces.py#L281-L282` |
| `mask_source` | `def mask_source(source: str) -> str` | `src/docu/adapters/langs/java.py#L50-L105` |
| `depth_map` | `def depth_map(masked: str) -> list[int]` | `src/docu/adapters/langs/java.py#L108-L118` |
| `matching_brace` | `def matching_brace(masked: str, open_index: int) -> int` | `src/docu/adapters/langs/java.py#L121-L132` |
| `_Lines.__init__` | `def __init__(self, source: str) -> None` | `src/docu/adapters/langs/java.py#L138-L142` |
| `_Lines.line_of` | `def line_of(self, offset: int) -> int` | `src/docu/adapters/langs/java.py#L144-L152` |
| `annotation_names` | `def annotation_names(text: str) -> tuple[str, ...]` | `src/docu/adapters/langs/java.py#L155-L157` |
| `route_of` | `def route_of(annotation: str, args: str | None) -> tuple[str, str | None] | None` | `src/docu/adapters/langs/java.py#L160-L172` |
| `class_level_route` | `def class_level_route(text: str) -> str | None` | `src/docu/adapters/langs/java.py#L175-L181` |
| `join_paths` | `def join_paths(base: str | None, suffix: str | None) -> str` | `src/docu/adapters/langs/java.py#L184-L192` |
| `_annotation_block` | `def _annotation_block(source: str, start: int, end: int) -> tuple[str, int]` | `src/docu/adapters/langs/java.py#L195-L206` |
| `_declaration_start` | `def _declaration_start(masked: str, depth: list[int], offset: int, floor: int, level: int)` | `src/docu/adapters/langs/java.py#L209-L226` |
| `_skip_whitespace` | `def _skip_whitespace(text: str, start: int, limit: int) -> int` | `src/docu/adapters/langs/java.py#L229-L234` |
| `JavaLangAdapter.symbols` | `def symbols(self, path: str, source: str) -> tuple[Symbol, ...]` | `src/docu/adapters/langs/java.py#L249-L327` |
| `JavaLangAdapter._members` | `def _members(self) -> tuple[list[Symbol], list[Symbol]]` | `src/docu/adapters/langs/java.py#L329-L415` |
| `JavaLangAdapter.imports` | `def imports(self, path: str, source: str) -> tuple[str, ...]` | `src/docu/adapters/langs/java.py#L419-L421` |
| `JavaLangAdapter.calls` | `def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]` | `src/docu/adapters/langs/java.py#L423-L448` |
| `PythonLangAdapter.symbols` | `def symbols(self, path: str, source: str) -> tuple[Symbol, ...]` | `src/docu/adapters/langs/python.py#L27-L39` |
| `PythonLangAdapter._module_member` | `def _module_member(self, path: str, node: ast.AST, container: str | None) -> Symbol | None` | `src/docu/adapters/langs/python.py#L41-L74` |
| `PythonLangAdapter._decorators` | `def _decorators(self, node: ast.AST) -> tuple[str, ...]` | `src/docu/adapters/langs/python.py#L76-L78` |
| `PythonLangAdapter._routes` | `def _routes(self, path: str, node: ast.AST, container: str | None) -> list[Symbol]` | `src/docu/adapters/langs/python.py#L80-L108` |
| `PythonLangAdapter.imports` | `def imports(self, path: str, source: str) -> tuple[str, ...]` | `src/docu/adapters/langs/python.py#L112-L123` |
| `PythonLangAdapter.calls` | `def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]` | `src/docu/adapters/langs/python.py#L125-L157` |
| `_base_name` | `def _base_name(node: ast.AST) -> str` | `src/docu/adapters/langs/python.py#L163-L168` |
| `_decorator_name` | `def _decorator_name(node: ast.AST) -> str` | `src/docu/adapters/langs/python.py#L171-L178` |
| `_route_of` | `def _route_of(short: str, decorator: ast.AST) -> tuple[str, str | None]` | `src/docu/adapters/langs/python.py#L181-L201` |
| `_signature` | `def _signature(node: ast.AST) -> str` | `src/docu/adapters/langs/python.py#L204-L221` |
| `_call_name` | `def _call_name(node: ast.AST) -> str | None` | `src/docu/adapters/langs/python.py#L224-L229` |
| `_function_table` | `def _function_table(tree: ast.AST) -> list[tuple[str, int, int]]` | `src/docu/adapters/langs/python.py#L232-L251` |
| `adapter_for` | `def adapter_for(path: str) -> object | None` | `src/docu/adapters/langs/registry.py#L16-L22` |
| `supported_languages` | `def supported_languages() -> tuple[str, ...]` | `src/docu/adapters/langs/registry.py#L25-L26` |
| `TypeScriptLangAdapter.symbols` | `def symbols(self, path: str, source: str) -> tuple[Symbol, ...]` | `src/docu/adapters/langs/typescript.py#L86-L182` |
| `TypeScriptLangAdapter._members` | `def _members(self) -> tuple[list[Symbol], list[Symbol]]` | `src/docu/adapters/langs/typescript.py#L184-L296` |
| `TypeScriptLangAdapter._express_routes` | `def _express_routes(self, path: str, source: str, masked: str, lines: Lines) -> list[Symbo` | `src/docu/adapters/langs/typescript.py#L298-L376` |
| `TypeScriptLangAdapter.imports` | `def imports(self, path: str, source: str) -> tuple[str, ...]` | `src/docu/adapters/langs/typescript.py#L378-L379` |
| `TypeScriptLangAdapter.calls` | `def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]` | `src/docu/adapters/langs/typescript.py#L381-L394` |
| `_annotation_block` | `def _annotation_block(source: str, start: int, end: int) -> tuple[str, int]` | `src/docu/adapters/langs/typescript.py#L400-L406` |
| `_decorators_in` | `def _decorators_in(text: str) -> tuple[str, ...]` | `src/docu/adapters/langs/typescript.py#L409-L412` |
| `_class_route` | `def _class_route(decorators: tuple[str, ...]) -> str | None` | `src/docu/adapters/langs/typescript.py#L415-L420` |
| `_route_path` | `def _route_path(text: str, annotation: str) -> str` | `src/docu/adapters/langs/typescript.py#L423-L430` |
| `_join` | `def _join(base: str | None, route: str) -> str` | `src/docu/adapters/langs/typescript.py#L433-L441` |
| `Check.passed` | `def passed(self) -> bool` | `src/docu/audit/verify.py#L51-L52` |
| `Check.score` | `def score(self) -> float` | `src/docu/audit/verify.py#L55-L58` |
| `Check.to_dict` | `def to_dict(self) -> dict[str, object]` | `src/docu/audit/verify.py#L60-L69` |
| `AuditReport.score` | `def score(self) -> float` | `src/docu/audit/verify.py#L78-L84` |
| `AuditReport.passed` | `def passed(self) -> bool` | `src/docu/audit/verify.py#L87-L88` |
| `AuditReport.to_dict` | `def to_dict(self) -> dict[str, object]` | `src/docu/audit/verify.py#L90-L98` |
| `AuditReport.to_markdown` | `def to_markdown(self) -> str` | `src/docu/audit/verify.py#L100-L124` |
| `check_citations` | `def check_citations(facts: Sequence[Fact], root: Path) -> Check` | `src/docu/audit/verify.py#L130-L170` |
| `_probes` | `def _probes(fact: Fact) -> list[str]` | `src/docu/audit/verify.py#L173-L187` |
| `check_duplicates` | `def check_duplicates(facts: Sequence[Fact]) -> Check` | `src/docu/audit/verify.py#L190-L205` |
| `_document_paths` | `def _document_paths(text: str) -> set[str]` | `src/docu/audit/verify.py#L208-L210` |
| `check_consistency` | `def check_consistency(docs: Mapping[str, str]) -> Check` | `src/docu/audit/verify.py#L213-L229` |
| `check_coverage` | `def check_coverage(facts: Sequence[Fact], root: Path) -> Check` | `src/docu/audit/verify.py#L232-L242` |
| `_evidence_kinds` | `def _evidence_kinds(kind: str) -> tuple[str, ...]` | `src/docu/audit/verify.py#L245-L248` |
| `check_freshness` | `def check_freshness(root: Path, levels: Sequence[str], manifest_path: Path | str | None=..` | `src/docu/audit/verify.py#L251-L281` |
| `audit` | `def audit(root: Path | str, docs_dir: Path | str | None=..., levels: Sequence[str]=..., pr` | `src/docu/audit/verify.py#L287-L325` |
| `Discrepancy.severity` | `def severity(self) -> str` | `src/docu/conformance/drift.py#L46-L47` |
| `Discrepancy.action` | `def action(self) -> str` | `src/docu/conformance/drift.py#L50-L51` |
| `Discrepancy.to_dict` | `def to_dict(self) -> dict[str, object]` | `src/docu/conformance/drift.py#L53-L62` |
| `DriftReport.errors` | `def errors(self) -> list[Discrepancy]` | `src/docu/conformance/drift.py#L73-L74` |
| `DriftReport.warnings` | `def warnings(self) -> list[Discrepancy]` | `src/docu/conformance/drift.py#L77-L78` |
| `DriftReport.is_clean` | `def is_clean(self) -> bool` | `src/docu/conformance/drift.py#L81-L82` |
| `DriftReport.to_dict` | `def to_dict(self) -> dict[str, object]` | `src/docu/conformance/drift.py#L84-L93` |
| `DriftReport.to_markdown` | `def to_markdown(self) -> str` | `src/docu/conformance/drift.py#L95-L112` |
| `DriftReport.save` | `def save(self, path: Path | str) -> Path` | `src/docu/conformance/drift.py#L114-L118` |
| `describe_code` | `def describe_code(root: Path | str, include_tests: bool=...) -> CodeFacts` | `src/docu/conformance/drift.py#L140-L174` |
| `_short` | `def _short(name: str) -> str` | `src/docu/conformance/drift.py#L180-L182` |
| `_owner` | `def _owner(qualname: str) -> str` | `src/docu/conformance/drift.py#L185-L191` |
| `compare` | `def compare(model: ArchitectureModel, code: CodeFacts) -> DriftReport` | `src/docu/conformance/drift.py#L194-L267` |
| `analyze` | `def analyze(root: Path | str, architecture: Path | str | None=..., include_tests: bool=...` | `src/docu/conformance/drift.py#L270-L277` |
| `bootstrap` | `def bootstrap(root: Path | str, include_tests: bool=...) -> ArchitectureModel` | `src/docu/conformance/drift.py#L280-L317` |
| `Route.key` | `def key(self) -> str` | `src/docu/conformance/model.py#L36-L37` |
| `Route.__str__` | `def __str__(self) -> str` | `src/docu/conformance/model.py#L39-L40` |
| `ArchitectureModel.component_names` | `def component_names(self) -> set[str]` | `src/docu/conformance/model.py#L60-L61` |
| `ArchitectureModel.declared_routes` | `def declared_routes(self) -> set[str]` | `src/docu/conformance/model.py#L64-L68` |
| `ArchitectureModel.declared_dependencies` | `def declared_dependencies(self) -> set[tuple[str, str]]` | `src/docu/conformance/model.py#L70-L75` |
| `ArchitectureModel.is_empty` | `def is_empty(self) -> bool` | `src/docu/conformance/model.py#L78-L79` |
| `_read_document` | `def _read_document(path: Path) -> Mapping[str, object] | None` | `src/docu/conformance/model.py#L85-L97` |
| `load_architecture` | `def load_architecture(root: Path, explicit: Path | str | None=...) -> ArchitectureModel` | `src/docu/conformance/model.py#L100-L135` |
| `_components_from` | `def _components_from(block: Mapping[str, object], source: str) -> list[DeclaredComponent]` | `src/docu/conformance/model.py#L138-L159` |
| `_routes_from_openapi` | `def _routes_from_openapi(document: Mapping[str, object]) -> list[Route]` | `src/docu/conformance/model.py#L162-L173` |
| `_as_list` | `def _as_list(value: object) -> Iterable[object]` | `src/docu/conformance/model.py#L176-L181` |
| `_route_from_text` | `def _route_from_text(text: str) -> Route | None` | `src/docu/conformance/model.py#L184-L192` |
| `to_yaml` | `def to_yaml(model: ArchitectureModel, project: str) -> str` | `src/docu/conformance/model.py#L195-L218` |
| `utcnow` | `def utcnow() -> datetime` | `src/docu/core/contracts.py#L22-L24` |
| `sha256_of` | `def sha256_of(data: str | bytes) -> str` | `src/docu/core/contracts.py#L27-L29` |
| `Artifact.__post_init__` | `def __post_init__(self) -> None` | `src/docu/core/contracts.py#L104-L110` |
| `Symbol.is_container` | `def is_container(self) -> bool` | `src/docu/core/contracts.py#L129-L130` |
| `Chunk.__post_init__` | `def __post_init__(self) -> None` | `src/docu/core/contracts.py#L160-L164` |
| `Chunk.citation` | `def citation(self) -> str` | `src/docu/core/contracts.py#L167-L169` |
| `Chunk.to_record` | `def to_record(self) -> dict[str, Any]` | `src/docu/core/contracts.py#L171-L192` |
| `Claim.verified` | `def verified(self) -> bool` | `src/docu/core/contracts.py#L209-L210` |
| `ContentNode.unsupported` | `def unsupported(self) -> list[Claim]` | `src/docu/core/contracts.py#L232-L233` |
| `ContentNode.is_publishable` | `def is_publishable(self) -> bool` | `src/docu/core/contracts.py#L235-L236` |
| `GateDecision.may_write` | `def may_write(self) -> bool` | `src/docu/core/contracts.py#L264-L266` |
| `GateDecision.describe` | `def describe(self) -> str` | `src/docu/core/contracts.py#L268-L270` |
| `RunRecord.duration_s` | `def duration_s(self) -> float | None` | `src/docu/core/contracts.py#L296-L299` |
| `RunRecord.to_jsonl` | `def to_jsonl(self) -> str` | `src/docu/core/contracts.py#L301-L321` |
| `FreshnessRecord.is_expired` | `def is_expired(self, now: datetime | None=...) -> bool` | `src/docu/core/contracts.py#L338-L340` |
| `Thresholds.as_mapping` | `def as_mapping(self) -> Mapping[str, float]` | `src/docu/core/policy.py#L28-L34` |
| `Budget.spend` | `def spend(self) -> None` | `src/docu/core/policy.py#L50-L56` |
| `Budget.exceeded` | `def exceeded(self) -> list[str]` | `src/docu/core/policy.py#L58-L68` |
| `Budget.remaining_usd` | `def remaining_usd(self) -> float` | `src/docu/core/policy.py#L71-L72` |
| `GatePolicy.evaluate` | `def evaluate(self, metrics: Metrics, mode: Mode) -> GateDecision` | `src/docu/core/policy.py#L83-L104` |
| `SourceAdapter.discover` | `def discover(self, root: str, include: Sequence[str], exclude: Sequence[str]) -> Iterable[` | `src/docu/core/ports.py#L24-L25` |
| `SourceAdapter.read` | `def read(self, artifact: Artifact) -> str | bytes` | `src/docu/core/ports.py#L27-L28` |
| `LangAdapter.symbols` | `def symbols(self, path: str, source: str) -> Sequence[Symbol]` | `src/docu/core/ports.py#L41-L42` |
| `LangAdapter.imports` | `def imports(self, path: str, source: str) -> Sequence[str]` | `src/docu/core/ports.py#L44-L45` |
| `LangAdapter.calls` | `def calls(self, path: str, source: str) -> Sequence[tuple[str, str]]` | `src/docu/core/ports.py#L47-L52` |
| `Chunker.chunk` | `def chunk(self, artifact: Artifact, symbols: Sequence[Symbol], source: str) -> Sequence[Ch` | `src/docu/core/ports.py#L61-L62` |
| `Embedder.embed` | `def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]` | `src/docu/core/ports.py#L75-L76` |
| `VectorStore.upsert` | `def upsert(self, namespace: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float` | `src/docu/core/ports.py#L85-L86` |
| `VectorStore.query` | `def query(self, namespace: str, vector: Sequence[float], top_k: int, filters: Mapping[str,` | `src/docu/core/ports.py#L88-L91` |
| `VectorStore.delete_by_filter` | `def delete_by_filter(self, namespace: str, filters: Mapping[str, Any]) -> int` | `src/docu/core/ports.py#L93-L94` |
| `Reranker.rank` | `def rank(self, query: str, chunks: Sequence[Chunk], top_n: int) -> Sequence[tuple[Chunk, f` | `src/docu/core/ports.py#L103-L104` |
| `RenderAdapter.render` | `def render(self, node: ContentNode, context: Mapping[str, Any]) -> str` | `src/docu/core/ports.py#L117-L118` |
| `Judge.score` | `def score(self, document: str, evidence: Sequence[Chunk], rubric: Mapping[str, Any]) -> Me` | `src/docu/core/ports.py#L128-L129` |
| `Publisher.propose` | `def propose(self, path: str, content: str, message: str) -> str` | `src/docu/core/ports.py#L138-L139` |
| `Publisher.apply` | `def apply(self, proposal_id: str) -> str` | `src/docu/core/ports.py#L141-L142` |
| `Publisher.revert` | `def revert(self, applied_id: str) -> None` | `src/docu/core/ports.py#L144-L145` |
| `Profile.exists` | `def exists(self) -> bool` | `src/docu/core/profile.py#L71-L72` |
| `Profile.effective_exclude` | `def effective_exclude(self) -> tuple[str, ...]` | `src/docu/core/profile.py#L75-L81` |
| `Profile.to_dict` | `def to_dict(self) -> dict[str, object]` | `src/docu/core/profile.py#L83-L105` |
| `_mapping` | `def _mapping(value: object, name: str) -> Mapping[str, object]` | `src/docu/core/profile.py#L111-L116` |
| `_string_tuple` | `def _string_tuple(value: object, name: str) -> tuple[str, ...]` | `src/docu/core/profile.py#L119-L126` |
| `_levels` | `def _levels(value: object) -> tuple[str, ...]` | `src/docu/core/profile.py#L129-L137` |
| `_thresholds` | `def _thresholds(value: object, defaults: Thresholds) -> Thresholds` | `src/docu/core/profile.py#L140-L159` |
| `_glossary` | `def _glossary(value: object) -> dict[str, tuple[str, ...]]` | `src/docu/core/profile.py#L162-L167` |
| `from_dict` | `def from_dict(payload: Mapping[str, object]) -> Profile` | `src/docu/core/profile.py#L170-L212` |
| `load` | `def load(path: Path | str | None) -> Profile | None` | `src/docu/core/profile.py#L215-L226` |
| `candidate_paths` | `def candidate_paths(root: Path) -> tuple[Path, ...]` | `src/docu/core/profile.py#L229-L230` |
| `find` | `def find(root: Path) -> Path | None` | `src/docu/core/profile.py#L233-L235` |
| `detect` | `def detect(root: Path) -> dict[str, object]` | `src/docu/core/profile.py#L241-L279` |
| `propose` | `def propose(root: Path) -> Profile` | `src/docu/core/profile.py#L282-L311` |
| `to_yaml` | `def to_yaml(profile: Profile) -> str` | `src/docu/core/profile.py#L314-L377` |
| `Change.kind` | `def kind(self) -> str` | `src/docu/core/profile.py#L391-L392` |
| `Change.describe` | `def describe(self) -> str` | `src/docu/core/profile.py#L394-L395` |
| `plan_changes` | `def plan_changes(existing: Profile | None, proposed: Profile) -> list[Change]` | `src/docu/core/profile.py#L402-L455` |
| `merge` | `def merge(existing: Profile, proposed: Profile) -> Profile` | `src/docu/core/profile.py#L458-L467` |
| `render_change_order` | `def render_change_order(changes: Sequence[Change], project: str) -> str` | `src/docu/core/profile.py#L470-L498` |
| `parse` | `def parse(text: str) -> dict[str, object]` | `src/docu/core/yamlmini.py#L18-L28` |
| `_prepare` | `def _prepare(text: str) -> list[tuple[int, str, int]]` | `src/docu/core/yamlmini.py#L34-L48` |
| `_strip_comment` | `def _strip_comment(line: str) -> str` | `src/docu/core/yamlmini.py#L51-L64` |
| `_parse_block` | `def _parse_block(lines: list[tuple[int, str, int]], start: int, indent: int) -> tuple[obje` | `src/docu/core/yamlmini.py#L70-L75` |
| `_parse_mapping` | `def _parse_mapping(lines: list[tuple[int, str, int]], start: int, indent: int) -> tuple[di` | `src/docu/core/yamlmini.py#L78-L107` |

_(184 métodos adicionales omitidos del índice)_.

## 8. Alcance y límites

Secciones aplicables a este proyecto (y por tanto exigibles en la compuerta): **type, config_key, dependency, module**.

Secciones **no aplicables** —no existen en este proyecto y no se penalizan—: route.

No cubierto todavía por el generador: diagramas de componentes y de secuencia, diccionario de datos, contratos OpenAPI si no están declarados, y la capa de operación/despliegue (Nivel 2).

## 9. Trazabilidad

Cada afirmación de este documento enlaza a `ruta#L inicio-L fin`. Los archivos fuente y su huella son:

| Archivo | sha256 |
|---|---|
| `.github/workflows/docu.yml` | `1a164973b830` |
| `docu.profile.yaml` | `94dcacef07be` |
| `eval/__init__.py` | `65861c4d8840` |
| `eval/harness.py` | `6137ad8155a0` |
| `pyproject.toml` | `a4e309a1c90a` |
| `src/docu/__init__.py` | `ec3694c43263` |
| `src/docu/adapters/__init__.py` | `a2c1108f5fd9` |
| `src/docu/adapters/embedders/__init__.py` | `8864f7d0c67f` |
| `src/docu/adapters/embedders/onnx_local.py` | `9d4142107e83` |
| `src/docu/adapters/langs/__init__.py` | `db232e3411bb` |
| `src/docu/adapters/langs/_braces.py` | `408fed7da941` |
| `src/docu/adapters/langs/java.py` | `ae3449e495df` |
| `src/docu/adapters/langs/python.py` | `3e155a0d3d00` |
| `src/docu/adapters/langs/registry.py` | `97c5aef6b7cd` |
| `src/docu/adapters/langs/typescript.py` | `41c2481896b0` |
| `src/docu/audit/__init__.py` | `db19f5507fab` |
| `src/docu/audit/verify.py` | `fe90f029a031` |
| `src/docu/conformance/__init__.py` | `0362d002bd6b` |
| `src/docu/conformance/drift.py` | `8cba54b3c1fd` |
| `src/docu/conformance/model.py` | `1353357e8785` |
| `src/docu/core/__init__.py` | `f6d1da76275b` |
| `src/docu/core/contracts.py` | `1ed0e6d83f63` |
| `src/docu/core/policy.py` | `bb4c3a0a3ed5` |
| `src/docu/core/ports.py` | `88d8cfdb18c0` |
| `src/docu/core/profile.py` | `16d2c1150a38` |
| `src/docu/core/yamlmini.py` | `7a54cc7a2960` |
| `src/docu/delivery/__init__.py` | `1ee493763f5d` |
| `src/docu/delivery/cli.py` | `7f2d4faca627` |
| `src/docu/delivery/exit_codes.py` | `34e3a22d2847` |
| `src/docu/delivery/http_server.py` | `508873897a2b` |
| `src/docu/delivery/mcp_server.py` | `86ed3d803200` |
| `src/docu/generate/__init__.py` | `91d9129019a3` |
| `src/docu/generate/facts.py` | `eb5835430ed4` |
| `src/docu/generate/markdown.py` | `ce09d8045f2b` |
| `src/docu/generate/pipeline.py` | `42acd8ba388a` |
| `src/docu/index/__init__.py` | `06566a17f409` |
| `src/docu/index/chunker.py` | `5588ae08b6bf` |
| `src/docu/index/freshness.py` | `076f96a3fb8b` |
| `src/docu/index/manifest.py` | `f3ea859b5225` |
| `src/docu/index/packages.py` | `c95a5e61a5f3` |
| `src/docu/learn/__init__.py` | `4d33ba71c4c5` |
| `src/docu/learn/federation.py` | `ffeb217ac871` |
| `src/docu/learn/ledger.py` | `38818d4f92ec` |
| `src/docu/learn/patterns.py` | `39aec53783eb` |
| `src/docu/learn/promotion.py` | `66d049f788e8` |
| `src/docu/retrieve/__init__.py` | `d44cd2bb75d8` |
| `src/docu/retrieve/glossary.py` | `d45a6ee652f1` |
| `src/docu/retrieve/hybrid.py` | `8b665a8ae4c9` |
| `src/docu/retrieve/search.py` | `13d6e62bb88d` |
