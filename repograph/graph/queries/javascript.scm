; Symbol-graph captures for JavaScript (and JSX).
; Same capture vocabulary as python.scm; TypeScript-only node types removed.

(function_declaration name: (identifier) @name) @def.function
(generator_function_declaration name: (identifier) @name) @def.function

(class_declaration name: (identifier) @name) @def.class

(method_definition name: (property_identifier) @name) @def.method

(program
  (lexical_declaration
    (variable_declarator
      name: (identifier) @name
      value: [(arrow_function) (function_expression)]) @def.function))
(program
  (export_statement
    declaration: (lexical_declaration
      (variable_declarator
        name: (identifier) @name
        value: [(arrow_function) (function_expression)]) @def.function)))

(program
  (lexical_declaration
    (variable_declarator name: (identifier) @name) @def.variable))
(program
  (export_statement
    declaration: (lexical_declaration
      (variable_declarator name: (identifier) @name) @def.variable)))

(import_statement
  (import_clause
    (named_imports
      (import_specifier name: (identifier) @import.name)))
  source: (string (string_fragment) @import.module)) @import
(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name
        alias: (identifier) @import.alias)))
  source: (string (string_fragment) @import.module)) @import
(import_statement
  (import_clause (identifier) @import.name)
  source: (string (string_fragment) @import.module)) @import
(import_statement
  (import_clause (namespace_import (identifier) @import.alias))
  source: (string (string_fragment) @import.module)) @import

(call_expression function: (identifier) @call.name) @call
(call_expression function: (await_expression (identifier) @call.name)) @call
(call_expression
  function: (member_expression property: (property_identifier) @call.name)) @call
(new_expression constructor: (identifier) @call.name) @call

(identifier) @ref
(member_expression property: (property_identifier) @ref)
