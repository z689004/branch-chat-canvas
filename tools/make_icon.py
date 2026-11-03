# -*- coding: utf-8 -*-
"""生成应用图标（分支节点树），输出 assets/icon.png 与 assets/icon.ico。

用法：python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def draw_icon() -> Image.Image:
    # 背景：深色圆角方块 + 绿色渐变对角线，保证在浅色/深色任务栏都清楚
    top, bottom = (16, 185, 129), (5, 120, 87)      # emerald-500 -> emerald-700
    grad = Image.new("RGB", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * (S - 1))
            px[x, y] = lerp(top, bottom, t)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas.paste(grad, (0, 0), rounded_mask(S, 232))

    d = ImageDraw.Draw(canvas)

    # 节点坐标：左侧根节点 → 右侧两个子节点（分支语义）
    root = (286, 512)
    children = [(742, 306), (742, 718)]

    # 连线（先画线，后画节点覆盖端点）
    line_w = 44
    for c in children:
        d.line([root, c], fill=(255, 255, 255, 232), width=line_w, joint="curve")
    for c in children:
        d.ellipse(
            [c[0] - line_w / 2, c[1] - line_w / 2, c[0] + line_w / 2, c[1] + line_w / 2],
            fill=(255, 255, 255, 232),
        )

    # 子节点：白色实心圆
    for c in children:
        r = 92
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(255, 255, 255, 255))
        r2 = 44
        d.ellipse([c[0] - r2, c[1] - r2, c[0] + r2, c[1] + r2], fill=(6, 140, 100, 255))

    # 根节点：更大的白色圆 + 绿色内芯（视觉主角）
    r = 124
    d.ellipse([root[0] - r, root[1] - r, root[0] + r, root[1] + r], fill=(255, 255, 255, 255))
    r2 = 62
    d.ellipse([root[0] - r2, root[1] - r2, root[0] + r2, root[1] + r2], fill=(6, 140, 100, 255))
    r3 = 24
    d.ellipse([root[0] - r3, root[1] - r3, root[0] + r3, root[1] + r3], fill=(255, 255, 255, 255))

    return canvas


def main():
    icon = draw_icon()
    png_path = ASSETS / "icon.png"
    icon.save(png_path)

    ico_path = ASSETS / "icon.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icon.save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])

    # 预览大图（README 用）
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon-256.png")

    print("PNG:", png_path)
    print("ICO:", ico_path)


if __name__ == "__main__":
    main()
