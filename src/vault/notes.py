"""Parse one note: properties (YAML front matter), wikilinks, embeds, tags and a content hash."""

import datetime
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

MAX_FRONT_MATTER_CHARS = 20000
MAX_YAML_DEPTH = 12
_ALIAS = re.compile(  # YAML anchors and aliases
    r"(?:^|:\s+|-\s+|[\[,{]\s*)[&*][A-Za-z0-9_-]+", re.MULTILINE
)
FORBIDDEN_NAME_CHARS = '#|^:%[]\\/"<>?*'  # characters that break links or file names
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
_WIKILINK = re.compile(r"(!?)\[\[([^\[\]|#^]*)(?:#([^\[\]|]*))?(?:\|([^\[\]]*))?\]\]")
_TAG = re.compile(r"(?<![\w#/&])#([A-Za-z][\w/-]*)")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+\.md)(?:#[^)]*)?\)")
_BLOCK_ID = re.compile(r"(?:^|\s)\^([A-Za-z0-9-]+)\s*$", re.MULTILINE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Link:
    target: str  # note name or path as written, without heading or alias
    heading: str = ""
    alias: str = ""
    embed: bool = False
    source: str = "body"  # body | property
    prop: str = ""  # property name when the link sits in a property


@dataclass
class Note:
    path: str  # vault-relative, forward slashes
    title: str  # file stem; the note's name in links
    props: Dict[str, Any] = field(default_factory=dict)
    body: str = ""
    links: List[Link] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)
    headings: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)  # block ids (`^id`) defined in the body
    sha256: str = ""
    errors: List[str] = field(default_factory=list)

    def prop_list(self, name: str) -> List[str]:
        value = self.props.get(name)
        if value is None:
            return []
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    """Return (yaml text or None, body). Front matter must open on the first line."""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]).lstrip("\n")
    return None, text


def _strip_code(text: str) -> str:
    text = _COMMENT.sub(" ", text)
    text = _FENCE.sub(" ", text)
    return _INLINE_CODE.sub(" ", text)


def wikilinks(text: str, source: str = "body", prop: str = "") -> List[Link]:
    found = []
    for embed, target, heading, alias in _WIKILINK.findall(text):
        target = target.strip()
        if target or heading:
            found.append(
                Link(target, heading.strip(), (alias or "").strip(), bool(embed), source, prop)
            )
    return found


def _property_links(props: Dict[str, Any]) -> List[Link]:
    found: List[Link] = []
    for name, value in props.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str):
                found += wikilinks(item, "property", str(name))
    return found


def _depth(value: Any, level: int = 0) -> int:
    if level > MAX_YAML_DEPTH:
        return level
    if isinstance(value, dict):
        return max([_depth(v, level + 1) for v in value.values()] or [level + 1])
    if isinstance(value, list):
        return max([_depth(v, level + 1) for v in value] or [level + 1])
    return level


def parse_note(text: str, path: str) -> Note:
    stem = path.rsplit("/", 1)[-1]
    title = stem[:-3] if stem.lower().endswith(".md") else stem
    raw, body = split_front_matter(text)
    props: Dict[str, Any] = {}
    errors: List[str] = []
    loaded: Any = {}
    if raw is not None:
        if len(raw) > MAX_FRONT_MATTER_CHARS:
            loaded, errors = {}, ["properties are too large"]
        elif _ALIAS.search(raw):  # aliases can expand a few bytes into gigabytes
            loaded, errors = {}, ["properties must not use YAML anchors or aliases"]
        else:
            try:
                loaded = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError:
                loaded, errors = {}, ["properties are not valid YAML"]
            if loaded and _depth(loaded) > MAX_YAML_DEPTH:
                loaded, errors = {}, ["properties are nested too deeply"]
        if isinstance(loaded, dict):
            props = {str(k): v for k, v in loaded.items()}
        else:
            errors.append("properties must be a mapping")
    clean = _strip_code(body)
    links = _property_links(props) + wikilinks(clean)
    links += [Link(m.removesuffix(".md").rsplit("/", 1)[-1]) for m in _MD_LINK.findall(clean)]
    tags = {t for t in _TAG.findall(clean)}
    raw_tags = props.get("tags", [])
    for t in raw_tags if isinstance(raw_tags, list) else [raw_tags]:
        if isinstance(t, str) and t:
            tags.add(t.lstrip("#"))
    return Note(
        path=path,
        title=title,
        props=props,
        body=body,
        links=links,
        tags=tags,
        headings=[h[1] for h in _HEADING.findall(_strip_code(body))],
        blocks=sorted(set(_BLOCK_ID.findall(clean))),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        errors=errors,
    )


def link_name(value: str) -> str:
    """The note name inside a `[[...]]` property value (or the value itself)."""
    found = wikilinks(value)
    return found[0].target if found else value.strip()


def wikilink(title: str) -> str:
    return f"[[{title}]]"


def _encode(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.datetime.fromisoformat(value["__datetime__"])
        if set(value) == {"__date__"}:
            return datetime.date.fromisoformat(value["__date__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def note_to_dict(note: Note) -> Dict[str, Any]:
    """A JSON-safe form of a parsed note (for the disposable index cache)."""
    return {
        "path": note.path,
        "title": note.title,
        "props": _encode(note.props),
        "body": note.body,
        "links": [[k.target, k.heading, k.alias, k.embed, k.source, k.prop] for k in note.links],
        "tags": sorted(note.tags),
        "headings": note.headings,
        "blocks": note.blocks,
        "sha256": note.sha256,
        "errors": note.errors,
    }


def note_from_dict(data: Dict[str, Any]) -> Note:
    return Note(
        path=data["path"],
        title=data["title"],
        props=_decode(data["props"]),
        body=data["body"],
        links=[Link(*row) for row in data["links"]],
        tags=set(data["tags"]),
        headings=list(data["headings"]),
        blocks=list(data.get("blocks", [])),
        sha256=data["sha256"],
        errors=list(data["errors"]),
    )
