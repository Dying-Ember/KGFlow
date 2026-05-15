; Direct call: foo()
(call_expression
  function: (identifier) @call.func
  arguments: (arguments) @call.args)

; Method call: obj.method()
(call_expression
  function: (member_expression
    object: (_) @call.object
    property: [(property_identifier) @call.method (_) @call.method])
  arguments: (arguments) @call.args)

; Chained: foo().bar()
(call_expression
  function: (member_expression
    object: (call_expression) @call.chain
    property: (property_identifier) @call.method))
