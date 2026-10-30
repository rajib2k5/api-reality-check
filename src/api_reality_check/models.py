"""Shared types (DESIGN.md §3, amended by §14)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["module", "attribute", "kwarg"]
Verdict = Literal["MISSING", "SUSPECT", "UNKNOWN"]

# Reason codes (§4.6 + §14). MISSING reasons are the only ones that may produce a MISSING verdict.
MISSING_REASONS = frozenset({"not_installed", "not_found", "not_in_signature", "positional_only"})
SUSPECT_REASONS = frozenset({"untrusted_signature", "instance_attr_not_on_class", "star_kwargs_call",
                             "instance_may_shadow"})
# The only reasons the probe may send, per status (F3). Anything else in a probe record is a protocol error.
PROBE_REASONS = {
    "ok": frozenset({None}),
    "missing": MISSING_REASONS,
    "suspect": frozenset({"untrusted_signature", "instance_attr_not_on_class", "instance_may_shadow"}),
    "unknown": frozenset({"invalid_name", "denied", "origin_outside_env", "pth_configured", "import_error",
                          "dynamic_getattr", "not_a_class", "instance_data_attr", "descriptor_callable",
                          "no_signature", "var_keyword", "wrapper_varkw", "optional_dep_outside_env"}),
}


@dataclass(frozen=True)
class Loc:
    line: int  # 1-based
    col: int   # 0-based


@dataclass(frozen=True)
class KwargUse:
    name: str
    loc: Loc


@dataclass(frozen=True)
class Reference:
    file: str
    module: str                    # importable dotted module ("numpy", "xml.etree")
    path: tuple[str, ...]          # attribute chain walked from the module
    path_locs: tuple[Loc, ...]     # one Loc per path element
    module_loc: Loc
    module_as_written: str         # dotted module as written in the import statement
    instance_attr: str | None = None
    instance_loc: Loc | None = None
    kwargs: tuple[KwargUse, ...] = ()
    is_call: bool = False
    caller_star_kwargs: bool = False
    guard: bool = False
    optional_import: bool = False
    # Elements [module] + path[:owned-1] are checked by the import reference that created the
    # binding; failures there are reported by that reference, not this one.
    owned: int = 0
    # Set when the parent decides not to query at all (local_module, relative_import, ...).
    skip_reason: str | None = None

    def elements(self) -> tuple[str, ...]:
        tail = (self.instance_attr,) if self.instance_attr is not None else ()
        return (self.module,) + self.path + tail

    def element_loc(self, index: int) -> Loc:
        if index == 0:
            return self.module_loc
        if index <= len(self.path):
            return self.path_locs[index - 1]
        return self.instance_loc or self.module_loc


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    col: int
    verdict: Verdict
    kind: Kind
    name: str
    qualname: str
    reason: str
    suggestions: tuple[str, ...] = ()
    hint: str | None = None
    dist: str | None = None
    dist_version: str | None = None

    def to_json(self) -> dict:
        return {
            "file": self.file, "line": self.line, "col": self.col, "verdict": self.verdict,
            "kind": self.kind, "name": self.name, "qualname": self.qualname, "reason": self.reason,
            "suggestions": list(self.suggestions), "hint": self.hint, "dist": self.dist,
            "dist_version": self.dist_version,
        }


@dataclass
class FileAnalysis:
    path: str
    status: Literal["analysed", "syntax_error", "too_large", "unreadable", "timeout"]
    references: list[Reference] = field(default_factory=list)
    skipped_local: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    # Identifier-like tokens found in any string literal in the file (§14 A3 file-wide rule).
    string_tokens: frozenset[str] = frozenset()
    # Top-level modules the file imports (cross-module suggestions, §4.4 step 6).
    imported_tops: tuple[str, ...] = ()
