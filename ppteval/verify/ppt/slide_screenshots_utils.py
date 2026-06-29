"""
Utility functions for generating PowerPoint slide screenshots using various methods.

This module provides a unified interface for converting PowerPoint presentations to images
using different tools and approaches, with automatic fallback based on available tools.
"""

import glob
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from dataclasses import dataclass

from ppteval.utils.onedrive import OneDriveClient
from ppteval.utils.powerpoint import convert_powerpoint_to_images_sync


@dataclass
class SlideScreenshot:
    """Represents a slide screenshot"""

    slide_number: int
    image_path: str
    slide_id: Optional[str] = None


class SlideScreenshotGenerator:
    """
    Generator for PowerPoint slide screenshots using various conversion methods.

    Supports:
    - OneDrive online conversion (when use_online=True)
    - Local conversion with automatic tool detection and preference:
      1. LibreOffice + Poppler (preferred)
      2. LibreOffice + ImageMagick
      3. PowerPoint COM automation (Windows only)
      4. LibreOffice + Ghostscript
    """

    def __init__(self):
        # Initialize OneDrive client only if CLIENT_ID is available
        client_id = os.getenv("CLIENT_ID")
        if client_id:
            try:
                self.onedrive_client = OneDriveClient(client_id)
            except Exception as e:
                print(f"Warning: Failed to initialize OneDrive client: {e}")
                self.onedrive_client = None
        else:
            self.onedrive_client = None

        # Cache for tools to avoid repeated detection
        self._tools_cache = None

    def clear_tools_cache(self):
        """Clear the tools cache to force re-detection of available tools."""
        self._tools_cache = None
        print("Tools cache cleared. Next conversion will re-detect available tools.")

    def generate_slide_screenshots(
        self,
        pptx_path: str,
        output_dir: Optional[str] = None,
        image_format: str = "jpg",
        density: int = 200,
        conversion_mode: str = "online",
        resolution: tuple|None = None
    ) -> List[SlideScreenshot]:
        """
        Generate screenshots for all slides in a PowerPoint presentation.

        Args:
            pptx_path: Path to the PowerPoint file
            output_dir: Directory to save screenshots (default: temp directory)
            image_format: Image format (jpg, png, etc.)
            density: Image density/DPI for conversion (higher = better quality)
            use_online: If True, use OneDrive online conversion; otherwise use local tools

        Returns:
            List of SlideScreenshot objects with paths to generated images
        """
        if conversion_mode == "online":
            return self._generate_online_screenshots(pptx_path, output_dir)
        else:
            return self._generate_local_screenshots(
                pptx_path, output_dir, image_format, density, conversion_mode=conversion_mode, resolution=resolution
            )

    def _generate_online_screenshots(
        self,
        pptx_path: str,
        output_dir: Optional[str] = None,
    ) -> List[SlideScreenshot]:
        """Generate screenshots using OneDrive online method."""
        if not self.onedrive_client:
            raise RuntimeError(
                "OneDrive client not available. Please set CLIENT_ID environment variable."
            )

        # Use online method via OneDrive
        temp_pptx_path = Path(pptx_path)
        return self._generate_screenshots_from_onedrive(
            path_on_onedrive=f"PowerPoint_Temp/{temp_pptx_path.name}_{str(uuid4())[:8]}.pptx",
            output_dir=output_dir,
            local_file_path=pptx_path,
        )

    def _generate_local_screenshots(
        self,
        pptx_path: str,
        output_dir: Optional[str] = None,
        image_format: str = "jpg",
        density: int = 200,
        conversion_mode: str = "com",
        resolution: tuple|None = None
    ) -> List[SlideScreenshot]:
        """Generate screenshots using local tools with automatic fallback."""
        # Create output directory if not specified
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="pptx_screenshots_")
        else:
            os.makedirs(output_dir, exist_ok=True)

        # Get tools needed for the specified conversion mode (cached and targeted)
        tools = self._get_tools_for_conversion_mode(conversion_mode)

        # Define all available conversion methods
        conversion_methods = {
            "libreoffice+poppler": self._try_libreoffice_poppler,
            "libreoffice+imagemagick": self._try_libreoffice_imagemagick,
            "com": self._try_powerpoint_com,
            "libreoffice+ghostscript": self._try_libreoffice_ghostscript,
        }

        if conversion_mode not in conversion_methods:
            raise ValueError(f"Unknown conversion mode: {conversion_mode}. Available modes: {list(conversion_methods.keys())}")

        # STEP 1: Try the specified conversion mode FIRST
        print(f"[target] Attempting conversion using specified mode: {conversion_mode}")
        if tools:
            print(f"   Using tools: {list(tools.keys())}")
        else:
            if conversion_mode != "com":
                print(f"   Warning: Required tools for {conversion_mode} not found in cache, will attempt anyway")
                # Get all tools for fallback methods too
                tools = self._find_conversion_tools()
                print(f"   Available tools: {list(tools.keys())}")

        try:
            screenshots = conversion_methods[conversion_mode](
                pptx_path, output_dir, tools, image_format, density, resolution=resolution
            )
            if screenshots:
                print(f"[ok] Successfully converted using {conversion_mode}")
                return screenshots
            else:
                print(f"[warn] {conversion_mode} completed but generated no images")
        except Exception as e:
            print(f"[error] {conversion_mode} failed with error: {e}")

        # STEP 2: Only try fallback methods if primary method failed
        print(f"[retry] Primary method {conversion_mode} failed, trying fallback methods...")

        # Ensure we have all tools for fallback methods
        if not tools or len(tools) == 0:
            print("   Discovering all available tools for fallback methods...")
            tools = self._find_conversion_tools()
            print(f"   Available tools: {list(tools.keys())}")

        # Try remaining methods in preferred order
        fallback_order = ["libreoffice+poppler", "libreoffice+imagemagick", "com", "libreoffice+ghostscript"]
        remaining_methods = [method for method in fallback_order if method != conversion_mode and method in conversion_methods]

        for method_name in remaining_methods:
            try:
                print(f"   Trying fallback method: {method_name}...")
                screenshots = conversion_methods[method_name](
                    pptx_path, output_dir, tools, image_format, density, resolution=resolution
                )
                if screenshots:
                    print(f"[ok] Successfully converted using fallback method: {method_name}")
                    return screenshots
                else:
                    print(f"[error] {method_name} completed but generated no images")
            except Exception as e:
                print(f"[error] {method_name} failed with error: {e}")

        # If all methods fail, clean up and raise error
        if output_dir.startswith(tempfile.gettempdir()):
            try:
                shutil.rmtree(output_dir, ignore_errors=True)
            except Exception:
                pass

        raise RuntimeError(
            "All conversion methods failed. Please install one of: "
            "LibreOffice + Poppler, LibreOffice + ImageMagick, or ensure PowerPoint COM is available."
        )

    def _generate_screenshots_from_onedrive(
        self,
        path_on_onedrive: str,
        output_dir: Optional[str] = None,
        local_file_path: Optional[str] = None,
    ) -> List[SlideScreenshot]:
        """Generate screenshots using PowerPoint Online via OneDrive edit link."""

        if local_file_path:
            self.onedrive_client.upload_file(local_file_path, path_on_onedrive)

        # Create output directory if not specified
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="ppt_screenshots_")
        else:
            Path(output_dir).mkdir(parents=True, exist_ok=True)

        try:
            # Get the edit link for the PowerPoint file
            edit_link = self.onedrive_client.get_edit_link(path_on_onedrive)

            # Use the PowerPoint converter to download images as a ZIP
            zip_path = convert_powerpoint_to_images_sync(
                edit_link=edit_link,
                download_dir=output_dir,
                headless=True,
                verbose=True,
                wait_timeout=10,
                download_timeout=20,
            )

            if not zip_path or not os.path.exists(zip_path):
                raise Exception("Failed to download images from PowerPoint Online")

            # Extract images from ZIP and create SlideScreenshot objects
            screenshots = self._convert_zip_to_screenshots(zip_path, output_dir, local_file_path)
            return screenshots

        except Exception as e:
            print(f"Error generating screenshots from OneDrive: {e}")
            return []

    def _convert_zip_to_screenshots(
        self, zip_path: str, output_dir: str, pptx_path: Optional[str] = None
    ) -> List[SlideScreenshot]:
        """
        Convert a ZIP file containing slide images to a list of SlideScreenshot objects.

        Args:
            zip_path: Path to the ZIP file containing slide images
            output_dir: Directory where extracted images should be placed
            pptx_path: Optional path to the PowerPoint presentation file for proper slide_id mapping

        Returns:
            List of SlideScreenshot objects
        """
        screenshots = []
        extract_dir = os.path.join(output_dir, "extracted_images")
        Path(extract_dir).mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            # Find all image files in the extracted directory
            image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
            image_files = []

            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in image_extensions):
                        image_files.append(os.path.join(root, file))

            # Sort image files numerically by slide number to maintain correct slide order
            def extract_slide_number_from_filename(filepath):
                """Extract slide number from filename like 'Slide11.jpg' -> 11"""
                filename = os.path.basename(filepath)
                slide_match = re.search(r"Slide(\d+)", filename, re.IGNORECASE)
                return int(slide_match.group(1)) if slide_match else 0

            image_files.sort(key=extract_slide_number_from_filename)

            # Get proper slide_id mapping from presentation if available
            slide_id_mapping = {}
            if pptx_path and os.path.exists(pptx_path):
                try:
                    from pptx import Presentation
                    prs = Presentation(pptx_path)
                    for i, slide in enumerate(prs.slides):
                        slide_number = i + 1  # 1-indexed
                        slide_id_mapping[slide_number] = str(slide.slide_id)
                except Exception as e:
                    print(f"Warning: Could not load presentation for slide_id mapping: {e}")

            # Create SlideScreenshot objects
            for i, image_path in enumerate(image_files):
                slide_number = i + 1  # Slides are 1-indexed

                # Get proper slide_id from presentation if available, otherwise use position-based approach
                slide_id = slide_id_mapping.get(slide_number)

                if slide_id is None:
                    # When no presentation file is available, use position-based slide_id to maintain consistency
                    # This ensures slide_number and slide_id are aligned
                    slide_id = f"slide{slide_number}"

                screenshot = SlideScreenshot(
                    slide_number=slide_number, image_path=image_path, slide_id=slide_id
                )
                screenshots.append(screenshot)

            return screenshots

        except Exception as e:
            print(f"Error converting ZIP to screenshots: {e}")
            return []

    def _get_tools_for_conversion_mode(self, conversion_mode: str) -> dict:
        """Get only the tools needed for the specified conversion mode, with caching."""
        # Define what tools each conversion mode needs
        mode_requirements = {
            "libreoffice+poppler": ["libreoffice", "poppler"],
            "libreoffice+imagemagick": ["libreoffice", "imagemagick"],
            "com": [],  # COM doesn't need external tools
            "libreoffice+ghostscript": ["libreoffice", "ghostscript"],
        }

        required_tools = mode_requirements.get(conversion_mode, [])
        if not required_tools:
            return {}  # For modes like 'com' that don't need external tools

        # Check cache first
        if self._tools_cache is None:
            self._tools_cache = {}

        # Only search for tools we haven't found yet
        tools_to_find = [tool for tool in required_tools if tool not in self._tools_cache]

        if tools_to_find:
            # Search only for the tools we need
            found_tools = self._find_specific_tools(tools_to_find)
            self._tools_cache.update(found_tools)

        # Return only the tools needed for this conversion mode
        return {tool: path for tool, path in self._tools_cache.items() if tool in required_tools}

    def _find_specific_tools(self, tool_names: List[str]) -> dict:
        """Find specific tools by name, more efficient than finding all tools."""
        tools = {}

        for tool_name in tool_names:
            if tool_name == "libreoffice":
                tools.update(self._find_libreoffice())
            elif tool_name == "imagemagick":
                tools.update(self._find_imagemagick())
            elif tool_name == "poppler":
                tools.update(self._find_poppler())
            elif tool_name == "ghostscript":
                tools.update(self._find_ghostscript())

        return tools

    def _find_libreoffice(self) -> dict:
        """Find LibreOffice installation."""
        libreoffice_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "soffice",
            "libreoffice",
        ]

        for path in libreoffice_paths:
            try:
                if os.path.exists(path):
                    return {"libreoffice": path}
                else:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        return {"libreoffice": path}
            except Exception:
                continue
        return {}

    def _find_imagemagick(self) -> dict:
        """Find ImageMagick installation."""
        magick_paths = ["magick", "convert"]
        for path in magick_paths:
            try:
                result = subprocess.run(
                    [path, "--version"], capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    return {"imagemagick": path}
            except Exception:
                continue
        return {}

    def _find_poppler(self) -> dict:
        """Find Poppler installation."""
        poppler_paths = ["pdftoppm", r"C:\Program Files\poppler\bin\pdftoppm.exe"]
        for path in poppler_paths:
            try:
                if os.path.exists(path):
                    return {"poppler": path}
                else:
                    result = subprocess.run(
                        [path, "-v"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        return {"poppler": path}
            except Exception:
                continue
        return {}

    def _find_ghostscript(self) -> dict:
        """Find Ghostscript installation."""
        gs_paths = ["gs", "gswin64c", "gswin32c"]
        # Also check common installation paths
        gs_paths.extend(glob.glob(r"C:\Program Files\gs\gs*\bin\gswin64c.exe"))
        gs_paths.extend(glob.glob(r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"))

        for path in gs_paths:
            try:
                if os.path.exists(path):
                    return {"ghostscript": path}
                else:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        return {"ghostscript": path}
            except Exception:
                continue
        return {}

    def _find_conversion_tools(self):
        """Find available conversion tools on the system"""
        tools = {}

        # LibreOffice
        libreoffice_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "soffice",
            "libreoffice",
        ]

        for path in libreoffice_paths:
            try:
                if os.path.exists(path):
                    tools["libreoffice"] = path
                    break
                else:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        tools["libreoffice"] = path
                        break
            except Exception:
                continue

        # ImageMagick
        magick_paths = ["magick", "convert"]
        for path in magick_paths:
            try:
                result = subprocess.run(
                    [path, "--version"], capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    tools["imagemagick"] = path
                    break
            except Exception:
                continue

        # Poppler (pdftoppm)
        poppler_paths = ["pdftoppm", r"C:\Program Files\poppler\bin\pdftoppm.exe"]
        for path in poppler_paths:
            try:
                if os.path.exists(path):
                    tools["poppler"] = path
                    break
                else:
                    result = subprocess.run(
                        [path, "-v"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        tools["poppler"] = path
                        break
            except Exception:
                continue

        # Ghostscript
        gs_paths = ["gs", "gswin64c", "gswin32c"]
        # Also check common installation paths
        gs_paths.extend(glob.glob(r"C:\Program Files\gs\gs*\bin\gswin64c.exe"))
        gs_paths.extend(glob.glob(r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"))

        for path in gs_paths:
            try:
                if os.path.exists(path):
                    tools["ghostscript"] = path
                    break
                else:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, timeout=5
                    )
                    if result.returncode == 0:
                        tools["ghostscript"] = path
                        break
            except Exception:
                continue

        return tools

    def _try_libreoffice_poppler(
        self,
        pptx_path: str,
        output_dir: str,
        tools: dict,
        image_format: str,
        density: int,
        **kwargs
    ) -> List[SlideScreenshot]:
        """Try LibreOffice + Poppler conversion method."""
        if "libreoffice" not in tools or "poppler" not in tools:
            return []

        # Convert PPTX to PDF using LibreOffice
        pdf_path = self._convert_pptx_to_pdf_libreoffice(
            pptx_path, output_dir, tools["libreoffice"]
        )
        if not pdf_path:
            return []

        # Convert PDF to images using Poppler
        image_paths = self._convert_pdf_to_images_poppler(
            pdf_path, output_dir, tools["poppler"], image_format, density
        )

        # Clean up PDF
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

        return self._create_screenshots_from_paths(image_paths)

    def _try_libreoffice_imagemagick(
        self,
        pptx_path: str,
        output_dir: str,
        tools: dict,
        image_format: str,
        density: int,
        **kwargs
    ) -> List[SlideScreenshot]:
        """Try LibreOffice + ImageMagick conversion method."""
        if "libreoffice" not in tools or "imagemagick" not in tools:
            return []

        # Convert PPTX to PDF using LibreOffice
        pdf_path = self._convert_pptx_to_pdf_libreoffice(
            pptx_path, output_dir, tools["libreoffice"]
        )
        if not pdf_path:
            return []

        # Convert PDF to images using ImageMagick
        image_paths = self._convert_pdf_to_images_imagemagick(
            pdf_path, output_dir, tools["imagemagick"], image_format, density
        )

        # Clean up PDF
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

        return self._create_screenshots_from_paths(image_paths)

    def _try_powerpoint_com(
        self,
        pptx_path: str,
        output_dir: str,
        tools: dict,
        image_format: str,
        density: int,
        resolution: tuple|None = None,
        **kwargs
    ) -> List[SlideScreenshot]:
        """Try PowerPoint COM automation method (Windows only)."""
        if os.name != "nt":
            return []

        try:
            from win32com.client import Dispatch  # noqa: F401
            import pythoncom    # noqa: F401
        except ImportError:
            return []

        return self._generate_screenshots_powerpoint_com(pptx_path, output_dir, resolution=resolution)

    def _try_libreoffice_ghostscript(
        self,
        pptx_path: str,
        output_dir: str,
        tools: dict,
        image_format: str,
        density: int,
        **kwargs
    ) -> List[SlideScreenshot]:
        """Try LibreOffice + Ghostscript conversion method."""
        if "libreoffice" not in tools or "ghostscript" not in tools:
            return []

        # Convert PPTX to PDF using LibreOffice
        pdf_path = self._convert_pptx_to_pdf_libreoffice(
            pptx_path, output_dir, tools["libreoffice"]
        )
        if not pdf_path:
            return []

        # Convert PDF to images using Ghostscript
        image_paths = self._convert_pdf_to_images_ghostscript(
            pdf_path, output_dir, tools["ghostscript"], image_format, density
        )

        # Clean up PDF
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

        return self._create_screenshots_from_paths(image_paths)

    def _convert_pptx_to_pdf_libreoffice(
        self, pptx_path: str, output_dir: str, soffice_path: str
    ) -> Optional[str]:
        """Convert PPTX to PDF using LibreOffice"""
        try:
            abs_input = os.path.abspath(pptx_path)

            # Kill any existing LibreOffice processes to avoid conflicts
            try:
                subprocess.run(
                    ["taskkill", "/f", "/im", "soffice.exe"],
                    capture_output=True,
                    check=False,
                )
                subprocess.run(
                    ["taskkill", "/f", "/im", "soffice.bin"],
                    capture_output=True,
                    check=False,
                )
                time.sleep(1)  # Give processes time to terminate
            except Exception:
                pass  # Ignore errors if processes don't exist

            cmd = [
                soffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                abs_input,
            ]

            print("Converting PPTX to PDF using LibreOffice...")
            print(f"Command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"LibreOffice PDF conversion failed: {result.stderr}")
                print(f"LibreOffice stdout: {result.stdout}")
                return None

            # Find the generated PDF
            pdf_files = [f for f in os.listdir(output_dir) if f.endswith(".pdf")]
            if pdf_files:
                pdf_path = os.path.join(output_dir, pdf_files[0])
                print(f"PDF generated: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
                return pdf_path

            print("No PDF files found in output directory")
            return None

        except Exception as e:
            print(f"Error in LibreOffice conversion: {e}")
            return None

    def _convert_pdf_to_images_poppler(
        self,
        pdf_path: str,
        output_dir: str,
        poppler_path: str,
        image_format: str,
        density: int,
    ) -> List[str]:
        """Convert PDF to images using Poppler"""
        try:
            output_prefix = os.path.join(output_dir, "slide")

            # Map image format to poppler argument
            format_args = {
                "jpg": "-jpeg",
                "jpeg": "-jpeg",
                "png": "-png",
                "tiff": "-tiff",
            }

            format_arg = format_args.get(image_format.lower(), "-jpeg")

            cmd = [
                poppler_path,
                format_arg,
                "-r",
                str(density),  # DPI
                pdf_path,
                output_prefix,
            ]

            print("Converting PDF to images using Poppler...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                print(f"Poppler conversion failed: {result.stderr}")
                return []

            # Find generated images
            image_files = []
            for f in os.listdir(output_dir):
                # Poppler generates files like slide-01.jpg, slide-02.jpg, etc.
                if f.startswith("slide-") and f.lower().endswith(
                    f".{image_format.lower()}"
                ):
                    image_files.append(f)

            # Sort image files numerically by slide number
            def extract_slide_number_poppler(filename):
                """Extract slide number from filename like 'slide-12.jpg' -> 12"""
                match = re.search(r'slide-(\d+)', filename, re.IGNORECASE)
                return int(match.group(1)) if match else 0

            image_paths = [os.path.join(output_dir, f) for f in sorted(image_files, key=extract_slide_number_poppler)]

            print(f"Poppler generated {len(image_paths)} images")
            return image_paths

        except Exception as e:
            print(f"Error in Poppler conversion: {e}")
            return []

    def _convert_pdf_to_images_imagemagick(
        self,
        pdf_path: str,
        output_dir: str,
        magick_path: str,
        image_format: str,
        density: int,
    ) -> List[str]:
        """Convert PDF to images using ImageMagick"""
        try:
            output_pattern = os.path.join(
                output_dir, f"slide-%02d.{image_format.lower()}"
            )

            cmd = [
                magick_path,
                "-density",
                str(density),  # DPI
                "-quality",
                "95",  # Quality
                pdf_path,
                output_pattern,
            ]

            print("Converting PDF to images using ImageMagick...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                print(f"ImageMagick conversion failed: {result.stderr}")
                return []

            # Find generated images
            image_files = []
            for f in os.listdir(output_dir):
                if f.startswith("slide-") and f.lower().endswith(
                    f".{image_format.lower()}"
                ):
                    image_files.append(f)

            # Sort image files numerically by slide number
            def extract_slide_number_imagemagick(filename):
                """Extract slide number from filename like 'slide-12.jpg' -> 12"""
                match = re.search(r'slide-(\d+)', filename, re.IGNORECASE)
                return int(match.group(1)) if match else 0

            image_paths = [os.path.join(output_dir, f) for f in sorted(image_files, key=extract_slide_number_imagemagick)]

            print(f"ImageMagick generated {len(image_paths)} images")
            return image_paths

        except Exception as e:
            print(f"Error in ImageMagick conversion: {e}")
            return []

    def _convert_pdf_to_images_ghostscript(
        self,
        pdf_path: str,
        output_dir: str,
        gs_path: str,
        image_format: str,
        density: int,
    ) -> List[str]:
        """Convert PDF to images using Ghostscript"""
        try:
            # Map image formats to Ghostscript devices
            gs_devices = {
                "png": "pngalpha",
                "jpg": "jpeg",
                "jpeg": "jpeg",
                "tiff": "tiff24nc",
                "bmp": "bmp16m",
            }

            gs_device = gs_devices.get(image_format.lower(), "jpeg")
            output_pattern = os.path.join(
                output_dir, f"slide-%02d.{image_format.lower()}"
            )

            cmd = [
                gs_path,
                f"-sDEVICE={gs_device}",
                f"-o{output_pattern}",
                f"-r{density}",  # DPI
                "-dNOPAUSE",
                "-dBATCH",
                "-dSAFER",
                pdf_path,
            ]

            print("Converting PDF to images using Ghostscript...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                print(f"Ghostscript conversion failed: {result.stderr}")
                return []

            # Find generated images
            image_files = []
            for f in os.listdir(output_dir):
                if f.startswith("slide-") and f.lower().endswith(
                    f".{image_format.lower()}"
                ):
                    image_files.append(f)

            # Sort image files numerically by slide number
            def extract_slide_number_ghostscript(filename):
                """Extract slide number from filename like 'slide-12.jpg' -> 12"""
                match = re.search(r'slide-(\d+)', filename, re.IGNORECASE)
                return int(match.group(1)) if match else 0

            image_paths = [os.path.join(output_dir, f) for f in sorted(image_files, key=extract_slide_number_ghostscript)]

            print(f"Ghostscript generated {len(image_paths)} images")
            return image_paths

        except Exception as e:
            print(f"Error in Ghostscript conversion: {e}")
            return []

    def _generate_screenshots_powerpoint_com(
        self,
        pptx_path: str,
        output_dir: str,
        timeout_seconds: int = 120,
        resolution: tuple|None = None,
    ) -> List[SlideScreenshot]:
        """Generate screenshots using PowerPoint COM automation (Windows only)."""
        result = []
        exception = None

        def target():
            nonlocal result, exception
            try:
                result = self._generate_screenshots_powerpoint_com_core(
                    pptx_path, output_dir, resolution=resolution
                )
            except Exception as e:
                exception = e

        # Run the function in a separate thread with timeout
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            print(
                f"Warning: PowerPoint COM automation timed out after {timeout_seconds} seconds"
            )
            print(
                "This may leave PowerPoint processes running. Attempting to kill them..."
            )
            # Force kill any PowerPoint processes if needed
            # try:
            #     subprocess.run(
            #         ["taskkill", "/f", "/im", "POWERPNT.EXE"],
            #         capture_output=True,
            #         check=False,
            #     )
            #     print("Successfully killed PowerPoint processes")
            # except Exception as e:
            #     print(f"Could not kill PowerPoint processes: {e}")
            return result  # Return whatever we got before timeout

        if exception:
            raise exception

        return result

    def _generate_screenshots_powerpoint_com_core(
        self,
        pptx_path: str,
        output_dir: str,
        resolution: tuple|None = None,
    ) -> List[SlideScreenshot]:
        """Core implementation of Windows PowerPoint COM screenshot generation."""
        try:
            from win32com.client import Dispatch
            import pythoncom
        except ImportError:
            raise ImportError(
                "pywin32 package is required for Windows PowerPoint automation. Install with: pip install pywin32"
            )

        screenshots = []
        ppt_app = None
        presentation = None

        # Convert to absolute path to avoid COM issues
        pptx_path = os.path.abspath(pptx_path)

        if not os.path.exists(pptx_path):
            raise FileNotFoundError(f"PowerPoint file not found: {pptx_path}")

        try:
            # Initialize COM for this thread
            pythoncom.CoInitialize()

            # Initialize PowerPoint application
            print("Initializing PowerPoint application...")
            ppt_app = Dispatch("PowerPoint.Application")

            # Try to keep PowerPoint invisible, but handle cases where it's not allowed
            try:
                ppt_app.Visible = 0
                print("PowerPoint set to invisible mode")
            except Exception:
                print("Warning: Cannot hide PowerPoint, keeping it visible")
                ppt_app.Visible = 1

            # Disable alerts to prevent dialog boxes
            ppt_app.DisplayAlerts = 0

            # Open the presentation
            print(f"Opening presentation: {pptx_path}")
            presentation = ppt_app.Presentations.Open(
                pptx_path,
                ReadOnly=1,  # Open as read-only
                Untitled=0,  # Don't create untitled copy
                WithWindow=0,  # Don't show window
            )

            print(f"Found {presentation.Slides.Count} slides")

            # Get actual slide dimensions from presentation page setup
            page_setup = presentation.PageSetup
            slide_width = int(page_setup.SlideWidth)  # Width in points
            slide_height = int(page_setup.SlideHeight)  # Height in points

            print(f"Slide dimensions: {slide_width} x {slide_height} points")
            print("Resolution input:", resolution)
            print(f"Exporting slides to {output_dir}")
            # Export each slide as an image
            for i in range(
                1, presentation.Slides.Count + 1
            ):  # PowerPoint uses 1-based indexing
                slide = presentation.Slides(i)
                slide_number = i
                image_path = os.path.join(output_dir, f"slide-{slide_number:02d}.jpg")


                # Export slide as JPEG using actual slide dimensions
                if resolution is None:
                    slide.Export(image_path, "JPG", slide_width, slide_height)
                else:
                    slide.Export(image_path, "JPG", resolution[0], resolution[1])
                # Verify the image was created
                if not os.path.exists(image_path):
                    print(
                        f"Warning: Image file was not created for slide {slide_number}"
                    )
                    continue

                # Check file size to ensure it's not empty
                file_size = os.path.getsize(image_path)
                if file_size == 0:
                    print(f"Warning: Empty image file created for slide {slide_number}")
                    continue
                screenshot = SlideScreenshot(
                    slide_number=slide_number,
                    image_path=image_path,
                    slide_id=str(slide.SlideId),
                )
                screenshots.append(screenshot)

        except Exception as e:
            print(f"Error generating screenshots using PowerPoint COM: {e}")
            import traceback

            print(f"Detailed error: {traceback.format_exc()}")

        finally:
            # Clean up PowerPoint objects with aggressive timeout
            print("Starting aggressive cleanup...")

            # Use a separate thread for cleanup with its own timeout
            # def cleanup_powerpoint():
            #     try:
            #         if presentation is not None:
            #             print("Closing presentation...")
            #             presentation.Close()
            #             print("Presentation closed")
            #     except Exception as e:
            #         print(f"Error closing presentation: {e}")

            #     # try:
            #     #     pythoncom.CoUninitialize()
            #     #     print("COM uninitialized")
            #     # except Exception as e:
            #     #     print(f"Error uninitializing COM: {e}")

            # # Run cleanup in thread with 10 second timeout
            # cleanup_thread = threading.Thread(target=cleanup_powerpoint, daemon=True)
            # cleanup_thread.start()
            # cleanup_thread.join(timeout=10)
            # # Force garbage collection
            # import gc
            # gc.collect()

        return screenshots

    def _create_screenshots_from_paths(
        self, image_paths: List[str]
    ) -> List[SlideScreenshot]:
        """Create SlideScreenshot objects from a list of image paths."""
        screenshots = []

        for i, image_path in enumerate(image_paths):
            # Extract slide number from filename
            filename = os.path.basename(image_path)
            slide_number = i + 1  # Default to sequential numbering

            # Try to extract slide number from filename
            match = re.search(r"slide-(\d+)", filename)
            if match:
                slide_number = int(match.group(1))

            screenshot = SlideScreenshot(
                slide_number=slide_number,
                image_path=image_path,
                slide_id=f"slide{slide_number}",
            )
            screenshots.append(screenshot)

            # Verify file size
            file_size = os.path.getsize(image_path)
            print(f"Generated slide {slide_number}: {filename} ({file_size} bytes)")

        return screenshots
