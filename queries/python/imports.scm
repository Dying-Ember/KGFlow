; import X
(import_statement
  name: (dotted_name) @import.module)

; from X import Y
(import_from_statement
  module_name: (dotted_name) @import.from_module
  name: [(dotted_name) @import.name (aliased_import (dotted_name) @import.name)])

; from X import Y as Z
(aliased_import
  name: (dotted_name) @import.name
  alias: (identifier) @import.alias)
