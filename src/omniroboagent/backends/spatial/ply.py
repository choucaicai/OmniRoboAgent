from pathlib import Path
from struct import Struct
from typing import BinaryIO


_PLY_SCALAR_FORMATS = {
    "char": "b",
    "int8": "b",
    "uchar": "B",
    "uint8": "B",
    "short": "h",
    "int16": "h",
    "ushort": "H",
    "uint16": "H",
    "int": "i",
    "int32": "i",
    "uint": "I",
    "uint32": "I",
    "float": "f",
    "float32": "f",
    "double": "d",
    "float64": "d",
}
_INTEGER_FORMATS = {"b", "B", "h", "H", "i", "I"}


def load_ply_points_colors(
    path: str | Path,
) -> tuple[list[list[float]], list[list[float]] | None]:
    """Read scalar PLY vertices as XYZ and optional RGB(A) arrays."""
    point_cloud_path = Path(path)
    if point_cloud_path.suffix.lower() != ".ply":
        raise ValueError("SpatialLM point-cloud path must end with .ply")
    if not point_cloud_path.is_file():
        raise FileNotFoundError(
            f"SpatialLM point-cloud file does not exist: {point_cloud_path}"
        )

    with point_cloud_path.open("rb") as source:
        (
            ply_format,
            vertex_count,
            vertex_properties,
        ) = _read_vertex_header(source)
        property_indices = {
            name: index for index, (name, _) in enumerate(vertex_properties)
        }
        missing = sorted({"x", "y", "z"} - property_indices.keys())
        if missing:
            raise ValueError(
                "PLY is missing required vertex properties: " + ", ".join(missing)
            )

        color_names = ("red", "green", "blue")
        color_presence = [name in property_indices for name in color_names]
        if any(color_presence) and not all(color_presence):
            raise ValueError("PLY must contain all of red, green, and blue")
        include_colors = all(color_presence)
        if "alpha" in property_indices and not include_colors:
            raise ValueError("PLY alpha requires red, green, and blue properties")

        if ply_format == "binary_little_endian":
            rows = _read_binary_vertices(source, vertex_count, vertex_properties)
        else:
            rows = _read_ascii_vertices(source, vertex_count, vertex_properties)

    if not rows:
        raise ValueError(f"PLY contains no points: {point_cloud_path}")

    points = [
        [
            float(row[property_indices["x"]]),
            float(row[property_indices["y"]]),
            float(row[property_indices["z"]]),
        ]
        for row in rows
    ]
    colors: list[list[float]] | None = None
    if include_colors:
        channels = color_names + (("alpha",) if "alpha" in property_indices else ())
        colors = [
            [float(row[property_indices[name]]) for name in channels]
            for row in rows
        ]
    return points, colors


def _read_vertex_header(
    source: BinaryIO,
) -> tuple[str, int, list[tuple[str, str]]]:
    if source.readline().strip() != b"ply":
        raise ValueError("input is not a PLY file")

    ply_format: str | None = None
    current_element: str | None = None
    vertex_count: int | None = None
    vertex_properties: list[tuple[str, str]] = []
    nonempty_element_before_vertex = False

    while True:
        raw_line = source.readline()
        if not raw_line:
            raise ValueError("PLY header is missing end_header")
        try:
            parts = raw_line.decode("ascii").strip().split()
        except UnicodeDecodeError as error:
            raise ValueError("PLY header must contain ASCII text") from error
        if not parts or parts[0] in {"comment", "obj_info"}:
            continue
        if parts[0] == "end_header":
            break
        if parts[0] == "format":
            if len(parts) != 3 or parts[2] != "1.0":
                raise ValueError("PLY format must use version 1.0")
            if parts[1] not in {"ascii", "binary_little_endian"}:
                raise ValueError(
                    "only ASCII and binary_little_endian PLY are supported"
                )
            ply_format = parts[1]
            continue
        if parts[0] == "element":
            if len(parts) != 3:
                raise ValueError("invalid PLY element declaration")
            try:
                element_count = int(parts[2])
            except ValueError as error:
                raise ValueError("PLY element count must be an integer") from error
            if element_count < 0:
                raise ValueError("PLY element count must not be negative")
            current_element = parts[1]
            if current_element == "vertex":
                if vertex_count is not None:
                    raise ValueError("PLY contains more than one vertex element")
                vertex_count = element_count
            elif vertex_count is None and element_count:
                nonempty_element_before_vertex = True
            continue
        if parts[0] == "property" and current_element == "vertex":
            if len(parts) != 3 or parts[1] == "list":
                raise ValueError("list-valued vertex properties are not supported")
            scalar_format = _PLY_SCALAR_FORMATS.get(parts[1])
            if scalar_format is None:
                raise ValueError(f"unsupported PLY scalar type: {parts[1]}")
            if any(name == parts[2] for name, _ in vertex_properties):
                raise ValueError(f"duplicate PLY vertex property: {parts[2]}")
            vertex_properties.append((parts[2], scalar_format))

    if ply_format is None:
        raise ValueError("PLY header is missing format declaration")
    if vertex_count is None:
        raise ValueError("PLY does not contain a vertex element")
    if nonempty_element_before_vertex:
        raise ValueError("vertex must be the first non-empty PLY element")
    return ply_format, vertex_count, vertex_properties


def _read_binary_vertices(
    source: BinaryIO,
    vertex_count: int,
    vertex_properties: list[tuple[str, str]],
) -> list[tuple[int | float, ...]]:
    vertex_struct = Struct("<" + "".join(code for _, code in vertex_properties))
    rows: list[tuple[int | float, ...]] = []
    for vertex_index in range(vertex_count):
        record = source.read(vertex_struct.size)
        if len(record) != vertex_struct.size:
            raise ValueError(
                "unexpected end of file while reading "
                f"vertex {vertex_index} of {vertex_count}"
            )
        rows.append(vertex_struct.unpack(record))
    return rows


def _read_ascii_vertices(
    source: BinaryIO,
    vertex_count: int,
    vertex_properties: list[tuple[str, str]],
) -> list[tuple[int | float, ...]]:
    rows: list[tuple[int | float, ...]] = []
    for vertex_index in range(vertex_count):
        raw_line = source.readline()
        if not raw_line:
            raise ValueError(
                "unexpected end of file while reading "
                f"vertex {vertex_index} of {vertex_count}"
            )
        try:
            values = raw_line.decode("ascii").strip().split()
        except UnicodeDecodeError as error:
            raise ValueError("ASCII PLY vertex data must contain ASCII text") from error
        if len(values) != len(vertex_properties):
            raise ValueError(
                f"PLY vertex {vertex_index} has {len(values)} values; "
                f"expected {len(vertex_properties)}"
            )
        parsed: list[int | float] = []
        for value, (_, scalar_format) in zip(
            values, vertex_properties, strict=True
        ):
            try:
                parsed.append(
                    int(value) if scalar_format in _INTEGER_FORMATS else float(value)
                )
            except ValueError as error:
                raise ValueError(
                    f"PLY vertex {vertex_index} contains an invalid scalar"
                ) from error
        rows.append(tuple(parsed))
    return rows
