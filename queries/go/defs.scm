; Function declaration
(function_declaration
  name: (identifier) @func.name
  parameters: (parameter_list) @func.params
  result: (_)? @func.return
  body: (block) @func.body) @func.def

; Method declaration (func (r T) Name() {})
(method_declaration
  receiver: (parameter_list) @method.receiver
  name: (identifier) @method.name
  parameters: (parameter_list) @method.params
  result: (_)? @method.return
  body: (block) @method.body) @method.def

; Type definition as class-like
(type_declaration
  (type_spec
    name: (type_identifier) @class.name
    type: (struct_type) @class.body)) @class.def

; Interface definition
(type_declaration
  (type_spec
    name: (type_identifier) @class.name
    type: (interface_type) @class.body)) @interface.def
