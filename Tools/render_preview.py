# ABOUTME: Headless Blender script that renders a studio-lit preview of a plate or cap STL.
# ABOUTME: Usage: blender -b -P Tools/render_preview.py -- <input.stl> <output.png> [oblique|top]

import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
stl_path, out_path = argv[0], argv[1]
view = argv[2] if len(argv) > 2 else "oblique"

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Work in millimeters so the STL imports at its true size.
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 0.001

bpy.ops.wm.stl_import(filepath=stl_path)
obj = bpy.context.selected_objects[0]
bpy.ops.object.shade_smooth()

# Center the model on the origin, resting on z=0.
lo = [min(v.co[i] for v in obj.data.vertices) for i in range(3)]
hi = [max(v.co[i] for v in obj.data.vertices) for i in range(3)]
size = [hi[i] - lo[i] for i in range(3)]
obj.location = (-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])
extent = max(size[0], size[1])

# Cap material: blue-gray slightly glossy plastic, like the upstream previews.
mat = bpy.data.materials.new("CapPlastic")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.13, 0.17, 0.30, 1.0)
bsdf.inputs["Roughness"].default_value = 0.45
obj.data.materials.append(mat)

# Ground plane catches soft shadows.
bpy.ops.mesh.primitive_plane_add(size=extent * 8, location=(0, 0, 0))
ground = bpy.context.active_object
gmat = bpy.data.materials.new("Ground")
gmat.use_nodes = True
gb = gmat.node_tree.nodes["Principled BSDF"]
gb.inputs["Base Color"].default_value = (0.92, 0.92, 0.94, 1.0)
gb.inputs["Roughness"].default_value = 0.9
ground.data.materials.append(gmat)


def area_light(name, loc, rot, energy, light_size):
    light = bpy.data.lights.new(name, type="AREA")
    light.energy = energy
    light.size = light_size
    holder = bpy.data.objects.new(name, light)
    holder.location = loc
    holder.rotation_euler = rot
    scene.collection.objects.link(holder)


# Three-point studio lighting, scaled to the model footprint.
e = extent
area_light("key", (-e * 0.9, -e * 0.9, e * 1.4), (math.radians(40), 0, math.radians(-45)), 2.2e6, e * 1.5)
area_light("fill", (e * 1.2, -e * 0.7, e * 0.9), (math.radians(55), 0, math.radians(55)), 0.7e6, e * 2.0)
area_light("rim", (0, e * 1.3, e * 1.1), (math.radians(-50), 0, 0), 2e6, e * 1.2)

# Soft white world so nothing is pitch black.
world = bpy.data.worlds.new("World")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.9, 0.92, 1.0)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25
scene.world = world

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
if view == "top":
    cam.location = (0, 0, extent * 1.9)
    cam.rotation_euler = (0, 0, 0)
else:
    cam.location = (-extent * 0.85, -extent * 1.35, extent * 1.1)
    cam.rotation_euler = (math.radians(57), 0, math.radians(-32))
cam_data.lens = 50

scene.render.engine = "CYCLES"
scene.cycles.samples = 96
scene.cycles.use_denoising = True
scene.render.resolution_x = 1920
scene.render.resolution_y = 1440
scene.render.filepath = out_path
scene.render.image_settings.file_format = "PNG"

bpy.ops.render.render(write_still=True)
print(f"rendered {out_path}")
