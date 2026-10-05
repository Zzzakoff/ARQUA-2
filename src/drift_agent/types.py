from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


@dataclass
class FieldSchema:
    name: str
    type: str
    format: Optional[str] = None
    required: bool = False
    nullable: bool = False
    items: Optional["FieldSchema"] = None
    properties: Optional[Dict[str, "FieldSchema"]] = None
    enum: Optional[List[Any]] = None
    description: Optional[str] = None
    analysis_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParameterSchema:
    name: str
    location: Literal["path", "query", "header", "cookie"]
    required: bool
    schema: FieldSchema

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RequestBodySchema:
    required: bool
    content_type: str
    schema: FieldSchema

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResponseSchema:
    status_code: str
    content_type: Optional[str]
    schema: Optional[FieldSchema]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EndpointContract:
    method: str
    path: str
    parameters: List[ParameterSchema] = field(default_factory=list)
    request_body: Optional[RequestBodySchema] = None
    responses: Dict[str, ResponseSchema] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    analysis_notes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedContract:
    endpoints: Dict[str, EndpointContract]
    source: Literal["spec", "code"]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DriftCategory(Enum):
    MISSING_ENDPOINT = "missing_endpoint"
    GHOST_ENDPOINT = "ghost_endpoint"
    ADDITIVE_DRIFT = "additive_drift"
    DESTRUCTIVE_DRIFT = "destructive_drift"
    TYPE_DRIFT = "type_drift"
    NULLABILITY_DRIFT = "nullability_drift"
    REQUIRED_DRIFT = "required_drift"
    STATUS_CODE_DRIFT = "status_code_drift"
    PARAMETER_DRIFT = "parameter_drift"
    ANALYSIS_LIMITATION = "analysis_limitation"


@dataclass
class DriftItem:
    id: str
    endpoint: str
    category: DriftCategory
    location: str
    detail: str
    spec_evidence: Optional[str]
    code_evidence: Optional[str]
    severity: Literal["error", "warning", "info"]
    schema_version: str = "1.1"
    source_kind: str = "static"
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    requires_review: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["category"] = self.category.value
        return payload


@dataclass
class PatchSpec:
    target: Literal["spec", "code"]
    patch_type: str
    location: str
    content: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentFinding:
    drift_item: DriftItem
    source_of_truth: Literal["CODE", "SPEC", "AMBIGUOUS"]
    confidence: Literal["high", "medium", "low"]
    reasoning: str
    evidence: List[Dict[str, Any]]
    patch: Optional[PatchSpec]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["drift_item"]["category"] = self.drift_item.category.value
        return payload


@dataclass
class PatchReport:
    spec_patches_applied: int
    code_patches_applied: int
    ambiguous_count: int
    patch_conflicts: int
    output_dir: str
    files_written: List[str]
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

