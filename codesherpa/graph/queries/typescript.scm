; Symbol-graph captures for TypeScript (also used for TSX; see languages.py).
; Same capture vocabulary as python.scm.

(function_declaration name: (identifier) @name) @def.function
(generator_function_declaration name: (identifier) @name) @def.function

(class_declaration name: (type_identifier) @name) @def.class
(abstract_class_declaration name: (type_identifier) @name) @def.class
(interface_declaration name: (type_identifier) @name) @def.class
(type_alias_declaration name: (type_identifier) @name) @def.class
(enum_declaration name: (identifier) @name) @def.class

(method_definition name: (property_identifier) @name) @def.method

; top-level const/let whose value is a function -> function definition
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

; other top-level const/let (extractor prefers @def.function on overlap)
(program
  (lexical_declaration
    (variable_declarator name: (identifier) @name) @def.variable))
(program
  (export_statement
    declaration: (lexical_declaration
      (variable_declarator name: (identifier) @name) @def.variable)))

; import { a, b as c } from './mod'   (one match per specifier)
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
; import Default from './mod'
(import_statement
  (import_clause (identifier) @import.name)
  source: (string (string_fragment) @import.module)) @import
; import * as ns from './mod'
(import_statement
  (import_clause (namespace_import (identifier) @import.alias))
  source: (string (string_fragment) @import.module)) @import

; foo(...)
(call_expression function: (identifier) @call.name) @call
; await foo<T>(...) — this grammar nests the callee in an await_expression
(call_expression function: (await_expression (identifier) @call.name)) @call
; obj.method(...)
(call_expression
  function: (member_expression property: (property_identifier) @call.name)) @call
; new Foo(...)
(new_expression constructor: (identifier) @call.name) @call

; identifier / type uses (filtered against known definitions by the extractor)
(identifier) @ref
(type_identifier) @ref
(member_expression property: (property_identifier) @ref)
