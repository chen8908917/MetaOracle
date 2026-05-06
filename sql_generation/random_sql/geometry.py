"""Geometry/geo-type helper functions used by random SQL generation."""

import random
import struct
from typing import Optional

from ast_nodes import LiteralNode
from data_structures.db_dialect import get_current_dialect


def is_geometry_type(data_type: str) -> bool:
    if not data_type:
        return False
    data_type = str(data_type).lower()
    geometry_types = [
        "geometry",
        "point",
        "linestring",
        "polygon",
        "multipoint",
        "multilinestring",
        "multipolygon",
        "geometrycollection",
    ]
    return any(t in data_type for t in geometry_types)


def _random_point() -> tuple:
    return (random.uniform(-180, 180), random.uniform(-90, 90))

def _random_bbox() -> tuple:
    x1, y1 = _random_point()
    x2, y2 = _random_point()
    min_x, max_x = (x1, x2) if x1 <= x2 else (x2, x1)
    min_y, max_y = (y1, y2) if y1 <= y2 else (y2, y1)
    if min_x == max_x:
        max_x = min_x + 0.1
    if min_y == max_y:
        max_y = min_y + 0.1
    return min_x, min_y, max_x, max_y

def get_geometry_type_for_function(func_name: Optional[str]) -> str:
    if not func_name:
        return random.choice(["POINT", "LINESTRING", "POLYGON"])
    func_name = func_name.upper()
    mapping = {
        "ST_GEOMFROMTEXT": "POINT",
        "ST_GEOMFROMWKB": "POINT",
        "ST_GEOMFROMGEOHASH": "POINT",
        "ST_GEOMFROMGEOJSON": "POINT",
        "ST_POINTFROMTEXT": "POINT",
        "ST_LINEFROMTEXT": "LINESTRING",
        "ST_POLYFROMTEXT": "POLYGON",
        "ST_LONGITUDE": "POINT",
        "ST_LATITUDE": "POINT",
        "ST_X": "POINT",
        "ST_Y": "POINT",
        "ST_DISTANCE_SPHERE": "POINT",
        "ST_AREA": "POLYGON",
    }
    mapped = mapping.get(func_name)
    if mapped:
        return mapped
    inferred = _infer_geometry_type_from_name(func_name)
    if inferred:
        return inferred
    return random.choice(["POINT", "LINESTRING", "POLYGON"])


def _infer_geometry_type_from_name(func_name: str) -> Optional[str]:
    name = func_name.upper()
    if "GEOMCOLL" in name or "GEOMETRYCOLLECTION" in name:
        return "GEOMETRYCOLLECTION"
    if "MULTIPOLYGON" in name or "MPOLY" in name:
        return "MULTIPOLYGON"
    if "MULTILINESTRING" in name or "MLINE" in name:
        return "MULTILINESTRING"
    if "MULTIPOINT" in name or "MPOINT" in name:
        return "MULTIPOINT"
    if "POLYGON" in name or name.endswith("POLY"):
        return "POLYGON"
    if "LINESTRING" in name or "LINE" in name:
        return "LINESTRING"
    if "POINT" in name:
        return "POINT"
    return None


def get_required_geometry_type(func_name: Optional[str]) -> Optional[str]:
    if not func_name:
        return None
    func_name = func_name.upper()
    if func_name in {"ST_LONGITUDE", "ST_LATITUDE", "ST_X", "ST_Y", "ST_DISTANCE_SPHERE"}:
        return "POINT"
    if func_name in {"ST_AREA", "ST_EXTERIORRING", "ST_INTERIORRINGN"}:
        return "POLYGON"
    if func_name in {"ST_LENGTH", "ST_ISCLOSED", "ST_STARTPOINT", "ST_ENDPOINT", "ST_POINTN", "ST_NUMPOINTS"}:
        return "LINESTRING"
    if func_name in {"ST_GEOMETRYN", "ST_NUMGEOMETRIES"}:
        return "GEOMETRYCOLLECTION"
    return None


def create_geometry_wkt(geom_type: str) -> str:
    geom_type = geom_type.upper()
    if geom_type == "POINT":
        x, y = _random_point()
        return f"POINT({x} {y})"
    if geom_type == "LINESTRING":
        points = [_random_point() for _ in range(3)]
        return "LINESTRING(" + ", ".join([f"{x} {y}" for x, y in points]) + ")"
    if geom_type == "POLYGON":
        min_x, min_y, max_x, max_y = _random_bbox()
        points = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        return "POLYGON((" + ", ".join([f"{x} {y}" for x, y in points]) + "))"
    if geom_type == "MULTIPOINT":
        points = [_random_point() for _ in range(3)]
        return "MULTIPOINT(" + ", ".join([f"({x} {y})" for x, y in points]) + ")"
    if geom_type == "MULTILINESTRING":
        line1 = [_random_point() for _ in range(2)]
        line2 = [_random_point() for _ in range(2)]
        return "MULTILINESTRING((" + ", ".join([f"{x} {y}" for x, y in line1]) + "),(" + ", ".join([f"{x} {y}" for x, y in line2]) + "))"
    if geom_type == "MULTIPOLYGON":
        min_x, min_y, max_x, max_y = _random_bbox()
        poly1 = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        min_x2, min_y2, max_x2, max_y2 = _random_bbox()
        poly2 = [
            (min_x2, min_y2),
            (max_x2, min_y2),
            (max_x2, max_y2),
            (min_x2, max_y2),
            (min_x2, min_y2),
        ]
        p1 = ", ".join([f"{x} {y}" for x, y in poly1])
        p2 = ", ".join([f"{x} {y}" for x, y in poly2])
        return "MULTIPOLYGON(((" + p1 + ")),((" + p2 + ")))"
    if geom_type == "GEOMETRYCOLLECTION":
        return "GEOMETRYCOLLECTION(" + create_geometry_wkt("POINT") + "," + create_geometry_wkt("LINESTRING") + ")"
    return create_geometry_wkt("POINT")


def create_geometry_wkt_for_function(func_name: Optional[str]) -> str:
    return create_geometry_wkt(get_geometry_type_for_function(func_name))


def is_wkt_function(func_name: Optional[str]) -> bool:
    if not func_name:
        return False
    func_name = func_name.upper()
    if "FROMTEXT" in func_name or "FROMTXT" in func_name:
        return True
    return func_name in {"ST_GEOMFROMTEXT", "ST_POINTFROMTEXT", "ST_LINEFROMTEXT", "ST_POLYFROMTEXT"}


def is_geohash_function(func_name: Optional[str]) -> bool:
    if not func_name:
        return False
    return func_name.upper() in {"ST_GEOMFROMGEOHASH", "ST_LONGFROMGEOHASH", "ST_LATFROMGEOHASH"}

def is_geojson_function(func_name: Optional[str]) -> bool:
    if not func_name:
        return False
    return func_name.upper() == "ST_GEOMFROMGEOJSON"


def create_geohash_literal_node() -> LiteralNode:
    chars = "0123456789bcdefghjkmnpqrstuvwxyz"
    value = "".join(random.choice(chars) for _ in range(random.randint(5, 12)))
    return LiteralNode(value, "STRING")


def create_wkt_literal_node(func_name: Optional[str] = None) -> LiteralNode:
    return LiteralNode(create_geometry_wkt_for_function(func_name), "STRING")

def create_geojson_literal_node(func_name: Optional[str] = None) -> LiteralNode:
    geom_type = get_geometry_type_for_function(func_name).upper()
    if geom_type == "POINT":
        x, y = _random_point()
        value = f'{{"type":"Point","coordinates":[{x},{y}]}}'
    elif geom_type == "LINESTRING":
        points = [_random_point() for _ in range(3)]
        coords = ",".join([f"[{x},{y}]" for x, y in points])
        value = f'{{"type":"LineString","coordinates":[{coords}]}}'
    else:
        min_x, min_y, max_x, max_y = _random_bbox()
        points = [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
            (min_x, min_y),
        ]
        coords = ",".join([f"[{x},{y}]" for x, y in points])
        value = f'{{"type":"Polygon","coordinates":[[{coords}]]}}'
    return LiteralNode(value, "JSON")


def create_geometry_literal_node(func_name: Optional[str] = None) -> LiteralNode:
    if is_geohash_function(func_name):
        return create_geohash_literal_node()
    if is_geojson_function(func_name):
        return create_geojson_literal_node(func_name)
    if is_wkt_function(func_name):
        return create_wkt_literal_node(func_name)
    wkt = create_geometry_wkt_for_function(func_name)
    expr = f"ST_GeomFromText('{wkt}')"
    return LiteralNode(expr, "BINARY")


def create_wkb_literal_node(func_name: Optional[str] = None) -> LiteralNode:
    wkb_hex = _create_wkb_hex_for_function(func_name)
    return LiteralNode(f"X'{wkb_hex}'", "BINARY")


def _create_wkb_hex_for_function(func_name: Optional[str]) -> str:
    geom_type = get_geometry_type_for_function(func_name).upper()
    return _create_wkb_hex_for_geometry(geom_type)


def _pack(fmt: str, *values) -> bytes:
    return struct.pack("<" + fmt, *values)


def _wkb_point(x: float, y: float) -> bytes:
    return b"\x01" + _pack("I", 1) + _pack("dd", x, y)


def _wkb_linestring(points) -> bytes:
    data = b"\x01" + _pack("I", 2) + _pack("I", len(points))
    for x, y in points:
        data += _pack("dd", x, y)
    return data


def _wkb_polygon(ring) -> bytes:
    data = b"\x01" + _pack("I", 3) + _pack("I", 1) + _pack("I", len(ring))
    for x, y in ring:
        data += _pack("dd", x, y)
    return data


def _create_wkb_hex_for_geometry(geom_type: str) -> str:
    geom_type = geom_type.upper()
    if geom_type == "POINT":
        data = _wkb_point(1.0, 1.0)
    elif geom_type == "LINESTRING":
        data = _wkb_linestring([(0.0, 0.0), (1.0, 1.0)])
    elif geom_type == "POLYGON":
        ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        data = _wkb_polygon(ring)
    elif geom_type == "MULTIPOINT":
        points = [(0.0, 0.0), (1.0, 1.0)]
        data = b"\x01" + _pack("I", 4) + _pack("I", len(points))
        for x, y in points:
            data += _wkb_point(x, y)
    elif geom_type == "MULTILINESTRING":
        lines = [[(0.0, 0.0), (1.0, 1.0)]]
        data = b"\x01" + _pack("I", 5) + _pack("I", len(lines))
        for line in lines:
            data += _wkb_linestring(line)
    elif geom_type == "MULTIPOLYGON":
        ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        data = b"\x01" + _pack("I", 6) + _pack("I", 1) + _wkb_polygon(ring)
    elif geom_type == "GEOMETRYCOLLECTION":
        data = b"\x01" + _pack("I", 7) + _pack("I", 2)
        data += _wkb_point(0.0, 0.0)
        data += _wkb_linestring([(0.0, 0.0), (1.0, 1.0)])
    else:
        data = _wkb_point(1.0, 1.0)
    return data.hex().upper()
