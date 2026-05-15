; Function declaration
(function_declaration
  name: (identifier) @func.name
  parameters: (formal_parameters) @func.params
  body: (statement_block) @func.body) @func.def

; Arrow function (const x = () => {})
; See also: arrow_function

; Class declaration
(class_declaration
  name: (identifier) @class.name
  body: (class_body) @class.body) @class.def

; Method definition inside class
(method_definition
  name: [(property_identifier) @method.name (private_property_identifier) @method.name]
  parameters: (formal_parameters) @method.params
  body: (statement_block) @method.body) @method.def

; Export default function
(export_default_declaration
  value: (function_declaration
    name: (identifier) @func.name) @func.def)

; Export function
(export_statement
  declaration: (function_declaration
    name: (identifier) @func.name) @func.def)
