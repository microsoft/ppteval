"""
Generate a favicon.ico file from SVG
"""
from PIL import Image, ImageDraw
import io

def create_favicon():
    # Create a 32x32 image with transparency
    size = 32
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw an orange rounded square background (PowerPoint theme)
    try:
        draw.rounded_rectangle([2, 2, size-2, size-2], radius=6, fill=(255, 107, 53, 255))
    except AttributeError:
        # Fallback if rounded_rectangle not available: draw rectangle
        draw.rectangle([2,2,size-2,size-2], fill=(255,107,53,255))
    
    # Reduced trophy silhouette (smaller centered)
    gold = (255, 207, 51, 255)
    white = (255, 255, 255, 255)

    # Cup (smaller): top y≈9, bottom of cup y≈19
    cup_points = [(16,9), (12,11), (12,15), (12,18), (14,22), (16,23), (18,22), (20,18), (20,15), (20,11)]
    outline_points = [(16,8), (11,10), (11,15), (11,18), (13,23), (16,24), (19,23), (21,18), (21,15), (21,10)]
    outline = Image.new('RGBA', (size, size), (0,0,0,0))
    o = ImageDraw.Draw(outline)
    o.polygon(outline_points, fill=white)
    img.alpha_composite(outline)
    draw.polygon(cup_points, fill=gold)

    # Smaller handles
    draw.arc([9,12,14,22], 250, 110, fill=gold, width=3)
    draw.arc([18,12,23,22], 70, 290, fill=gold, width=3)

    # Stem and base reduced
    draw.rectangle([15,23,17,27], fill=gold)
    draw.rectangle([13,27,19,29], fill=gold)
    
    # Save as ICO (multiple sizes for compatibility)
    sizes = [(16, 16), (32, 32)]
    images = []
    
    for icon_size in sizes:
        if icon_size != (32, 32):
            resized = img.resize(icon_size, Image.Resampling.LANCZOS)
            images.append(resized)
        else:
            images.append(img)
    
    # Save as ICO file
    img.save('assets/images/favicon.ico', format='ICO', sizes=[(16, 16), (32, 32)])
    print("✓ favicon.ico created successfully!")
    
    # Also create a PNG for reference
    img.save('assets/images/favicon-32x32.png', format='PNG')
    print("✓ favicon-32x32.png created successfully!")

if __name__ == '__main__':
    try:
        create_favicon()
    except ImportError:
        print("Error: Pillow (PIL) is required. Install it with: pip install Pillow")
    except Exception as e:
        print(f"Error creating favicon: {e}")
