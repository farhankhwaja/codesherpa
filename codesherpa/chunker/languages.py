"""Per-language chunker configuration (CLAUDE.md §7.2).

Adding a language to the cAST chunker = adding one ``LanguageSpec`` entry
here (the grammar itself comes from tree-sitter-language-pack). Symbol-graph
query files (Phase 4) live separately under ``codesherpa/graph/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageSpec:
    """What the cAST chunker needs to know about one language."""

    grammar: str
    """Name understood by tree_sitter_language_pack.get_language()."""

    scope_types: frozenset[str]
    """Node types that contribute their name to the breadcrumb scope chain
    when the chunker recurses into them (classes, functions, ...)."""

    definition_types: frozenset[str] = field(default_factory=frozenset)
    """Node types whose first line makes a good signature (subset check for
    docstring extraction etc.)."""


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        grammar="python",
        scope_types=frozenset({"class_definition", "function_definition"}),
        definition_types=frozenset({"class_definition", "function_definition"}),
    ),
    "typescript": LanguageSpec(
        grammar="typescript",
        scope_types=frozenset(
            {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
                "internal_module",  # namespace X { ... }
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            }
        ),
        definition_types=frozenset(
            {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            }
        ),
    ),
    "tsx": LanguageSpec(
        grammar="tsx",
        scope_types=frozenset(
            {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
                "internal_module",
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            }
        ),
        definition_types=frozenset(
            {
                "class_declaration",
                "function_declaration",
                "method_definition",
            }
        ),
    ),
    "javascript": LanguageSpec(
        grammar="javascript",
        scope_types=frozenset(
            {
                "class_declaration",
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            }
        ),
        definition_types=frozenset(
            {
                "class_declaration",
                "function_declaration",
                "method_definition",
            }
        ),
    ),
    "go": LanguageSpec(
        grammar="go",
        scope_types=frozenset(
            {
                "function_declaration",
                "method_declaration",  # scope label is "(ReceiverType)" — cast.py
                "type_spec",  # struct/interface bodies recurse under the type name
                "const_declaration",
                "var_declaration",
            }
        ),
        definition_types=frozenset(
            {
                "function_declaration",
                "method_declaration",
                "type_declaration",
                "type_spec",
                "const_declaration",
                "var_declaration",
            }
        ),
    ),
}
