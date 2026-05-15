; if statements
(if_statement
  condition: (_) @if.condition
  consequence: (block) @if.then
  alternative: (else_clause)? @if.else)

; while statements
(while_statement
  condition: (_) @while.condition
  body: (block) @while.body)

; for statements
(for_statement
  left: (_) @for.var
  right: (_) @for.iterable
  body: (block) @for.body)

; try/except statements
(try_statement
  body: (block) @try.body
  (except_clause
    (identifier)? @except.type
    (identifier)? @except.alias
    body: (block) @except.body)*
  (else_clause (block) @try.else)?
  (finally_clause (block) @try.finally)?)

; raise statements
(raise_statement) @raise

; return statements
(return_statement
  (_)? @return.value)
