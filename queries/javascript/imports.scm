; import X from 'module'
(import_statement
  (import_clause (identifier) @import.name)
  (string (string_fragment) @import.module))

; import { a, b } from 'module'
(import_statement
  (import_clause (named_imports (import_specifier (identifier) @import.name) ))
  (string (string_fragment) @import.module))

; import * as X from 'module'
(import_statement
  (import_clause (namespace_import (identifier) @import.name))
  (string (string_fragment) @import.module))

; require('module')
(call_expression
  function: (identifier) @import.name (#eq? @import.name "require")
  arguments: (arguments (string (string_fragment) @import.module)))
