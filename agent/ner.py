"""
NER (Named Entity Recognition) for automotive KG query rewriting.

Pipeline (from NER.ipynb):
  1. detect_terms()          — fuzzy node label detection from query
  2. align_instances()       — exact/case-insensitive instance matching
  3. instance_value_rewrite()— rewrite query quoting found instances
  4. nodelabelextract()      — map instances → (label, value, attr_type)
  5. extract_entities()      — full pipeline entry point
"""
import re
import json
from pathlib import Path
from fuzzywuzzy import fuzz

# ── Schema data ────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent / "schema" / "data"


def _load_json_safe(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_label_dict: dict = _load_json_safe(_DATA_DIR / "graph_node_name_instances.json")

_raw = _load_json_safe(_DATA_DIR / "node_instances.json")
if isinstance(_raw, list):
    ALL_GRAPH_NODE_INSTANCES: list[str] = list(set(_raw))
elif isinstance(_raw, dict):
    _flat: list[str] = []
    for v in _raw.values():
        if isinstance(v, list):
            _flat.extend(v)
    ALL_GRAPH_NODE_INSTANCES = list(set(_flat))
else:
    ALL_GRAPH_NODE_INSTANCES = []

ALL_NODE_LABELS: list[str] = [
    'ManufacturingPlant', 'AssemblyShop', 'ProductionShop', 'VehicleFamily',
    'VehicleVariant', 'Supplier', 'WorkCellStorageArea', 'InPlantStorageLocation',
    'StorageLocation', 'ProductionOrder', 'ProductionProcess', 'ProductionPlan',
    'Vehicle', 'Personnel', 'OperationalTask', 'PrecisionTool', 'Equipment',
    'MaterialLot', 'Part', 'DiagnosticEquipment', 'ProcessEquipment',
    'RoboticEquipment', 'WorkStepSpec', 'PartSpec', 'EquipmentSpec', 'OperationSpec',
    'Operation', 'WorkStep', 'ProductDocumentSpec', 'ProductDocument',
    'ManualToolSpec', 'ManualTool', 'PrecisionToolSpec', 'DiagnosticEquipmentSpec',
    'DiagnosticEquipmentInstance', 'EquipmentInstance', 'ProcessEquipmentSpec',
    'ProcessEquipmentInstance', 'RoboticEquipmentSpec', 'RoboticEquipmentInstance',
    'MaterialHandlingEquipmentSpec', 'MaterialHandlingEquipment',
    'MaterialHandlingEquipmentInstance', 'ProductionOrderSpec', 'ProductionPlanSpec',
    'PrecisionToolInstance', 'PartInstance',
]

# Synonym map: common natural-language terms → canonical KG label.
# Keys are lowercase; multi-word keys must be checked before single-word ones.
LABEL_SYNONYMS: dict[str, str] = {
    # Vehicle
    "vehicle":              "Vehicle",
    "vehicles":             "Vehicle",
    "car":                  "Vehicle",
    "cars":                 "Vehicle",
    "automobile":           "Vehicle",
    "automobiles":          "Vehicle",
    # ProductionOrder
    "production order":     "ProductionOrder",
    "production orders":    "ProductionOrder",
    "order":                "ProductionOrder",
    "orders":               "ProductionOrder",
    "po":                   "ProductionOrder",
    # ManufacturingPlant
    "manufacturing plant":  "ManufacturingPlant",
    "manufacturing plants": "ManufacturingPlant",
    "plant":                "ManufacturingPlant",
    "plants":               "ManufacturingPlant",
    "factory":              "ManufacturingPlant",
    "factories":            "ManufacturingPlant",
    "facility":             "ManufacturingPlant",
    "facilities":           "ManufacturingPlant",
    # ProductionProcess
    "production process":   "ProductionProcess",
    "production processes": "ProductionProcess",
    "process":              "ProductionProcess",
    "processes":            "ProductionProcess",
    # ProductionPlan
    "production plan":      "ProductionPlan",
    "production plans":     "ProductionPlan",
    "plan":                 "ProductionPlan",
    "plans":                "ProductionPlan",
    # Operation
    "operation":            "Operation",
    "operations":           "Operation",
    "op":                   "Operation",
    "ops":                  "Operation",
    # WorkStep
    "work step":            "WorkStep",
    "work steps":           "WorkStep",
    "step":                 "WorkStep",
    "steps":                "WorkStep",
    # Part
    "part":                 "Part",
    "parts":                "Part",
    "component":            "Part",
    "components":           "Part",
    # Personnel
    "personnel":            "Personnel",
    "worker":               "Personnel",
    "workers":              "Personnel",
    "staff":                "Personnel",
    "employee":             "Personnel",
    "employees":            "Personnel",
    "operator":             "Personnel",
    "operators":            "Personnel",
    # Supplier
    "supplier":             "Supplier",
    "suppliers":            "Supplier",
    "vendor":               "Supplier",
    "vendors":              "Supplier",
    # VehicleFamily
    "vehicle family":       "VehicleFamily",
    "vehicle families":     "VehicleFamily",
    "family":               "VehicleFamily",
    # VehicleVariant
    "vehicle variant":      "VehicleVariant",
    "vehicle variants":     "VehicleVariant",
    "variant":              "VehicleVariant",
    "variants":             "VehicleVariant",
    # AssemblyShop / ProductionShop
    "assembly shop":        "AssemblyShop",
    "production shop":      "ProductionShop",
    "shop":                 "ProductionShop",
    "shops":                "ProductionShop",
    # Equipment
    "equipment":            "Equipment",
    "machine":              "Equipment",
    "machines":             "Equipment",
    "manual tool":          "ManualTool",
    "manual tools":         "ManualTool",
    "tool":                 "ManualTool",
    "tools":                "ManualTool",
    "robotic equipment":    "RoboticEquipment",
    "robot":                "RoboticEquipment",
    "robots":               "RoboticEquipment",
    "diagnostic equipment": "DiagnosticEquipment",
    "process equipment":    "ProcessEquipment",
    "material handling equipment": "MaterialHandlingEquipment",
    # StorageLocation
    "storage location":     "StorageLocation",
    "storage":              "StorageLocation",
    "warehouse":            "StorageLocation",
    # PartInstance
    "part instance":        "PartInstance",
    "material lot":         "MaterialLot",
    "serialized part":      "PartInstance",
}

# TTL (turns alive) for each source type
TTL_UI_CLICK = 5
TTL_NER = 3


# ── Step 1: Node label detection ───────────────────────────────────────────────

def _camel_to_phrase(label: str) -> str:
    parts = re.findall(r"[A-Z][a-z]*|[0-9]+", label)
    return " ".join(p.lower() for p in parts if p)


def _query_ngrams(text: str, n: int) -> list[str]:
    tokens = re.findall(r"\w+(?:-\w+)*", text.lower())
    if n <= 0 or len(tokens) < n:
        return []
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _label_forms(label: str) -> list[str]:
    forms = {label, _camel_to_phrase(label)}
    return [f for f in forms if f]


def _extract_adjacent_identifier_hints(
    nl_query: str,
    label_scores: list[tuple[str, float]],
    existing_pairs: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """
    Fallback for IDs that are not present in node_instances.json.
    Example: "OperationalTask Task011015-A-1-001-01" -> ("OperationalTask", "Task011015-A-1-001-01", "identifier")
    """
    existing = {(lbl, val) for lbl, val, _ in existing_pairs}
    inferred: list[tuple[str, str, str]] = []
    seen_vals: set[tuple[str, str]] = set()
    for label, score in label_scores:
        if score < 0.5:
            continue
        for form in _label_forms(label):
            pattern = re.compile(
                rf"\b{re.escape(form)}\b\s+[\"']?([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+|[A-Za-z]+[0-9][A-Za-z0-9\-]*)[\"']?",
                re.IGNORECASE,
            )
            for m in pattern.finditer(nl_query):
                ident = m.group(1)
                key = (label, ident)
                if key in existing or key in seen_vals:
                    continue
                inferred.append((label, ident, "identifier"))
                seen_vals.add(key)
    return inferred

def detect_terms(nl_query: str, top_k: int = 5, char_threshold: int = 80) -> list[tuple[str, float]]:
    """
    Detect KG node label types mentioned in the query.
    Checks (in order): exact synonym match, exact canonical-label match, fuzzy label match.
    """
    matched: dict[str, float] = {}
    nl_lower = nl_query.lower()

    # Pass 1: synonym map (multi-word before single-word — sort by length desc)
    for synonym, label in sorted(LABEL_SYNONYMS.items(), key=lambda x: -len(x[0])):
        if re.search(r'\b' + re.escape(synonym) + r'\b', nl_lower):
            matched[label] = max(matched.get(label, 0), 1.0)

    # Pass 2: exact / fuzzy match against canonical CamelCase labels
    for entity in ALL_NODE_LABELS:
        e_lower = entity.lower()
        if re.search(r'\b' + re.escape(e_lower) + r'\b', nl_lower):
            score = 1.0
        else:
            label_phrase = _camel_to_phrase(entity)
            label_len = len(label_phrase.split())
            if label_len == 1:
                score = 0.0
                if score > 0:
                    matched[entity] = max(matched.get(entity, 0), score)
                continue
            grams = _query_ngrams(nl_query, label_len)
            best = 0
            for gram in grams:
                best = max(best, fuzz.ratio(label_phrase, gram), fuzz.token_sort_ratio(label_phrase, gram))
            score = best / 100.0 if best >= char_threshold else 0.0
        if score > 0:
            matched[entity] = max(matched.get(entity, 0), score)

    return sorted(matched.items(), key=lambda x: -x[1])[:top_k]


# ── Step 2: Instance alignment ─────────────────────────────────────────────────

def align_instances(nl_query: str) -> list[str]:
    """Extract KG instance identifiers/names from the query string."""
    instances: list[str] = []
    seen: set[str] = set()
    nl_lower = nl_query.lower()
    for entity in sorted(ALL_GRAPH_NODE_INSTANCES, key=len, reverse=True):
        if entity in seen:
            continue
        if entity in nl_query:
            instances.append(entity)
            seen.add(entity)
        elif entity.lower() in nl_lower:
            instances.append(entity)
            seen.add(entity)
        elif "," in entity and entity.lower().replace(",", "") in nl_lower:
            instances.append(entity)
            seen.add(entity)
    return instances


# ── Step 3: Query rewrite ──────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    text = re.sub(r"'s\b", '', text)
    return re.findall(r'\w+(?:-\w+)*', text.lower())


def _find_matches_in_query(nl_query: str, word_list: list[str]) -> list[str]:
    input_tokens = _tokenize(nl_query.replace('"', ''))
    matching: list[str] = []
    matched_positions: set[int] = set()
    seen: set[str] = set()
    for phrase in sorted(word_list, key=len, reverse=True):
        phrase_tokens = _tokenize(phrase)
        plen = len(phrase_tokens)
        for i in range(len(input_tokens) - plen + 1):
            if input_tokens[i:i + plen] == phrase_tokens:
                positions = set(range(i, i + plen))
                if not positions & matched_positions and phrase not in seen:
                    matching.append(phrase)
                    seen.add(phrase)
                    matched_positions.update(positions)
    return matching


def instance_value_rewrite(instances: list[str], nl_query: str) -> tuple[list[str], str]:
    """
    Quote matched instances in the query string.
    Returns (matched_list, rewritten_query).
    """
    matchlist = _find_matches_in_query(nl_query, instances)
    if not matchlist:
        return [], nl_query

    result = nl_query
    for phrase in sorted(matchlist, key=len, reverse=True):
        phrase_tokens = re.findall(r'\w+(?:-\w+)*', phrase.lower())
        if not phrase_tokens:
            continue
        escaped = [re.escape(t) for t in phrase_tokens]
        gap = r'[\s\W]+'
        if phrase.strip().startswith('('):
            pattern = r'(\"?)(\(' + gap.join(escaped) + r')(\"?)(\'s)?'
        else:
            pattern = r'(\"?)\b(' + gap.join(escaped) + r')\b(\"?)(\'s)?'

        result = re.sub(
            pattern,
            lambda m, p=phrase: f'"{p}"{m.group(4) or ""}',
            result,
            flags=re.IGNORECASE,
        )

    result = re.sub(r'\"+', '"', result)
    result = re.sub(r'\s+([.,!?;])', r'\1', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return matchlist, result


# ── Step 4: Map instances → (label, id, attr_type) ────────────────────────────

def nodelabelextract(matchlist: list[str]) -> list[tuple[str, str, str]]:
    """Map matched instance strings to (label, value, attr_type) via label_dict."""
    instance2info: dict[str, tuple[str, str]] = {}
    for label, data in _label_dict.items():
        for name in data.get("names", []):
            instance2info[name] = (label, "name")
        for ident in data.get("ids", []):
            instance2info[ident] = (label, "identifier")
    pairs = []
    for instance in matchlist:
        if instance in instance2info:
            label, attr = instance2info[instance]
            pairs.append((label, instance, attr))
        else:
            pairs.append(("Unknown", instance, "Unknown"))
    return pairs


# ── Full pipeline entry point ──────────────────────────────────────────────────

def extract_entities(nl_query: str) -> dict:
    """
    Run the full NER pipeline on a natural language query.

    Returns:
        {
          "node_labels":         [("Part", 0.95), ...],   # detected KG label types
          "raw_instances":       ["TFA2A-105", ...],       # matched instance strings
          "node_instance_pairs": [("Equipment", "TFA2A-105", "identifier"), ...],
          "rewritten_query":     "Which ... \"TFA2A-105\" ...",
        }
    """
    label_scores = detect_terms(nl_query)
    raw_instances = align_instances(nl_query)
    matchlist, rewritten = instance_value_rewrite(raw_instances, nl_query)
    pairs = nodelabelextract(matchlist)
    pairs.extend(_extract_adjacent_identifier_hints(nl_query, label_scores, pairs))
    return {
        "node_labels":         label_scores,
        "raw_instances":       matchlist,
        "node_instance_pairs": pairs,
        "rewritten_query":     rewritten,
    }
