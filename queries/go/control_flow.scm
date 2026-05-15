; if statements
(if_statement
  condition: (_) @if.condition
  consequence: (block) @if.then
  alternative: (else_statement)? @if.else)

; for statements
(for_statement
  body: (block) @for.body)

; range loops
(for_range_statement
  body: (block) @for.body)

; defer
(defer_expression
  (call_expression) @defer.call)

; go routines
(go_expression
  (call_expression) @go.call)

; return
(return_statement
  (_)? @return.value)
