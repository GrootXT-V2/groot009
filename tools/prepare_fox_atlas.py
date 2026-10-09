"""Pack generated fox art into isolated, registered animation cells (macOS).

This is a build-time tool. The application only loads the resulting PNG.
No cell boundaries from the generated sheet are used to cut the foxes.
"""

import argparse
import json
from pathlib import Path

import AppKit


def prepare(source, destination):
    original = AppKit.NSBitmapImageRep.imageRepWithContentsOfFile_(str(source))
    if original is None or original.bitsPerPixel() != 32 or original.samplesPerPixel() != 4:
        raise ValueError("Expected a readable RGBA image")
    width, height = original.pixelsWide(), original.pixelsHigh()
    stride = original.bytesPerRow()
    pixels = bytes(original.bitmapData())
    pending = {y * width + x for y in range(height) for x in range(width)
               if pixels[y * stride + x * 4 + 3] >= 16}
    components = []
    while pending:
        seed = pending.pop()
        stack, component = [seed], [seed]
        while stack:
            index = stack.pop()
            x = index % width
            neighbors = [index - width, index + width]
            if x:
                neighbors.append(index - 1)
            if x + 1 < width:
                neighbors.append(index + 1)
            for neighbor in neighbors:
                if neighbor in pending:
                    pending.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        if len(component) > 500:
            components.append(component)
    components.sort(key=len, reverse=True)
    if len(components) < 16:
        raise ValueError(f"Only {len(components)} separate fox silhouettes found")
    components = components[:16]
    # Group by row using each silhouette's center, then sort left to right.
    center = lambda comp: (sum(i % width for i in comp) / len(comp),
                           sum(i // width for i in comp) / len(comp))
    components.sort(key=lambda comp: center(comp)[1])
    components = [comp for row in range(4)
                  for comp in sorted(components[row * 4:row * 4 + 4], key=lambda c: center(c)[0])]
    frames = []
    for component in components:
        points = [(i % width, i // width) for i in component]
        left = min(x for x, y in points)
        right = max(x for x, y in points) + 1
        top = min(y for x, y in points)
        bottom = max(y for x, y in points) + 1
        if left == 0 or top == 0 or right == width or bottom == height:
            raise ValueError("A fox reaches the source image border; regenerate with padding")
        paw_line = max(y + 1 for x, y in points if x < left + (right - left) * 0.65)
        nose = min(x for x, y in points
                   if top + (paw_line - top) * 0.2 <= y <= top + (paw_line - top) * 0.6)
        frames.append(dict(points=points, bounds=[left, top, right, bottom],
                           paw_line=paw_line, nose=nose, height=paw_line - top))

    cell, floor, nose_anchor = 512, 456, 70
    # One proportion for every pose; register nose, ear top and planted paws.
    tail_ratio = max((f["bounds"][2] - f["nose"]) / f["height"] for f in frames)
    body_height = min(340, (cell - nose_anchor - 36) / tail_ratio)
    atlas = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, cell * 4, cell * 4, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
    atlas.bitmapData()[:] = bytes(atlas.bytesPerRow() * atlas.pixelsHigh())
    context = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(atlas)
    context = AppKit.NSGraphicsContext.graphicsContextWithCGContext_flipped_(context.CGContext(), True)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(context)
    transform = AppKit.NSAffineTransform.transform()
    transform.translateXBy_yBy_(0, cell * 4)
    transform.scaleXBy_yBy_(1, -1)
    transform.concat()
    metadata = []
    try:
        for frame, details in enumerate(frames):
            left, top, right, bottom = details["bounds"]
            pad = 3
            left, top = max(0, left - pad), max(0, top - pad)
            right, bottom = min(width, right + pad), min(height, bottom + pad)
            cw, ch = right - left, bottom - top
            isolated = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
                None, cw, ch, 8, 4, True, False, original.colorSpaceName(), original.bitmapFormat(), 0, 0)
            output = bytearray(isolated.bytesPerRow() * ch)
            # Retain the original soft fur edge while excluding neighboring art.
            mask = {(x + dx, y + dy) for x, y in details["points"]
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1)}
            for x, y in mask:
                if left <= x < right and top <= y < bottom:
                    src = y * stride + x * 4
                    dst = (y - top) * isolated.bytesPerRow() + (x - left) * 4
                    output[dst:dst + 4] = pixels[src:src + 4]
            isolated.bitmapData()[:] = output
            image = AppKit.NSImage.alloc().initWithSize_((cw, ch))
            image.addRepresentation_(isolated)
            scale = body_height / details["height"]
            x = frame % 4 * cell + nose_anchor + (left - details["nose"]) * scale
            y = frame // 4 * cell + floor + (top - details["paw_line"]) * scale
            image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                ((x, y), (cw * scale, ch * scale)), ((0, 0), (cw, ch)),
                AppKit.NSCompositingOperationSourceOver, 1, True,
                {AppKit.NSImageHintInterpolation: AppKit.NSImageInterpolationHigh})
            metadata.append(dict(frame=frame, source_bounds=details["bounds"],
                                 nose_anchor=nose_anchor, paw_line=floor,
                                 ear_top=floor - body_height, scale=scale))
    finally:
        AppKit.NSGraphicsContext.restoreGraphicsState()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bytes(atlas.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})))
    destination.with_suffix(".json").write_text(json.dumps(dict(cell=cell, frames=metadata), indent=2))
    print(f"Packed {len(frames)} isolated foxes; cell={cell}, floor={floor}, ear_top={floor - body_height:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
