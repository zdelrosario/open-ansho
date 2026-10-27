"""Merging another project into the open one.

Like `reporting`, this works on plain `sqlite3.Connection`s with no Qt, so the
merge dialog only has to collect the user's choices and tests can drive the
whole thing directly.

The merge has three parts:

- **Codes** are matched across the two codebooks by name (by full path first,
  so a name used under two different parents still pairs up correctly). A
  matched pair whose parent or description differ is a *conflict*, and the
  caller picks which side's version survives; codes only in the other project
  are added.
- **Documents** are matched by name *and* content. Offsets only mean the same
  thing over the same text, so a same-named document whose text differs is
  added as a separate, renamed document rather than merged.
- **Segments** are the superset of both projects': every segment of the other
  project is copied over unless the open project already has the identical
  one (same document, code, range and coder), keeping its coder, memo and
  creation time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from openansho import db
from openansho.db import Code
from openansho.reporting import code_path


class MergeError(ValueError):
    """The chosen code versions can't be combined into one codebook."""


@dataclass(frozen=True)
class CodeMatch:
    """One code as it appears in either project, or both."""

    current: Code | None
    other: Code | None
    parent_differs: bool = False
    description_differs: bool = False

    @property
    def name(self) -> str:
        return (self.current or self.other).name

    @property
    def is_conflict(self) -> bool:
        return self.parent_differs or self.description_differs


@dataclass(frozen=True)
class MergePlan:
    current_codes: dict[int, Code]
    other_codes: dict[int, Code]
    matches: list[CodeMatch]

    def match_for_current(self, code_id: int) -> CodeMatch | None:
        return next((m for m in self.matches if m.current and m.current.id == code_id), None)

    def match_for_other(self, code_id: int) -> CodeMatch | None:
        return next((m for m in self.matches if m.other and m.other.id == code_id), None)

    @property
    def conflicts(self) -> list[CodeMatch]:
        return [match for match in self.matches if match.is_conflict]


@dataclass(frozen=True)
class MergeResult:
    documents_added: int
    documents_renamed: list[tuple[str, str]]
    codes_added: int
    codes_updated: int
    segments_added: int


def _normalized_description(code: Code) -> str:
    return (code.description or "").strip()


def plan_merge(current: sqlite3.Connection, other: sqlite3.Connection) -> MergePlan:
    """Pair up the two projects' codes and find the conflicting pairs."""
    current_codes = {code.id: code for code in db.list_codes(current)}
    other_codes = {code.id: code for code in db.list_codes(other)}

    other_for_current: dict[int, int] = {}

    # Same full path first: the unambiguous pairs.
    current_by_path: dict[str, list[int]] = {}
    for code_id in current_codes:
        current_by_path.setdefault(code_path(current_codes, code_id), []).append(code_id)
    for other_id in other_codes:
        candidates = current_by_path.get(code_path(other_codes, other_id), [])
        if candidates:
            other_for_current[candidates.pop(0)] = other_id

    # Then the same name under a different parent, where the name is used
    # only once among the codes still unpaired on each side.
    paired_other = set(other_for_current.values())
    unpaired_current: dict[str, list[int]] = {}
    for code_id, code in current_codes.items():
        if code_id not in other_for_current:
            unpaired_current.setdefault(code.name, []).append(code_id)
    unpaired_other: dict[str, list[int]] = {}
    for other_id, code in other_codes.items():
        if other_id not in paired_other:
            unpaired_other.setdefault(code.name, []).append(other_id)
    for name, current_ids in unpaired_current.items():
        other_ids = unpaired_other.get(name, [])
        if len(current_ids) == 1 and len(other_ids) == 1:
            other_for_current[current_ids[0]] = other_ids[0]

    current_for_other = {o: c for c, o in other_for_current.items()}
    matches = []
    for code_id, code in current_codes.items():
        other_id = other_for_current.get(code_id)
        if other_id is None:
            matches.append(CodeMatch(current=code, other=None))
            continue
        other_code = other_codes[other_id]
        # Parents are compared by what they pair up with, not by name: the
        # other parent is "the same" only if it is this parent's counterpart.
        other_parent_counterpart = (
            current_for_other.get(other_code.parent_id, -1)
            if other_code.parent_id is not None
            else None
        )
        matches.append(
            CodeMatch(
                current=code,
                other=other_code,
                parent_differs=other_parent_counterpart != code.parent_id,
                description_differs=(
                    _normalized_description(code) != _normalized_description(other_code)
                ),
            )
        )
    for other_id, code in other_codes.items():
        if other_id not in current_for_other:
            matches.append(CodeMatch(current=None, other=code))
    return MergePlan(current_codes, other_codes, matches)


def _merged_parents(plan: MergePlan, use_other: set[int]) -> dict[tuple, tuple | None]:
    """The parent every code will have after the merge.

    Keys are `("current", id)` for codes already in the open project and
    `("other", id)` for codes the merge adds, since the added ones have no id
    in the open project yet.
    """

    def key_for_other(other_id: int | None) -> tuple | None:
        if other_id is None:
            return None
        match = plan.match_for_other(other_id)
        if match is not None and match.current is not None:
            return ("current", match.current.id)
        return ("other", other_id)

    parents: dict[tuple, tuple | None] = {}
    for match in plan.matches:
        if match.current is None:
            parents[("other", match.other.id)] = key_for_other(match.other.parent_id)
        elif match.other is not None and match.is_conflict and match.other.id in use_other:
            parents[("current", match.current.id)] = key_for_other(match.other.parent_id)
        else:
            parent_id = match.current.parent_id
            parents[("current", match.current.id)] = (
                ("current", parent_id) if parent_id is not None else None
            )
    return parents


@dataclass(frozen=True)
class MergedCode:
    """One code of the codebook a merge would produce.

    `key` is `("current", id)` for a code already in the open project and
    `("other", id)` for one the merge adds; `parent` is a key the same way.
    `source` says whose version it is: "current" or "other".
    """

    key: tuple[str, int]
    name: str
    description: str | None
    parent: tuple[str, int] | None
    source: str


def merged_codebook(plan: MergePlan, use_other: set[int]) -> list[MergedCode]:
    """The codebook `apply_merge` would produce for these choices.

    It doesn't check the choices: a loop shows up as codes whose parents
    never lead back to a root, which a caller can point out.
    """
    parents = _merged_parents(plan, use_other)
    merged = []
    for match in plan.matches:
        if match.current is None:
            key, source, code = ("other", match.other.id), "other", match.other
        else:
            key = ("current", match.current.id)
            chose_other = (
                match.other is not None and match.is_conflict and match.other.id in use_other
            )
            source = "other" if chose_other else "current"
            code = match.other if chose_other else match.current
        merged.append(MergedCode(key, code.name, code.description, parents[key], source))
    return merged


def check_choices(plan: MergePlan, use_other: set[int]) -> None:
    """Raise `MergeError` if the chosen versions would nest codes in a loop.

    `use_other` holds the ids (in the other project) of the conflicting codes
    whose other version was chosen. Mixing versions can make two codes each
    other's ancestor — A under B here, B under A there — which no codebook
    can hold.
    """
    parents = _merged_parents(plan, use_other)
    for start in parents:
        seen = {start}
        node = parents[start]
        while node is not None:
            if node in seen:
                names = sorted(
                    (plan.current_codes if key[0] == "current" else plan.other_codes)[key[1]].name
                    for key in seen
                )
                raise MergeError(
                    "The chosen versions would nest these codes inside each "
                    f"other: {', '.join(names)}. Pick the same project's "
                    "version for all of them."
                )
            seen.add(node)
            node = parents.get(node)


def _unique_document_name(conn: sqlite3.Connection, name: str, label: str) -> str:
    candidate = f"{name} ({label})"
    number = 2
    while db.get_document_by_name(conn, candidate) is not None:
        candidate = f"{name} ({label} {number})"
        number += 1
    return candidate


def apply_merge(
    current: sqlite3.Connection,
    other: sqlite3.Connection,
    plan: MergePlan,
    use_other: set[int],
    other_label: str = "merged",
) -> MergeResult:
    """Merge `other` into `current`, per `plan` and the chosen versions.

    `other_label` tags the name of any document added alongside a same-named
    one with different text. Newly added codes keep the other project's
    colors; callers that maintain a color invariant should re-derive it.
    """
    check_choices(plan, use_other)

    # -- Codes -------------------------------------------------------------
    code_ids: dict[int, int] = {}
    codes_added = 0
    for match in plan.matches:
        if match.other is None:
            continue
        if match.current is not None:
            code_ids[match.other.id] = match.current.id
        else:
            created = db.create_code(
                current,
                match.other.name,
                color=match.other.color,
                color_class=match.other.color_class,
                description=match.other.description,
            )
            code_ids[match.other.id] = created.id
            codes_added += 1

    codes_updated = 0
    for match in plan.matches:
        if match.other is None:
            continue
        chose_other = match.current is None or (
            match.is_conflict and match.other.id in use_other
        )
        if not chose_other:
            continue
        target_id = code_ids[match.other.id]
        parent_id = (
            code_ids[match.other.parent_id] if match.other.parent_id is not None else None
        )
        db.set_code_parent(current, target_id, parent_id)
        if match.current is not None:
            db.set_code_description(current, target_id, match.other.description)
            codes_updated += 1

    # -- Documents -----------------------------------------------------------
    document_ids: dict[int, int] = {}
    documents_added = 0
    documents_renamed: list[tuple[str, str]] = []
    for document in db.list_documents(other):
        existing = db.get_document_by_name(current, document.name)
        if existing is not None and existing.content == document.content:
            document_ids[document.id] = existing.id
            continue
        name = document.name
        if existing is not None:
            name = _unique_document_name(current, document.name, other_label)
            documents_renamed.append((document.name, name))
        created = db.create_document(
            current,
            name,
            document.content,
            kind=document.kind or db.DOCUMENT_KIND_TEXT,
            source_data=document.source_data,
        )
        document_ids[document.id] = created.id
        documents_added += 1
        # The copied text carries the regions' marker characters at the same
        # offsets, so the regions come over unchanged. A matched document's
        # identical text means its regions are already here.
        for region in db.list_regions_for_document(other, document.id):
            db.create_region(
                current,
                created.id,
                region.page,
                region.text_offset,
                region.outline(),
                created_by=region.created_by,
                created_at=region.created_at,
            )

    # -- Segments ------------------------------------------------------------
    existing_segments = {
        (s.document_id, s.code_id, s.start_offset, s.end_offset, s.created_by)
        for s in db.list_all_segments(current)
    }
    segments_added = 0
    for segment in db.list_all_segments(other):
        key = (
            document_ids[segment.document_id],
            code_ids[segment.code_id],
            segment.start_offset,
            segment.end_offset,
            segment.created_by,
        )
        if key in existing_segments:
            continue
        db.create_segment(
            current,
            *key[:4],
            memo=segment.memo,
            created_by=segment.created_by,
            created_at=segment.created_at,
        )
        existing_segments.add(key)
        segments_added += 1

    return MergeResult(
        documents_added=documents_added,
        documents_renamed=documents_renamed,
        codes_added=codes_added,
        codes_updated=codes_updated,
        segments_added=segments_added,
    )
