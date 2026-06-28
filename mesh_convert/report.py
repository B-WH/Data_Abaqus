import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ConversionReport:
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    element_counts: dict[str, int] = field(default_factory=dict)
    node_count: int = 0
    degraded: bool = False
    input_path: str | None = None
    output_path: str | None = None
    dim: str | None = None
    target: str | None = None
    status: str = "pending"

    def add_warning(self, message):
        self.warnings.append(str(message))

    def add_diagnostic(self, message):
        self.diagnostics.append(str(message))

    def to_dict(self):
        return {
            "status": self.status,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "dim": self.dim,
            "target": self.target,
            "degraded": self.degraded,
            "node_count": self.node_count,
            "element_counts": dict(sorted(self.element_counts.items())),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def write_json(self, path):
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
