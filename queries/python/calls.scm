; Direct call: foo()
(call
  function: (identifier) @call.func
  arguments: (argument_list) @call.args)

; Method call: self.foo() / obj.method()
(call
  function: (attribute
    object: (_) @call.object
    attribute: (identifier) @call.method)
  arguments: (argument_list) @call.args)

; Chained call: foo().bar()
(call
  function: (attribute
    object: (call) @call.chain
    attribute: (identifier) @call.method))
