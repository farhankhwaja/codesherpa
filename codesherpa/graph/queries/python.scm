; Symbol-graph captures for Python (CLAUDE.md §7.3).
;
; Capture vocabulary (shared by every language's queries file):
;   @def.function / @def.class / @def.method / @def.variable  whole definition
;   @name                                                     its identifier
;   @import + @import.module / @import.name / @import.alias   import records
;   @call + @call.name                                        call sites
;   @ref                                                      identifier uses
;
; Python functions are captured as @def.function and reclassified as methods
; by the extractor when the smallest enclosing definition is a class.

(function_definition name: (identifier) @name) @def.function

(class_definition name: (identifier) @name) @def.class

; module-level assignments only (locals would be noise); this grammar build
; inlines expression_statement, so match both shapes
(module
  (expression_statement
    (assignment left: (identifier) @name) @def.variable))
(module
  (assignment left: (identifier) @name) @def.variable)

; import a.b
(import_statement name: (dotted_name) @import.module) @import
; import a.b as c
(import_statement
  name: (aliased_import
    name: (dotted_name) @import.module
    alias: (identifier) @import.alias)) @import
; from a.b import c        (one match per imported name)
(import_from_statement
  module_name: (dotted_name) @import.module
  name: (dotted_name) @import.name) @import
; from a.b import c as d
(import_from_statement
  module_name: (dotted_name) @import.module
  name: (aliased_import
    name: (dotted_name) @import.name
    alias: (identifier) @import.alias)) @import
; from . import x / from ..pkg import x
(import_from_statement
  module_name: (relative_import) @import.module
  name: (dotted_name) @import.name) @import
(import_from_statement
  module_name: (relative_import) @import.module
  name: (aliased_import
    name: (dotted_name) @import.name
    alias: (identifier) @import.alias)) @import

; foo(...)
(call function: (identifier) @call.name) @call
; obj.method(...)
(call function: (attribute attribute: (identifier) @call.name)) @call

; identifier uses (filtered against known definitions by the extractor)
(identifier) @ref
; obj.attr — the attribute name can reference a known method/const
(attribute attribute: (identifier) @ref)
