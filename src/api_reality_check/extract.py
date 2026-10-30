"""Static extraction (DESIGN §4.1, §4.3, §14 A3).

Pure: the file is parsed with ``ast`` and never executed or imported. The binding model is
deliberately small: a name is followed only when it is a *trusted import binding* (exactly one
binding in its scope, and that binding is an import) or an *obvious constructor result*
(``x = pkg.Class(...)`` as a direct child statement). Everything else is ignored, so an
unusual-but-correct program yields fewer references, never wrong ones.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

from .models import FileAnalysis, KwargUse, Loc, Reference

MAX_BYTES = 2 * 1024 * 1024

# Handlers that make a whole try statement a guard (§14 A3).
GUARD_EXCEPTIONS = frozenset({
    "ImportError", "ModuleNotFoundError", "AttributeError", "TypeError", "NameError",
    "Exception", "BaseException",
})
# Handlers that make an import inside the try "optional" (§4.4 step 1).
OPTIONAL_IMPORT_EXCEPTIONS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GUARD_CALLS = frozenset({"hasattr", "getattr", "signature", "version"})
_GUARD_ATTRS = frozenset({"platform", "parameters", "signature", "version_info", "__version__"})
_DECORATOR_WORDS = ("skip", "platform", "version")
# Consumers that only read a bare module/class object; passing a binding to anything else
# might attach attributes to it, so its attributes are no longer checked.
_READ_ONLY_CONSUMERS = frozenset({
    "isinstance", "issubclass", "print", "repr", "str", "type", "id", "len", "callable",
    "hash", "bool", "hasattr", "getattr", "dir", "format",
})
_POISON_CALLS = frozenset({"setattr", "delattr", "vars"})
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_TRY_NODES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)
_COMP_NODES = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


@dataclass
class _Binding:
    kind: str                       # "import" | "other"
    lineno: int
    # import bindings
    module: str | None = None
    path: tuple[str, ...] = ()
    module_as_written: str | None = None
    alias_loc: Loc | None = None
    optional: bool = False
    type_checking: bool = False
    star_shadowed: bool = False
    # other bindings: candidate constructor call for instance inference (§4.3)
    ctor_call: ast.Call | None = None


@dataclass(eq=False)
class _Scope:
    kind: str                       # module | function | class | comprehension
    node: ast.AST
    parent: "_Scope | None"
    bindings: dict[str, list[_Binding]] = field(default_factory=dict)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)

    def bind(self, name: str, b: _Binding) -> None:
        self.bindings.setdefault(name, []).append(b)


def _loc(node) -> Loc:
    return Loc(node.lineno, node.col_offset)


def _attr_loc(node: ast.Attribute) -> Loc:
    return Loc(node.end_lineno, node.end_col_offset - len(node.attr))


def _exc_names(handler: ast.ExceptHandler) -> set[str] | None:
    """Names caught by a handler; None means bare ``except:``."""
    if handler.type is None:
        return None
    elts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    out = set()
    for e in elts:
        if isinstance(e, ast.Name):
            out.add(e.id)
        elif isinstance(e, ast.Attribute):
            out.add(e.attr)
    return out


def _try_catches(node, names: frozenset[str]) -> bool:
    for h in node.handlers:
        caught = _exc_names(h)
        if caught is None or caught & names:
            return True
    return False


def _mentions_type_checking(test: ast.AST) -> bool:
    for n in ast.walk(test):
        if isinstance(n, ast.Name) and n.id == "TYPE_CHECKING":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "TYPE_CHECKING":
            return True
    return False


class _Builder:
    """Pass 1: scopes, every binding of every name, Name loads, import references."""

    def __init__(self, path: str):
        self.path = path
        self.name_loads: list[tuple[ast.Name, _Scope]] = []
        self.import_refs: list[tuple[Reference, ast.AST]] = []   # (ref, node used for guard lookup)
        self.imported_tops: list[str] = []
        self.type_checking = False
        self.optional = False
        self.module_scope: _Scope | None = None

    # -- helpers -------------------------------------------------------------------------
    def _binding_scope(self, scope: _Scope, name: str) -> _Scope:
        if name in scope.globals:
            return self.module_scope
        if name in scope.nonlocals:
            s = scope.parent
            while s is not None:
                if s.kind == "function" and name in s.bindings:
                    return s
                s = s.parent
            return scope
        return scope

    def _bind(self, scope: _Scope, name: str, b: _Binding) -> None:
        self._binding_scope(scope, name).bind(name, b)

    def _other(self, node) -> _Binding:
        return _Binding("other", getattr(node, "lineno", 0))

    def bind_target(self, target, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            self._bind(scope, target.id, self._other(target))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                self.bind_target(e, scope)
        elif isinstance(target, ast.Starred):
            self.bind_target(target.value, scope)
        else:  # Attribute / Subscript store: the expression around it is evaluated
            self.visit(target, scope)

    # -- traversal ------------------------------------------------------------------------
    def build(self, tree: ast.Module) -> _Scope:
        self.module_scope = _Scope("module", tree, None)
        self._prescan_declarations(tree.body, self.module_scope)
        self.visit_body(tree.body, self.module_scope, direct=True)
        return self.module_scope

    def _prescan_declarations(self, body, scope: _Scope) -> None:
        """global/nonlocal apply to the whole function, so collect them before binding."""
        stack = list(body)
        while stack:
            n = stack.pop()
            if isinstance(n, ast.Global):
                scope.globals.update(n.names)
                for name in n.names:  # a `global x` anywhere poisons module-level x
                    self.module_scope.bind(name, self._other(n))
            elif isinstance(n, ast.Nonlocal):
                scope.nonlocals.update(n.names)
            elif isinstance(n, (*_FUNC_NODES, ast.ClassDef)):
                continue
            else:
                stack.extend(ast.iter_child_nodes(n))

    def visit_body(self, stmts, scope: _Scope, direct: bool = False) -> None:
        for s in stmts:
            self.visit_stmt(s, scope, direct)

    def visit_stmt(self, node, scope: _Scope, direct: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                self.visit(d, scope)
            self._visit_args_outer(node.args, scope)
            if node.returns is not None:
                self.visit(node.returns, scope)
            self._bind(scope, node.name, self._other(node))
            fs = _Scope("function", node, scope)
            self._prescan_declarations(node.body, fs)
            self._bind_params(node.args, fs)
            self.visit_body(node.body, fs, direct=True)
        elif isinstance(node, ast.ClassDef):
            for d in node.decorator_list:
                self.visit(d, scope)
            for b in node.bases:
                self.visit(b, scope)
            for k in node.keywords:
                self.visit(k.value, scope)
            self._bind(scope, node.name, self._other(node))
            cs = _Scope("class", node, scope)
            self.visit_body(node.body, cs)
        elif isinstance(node, ast.Import):
            self._import(node, scope)
        elif isinstance(node, ast.ImportFrom):
            self._import_from(node, scope)
        elif isinstance(node, ast.Assign):
            self.visit(node.value, scope)
            for t in node.targets:
                self.bind_target(t, scope)
            if direct and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Call):
                self._last_binding(scope, node.targets[0].id).ctor_call = node.value
        elif isinstance(node, ast.AnnAssign):
            self.visit(node.annotation, scope)
            if node.value is not None:
                self.visit(node.value, scope)
            if isinstance(node.target, ast.Name):
                self._bind(scope, node.target.id, self._other(node))
                if direct and isinstance(node.value, ast.Call):
                    self._last_binding(scope, node.target.id).ctor_call = node.value
            else:
                self.visit(node.target, scope)
        elif isinstance(node, ast.AugAssign):
            self.visit(node.value, scope)
            if isinstance(node.target, ast.Name):
                self._bind(scope, node.target.id, self._other(node))
            else:
                self.visit(node.target, scope)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.visit(node.iter, scope)
            self.bind_target(node.target, scope)
            self.visit_body(node.body, scope)
            self.visit_body(node.orelse, scope)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.visit(item.context_expr, scope)
                if item.optional_vars is not None:
                    self.bind_target(item.optional_vars, scope)
            self.visit_body(node.body, scope)
        elif _TRY_NODES and isinstance(node, _TRY_NODES):
            prev = self.optional
            if _try_catches(node, OPTIONAL_IMPORT_EXCEPTIONS):
                self.optional = True
            self.visit_body(node.body, scope)
            for h in node.handlers:
                if h.type is not None:
                    self.visit(h.type, scope)
                if h.name:
                    self._bind(scope, h.name, self._other(h))
                self.visit_body(h.body, scope)
            self.visit_body(node.orelse, scope)
            self.visit_body(node.finalbody, scope)
            self.optional = prev
        elif isinstance(node, ast.If):
            self.visit(node.test, scope)
            if _mentions_type_checking(node.test):
                prev = self.type_checking
                self.type_checking = True
                self.visit_body(node.body, scope)
                self.type_checking = prev
            else:
                self.visit_body(node.body, scope)
            self.visit_body(node.orelse, scope)
        elif isinstance(node, ast.Delete):
            for t in node.targets:
                self.bind_target(t, scope) if isinstance(t, ast.Name) else self.visit(t, scope)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            pass
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            self.visit(node.subject, scope)
            for case in node.cases:
                self._bind_pattern(case.pattern, scope)
                if case.guard is not None:
                    self.visit(case.guard, scope)
                self.visit_body(case.body, scope)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    self.visit_stmt(child, scope)
                else:
                    self.visit(child, scope)

    def _last_binding(self, scope: _Scope, name: str) -> _Binding:
        return self._binding_scope(scope, name).bindings[name][-1]

    def _bind_pattern(self, pat, scope: _Scope) -> None:
        for n in ast.walk(pat):
            name = None
            if isinstance(n, ast.MatchAs) or isinstance(n, ast.MatchStar):
                name = n.name
            elif isinstance(n, ast.MatchMapping):
                name = n.rest
            if name:
                self._bind(scope, name, self._other(n))
            if isinstance(n, ast.MatchValue):
                self.visit(n.value, scope)
            elif isinstance(n, ast.MatchClass):
                self.visit(n.cls, scope)

    def _visit_args_outer(self, args: ast.arguments, scope: _Scope) -> None:
        for d in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.visit(d, scope)
        for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
            if a is not None and a.annotation is not None:
                self.visit(a.annotation, scope)

    def _bind_params(self, args: ast.arguments, fs: _Scope) -> None:
        for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
            if a is not None:
                fs.bind(a.arg, self._other(a))

    def visit(self, node, scope: _Scope) -> None:
        """Expressions."""
        if node is None:
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                self.name_loads.append((node, scope))
            else:
                self._bind(scope, node.id, self._other(node))
            return
        if isinstance(node, ast.Lambda):
            self._visit_args_outer(node.args, scope)
            ls = _Scope("function", node, scope)
            self._bind_params(node.args, ls)
            self.visit(node.body, ls)
            return
        if isinstance(node, _COMP_NODES):
            gens = node.generators
            self.visit(gens[0].iter, scope)
            cs = _Scope("comprehension", node, scope)
            for i, g in enumerate(gens):
                if i:
                    self.visit(g.iter, cs)
                self.bind_target(g.target, cs)
                for cond in g.ifs:
                    self.visit(cond, cs)
            if isinstance(node, ast.DictComp):
                self.visit(node.key, cs)
                self.visit(node.value, cs)
            else:
                self.visit(node.elt, cs)
            return
        if isinstance(node, ast.NamedExpr):
            self.visit(node.value, scope)
            s = scope
            while s.kind == "comprehension" and s.parent is not None:
                s = s.parent
            self._bind(s, node.target.id, self._other(node))
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child, scope)

    # -- imports ---------------------------------------------------------------------------
    def _import(self, node: ast.Import, scope: _Scope) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top == "__future__":     # compiler directives, never a library to check (A31)
                self._bind(scope, alias.asname or top, self._other(node))
                continue
            loc = _loc(alias)
            bound = alias.asname or top
            target = alias.name if alias.asname else top
            self._bind(scope, bound, _Binding(
                "import", node.lineno, module=target, path=(), module_as_written=target,
                alias_loc=loc, optional=self.optional, type_checking=self.type_checking))
            if self.type_checking:
                continue
            self.imported_tops.append(top)
            ref = Reference(file=self.path, module=alias.name, path=(), path_locs=(), module_loc=loc,
                            module_as_written=alias.name, optional_import=self.optional, owned=0)
            self.import_refs.append((ref, alias))

    def _import_from(self, node: ast.ImportFrom, scope: _Scope) -> None:
        if node.module == "__future__":
            return
        stmt_loc = _loc(node)
        if node.level:
            written = "." * node.level + (node.module or "")
            for alias in node.names:
                if alias.name != "*":
                    self._bind(scope, alias.asname or alias.name, self._other(node))
            if not self.type_checking:
                ref = Reference(file=self.path, module=written, path=(), path_locs=(), module_loc=stmt_loc,
                                module_as_written=written, skip_reason="relative_import")
                self.import_refs.append((ref, node))
            return
        if not self.type_checking:
            self.imported_tops.append(node.module.split(".")[0])
        for alias in node.names:
            if alias.name == "*":
                for bs in scope.bindings.values():
                    for b in bs:
                        if b.kind == "import" and b.lineno < node.lineno:
                            b.star_shadowed = True
                if not self.type_checking:
                    ref = Reference(file=self.path, module=node.module, path=(), path_locs=(),
                                    module_loc=stmt_loc, module_as_written=node.module,
                                    optional_import=self.optional)
                    self.import_refs.append((ref, node))
                continue
            loc = _loc(alias)
            self._bind(scope, alias.asname or alias.name, _Binding(
                "import", node.lineno, module=node.module, path=(alias.name,),
                module_as_written=node.module, alias_loc=loc, optional=self.optional,
                type_checking=self.type_checking))
            if self.type_checking:
                continue
            ref = Reference(file=self.path, module=node.module, path=(alias.name,), path_locs=(loc,),
                            module_loc=stmt_loc, module_as_written=node.module,
                            optional_import=self.optional, owned=0)
            self.import_refs.append((ref, alias))


def _lookup(scope: _Scope, name: str) -> _Scope | None:
    s, first = scope, True
    while s is not None:
        if s.kind == "class" and not first:
            s = s.parent
            continue
        if name in s.globals:
            while s.parent is not None:
                s = s.parent
            return s if name in s.bindings else None
        if name in s.bindings and name not in s.nonlocals:
            return s
        s, first = s.parent, False
    return None


def _trusted_import(scope: _Scope, name: str) -> _Binding | None:
    bs = scope.bindings.get(name) or []
    if not bs or any(b.kind != "import" or b.type_checking or b.star_shadowed for b in bs):
        return None
    if len({(b.module, b.path) for b in bs}) != 1:
        return None
    return bs[0]


class _Guards:
    """§14 A3 guard rules over one module."""

    def __init__(self, tree: ast.Module, parents: dict[int, ast.AST]):
        self.tree = tree
        self.parents = parents
        self.guarded: set[int] = set()
        self.flags: set[str] = set()
        self._compute_flags()
        self._compute()

    def guardish(self, expr) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Call):
                f = n.func
                fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if fname in _GUARD_CALLS or fname in self.flags:
                    return True
            elif isinstance(n, ast.Name):
                if n.id in self.flags or "version" in n.id.lower() or n.id == "platform":
                    return True
            elif isinstance(n, ast.Attribute):
                if n.attr in _GUARD_ATTRS or "version" in n.attr.lower() or n.attr in self.flags:
                    return True
                if n.attr == "name" and isinstance(n.value, ast.Name) and n.value.id == "os":
                    return True
                if isinstance(n.value, ast.Name) and n.value.id == "platform":
                    return True
        return False

    def _compute_flags(self) -> None:
        changed = True
        while changed:
            changed = False
            for n in ast.walk(self.tree):
                targets, value = [], None
                if isinstance(n, ast.Assign):
                    targets, value = n.targets, n.value
                elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value is not None:
                    targets, value = [n.target], n.value
                elif isinstance(n, ast.NamedExpr):
                    targets, value = [n.target], n.value
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if n.name not in self.flags and any(
                            isinstance(r, ast.Return) and r.value is not None and self.guardish(r.value)
                            for r in ast.walk(n)):
                        self.flags.add(n.name)
                        changed = True
                    continue
                if value is None or not self.guardish(value):
                    continue
                for t in targets:
                    for tn in ast.walk(t):
                        name = tn.id if isinstance(tn, ast.Name) else tn.attr if isinstance(tn, ast.Attribute) else None
                        if name and name not in self.flags:
                            self.flags.add(name)
                            changed = True

    def mark(self, node) -> None:
        for n in ast.walk(node):
            self.guarded.add(id(n))

    def enclosing_function(self, node):
        p = self.parents.get(id(node))
        while p is not None:
            if isinstance(p, _FUNC_NODES):
                return p
            p = self.parents.get(id(p))
        return None

    def _enclosing_stmt(self, node):
        n = node
        while n is not None and not isinstance(n, ast.stmt):
            n = self.parents.get(id(n))
        return n

    def _apply(self, node) -> None:
        fn = self.enclosing_function(node)
        if fn is not None:
            self.mark(fn)
            return
        stmt = self._enclosing_stmt(node)
        if stmt is None:
            return
        self.mark(stmt)
        exits = isinstance(stmt, ast.Assert) or any(
            isinstance(n, (ast.Raise, ast.Return, ast.Continue, ast.Break)) or
            (isinstance(n, ast.Call) and _call_name(n.func) in ("exit", "quit", "_exit"))
            for n in ast.walk(stmt))
        if exits:
            parent = self.parents.get(id(stmt))
            for fname in ("body", "orelse", "finalbody"):
                block = getattr(parent, fname, None)
                if isinstance(block, list) and stmt in block:
                    for later in block[block.index(stmt) + 1:]:
                        self.mark(later)

    def _compute(self) -> None:
        for n in ast.walk(self.tree):
            if _TRY_NODES and isinstance(n, _TRY_NODES) and _try_catches(n, GUARD_EXCEPTIONS):
                self.mark(n)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in n.decorator_list:
                    text = ast.unparse(d).lower()
                    if any(w in text for w in _DECORATOR_WORDS):
                        self.mark(n)
                        break
            if isinstance(n, (ast.If, ast.While, ast.IfExp, ast.Assert)) and self.guardish(n.test):
                self._apply(n)
            elif isinstance(n, ast.BoolOp) and any(self.guardish(v) for v in n.values):
                self._apply(n)
            elif hasattr(ast, "Match") and isinstance(n, ast.Match):
                if self.guardish(n.subject) or any(c.guard is not None and self.guardish(c.guard) for c in n.cases):
                    self._apply(n)


def _call_name(func) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _decode(data: bytes) -> str:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)


def extract(path: str, data: bytes) -> FileAnalysis:
    if len(data) > MAX_BYTES:
        return FileAnalysis(path, "too_large", notes=[f"file larger than {MAX_BYTES} bytes"])
    try:
        source = _decode(data)
    except (UnicodeDecodeError, LookupError, SyntaxError, ValueError) as e:
        return FileAnalysis(path, "unreadable", notes=[f"cannot decode: {type(e).__name__}"])
    try:
        tree = ast.parse(source, filename=path)
        return _Extractor(path, tree).run()
    except (SyntaxError, ValueError) as e:
        return FileAnalysis(path, "syntax_error", notes=[f"{type(e).__name__}: {e}"[:200]])
    except (RecursionError, MemoryError) as e:
        return FileAnalysis(path, "syntax_error", notes=[f"{type(e).__name__} while parsing"])


class _Extractor:
    def __init__(self, path: str, tree: ast.Module):
        self.path = path
        self.tree = tree
        self.parents: dict[int, ast.AST] = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parents[id(c)] = n

    def run(self) -> FileAnalysis:
        b = _Builder(self.path)
        b.build(self.tree)
        guards = _Guards(self.tree, self.parents)
        self.guards = guards

        string_tokens = set()
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                string_tokens.update(_TOKEN_RE.findall(n.value))

        refs: list[Reference] = []
        for ref, node in b.import_refs:
            refs.append(_replace(ref, guard=id(node) in guards.guarded))

        # Root objects of getattr/hasattr, per enclosing function (None = module-level code).
        guarded_roots: set[tuple[int, str, int | None]] = set()
        poisoned: set[tuple[int, str]] = set()
        assigned: dict[tuple[int, str], set[tuple[str, ...]]] = {}
        pending: list[tuple[Reference, tuple[int, str], tuple[str, ...], ast.Name]] = []

        for name_node, scope in b.name_loads:
            s = _lookup(scope, name_node.id)
            if s is None:
                continue
            key = (id(s), name_node.id)
            imp = _trusted_import(s, name_node.id)
            inst = None if imp is not None else self._instance(s, name_node.id)
            if imp is None and inst is None:
                continue
            attrs, top, store = self._climb(name_node)
            fn = guards.enclosing_function(name_node)
            parent = self.parents.get(id(top))
            if store is not None:
                assigned.setdefault(key, set()).add(tuple(a.attr for a in attrs) + (store.attr,))
            if not attrs:
                if store is None:
                    self._bare_use(name_node, parent, key, fn, poisoned, guarded_roots, imp is not None)
                if imp is not None and isinstance(parent, ast.Call) and parent.func is name_node:
                    ref = self._import_ref(imp, (), parent, name_node, guards)
                    pending.append((ref, key, (), name_node))
                    inline = self._inline_instance(ref, parent, name_node, guards)
                    if inline is not None:
                        pending.append((inline, key, (), name_node))
                continue
            if any(a.attr == "__dict__" for a in attrs):
                poisoned.add(key)
            call = parent if isinstance(parent, ast.Call) and parent.func is top else None
            rel = tuple(a.attr for a in attrs)
            if imp is not None:
                ref = self._import_ref(imp, attrs, call, name_node, guards)
                pending.append((ref, key, rel, name_node))
                if call is not None:
                    inline = self._inline_instance(ref, call, name_node, guards)
                    if inline is not None:
                        pending.append((inline, key, rel, name_node))
            else:
                ref = self._instance_ref(inst, attrs[0], name_node, guards)
                pending.append((ref, key, rel[:1], name_node))

        for ref, key, rel, name_node in pending:
            fn = guards.enclosing_function(name_node)
            if (key[0], key[1], id(fn) if fn is not None else None) in guarded_roots:
                ref = _replace(ref, guard=True)
            if key in poisoned:
                ref = _replace(ref, skip_reason="assigned_in_file")
            elif any(rel[:len(p)] == p for p in assigned.get(key, ())):
                ref = _replace(ref, skip_reason="assigned_in_file")
            refs.append(ref)

        return FileAnalysis(self.path, "analysed", references=refs, string_tokens=frozenset(string_tokens),
                            imported_tops=tuple(dict.fromkeys(b.imported_tops)))

    # -- pieces -----------------------------------------------------------------------------
    def _climb(self, name_node):
        attrs, node = [], name_node
        while True:
            p = self.parents.get(id(node))
            if isinstance(p, ast.Attribute) and p.value is node:
                if not isinstance(p.ctx, ast.Load):
                    return attrs, node, p
                attrs.append(p)
                node = p
                continue
            return attrs, node, None

    def _bare_use(self, name_node, parent, key, fn, poisoned, guarded_roots, is_import) -> None:
        if isinstance(parent, ast.Call) and name_node in parent.args:
            fname = parent.func.id if isinstance(parent.func, ast.Name) else None
            if fname in ("hasattr", "getattr") and parent.args and parent.args[0] is name_node:
                guarded_roots.add((key[0], key[1], id(fn) if fn is not None else None))
                return
            if fname in _POISON_CALLS:
                poisoned.add(key)
                return
            if fname in _READ_ONLY_CONSUMERS:
                return
        if isinstance(parent, ast.Call) and parent.func is name_node:
            return
        if isinstance(parent, (ast.Compare, ast.Expr)) or self._in_annotation(name_node):
            return
        if isinstance(parent, ast.Tuple):
            gp = self.parents.get(id(parent))
            if isinstance(gp, ast.Call) and isinstance(gp.func, ast.Name) and gp.func.id in _READ_ONLY_CONSUMERS:
                return
        if is_import:
            poisoned.add(key)

    def _in_annotation(self, node) -> bool:
        child, p = node, self.parents.get(id(node))
        while p is not None and not isinstance(p, ast.stmt):
            if isinstance(p, ast.arg) and p.annotation is child:
                return True
            child, p = p, self.parents.get(id(p))
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)) and p.returns is child:
            return True
        if isinstance(p, ast.AnnAssign) and p.annotation is child:
            return True
        return False

    def _guard_for(self, name_node, guards: _Guards) -> bool:
        return id(name_node) in guards.guarded

    def _kwargs(self, call):
        if call is None:
            return (), False
        kws = tuple(KwargUse(k.arg, _loc(k)) for k in call.keywords if k.arg is not None)
        star = any(k.arg is None for k in call.keywords)
        return kws, star

    def _import_ref(self, imp: _Binding, attrs, call, name_node, guards) -> Reference:
        kws, star = self._kwargs(call)
        return Reference(
            file=self.path, module=imp.module, path=imp.path + tuple(a.attr for a in attrs),
            path_locs=(imp.alias_loc,) * len(imp.path) + tuple(_attr_loc(a) for a in attrs),
            module_loc=imp.alias_loc, module_as_written=imp.module_as_written, kwargs=kws,
            is_call=call is not None, caller_star_kwargs=star, guard=self._guard_for(name_node, guards),
            optional_import=imp.optional, owned=1 + len(imp.path))

    def _inline_instance(self, ctor: Reference, call: ast.Call, name_node, guards) -> Reference | None:
        p = self.parents.get(id(call))
        if not (isinstance(p, ast.Attribute) and p.value is call and isinstance(p.ctx, ast.Load)):
            return None
        gp = self.parents.get(id(p))
        icall = gp if isinstance(gp, ast.Call) and gp.func is p else None
        kws, star = self._kwargs(icall)
        return _replace(ctor, instance_attr=p.attr, instance_loc=_attr_loc(p), kwargs=kws,
                        is_call=icall is not None, caller_star_kwargs=star,
                        owned=1 + len(ctor.path))

    def _instance(self, scope: _Scope, name: str):
        """§4.3: x has exactly one binding, a direct-child `x = <chain>(...)` on a trusted import."""
        bs = scope.bindings.get(name) or []
        if len(bs) != 1 or bs[0].kind != "other" or bs[0].ctor_call is None:
            return None
        func = bs[0].ctor_call.func
        attrs = []
        while isinstance(func, ast.Attribute):
            attrs.append(func)
            func = func.value
        if not isinstance(func, ast.Name):
            return None
        root_scope = _lookup(scope, func.id)
        imp = _trusted_import(root_scope, func.id) if root_scope is not None else None
        if imp is None:
            return None
        attrs.reverse()
        return imp, attrs

    def _instance_ref(self, inst, attr: ast.Attribute, name_node, guards) -> Reference:
        imp, ctor_attrs = inst
        p = self.parents.get(id(attr))
        call = p if isinstance(p, ast.Call) and p.func is attr else None
        kws, star = self._kwargs(call)
        path = imp.path + tuple(a.attr for a in ctor_attrs)
        return Reference(
            file=self.path, module=imp.module, path=path,
            path_locs=(imp.alias_loc,) * len(imp.path) + tuple(_attr_loc(a) for a in ctor_attrs),
            module_loc=imp.alias_loc, module_as_written=imp.module_as_written,
            instance_attr=attr.attr, instance_loc=_attr_loc(attr), kwargs=kws, is_call=call is not None,
            caller_star_kwargs=star, guard=self._guard_for(name_node, guards),
            optional_import=imp.optional, owned=1 + len(path))


def _replace(ref: Reference, **kw) -> Reference:
    from dataclasses import replace
    return replace(ref, **kw)
