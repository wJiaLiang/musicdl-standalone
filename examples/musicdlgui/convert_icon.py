import os
import sys
import subprocess

def convert():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(current_dir, 'music-1.png')
    ico_path = os.path.join(current_dir, 'music-1.ico')
    icon_ico_path = os.path.join(current_dir, 'icon.ico')

    if not os.path.exists(png_path):
        print(f"Error: {png_path} does not exist.")
        sys.exit(1)

    print("Checking for Pillow...")
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed. Installing Pillow...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
        from PIL import Image

    print("Converting PNG to ICO...")
    img = Image.open(png_path)
    
    # Save as music-1.ico with standard resolutions (16x16, 32x32, 48x48, 64x64, 128x128, 256x256)
    img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f"Saved to {ico_path}")

    # Overwrite icon.ico for compatibility with PyInstaller specs and default code loading
    img.save(icon_ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f"Saved to {icon_ico_path}")

if __name__ == '__main__':
    convert()
