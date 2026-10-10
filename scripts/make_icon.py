from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGBA", (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((50, 50, 974, 974), radius=204, fill="#bf5035")
draw.rounded_rectangle((123, 123, 901, 901), radius=139, outline="#d79272", width=9)
for x in (280, 580):
    draw.line((x - 30, 192, x + 144, 192), fill="#fff2d5", width=19)
    draw.rectangle((x, 269, x + 128, 616), fill="#fff2d5")
    draw.pieslice((x - 150, 476, x + 128, 754), 0, 180, fill="#fff2d5")
    draw.rectangle((x - 150, 550, x - 20, 637), fill="#bf5035")
Path("build").mkdir(exist_ok=True)
image.save("build/AppIcon.icns")
image.save("build/AppIcon.png")
image.save("build/AppIcon.ico", sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
