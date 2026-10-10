from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGBA", (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((50, 50, 974, 974), radius=210, fill="#d5ed9e")
for x in (280, 580):
    draw.rectangle((x, 236, x + 128, 616), fill="#20372d")
    draw.pieslice((x - 150, 476, x + 128, 754), 0, 180, fill="#20372d")
    draw.rectangle((x - 150, 550, x - 20, 637), fill="#d5ed9e")
Path("build").mkdir(exist_ok=True)
image.save("build/AppIcon.icns")
image.save("build/AppIcon.png")
image.save("build/AppIcon.ico", sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
