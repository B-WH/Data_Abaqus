import argparse
from dataclasses import dataclass
from enum import Enum

from .errors import MeshConversionError


class DimMode(str, Enum):
    AUTO = "auto"
    TWO_D = "2d"
    THREE_D = "3d"


class ElementTarget(str, Enum):
    HEX = "hex"
    QUAD = "quad"
    MIXED = "mixed"


VALID_3D_ELEMENT_TYPES = {"C3D8", "C3D8R"}
VALID_2D_ELEMENT_TYPES = {"S4", "S4R"}


@dataclass
class MeshConfig:
    input_path: str
    output_path: str
    dim: DimMode = DimMode.AUTO
    target: ElementTarget = ElementTarget.HEX
    size: float = 1.0
    order: int = 1
    allow_degrade: bool = False
    element_type: str | None = None
    log_path: str | None = None
    report_path: str | None = None


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mesh_convert",
        description="Convert STEP/STP or recognized STEP-like INS geometry to Abaqus INP meshes.",
    )
    parser.add_argument("input_path", help="Input .stp, .step, or STEP-like .ins file.")
    parser.add_argument("output_path", help="Output Abaqus .inp file.")
    parser.add_argument("--size", type=float, default=1.0, help="Global mesh seed size.")
    parser.add_argument(
        "--dim",
        choices=[item.value for item in DimMode],
        default=DimMode.AUTO.value,
        help="Dimension mode: auto, 2d, or 3d.",
    )
    parser.add_argument(
        "--target",
        choices=[item.value for item in ElementTarget],
        default=ElementTarget.HEX.value,
        help="Preferred element family: hex, quad, or mixed.",
    )
    parser.add_argument(
        "--order",
        type=int,
        choices=[1, 2],
        default=1,
        help="Mesh order. Only first-order output is currently supported.",
    )
    parser.add_argument(
        "--element-type",
        default=None,
        help="Preferred Abaqus element type, e.g. C3D8, C3D8R, S4, or S4R.",
    )
    degrade_group = parser.add_mutually_exclusive_group()
    degrade_group.add_argument(
        "--allow-degrade",
        dest="allow_degrade",
        action="store_true",
        help="Allow explained fallback to mixed elements.",
    )
    degrade_group.add_argument(
        "--no-allow-degrade",
        dest="allow_degrade",
        action="store_false",
        help="Fail if preferred element family cannot be generated.",
    )
    parser.set_defaults(allow_degrade=False)
    parser.add_argument("--log", dest="log_path", default=None, help="Optional log file path.")
    parser.add_argument(
        "--report",
        dest="report_path",
        default=None,
        help="Optional JSON conversion report path.",
    )
    return parser


def config_from_args(args):
    config = MeshConfig(
        input_path=args.input_path,
        output_path=args.output_path,
        dim=DimMode(args.dim),
        target=ElementTarget(args.target),
        size=args.size,
        order=args.order,
        allow_degrade=args.allow_degrade,
        element_type=args.element_type,
        log_path=args.log_path,
        report_path=args.report_path,
    )
    validate_config(config)
    return config


def validate_config(config):
    if config.size <= 0:
        raise MeshConversionError("--size must be greater than zero.")
    if config.order != 1:
        raise MeshConversionError("Only first-order meshes are currently supported.")
    if config.element_type is not None:
        normalized = config.element_type.upper()
        if normalized not in VALID_3D_ELEMENT_TYPES | VALID_2D_ELEMENT_TYPES:
            raise MeshConversionError(
                "--element-type must be one of C3D8, C3D8R, S4, or S4R."
            )
        config.element_type = normalized
    return config


def resolve_element_type(dim, requested):
    if requested:
        requested = requested.upper()
        if dim == DimMode.THREE_D and requested not in VALID_3D_ELEMENT_TYPES:
            raise MeshConversionError("3D meshes require C3D8 or C3D8R element output.")
        if dim == DimMode.TWO_D and requested not in VALID_2D_ELEMENT_TYPES:
            raise MeshConversionError("2D meshes require S4 or S4R element output.")
        return requested
    if dim == DimMode.THREE_D:
        return "C3D8R"
    if dim == DimMode.TWO_D:
        return "S4R"
    raise MeshConversionError("Element type cannot be resolved before dimension classification.")
