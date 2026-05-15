; import "path"
(import_declaration
  (import_spec
    path: (interpreted_string_literal) @import.module
    name: (package_identifier)? @import.alias))

; import ( "a" "b" )
(import_declaration
  (import_spec_list
    (import_spec
      path: (interpreted_string_literal) @import.module)))
