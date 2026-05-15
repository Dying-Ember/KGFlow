"""JavaScript/TypeScript extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from extractors.base import BaseExtractor, OneFileResult
from extractors import register

try:
    import tree_sitter_javascript as tsjavascript
    from tree_sitter import Language, Parser
    HAS_TS = True
except ImportError:
    HAS_TS = False

# Node types that can appear as named children of export_statement.
_EXPORTABLE_DECLARATIONS = {
    "function_declaration", "generator_function_declaration",
    "class_declaration",
    "lexical_declaration", "variable_declaration",
}

# Node types that represent function/method bodies (contain statements).
_BLOCK_TYPES = {"statement_block", "switch_body"}

# Node types that open a nested execution context — we recurse into their
# blocks to find calls, conditions, etc.
_CONTAINER_STATEMENTS = {
    "if_statement", "while_statement", "do_while_statement",
    "for_statement", "for_in_statement",
    "try_statement", "try_statement",  # catch_clause, finally_clause handled separately
    "switch_statement", "with_statement",
    "labeled_statement",
    "arrow_function", "function_declaration",
}


@register("javascript")
class JavaScriptExtractor(BaseExtractor):
    """JavaScript/TypeScript extractor using tree-sitter."""

    def __init__(self, project_root: Path):
        super().__init__(project_root, language="javascript")
        self.extractor_version = "1.0.0"
        self.file_suffixes = {".js", ".jsx", ".ts", ".tsx"}

        if HAS_TS:
            self._lang = Language(tsjavascript.language())
            self._parser = Parser(self._lang)
        else:
            self._parser = None

    # ── Main entry point ─────────────────────────────────────────────

    def extract_file(self, source: str, file_path: str, mod_name: str) -> OneFileResult:
        """Parse one JS/TS file using tree-sitter."""
        result = OneFileResult()

        if not HAS_TS or self._parser is None:
            result.errors.append(
                "tree-sitter-javascript not installed "
                "(pip install tree-sitter-javascript)"
            )
            return result

        try:
            tree = self._parser.parse(source.encode("utf-8"))
        except Exception as e:
            result.errors.append(f"Parse error: {e}")
            return result

        root = tree.root_node
        src = source.encode("utf-8")

        # Walk top-level declarations
        self._walk_program(root, src, mod_name, file_path, result)

        return result

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _start_line(node) -> int:
        return node.start_point[0] + 1

    @staticmethod
    def _end_line(node) -> int:
        return node.end_point[0] + 1

    @staticmethod
    def _start_col(node) -> int:
        return node.start_point[1]

    @staticmethod
    def _end_col(node) -> int:
        return node.end_point[1]

    @staticmethod
    def _text(node) -> str:
        return node.text.decode("utf-8") if node.text else ""

    def _child_by_type(self, node, child_type: str):
        """Return *all* direct named children matching `child_type`."""
        return [c for c in node.named_children if c.type == child_type]

    def _first_by_type(self, node, child_type: str):
        for c in node.named_children:
            if c.type == child_type:
                return c
        return None

    # ── Top-level walk ───────────────────────────────────────────────

    def _walk_program(self, node, src: bytes, mod_name: str, file_path: str,
                      result: OneFileResult) -> None:
        for child in node.named_children:
            ct = child.type

            if ct == "import_statement":
                self._handle_import(child, src, mod_name, result)
            elif ct == "export_statement":
                self._walk_export(child, src, mod_name, file_path, result)
            elif ct in ("function_declaration", "generator_function_declaration"):
                self._handle_function(child, src, mod_name, file_path, result)
            elif ct == "class_declaration":
                self._handle_class(child, src, mod_name, file_path, result)
            elif ct in ("lexical_declaration", "variable_declaration"):
                self._handle_var_declaration(child, src, mod_name, file_path, result)
            elif ct == "expression_statement":
                # Top-level call, assignment, require(), etc.
                self._walk_stmt(child, src, mod_name, file_path, result)
            elif ct in ("for_statement", "for_in_statement", "while_statement",
                         "do_while_statement", "if_statement",
                         "try_statement", "throw_statement", "switch_statement"):
                # Top-level control flow — use the module as owner
                self._walk_stmt(child, src, mod_name, None, result)

    def _walk_export(self, node, src: bytes, mod_name: str, file_path: str,
                     result: OneFileResult) -> None:
        """Unwrap export_statement to process the inner declaration."""
        for child in node.named_children:
            ct = child.type
            if ct in ("function_declaration", "generator_function_declaration"):
                self._handle_function(child, src, mod_name, file_path, result)
            elif ct == "class_declaration":
                self._handle_class(child, src, mod_name, file_path, result)
            elif ct in ("lexical_declaration", "variable_declaration"):
                self._handle_var_declaration(child, src, mod_name, file_path, result)
            elif ct == "export_clause":
                # export { foo, bar } — just named re-exports, skip for now
                pass
            elif ct == "identifier":
                # export default <expr> where <expr> is an identifier
                pass

    # ── Import handling ──────────────────────────────────────────────

    def _handle_import(self, node, src: bytes, mod_name: str,
                       result: OneFileResult) -> None:
        """Extract ES module import statements."""
        line = self._start_line(node)

        # Find the module specifier (string node)
        module_spec = self._extract_module_specifier(node, src)
        if not module_spec:
            return

        # Find the import_clause to get named imports
        clause = self._first_by_type(node, "import_clause")
        names = self._extract_import_names(clause) if clause else []

        if not names:
            # Side-effect import: import 'foo' — record as bare import
            result.imports.append({
                "from_module": mod_name,
                "to_module": module_spec,
                "what": "*",
                "line": line,
            })
            return

        for name in names:
            result.imports.append({
                "from_module": mod_name,
                "to_module": module_spec,
                "what": name,
                "line": line,
            })

    @staticmethod
    def _extract_module_specifier(node, src: bytes) -> str:
        """Get the module string from an import/require node, stripping quotes.

        Searches recursively since the string may be nested inside an
        ``arguments`` node (for require() calls) or be a direct child
        (for import statements).
        """
        string_node = JavaScriptExtractor._find_descendant(node, "string")
        if string_node is None:
            return ""
        text = string_node.text.decode("utf-8")
        # Remove surrounding quotes
        if (text.startswith("'") and text.endswith("'")) or \
           (text.startswith('"') and text.endswith('"')):
            text = text[1:-1]
        return text

    @staticmethod
    def _find_descendant(node, target_type: str):
        """Depth-first search for a descendant of a given type."""
        if node.type == target_type:
            return node
        for child in node.children:
            result = JavaScriptExtractor._find_descendant(child, target_type)
            if result is not None:
                return result
        return None

    @staticmethod
    def _extract_import_names(clause_node) -> list[str]:
        """Extract all imported identifier names from an import_clause node."""
        names: list[str] = []
        for child in clause_node.named_children:
            ct = child.type
            if ct == "identifier":
                names.append(child.text.decode("utf-8"))
            elif ct == "named_imports":
                for spec in child.named_children:
                    if spec.type == "import_specifier":
                        for inner in spec.named_children:
                            if inner.type == "identifier":
                                names.append(inner.text.decode("utf-8"))
                                break  # first identifier is the local name
            elif ct == "namespace_import":
                for inner in child.named_children:
                    if inner.type == "identifier":
                        names.append(inner.text.decode("utf-8"))
                        break
        return names

    # ── Function handling ────────────────────────────────────────────

    def _handle_function(self, node, src: bytes, mod_name: str, file_path: str,
                         result: OneFileResult) -> None:
        """Handle function_declaration at any level."""
        name_node = self._first_by_type(node, "identifier")
        name = self._text(name_node) if name_node else "<anonymous>"
        fqn = f"{mod_name}.{name}"

        params_node = self._first_by_type(node, "formal_parameters")
        params = self._extract_params(params_node) if params_node else []

        body = self._first_by_type(node, "statement_block")

        result.functions.append({
            "name": name,
            "fqn": fqn,
            "module": mod_name,
            "file_path": file_path,
            "start_line": self._start_line(node),
            "end_line": self._end_line(node),
            "start_col": self._start_col(node),
            "end_col": self._end_col(node),
            "params": params,
            "decorators": [],
            "language": "javascript",
        })

        if body:
            self._walk_body(body, src, fqn, None, result)

    def _extract_params(self, params_node) -> list[str]:
        """Extract parameter names from formal_parameters node."""
        params: list[str] = []
        for child in params_node.named_children:
            if child.type == "identifier":
                params.append(self._text(child))
            elif child.type == "rest_pattern":
                for inner in child.named_children:
                    if inner.type == "identifier":
                        params.append(f"...{self._text(inner)}")
            elif child.type == "assignment_pattern":
                for inner in child.named_children:
                    if inner.type == "identifier":
                        params.append(self._text(inner))
                        break
            elif child.type == "object_pattern":
                props: list[str] = []
                for inner in child.named_children:
                    if inner.type in ("shorthand_property_identifier",
                                       "pair_pattern"):
                        props.append(self._text(inner))
                if props:
                    params.append("{" + ", ".join(props) + "}")
                else:
                    params.append("{}")
            elif child.type == "array_pattern":
                elems: list[str] = []
                for inner in child.named_children:
                    if inner.type == "identifier":
                        elems.append(self._text(inner))
                params.append("[" + ", ".join(elems) + "]")
        return params

    # ── Class handling ───────────────────────────────────────────────

    def _handle_class(self, node, src: bytes, mod_name: str, file_path: str,
                      result: OneFileResult) -> None:
        """Handle class_declaration."""
        name_node = self._first_by_type(node, "identifier")
        name = self._text(name_node) if name_node else "<anonymous>"
        fqn = f"{mod_name}.{name}"

        bases = self._extract_bases(node)

        body = self._first_by_type(node, "class_body")

        result.classes.append({
            "name": name,
            "fqn": fqn,
            "module": mod_name,
            "bases": bases,
            "file_path": file_path,
            "start_line": self._start_line(node),
            "end_line": body.end_point[0] + 1 if body else self._end_line(node),
            "start_col": self._start_col(node),
            "end_col": self._end_col(node),
            "language": "javascript",
        })

        if body:
            self._walk_class_body(body, src, mod_name, file_path, fqn, result)

    def _extract_bases(self, class_node) -> list[str]:
        """Extract base class names from class_heritage."""
        heritage = self._first_by_type(class_node, "class_heritage")
        if heritage is None:
            return []
        bases: list[str] = []
        # In JS tree-sitter, class_heritage directly contains the extends
        # identifiers (e.g. class Foo extends Bar → class_heritage > identifier)
        for child in heritage.named_children:
            if child.type in ("identifier", "member_expression"):
                bases.append(self._text(child))
        return bases

    def _walk_class_body(self, body_node, src: bytes, mod_name: str,
                         file_path: str, class_fqn: str,
                         result: OneFileResult) -> None:
        """Walk class body for methods, field declarations, and static blocks."""
        for child in body_node.named_children:
            ct = child.type

            if ct == "method_definition":
                self._handle_method(child, src, mod_name, file_path, class_fqn, result)
            elif ct == "field_definition":
                self._handle_field(child, src, class_fqn, mod_name, result)
            elif ct == "public_field_definition":
                # TypeScript public field
                for inner in child.named_children:
                    if inner.type == "identifier":
                        # Record as attr_assignment
                        pass
                    elif inner.type == "arrow_function":
                        self._handle_arrow_as_method(
                            inner, child, src, mod_name, file_path, class_fqn, result)
            elif ct == "static_block":
                self._walk_body(child, src, class_fqn, class_fqn, result)
            elif ct in ("lexical_declaration", "variable_declaration"):
                self._handle_var_declaration(child, src, mod_name, file_path, result)
            elif ct == "expression_statement":
                self._walk_stmt(child, src, mod_name, file_path, result)

    # ── Method handling ──────────────────────────────────────────────

    def _handle_method(self, node, src: bytes, mod_name: str, file_path: str,
                       class_fqn: str, result: OneFileResult) -> None:
        """Handle method_definition inside a class body."""
        # Find name — could be property_identifier, identifier, or string
        name_node = None
        for child in node.named_children:
            if child.type in ("property_identifier", "identifier"):
                name_node = child
                break
        if name_node is None:
            return
        name = self._text(name_node)

        fqn = f"{class_fqn}.{name}"

        params_node = self._first_by_type(node, "formal_parameters")
        params = self._extract_params(params_node) if params_node else []

        body = self._first_by_type(node, "statement_block")

        result.methods.append({
            "name": name,
            "fqn": fqn,
            "owner_class": class_fqn,
            "file_path": file_path,
            "start_line": self._start_line(node),
            "end_line": self._end_line(node),
            "start_col": self._start_col(node),
            "end_col": self._end_col(node),
            "params": params,
            "decorators": [],
            "language": "javascript",
        })

        if body:
            self._walk_body(body, src, fqn, class_fqn, result)

    def _handle_arrow_as_method(self, arrow_node, parent_node, src: bytes,
                                 mod_name: str, file_path: str, class_fqn: str,
                                 result: OneFileResult) -> None:
        """Handle arrow function assigned to a class field as a method."""
        name_node = None
        for child in parent_node.named_children:
            if child.type in ("property_identifier", "identifier",
                               "private_property_identifier"):
                name_node = child
                break
        if name_node is None:
            return
        name = self._text(name_node)
        fqn = f"{class_fqn}.{name}"

        params_node = self._first_by_type(arrow_node, "formal_parameters")
        params = self._extract_params(params_node) if params_node else []

        body_candidate = self._first_by_type(arrow_node, "statement_block")

        result.methods.append({
            "name": name,
            "fqn": fqn,
            "owner_class": class_fqn,
            "file_path": file_path,
            "start_line": self._start_line(parent_node),
            "end_line": self._end_line(arrow_node),
            "start_col": self._start_col(parent_node),
            "end_col": self._end_col(arrow_node),
            "params": params,
            "decorators": [],
            "language": "javascript",
        })

        if body_candidate:
            self._walk_body(body_candidate, src, fqn, class_fqn, result)

    def _handle_field(self, node, src: bytes, class_fqn: str, mod_name: str,
                      result: OneFileResult) -> None:
        """Handle class field definition (potential composition-like attr)."""
        name_node = None
        for child in node.named_children:
            if child.type in ("property_identifier", "identifier",
                               "private_property_identifier"):
                name_node = child
                break
        if name_node is None:
            return
        attr_name = self._text(name_node)
        # Check if the value is a new/call expression (composition candidate)
        value = self._first_by_type(node, "new_expression") or \
                self._first_by_type(node, "call_expression")
        if value is not None:
            composed = self._extract_constructor_name(value, src)
            if composed:
                result.compositions.append({
                    "class": class_fqn,
                    "composes": composed,
                    "attr": attr_name,
                    "line": self._start_line(node),
                })

    def _extract_constructor_name(self, node, src: bytes) -> Optional[str]:
        """Get the class/function name from a new/call expression."""
        func = self._first_by_type(node, "identifier") or \
               self._first_by_type(node, "member_expression")
        if func:
            return self._text(func)
        return None

    # ── Variable declaration handling ────────────────────────────────

    def _handle_var_declaration(self, node, src: bytes, mod_name: str,
                                file_path: str, result: OneFileResult) -> None:
        """Handle var/let/const declarations — detect arrow functions and require()."""
        for child in node.named_children:
            ct = child.type
            if ct == "variable_declarator":
                value = child.child_by_field_name("value")

                if value is None:
                    continue

                if value.type == "arrow_function":
                    self._handle_arrow_function(
                        child, value, src, mod_name, file_path, result)
                elif value.type == "call_expression":
                    # Check for require() calls
                    func_node = self._first_by_type(value, "identifier")
                    if func_node and self._text(func_node) == "require":
                        self._handle_require(child, value, src, mod_name, result)
            elif ct.type == "arrow_function":
                # Direct arrow function without variable_declarator wrapping
                pass

    def _handle_arrow_function(self, decl_node, arrow_node, src: bytes,
                                mod_name: str, file_path: str,
                                result: OneFileResult) -> None:
        """Handle arrow function assigned to a const/let/var."""
        name_node = self._first_by_type(decl_node, "identifier")
        if name_node is None:
            return
        name = self._text(name_node)
        fqn = f"{mod_name}.{name}"

        params_node = self._first_by_type(arrow_node, "formal_parameters")
        params = self._extract_params(params_node) if params_node else []

        body = self._first_by_type(arrow_node, "statement_block")
        # Arrow with expression body (no braces)
        if body is None:
            body = next(
                (c for c in arrow_node.named_children
                 if c.type not in ("formal_parameters", "identifier", "=>")),
                None)

        result.functions.append({
            "name": name,
            "fqn": fqn,
            "module": mod_name,
            "file_path": file_path,
            "start_line": self._start_line(decl_node),
            "end_line": self._end_line(arrow_node),
            "start_col": self._start_col(decl_node),
            "end_col": self._end_col(arrow_node),
            "params": params,
            "decorators": [],
            "language": "javascript",
        })

        if body and body.type == "statement_block":
            self._walk_body(body, src, fqn, None, result)

    def _handle_require(self, decl_node, call_node, src: bytes, mod_name: str,
                        result: OneFileResult) -> None:
        """Handle CommonJS require() as an import."""
        module_spec = self._extract_module_specifier(call_node, src)
        if not module_spec:
            return

        name_node = self._first_by_type(decl_node, "identifier")
        if name_node:
            names = [self._text(name_node)]
        else:
            # Destructured: const { a, b } = require('foo')
            pattern = self._first_by_type(decl_node, "object_pattern")
            if pattern:
                names = [self._text(c) for c in pattern.named_children
                         if c.type in ("shorthand_property_identifier", "identifier")]
            else:
                names = ["*"]

        line = self._start_line(decl_node)
        for name in names:
            result.imports.append({
                "from_module": mod_name,
                "to_module": module_spec,
                "what": name,
                "line": line,
            })

    # ── Body walking: calls, conditions, error handlers ──────────────

    def _walk_body(self, body_node, src: bytes, owner_fqn: str,
                   class_fqn: Optional[str], result: OneFileResult) -> None:
        """Walk all statements inside a function/method/block body."""
        for stmt in body_node.named_children:
            self._walk_stmt(stmt, src, owner_fqn, class_fqn, result)

    def _walk_stmt(self, stmt, src: bytes, owner_fqn: str,
                   class_fqn: Optional[str], result: OneFileResult) -> None:
        """Dispatch a single statement node."""
        ct = stmt.type

        if ct == "expression_statement":
            self._walk_expression_stmt(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "if_statement":
            self._handle_if(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "while_statement":
            self._handle_while(stmt, src, owner_fqn, result)
        elif ct == "do_while_statement":
            self._handle_do_while(stmt, src, owner_fqn, result)
        elif ct == "for_statement":
            self._handle_for(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "for_in_statement":
            self._handle_for_in(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "try_statement":
            self._handle_try(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "throw_statement":
            self._handle_throw(stmt, src, owner_fqn, result)
        elif ct == "return_statement":
            self._handle_return(stmt, src, owner_fqn, result)
        elif ct == "switch_statement":
            self._handle_switch(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "lexical_declaration" or ct == "variable_declaration":
            self._handle_body_var_decl(stmt, src, owner_fqn, class_fqn, result)
        elif ct == "with_statement":
            self._handle_with(stmt, src, owner_fqn, result)
        elif ct == "labeled_statement":
            for child in stmt.named_children:
                self._walk_stmt(child, src, owner_fqn, class_fqn, result)
        elif ct in ("function_declaration", "generator_function_declaration"):
            # Nested function/generator — body not recursed into here;
            # handled when encountered as a declaration itself.
            pass
        elif ct == "statement_block":
            self._walk_body(stmt, src, owner_fqn, class_fqn, result)

    def _walk_expression_stmt(self, node, src: bytes, owner_fqn: str,
                               class_fqn: Optional[str],
                               result: OneFileResult) -> None:
        """Walk an expression_statement: extract call, assignment, etc."""
        for child in node.named_children:
            ct = child.type
            if ct == "call_expression":
                self._handle_call(child, src, owner_fqn, result)
            elif ct == "assignment_expression":
                self._handle_assignment(child, src, owner_fqn, class_fqn, result)
            elif ct == "new_expression":
                # new Foo() — potential composition instantiator in constructor
                self._handle_new_expression(child, src, owner_fqn, class_fqn, result)
            elif ct == "await_expression":
                for inner in child.named_children:
                    if inner.type == "call_expression":
                        self._handle_call(inner, src, owner_fqn, result)
                    elif inner.type == "member_expression":
                        # await obj.method() — the call_expression wraps the member
                        pass
            elif ct == "member_expression":
                # Member expression at statement level (e.g. standalone property access)
                pass
            elif ct == "update_expression":
                # i++ / i-- — no call to extract
                pass

    # ── Call extraction ──────────────────────────────────────────────

    @staticmethod
    def _is_this_access(obj_node) -> bool:
        """Check if a member_expression's object chain starts with 'this'."""
        if obj_node.type == "this":
            return True
        if obj_node.type == "member_expression":
            inner = obj_node.child_by_field_name("object")
            if inner:
                return JavaScriptExtractor._is_this_access(inner)
        return False

    def _handle_call(self, node, src: bytes, owner_fqn: str,
                     result: OneFileResult) -> None:
        """Extract a call_expression as a call_site."""
        func = node.child_by_field_name("function")
        if func is None:
            return

        call_expr = self._text(node)
        # Truncate very long expressions
        if len(call_expr) > 200:
            call_expr = call_expr[:197] + "..."

        is_self_call = False
        resolved_target = None

        if func.type == "identifier":
            call_name = self._text(func)
            if call_name == "require":
                # require() calls are handled as imports, skip here
                return
        elif func.type == "member_expression":
            obj = func.child_by_field_name("object")
            if obj and self._is_this_access(obj):
                is_self_call = True

        result.call_sites.append({
            "caller_fqn": owner_fqn,
            "call_expr": call_expr,
            "resolved_target": resolved_target,
            "is_self_call": is_self_call,
            "line": self._start_line(node),
            "confidence": "low",
            "resolution": "unresolved",
            "evidence": "",
        })

    def _handle_assignment(self, node, src: bytes, owner_fqn: str,
                            class_fqn: Optional[str],
                            result: OneFileResult) -> None:
        """Extract assignment as attr_assignment if it targets this.xxx."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")

        if left is None:
            return

        attr_name = None
        is_self = False

        if left.type == "member_expression":
            obj = left.child_by_field_name("object")
            prop = left.child_by_field_name("property")
            if obj and prop:
                obj_text = self._text(obj)
                if obj_text == "this":
                    is_self = True
                    attr_name = self._text(prop)

        if is_self and attr_name and class_fqn:
            assigned_type = self._infer_value_type(right, src) if right else None
            result.attr_assignments.append({
                "owner_class": class_fqn,
                "attr": attr_name,
                "assigned_type": assigned_type,
                "method_fqn": owner_fqn,
                "line": self._start_line(node),
            })

    def _infer_value_type(self, value_node, src: bytes) -> Optional[str]:
        """Infer the type name from a value expression."""
        if value_node is None:
            return None
        ct = value_node.type
        if ct == "new_expression":
            func = self._first_by_type(value_node, "identifier")
            if func:
                return self._text(func)
        elif ct == "call_expression":
            func = self._first_by_type(value_node, "identifier")
            if func:
                return self._text(func)
        elif ct == "string":
            return "string"
        elif ct == "number":
            return "number"
        elif ct in ("true", "false"):
            return "boolean"
        elif ct == "null":
            return "null"
        elif ct == "undefined":
            return "undefined"
        elif ct == "object":
            return "object"
        elif ct == "array":
            return "array"
        elif ct == "arrow_function":
            return "function"
        elif ct == "identifier":
            return self._text(value_node)
        return ct

    def _handle_new_expression(self, node, src: bytes, owner_fqn: str,
                                class_fqn: Optional[str],
                                result: OneFileResult) -> None:
        """Handle new ClassName() — composition is tracked via assignments, not bare 'new'."""
        # Bare new expressions without assignment (e.g. `new Foo()`) are not
        # recorded as compositions — only assignments like `this.x = new Foo()` are.
        pass

    @staticmethod
    def _unwrap_await_yield(node):
        """Unwrap await_expression / yield_expression to get the inner call."""
        if node.type in ("await_expression", "yield_expression"):
            for c in node.named_children:
                if c.type not in ("await", "yield", "*"):
                    return c
        return node

    def _handle_body_var_decl(self, node, src: bytes, owner_fqn: str,
                               class_fqn: Optional[str],
                               result: OneFileResult) -> None:
        """Handle var/let/const inside a function body."""
        for decl in node.named_children:
            if decl.type != "variable_declarator":
                continue
            value = decl.child_by_field_name("value")
            if value is None:
                continue
            # Unwrap await / yield
            value = self._unwrap_await_yield(value)

            if value.type == "call_expression":
                # Detect require() even inside function bodies
                func_node = self._first_by_type(value, "identifier")
                if func_node and self._text(func_node) == "require":
                    self._handle_require(decl, value, src, owner_fqn.rsplit(".", 1)[0], result)
                else:
                    self._handle_call(value, src, owner_fqn, result)
            elif value.type == "new_expression":
                # Check if assigned to this.xxx for composition
                name_node = self._first_by_type(decl, "identifier")
                if name_node and class_fqn:
                    func = self._first_by_type(value, "identifier")
                    if func:
                        result.attr_assignments.append({
                            "owner_class": class_fqn,
                            "attr": self._text(name_node),
                            "assigned_type": self._text(func),
                            "method_fqn": owner_fqn,
                            "line": self._start_line(decl),
                        })

    # ── Condition extraction ─────────────────────────────────────────

    def _handle_if(self, node, src: bytes, owner_fqn: str,
                   class_fqn: Optional[str], result: OneFileResult) -> None:
        """Extract if statement as condition."""
        cond_node = self._first_by_type(node, "parenthesized_expression")
        cond_text = ""
        if cond_node:
            inner = cond_node.named_children[0] if cond_node.named_children else None
            cond_text = self._text(inner) if inner else self._text(cond_node)

        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_text,
            "type": "if",
            "line": self._start_line(node),
        })

        # Recurse into consequence and alternative
        for child in node.named_children:
            if child.type == "statement_block":
                self._walk_body(child, src, owner_fqn, class_fqn, result)
            elif child.type == "if_statement":
                # else-if chain
                self._handle_if(child, src, owner_fqn, class_fqn, result)

    def _handle_while(self, node, src: bytes, owner_fqn: str,
                      result: OneFileResult) -> None:
        """Extract while statement as condition."""
        cond_node = self._first_by_type(node, "parenthesized_expression")
        cond_text = ""
        if cond_node:
            inner = cond_node.named_children[0] if cond_node.named_children else None
            cond_text = self._text(inner) if inner else self._text(cond_node)

        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_text,
            "type": "while",
            "line": self._start_line(node),
        })
        # Recurse into body
        body = self._first_by_type(node, "statement_block")
        if body:
            self._walk_body(body, src, owner_fqn, None, result)

    def _handle_do_while(self, node, src: bytes, owner_fqn: str,
                          result: OneFileResult) -> None:
        """Extract do-while statement as condition."""
        cond_node = self._first_by_type(node, "parenthesized_expression")
        cond_text = ""
        if cond_node:
            inner = cond_node.named_children[0] if cond_node.named_children else None
            cond_text = self._text(inner) if inner else self._text(cond_node)

        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_text,
            "type": "while",
            "line": self._start_line(node),
        })
        # Recurse into body (do-while body is the statement_block before the condition)
        body = self._first_by_type(node, "statement_block")
        if body:
            self._walk_body(body, src, owner_fqn, None, result)

    def _handle_for(self, node, src: bytes, owner_fqn: str,
                    class_fqn: Optional[str], result: OneFileResult) -> None:
        """Extract for(;;) statement as condition."""
        cond_node = self._first_by_type(node, "parenthesized_expression")
        cond_text = ""
        if cond_node:
            inner = cond_node.named_children[0] if cond_node.named_children else None
            cond_text = self._text(inner) if inner else self._text(cond_node)

        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_text if cond_text else "for(;;)",
            "type": "for",
            "line": self._start_line(node),
        })

        # Recurse into body
        body = self._first_by_type(node, "statement_block")
        if body:
            self._walk_body(body, src, owner_fqn, class_fqn, result)

    def _handle_for_in(self, node, src: bytes, owner_fqn: str,
                        class_fqn: Optional[str], result: OneFileResult) -> None:
        """Extract for...in / for...of statement as condition."""
        # Build a readable condition from left + right
        left = None
        right = None
        kind = "for_in"
        for child in node.named_children:
            if child.type in ("identifier", "variable_declaration", "object_pattern"):
                left = self._text(child)
            elif child.type in ("identifier", "member_expression"):
                if left is not None:
                    right = self._text(child)
            elif child.type == "of":
                kind = "for_of"

        cond_text = f"{left or '?'} in {right or '?'}" if kind == "for_in" \
                    else f"{left or '?'} of {right or '?'}"

        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_text,
            "type": "for",
            "line": self._start_line(node),
        })

        body = self._first_by_type(node, "statement_block")
        if body:
            self._walk_body(body, src, owner_fqn, class_fqn, result)

    def _handle_switch(self, node, src: bytes, owner_fqn: str,
                        class_fqn: Optional[str], result: OneFileResult) -> None:
        """Recurse into switch cases."""
        body = self._first_by_type(node, "switch_body")
        if body:
            for case in body.named_children:
                if case.type in ("switch_case", "switch_default"):
                    for stmt in case.named_children:
                        self._walk_stmt(stmt, src, owner_fqn, class_fqn, result)

    # ── Error handling ───────────────────────────────────────────────

    def _handle_try(self, node, src: bytes, owner_fqn: str,
                    class_fqn: Optional[str], result: OneFileResult) -> None:
        """Extract try/catch as error_handler."""
        has_finally = False
        exception_types: list[str] = []

        for child in node.named_children:
            ct = child.type
            if ct == "catch_clause":
                param = child.child_by_field_name("parameter")
                if param and param.type == "identifier":
                    exception_types.append(self._text(param))
                elif param:
                    exception_types.append(self._text(param))
                else:
                    exception_types.append("Error")
                # Recurse into catch body
                catch_body = self._first_by_type(child, "statement_block")
                if catch_body:
                    self._walk_body(catch_body, src, owner_fqn, class_fqn, result)
            elif ct == "finally_clause":
                has_finally = True
                fin_body = self._first_by_type(child, "statement_block")
                if fin_body:
                    self._walk_body(fin_body, src, owner_fqn, class_fqn, result)
            elif ct == "statement_block":
                # Try body
                self._walk_body(child, src, owner_fqn, class_fqn, result)

        if not exception_types:
            exception_types.append("Error")

        result.error_handlers.append({
            "owner_fqn": owner_fqn,
            "exception_types": exception_types,
            "has_finally": has_finally,
            "line": self._start_line(node),
        })

    def _handle_throw(self, node, src: bytes, owner_fqn: str,
                      result: OneFileResult) -> None:
        """Extract throw statement as raise."""
        exc_name = "Error"
        for child in node.named_children:
            if child.type == "new_expression":
                func = self._first_by_type(child, "identifier")
                if func:
                    exc_name = self._text(func)
                    break
            elif child.type == "identifier":
                exc_name = self._text(child)
                break
            elif child.type == "string":
                exc_name = self._text(child)
                break

        result.raises.append({
            "owner_fqn": owner_fqn,
            "exception_name": exc_name,
            "line": self._start_line(node),
        })

    def _handle_return(self, node, src: bytes, owner_fqn: str,
                       result: OneFileResult) -> None:
        """Extract return statement."""
        value = node.named_children[0] if node.named_children else None
        if value is None:
            result.returns.append({
                "owner_fqn": owner_fqn,
                "return_type": "undefined",
                "is_none": True,
                "line": self._start_line(node),
            })
        else:
            val_text = self._text(value)
            is_none = val_text in ("undefined", "null") or \
                      value.type in ("undefined", "null")
            result.returns.append({
                "owner_fqn": owner_fqn,
                "return_type": val_text,
                "is_none": is_none,
                "line": self._start_line(node),
            })

    def _handle_with(self, node, src: bytes, owner_fqn: str,
                     result: OneFileResult) -> None:
        """Extract with statement (rare but still valid JS)."""
        obj_node = self._first_by_type(node, "parenthesized_expression")
        if obj_node:
            inner = obj_node.named_children[0] if obj_node.named_children else None
            ctx_expr = self._text(inner) if inner else self._text(obj_node)
        else:
            ctx_expr = self._text(node)

        result.withs.append({
            "owner_fqn": owner_fqn,
            "context_expr": ctx_expr,
            "line": self._start_line(node),
        })

    # ── Override module name computation for path-based JS modules ───

    def _compute_module_name(self, rel_path: str) -> str:
        """Convert relative file path to dotted module name.

        JS modules are path-based, so we use a path-like FQN:
        e.g. 'src/components/Button.js' → 'src.components.Button'
        """
        name = rel_path.replace("\\", "/")
        for suffix in self.file_suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name.replace("/", ".")
