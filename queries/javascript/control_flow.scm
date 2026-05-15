; if statements
(if_statement
  condition: (_) @if.condition
  consequence: (statement_block) @if.then
  alternative: (else_clause)? @if.else)

; while statements
(while_statement
  condition: (_) @while.condition
  body: (statement_block) @while.body)

; for statements
(for_statement
  body: (statement_block) @for.body)

; for...of / for...in
(for_in_statement body: (statement_block) @for.body)
(for_of_statement body: (statement_block) @for.body)

; try/catch statements
(try_statement
  body: (statement_block) @try.body
  (catch_clause
    (identifier)? @catch.type
    body: (statement_block) @catch.body)*
  (finally_clause (statement_block) @try.finally)?)

; throw statements
(throw_statement) @throw

; return statements
(return_statement (_)? @return.value)
