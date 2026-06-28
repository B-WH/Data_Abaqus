from collections import defaultdict

from .config import DimMode, ElementTarget, resolve_element_type
from .errors import MeshConversionError, MeshGenerationError
from .geometry_classify import classify_geometry
from .geometry_import import import_geometry
from .inp_writer import ElementBlock, MeshData
from .report import ConversionReport


GMSH_TO_ABAQUS = {
    2: ("S3", 3),
    3: ("S4R", 4),
    4: ("C3D4", 4),
    5: ("C3D8R", 8),
    6: ("C3D6", 6),
    7: ("C3D5", 5),
}


def convert(config, gmsh_module):
    report = ConversionReport(
        input_path=config.input_path,
        output_path=config.output_path,
        target=config.target.value,
    )
    gmsh = gmsh_module
    try:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        import_geometry(gmsh, config.input_path, report)
        geometry = classify_geometry(gmsh, config.dim, report)
        _prepare_physical_groups(gmsh, geometry, report)
        _configure_mesh_options(gmsh, config, geometry, report)
        gmsh.model.mesh.generate(3 if geometry.dim == DimMode.THREE_D else 2)
        mesh_data = extract_mesh_data(gmsh, config, geometry, report)
        enforce_target_policy(config_for_dim(config, geometry.dim), report.element_counts, report)
        mesh_data.metadata.update(
            {
                "input": config.input_path,
                "dimension": geometry.dim.value,
                "target": config.target.value,
                "size": config.size,
                "degraded": report.degraded,
                "element_counts": dict(sorted(report.element_counts.items())),
            }
        )
        report.status = "ok"
        return mesh_data, report
    except MeshConversionError:
        report.status = "failed"
        raise
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


def config_for_dim(config, dim):
    if config.dim == dim:
        return config
    return type(config)(
        input_path=config.input_path,
        output_path=config.output_path,
        dim=dim,
        target=config.target,
        size=config.size,
        order=config.order,
        allow_degrade=config.allow_degrade,
        element_type=config.element_type,
        log_path=config.log_path,
        report_path=config.report_path,
    )


def enforce_target_policy(config, element_counts, report):
    names = set(element_counts)
    if config.dim == DimMode.TWO_D:
        target = ElementTarget.QUAD if config.target == ElementTarget.HEX else config.target
        if config.target == ElementTarget.HEX:
            report.add_warning("2D geometry requested target hex; treating target as quad.")
        if target == ElementTarget.QUAD and any(name == "S3" for name in names):
            _degrade_or_fail(config, report, "2D quad target produced triangular elements.")
    elif config.dim == DimMode.THREE_D and config.target == ElementTarget.HEX:
        non_hex = names - {"C3D8", "C3D8R"}
        if non_hex:
            _degrade_or_fail(
                config,
                report,
                "3D hex target produced non-hex element types: {}".format(
                    ", ".join(sorted(non_hex))
                ),
            )


def _degrade_or_fail(config, report, message):
    if not config.allow_degrade:
        raise MeshGenerationError(
            "{} Use --allow-degrade to write an explained mixed mesh.".format(message)
        )
    report.degraded = True
    report.add_warning(message + " Writing explained mixed mesh because --allow-degrade is set.")


def _configure_mesh_options(gmsh, config, geometry, report):
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", config.size)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", config.size)
    gmsh.option.setNumber("Mesh.ElementOrder", config.order)
    if geometry.dim == DimMode.TWO_D:
        gmsh.option.setNumber("Mesh.RecombineAll", 1)
        gmsh.option.setNumber("Mesh.Algorithm", 8)
        for surface in geometry.surfaces:
            gmsh.model.mesh.setRecombine(surface[0], surface[1])
        report.add_diagnostic("Configured 2D recombination for quadrilateral preference.")
    elif config.target in (ElementTarget.HEX, ElementTarget.MIXED):
        gmsh.option.setNumber("Mesh.RecombineAll", 1)
        try:
            gmsh.option.setNumber("Mesh.Recombine3DAll", 1)
        except Exception:
            report.add_warning("Gmsh Recombine3DAll option is unavailable in this build.")
        _try_transfinite_for_simple_entities(gmsh, geometry, report)


def _try_transfinite_for_simple_entities(gmsh, geometry, report):
    for curve in geometry.curves:
        try:
            gmsh.model.mesh.setTransfiniteCurve(curve[1], 2)
        except Exception:
            pass
    for surface in geometry.surfaces:
        try:
            gmsh.model.mesh.setTransfiniteSurface(surface[1])
            gmsh.model.mesh.setRecombine(surface[0], surface[1])
        except Exception:
            pass
    for volume in geometry.volumes:
        try:
            gmsh.model.mesh.setTransfiniteVolume(volume[1])
        except Exception:
            pass
    report.add_diagnostic(
        "Attempted transfinite/recombine setup for structured or sweepable geometry."
    )


def _prepare_physical_groups(gmsh, geometry, report):
    try:
        existing = gmsh.model.getPhysicalGroups()
    except Exception:
        existing = []
    if existing:
        report.add_diagnostic("Preserving {} existing physical groups.".format(len(existing)))
        return
    if geometry.dim == DimMode.THREE_D:
        for _, tag in geometry.volumes:
            group = gmsh.model.addPhysicalGroup(3, [tag])
            gmsh.model.setPhysicalName(3, group, "VOL_{}".format(tag))
    else:
        for _, tag in geometry.surfaces:
            group = gmsh.model.addPhysicalGroup(2, [tag])
            gmsh.model.setPhysicalName(2, group, "SURF_{}".format(tag))
    report.add_diagnostic("Created default physical groups for imported geometry.")


def extract_mesh_data(gmsh, config, geometry, report):
    node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
    nodes = {}
    for index, node_tag in enumerate(node_tags):
        base = index * 3
        nodes[int(node_tag)] = (
            float(coordinates[base]),
            float(coordinates[base + 1]),
            float(coordinates[base + 2]),
        )

    requested_type = resolve_element_type(geometry.dim, config.element_type)
    block_elements = defaultdict(dict)
    element_sets = defaultdict(list)
    entity_dim = 3 if geometry.dim == DimMode.THREE_D else 2

    for dim, tag in gmsh.model.getEntities(entity_dim):
        types, element_tags, node_tags_by_type = gmsh.model.mesh.getElements(dim, tag)
        set_name = _entity_set_name(gmsh, dim, tag)
        for gmsh_type, tags, flat_nodes in zip(types, element_tags, node_tags_by_type):
            abaqus_type, node_count = _abaqus_type_for(gmsh_type, requested_type, geometry.dim)
            for offset, element_id in enumerate(tags):
                start = offset * node_count
                connectivity = tuple(int(value) for value in flat_nodes[start : start + node_count])
                element_id = int(element_id)
                block_elements[(abaqus_type, set_name)][element_id] = connectivity
                element_sets[set_name].append(element_id)
                report.element_counts[abaqus_type] = report.element_counts.get(abaqus_type, 0) + 1

    if not block_elements:
        raise MeshGenerationError("Gmsh generated no supported elements for INP output.")

    element_blocks = [
        ElementBlock(element_type=element_type, elements=elements, elset_name=set_name)
        for (element_type, set_name), elements in sorted(block_elements.items())
    ]
    report.node_count = len(nodes)
    return MeshData(
        nodes=nodes,
        element_blocks=element_blocks,
        node_sets={"ALLNODES": sorted(nodes)},
        element_sets={name: values for name, values in element_sets.items()},
        metadata={},
    )


def _abaqus_type_for(gmsh_type, requested_type, dim):
    if gmsh_type not in GMSH_TO_ABAQUS:
        raise MeshGenerationError("Unsupported Gmsh element type {}.".format(gmsh_type))
    default_type, node_count = GMSH_TO_ABAQUS[gmsh_type]
    if dim == DimMode.THREE_D and default_type in {"C3D8", "C3D8R"}:
        return requested_type, node_count
    if dim == DimMode.TWO_D and default_type in {"S4", "S4R"}:
        return requested_type, node_count
    return default_type, node_count


def _entity_set_name(gmsh, dim, tag):
    try:
        groups = gmsh.model.getPhysicalGroupsForEntity(dim, tag)
    except Exception:
        groups = []
    for group in groups:
        try:
            name = gmsh.model.getPhysicalName(dim, group)
        except Exception:
            name = ""
        if name:
            return name
    prefix = "VOL" if dim == 3 else "SURF"
    return "{}_{}".format(prefix, tag)
