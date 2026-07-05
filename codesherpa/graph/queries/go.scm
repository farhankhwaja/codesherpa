; Symbol-graph captures for Go. Same capture vocabulary as the other
; languages, plus three Go-only capture families the extractor understands:
;   @method.receiver — bare receiver type; methods are keyed with it
;   @call.recv       — selector operand, for receiver-typed call resolution
;   @bind.name/@bind.type — locally-evident variable types (params,
;                       `x := T{...}` / `x := &T{...}` / `var x T`)
; Interface-satisfaction resolution is deliberately NOT attempted — it
; requires type checking (DECISIONS.md).

(function_declaration name: (identifier) @name) @def.function

(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: [(type_identifier) @method.receiver
             (pointer_type (type_identifier) @method.receiver)
             (generic_type type: (type_identifier) @method.receiver)
             (pointer_type (generic_type type: (type_identifier) @method.receiver))]))
  name: (field_identifier) @name) @def.method

; structs, interfaces, and type aliases all register as type definitions
(type_declaration (type_spec name: (type_identifier) @name)) @def.class

; package-level consts and vars only (block-local ones are noise)
(source_file
  (const_declaration (const_spec name: (identifier) @name) @def.variable))
(source_file
  (var_declaration (var_spec name: (identifier) @name) @def.variable))

; import "pkg/path"  |  alias "pkg/path"  (quotes stripped by the resolver)
(import_spec
  name: (package_identifier) @import.alias
  path: (interpreted_string_literal) @import.module) @import
(import_spec
  !name
  path: (interpreted_string_literal) @import.module) @import

; x.Foo(...) — operand captured for receiver-typed resolution
(call_expression
  function: (selector_expression
    operand: (identifier) @call.recv
    field: (field_identifier) @call.name)) @call
; Foo(...)
(call_expression function: (identifier) @call.name) @call
; expr.Foo(...) with a non-identifier operand (chained calls etc.)
(call_expression
  function: (selector_expression field: (field_identifier) @call.name)) @call

; locally-evident types: parameters (incl. method receivers), var decls,
; and composite-literal initializations
(parameter_declaration
  name: (identifier) @bind.name
  type: [(type_identifier) @bind.type
         (pointer_type (type_identifier) @bind.type)])
(var_spec
  name: (identifier) @bind.name
  type: [(type_identifier) @bind.type
         (pointer_type (type_identifier) @bind.type)])
(short_var_declaration
  left: (expression_list (identifier) @bind.name)
  right: (expression_list (composite_literal type: (type_identifier) @bind.type)))
(short_var_declaration
  left: (expression_list (identifier) @bind.name)
  right: (expression_list
    (unary_expression operand: (composite_literal type: (type_identifier) @bind.type))))

; identifier / type / selector-field uses (filtered by the extractor)
(identifier) @ref
(type_identifier) @ref
(field_identifier) @ref
