; Symbol-graph captures for Protocol Buffers. Messages, enums, and services
; register as type definitions; rpcs as methods. proto is its own language
; family: references resolve proto->proto only (generated Go/TS bindings are
; separate artifacts — cross-language linking would be guesswork).

(message (message_name (identifier) @name)) @def.class
(enum (enum_name (identifier) @name)) @def.class
(service (service_name (identifier) @name)) @def.class
(rpc (rpc_name (identifier) @name)) @def.method

; import "common/proto/errors.proto";
(import path: (string) @import.module) @import

; message/enum type uses (rpc inputs/outputs, field types)
(message_or_enum_type (identifier) @ref)
