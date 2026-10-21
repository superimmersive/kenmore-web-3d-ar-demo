import json
import pathlib
import struct

from PIL import Image

root = pathlib.Path(__file__).resolve().parent.parent


def to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_of(rgb):
    return "#" + "".join(f"{round(v):02X}" for v in rgb)


data = (root / "_work" / "source" / "cone-crusher.glb").read_bytes()
gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
for mat in gltf.get("materials", []):
    pbr = mat.get("pbrMetallicRoughness", {})
    base = pbr.get("baseColorFactor", [1, 1, 1, 1])
    print("model material", mat.get("name"), "linear", base[:3],
          "hex", hex_of([to_srgb(c) * 255 for c in base[:3]]),
          "metallic", pbr.get("metallicFactor", 1), "roughness", pbr.get("roughnessFactor", 1))

full = Image.open(root / "images" / "products" / "cone-crusher.jpg").convert("RGB")
print("size", full.size)
patches = {
    "body, lit (upper bowl)": (440, 160, 20, 10),
    "body, mid (main frame)": (480, 420, 20, 10),
    "body, shadow (lower frame)": (460, 500, 16, 10),
    "green ring (adjustment ring)": (560, 262, 20, 4),
    "green pulley rim": (835, 470, 6, 20),
    "logo mark teal": (376, 147, 6, 6),
    "logo text": (450, 148, 4, 4),
    "pulley hub / shaft": (812, 440, 6, 6),
}
k = full.size[0] / 1024
for label, (x, y, w, h) in patches.items():
    x, y = round(x * k), round(y * k)
    box = sorted(full.crop((x, y, x + w, y + h)).get_flattened_data(), key=sum)
    mid = box[len(box) // 2]
    print(f"{label:30s} {hex_of(mid)}  rgb{mid}")

img = full.copy()
img.thumbnail((300, 300))
pixels = [p for p in img.get_flattened_data() if not all(v > 235 for v in p)]
small = Image.new("RGB", (len(pixels), 1))
small.putdata(pixels)
quant = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
palette = quant.getpalette()
counts = sorted(quant.getcolors(), reverse=True)
total = sum(c for c, _ in counts)
for count, idx in counts:
    rgb = palette[idx * 3: idx * 3 + 3]
    print(f"{hex_of(rgb)}  {100 * count / total:5.1f}%  rgb{tuple(rgb)}")
