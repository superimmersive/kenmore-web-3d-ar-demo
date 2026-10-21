"""Build the web/AR cone crusher models from the Blender exports in _work/source.

GLB (web viewer, Android Scene Viewer) and USDZ (iOS Quick Look) both get the
same uniform scale baked in, so every viewer opens at the same default size.

Also:
- the 4K baked body texture is stored as JPEG (its alpha is only bake padding)
- the USD logo decal gets the logo image from the GLB, since Blender's USD
  export gave it a plain dark material
- the USD dome light is dropped; Quick Look uses its own lighting
"""
import io
import json
import pathlib
import shutil
import struct
import tempfile

from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade, UsdUtils

SCALE = 0.2
BODY_TEXTURE = "4k"
LOGO_MATERIAL = "Kenmore+logo+-+wide+-+charcoal-1920w"
JPEG_QUALITY = 90

root = pathlib.Path(__file__).resolve().parent.parent
source = root / "_work" / "source"
models = root / "models"


def read_glb(path):
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + json_len])
    bin_start = 20 + json_len + 8
    bin_len = struct.unpack_from("<I", data, 20 + json_len)[0]
    return gltf, data[bin_start:bin_start + bin_len]


def view_bytes(gltf, blob, index):
    view = gltf["bufferViews"][index]
    start = view.get("byteOffset", 0)
    return blob[start:start + view["byteLength"]]


def write_glb(path, gltf, views):
    blob = bytearray()
    for view, chunk in zip(gltf["bufferViews"], views):
        blob += b"\0" * (-len(blob) % 4)
        view["byteOffset"] = len(blob)
        view["byteLength"] = len(chunk)
        blob += chunk
    blob += b"\0" * (-len(blob) % 4)
    gltf["buffers"] = [{"byteLength": len(blob)}]

    text = json.dumps(gltf, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def to_jpeg(png_bytes):
    buf = io.BytesIO()
    Image.open(io.BytesIO(png_bytes)).convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
    return buf.getvalue()


def build_glb():
    gltf, blob = read_glb(source / "cone-crusher.glb")
    views = [view_bytes(gltf, blob, i) for i in range(len(gltf["bufferViews"]))]

    logo_png = None
    logo_material = next(m for m in gltf["materials"] if m["name"] == LOGO_MATERIAL)
    logo_image = gltf["textures"][logo_material["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]

    for i, image in enumerate(gltf["images"]):
        if image.get("name") == BODY_TEXTURE:
            jpeg = to_jpeg(views[image["bufferView"]])
            views[image["bufferView"]] = jpeg
            image["mimeType"] = "image/jpeg"
        if i == logo_image:
            logo_png = views[image["bufferView"]]

    scene = gltf["scenes"][gltf.get("scene", 0)]
    gltf["nodes"].append({"name": "scale_root", "scale": [SCALE] * 3, "children": scene["nodes"]})
    scene["nodes"] = [len(gltf["nodes"]) - 1]

    out = models / "cone-crusher.glb"
    write_glb(out, gltf, views)
    print("glb", out.stat().st_size)
    return jpeg, logo_png


def logo_material(stage, path, texture_file):
    material = UsdShade.Material.Define(stage, path)
    surface = UsdShade.Shader.Define(stage, path.AppendChild("surface"))
    surface.CreateIdAttr("UsdPreviewSurface")
    surface.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)

    reader = UsdShade.Shader.Define(stage, path.AppendChild("uv"))
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.String).Set("st")

    texture = UsdShade.Shader.Define(stage, path.AppendChild("logo"))
    texture.CreateIdAttr("UsdUVTexture")
    texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_file)
    texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    texture.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("clamp")
    texture.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("clamp")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
    rgb = texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
    alpha = texture.CreateOutput("a", Sdf.ValueTypeNames.Float)

    surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(rgb)
    surface.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(alpha)
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    return material


def build_usdz(body_jpeg, logo_png):
    flat = Usd.Stage.Open(Usd.Stage.Open(str(source / "cone-crusher.usdc")).Flatten())

    for prim in list(flat.Traverse()):
        if prim.IsA(UsdLux.DomeLight):
            flat.RemovePrim(prim.GetPath())

    for prim in flat.Traverse():
        if prim.IsA(UsdShade.Shader):
            file_input = UsdShade.Shader(prim).GetInput("file")
            if file_input and file_input.Get() and file_input.Get().path.endswith(BODY_TEXTURE + ".png"):
                file_input.Set(Sdf.AssetPath("./textures/" + BODY_TEXTURE + ".jpg"))

    materials = flat.GetDefaultPrim().GetPath().AppendChild("_materials")
    logo = logo_material(flat, materials.AppendChild("kenmore_logo"), Sdf.AssetPath("./textures/kenmore-logo.png"))
    for prim in flat.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
        if bound and bound.GetPath().name == "MainBody_001":
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(logo)
            UsdGeom.Mesh(prim).CreateDoubleSidedAttr(True)
            flat.RemovePrim(bound.GetPath())
            print("logo decal", prim.GetPath())
            break

    top = UsdGeom.Xformable(flat.GetDefaultPrim())
    ops = top.GetOrderedXformOps()
    scale = top.AddScaleOp(opSuffix="arDefault")
    scale.Set(Gf.Vec3f(SCALE, SCALE, SCALE))
    top.SetXformOpOrder([scale] + ops)

    dst = models / "cone-crusher.usdz"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "textures").mkdir()
        (tmp / "textures" / (BODY_TEXTURE + ".jpg")).write_bytes(body_jpeg)
        (tmp / "textures" / "kenmore-logo.png").write_bytes(logo_png)
        clean = tmp / "cone-crusher.usdc"
        flat.GetRootLayer().Export(str(clean))
        if dst.exists():
            dst.unlink()
        if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(clean)), str(dst)):
            raise RuntimeError("USDZ packaging failed")

    packed = Usd.Stage.Open(str(dst))
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    size = box.ComputeWorldBound(packed.GetPseudoRoot()).ComputeAlignedRange().GetSize()
    _, assets, unresolved = UsdUtils.ComputeAllDependencies(str(dst))
    print("usdz", dst.stat().st_size, "size m", [round(v, 3) for v in size],
          "assets", [str(a).split("[")[-1].rstrip("]") for a in assets], "unresolved", unresolved)


body, logo_png = build_glb()
build_usdz(body, logo_png)
