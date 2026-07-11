import os
import urllib.request
import PyInstaller.__main__

def download_font():
    font_name = "Montserrat-Bold.ttf"
    if not os.path.exists(font_name):
        print(f"Downloading {font_name} for bundling...")
        urls = [
            "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
            "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf",
            "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf"
        ]
        success = False
        for url in urls:
            try:
                print(f"Attempting font download from: {url}")
                urllib.request.urlretrieve(url, font_name)
                if os.path.exists(font_name) and os.path.getsize(font_name) > 1000:
                    print("Font downloaded successfully.")
                    success = True
                    break
            except Exception as e:
                print(f"Failed download from {url}: {e}")
        if not success:
            print("The executable will fall back to system fonts (Arial) at runtime.")
    else:
        print(f"{font_name} already exists locally.")

def build():
    download_font()
    
    # Define arguments for PyInstaller
    opts = [
        "app.py",
        "--onefile",
        "--windowed",
        "--name=RankingVideoGenerator",
        "--clean",
        "--copy-metadata=imageio",
        "--collect-all=yt_dlp",
    ]

    # If the font was downloaded successfully, bundle it
    if os.path.exists("Montserrat-Bold.ttf"):
        # On Windows, PyInstaller uses a semicolon (;) as a path separator for --add-data
        opts.append("--add-data=Montserrat-Bold.ttf;.")

    print(f"Running PyInstaller with options: {opts}")
    PyInstaller.__main__.run(opts)

if __name__ == "__main__":
    build()
