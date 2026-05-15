; Function definitions (standalone)
(function_definition
  name: (identifier) @func.name
  parameters: (parameters) @func.params
  body: (block) @func.body) @func.def

; Class definitions
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list)? @class.bases
  body: (block) @class.body) @class.def

; Decorated definitions (decorator + function/class)
(decorated_definition
  (decorator) @decorator
  definition: [(function_definition) @decorated.func (class_definition) @decorated.class])
