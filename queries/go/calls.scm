; Direct call: foo()
(call_expression
  function: (identifier) @call.func
  arguments: (argument_list) @call.args)

; Method/package call: obj.Method() or pkg.Func()
(call_expression
  function: (selector_expression
    operand: (_) @call.object
    field: (field_identifier) @call.method)
  arguments: (argument_list) @call.args)
