"""
thumbnail_creator.py
Creates a visually rich YouTube thumbnail using PIL (Pillow) and extracts scenes from the processed video.
Falls back gracefully if Pillow or video file is not available.
"""
import os
import textwrap
import re

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def shape_bengali(text: str) -> str:
    """
    Decompose combined Bengali vowels (ো, ৌ) and reorder pre-vowels (ি, ে, ৈ)
    to the left of their consonant/conjunct clusters for standard Pillow FreeType rendering.
    """
    text = text.replace("\u09CB", "\u09C7\u09BE")  # ো -> ে + া
    text = text.replace("\u09CC", "\u09C7\u09D7")  # ৌ -> ে + ৗ
    
    chars = list(text)
    pre_vowels = {"\u09BF", "\u09C7", "\u09C8"} # ি, ে, ৈ
    
    i = 0
    while i < len(chars):
        if chars[i] in pre_vowels:
            val = chars.pop(i)
            j = i - 1
            while j > 0:
                if chars[j - 1] == "\u09CD":
                    j -= 2
                else:
                    break
            chars.insert(max(0, j), val)
        else:
            i += 1
    return "".join(chars)


def get_best_font_path(font_type="bangla"):
    """
    Find a valid font file path dynamically based on OS to prevent crashes.
    """
    import os
    if font_type == "bangla":
        candidates = [
            # macOS paths
            "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
            "/System/Library/Fonts/Supplemental/Bangla MN.ttc",
            "/System/Library/Fonts/KohinoorBangla.ttc",
            # Linux paths
            "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/opentype/malayalam/SolaimanLipi.ttf",
            "/usr/share/fonts/SolaimanLipi.ttf",
            # Windows paths
            "C:\\Windows\\Fonts\\vrinda.ttf",
            "C:\\Windows\\Fonts\\shonar.ttf"
        ]
    else: # english / default / helvetica
        candidates = [
            # macOS paths
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Verdana.ttf",
            # Linux paths
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            # Windows paths
            "C:\\Windows\\Fonts\\arial.ttf"
        ]
        
    for p in candidates:
        if os.path.exists(p):
            return p
            
    # Absolute fallbacks
    return candidates[0]


def resize_and_crop(im, target_size):
    """
    Resize image to cover target_size, then crop from center.
    Prevents any squishing or stretching of the frame.
    """
    tw, th = target_size
    w, h = im.size
    scale = max(tw / w, th / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    im_resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - tw) // 2
    top = (new_h - th) // 2
    return im_resized.crop((left, top, left + tw, top + th))


def _get_video_duration_ffmpeg(video_path: str) -> float:
    """Get video duration in seconds using ffmpeg output to stderr."""
    try:
        import subprocess
        import imageio_ffmpeg
        import re
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ffmpeg_exe, "-i", video_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 300.0


def _extract_frame_ffmpeg(video_path: str, time_sec: float) -> Image.Image | None:
    """Extract a PIL Image frame from a video at time_sec using ffmpeg."""
    try:
        import subprocess, tempfile
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        tmp_img = tempfile.mktemp(suffix=".jpg")
        cmd = [ffmpeg_exe, "-y", "-ss", str(time_sec), "-i", video_path, "-vframes", "1", tmp_img]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(tmp_img):
            im = Image.open(tmp_img).copy()
            try:
                os.remove(tmp_img)
            except Exception:
                pass
            return im
    except Exception as e:
        print(f"[thumbnail_creator] ffmpeg frame extraction error: {e}")
    return None


def draw_crying_emoji(draw, center_x, center_y, size):
    """
    Draw a custom vector-style crying emoji programmatically on the PIL Image.
    This guarantees it works offline and looks sharp.
    """
    r = size // 2
    cx, cy = center_x, center_y
    
    # 1. Base yellow face
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=(255, 230, 0), outline=(0, 0, 0), width=4)
    
    # 2. Crying eyes (curved arcs)
    eye_offset_x = int(r * 0.35)
    eye_offset_y = int(r * 0.15)
    eye_r = int(r * 0.15)
    
    draw.arc([(cx - eye_offset_x - eye_r, cy - eye_offset_y - eye_r), (cx - eye_offset_x + eye_r, cy - eye_offset_y + eye_r)], 180, 360, fill=(0, 0, 0), width=5)
    draw.arc([(cx + eye_offset_x - eye_r, cy - eye_offset_y - eye_r), (cx + eye_offset_x + eye_r, cy - eye_offset_y + eye_r)], 180, 360, fill=(0, 0, 0), width=5)
    
    # 3. Open sad mouth (gasping mouth)
    mouth_w = int(r * 0.5)
    mouth_h = int(r * 0.35)
    mouth_y = cy + int(r * 0.3)
    draw.ellipse([(cx - mouth_w//2, mouth_y - mouth_h//2), (cx + mouth_w//2, mouth_y + mouth_h//2)], fill=(0, 0, 0))
    
    # 4. Large blue tears flowing down from both eyes (crossing the face border)
    tear_color = (0, 162, 255)
    tear_w = int(r * 0.22)
    tear_len = int(r * 1.1)
    
    # Left tear line and drops
    tear_lx = cx - eye_offset_x
    tear_ly = cy - eye_offset_y
    # Draw black outline (slightly wider)
    draw.line([(tear_lx, tear_ly), (tear_lx, tear_ly + tear_len)], fill=(0, 0, 0), width=tear_w + 6)
    draw.ellipse([(tear_lx - (tear_w+6)//2, tear_ly + tear_len - (tear_w+6)//2), (tear_lx + (tear_w+6)//2, tear_ly + tear_len + (tear_w+6)//2)], fill=(0, 0, 0))
    # Draw main blue tear
    draw.line([(tear_lx, tear_ly), (tear_lx, tear_ly + tear_len)], fill=tear_color, width=tear_w)
    draw.ellipse([(tear_lx - tear_w//2, tear_ly + tear_len - tear_w//2), (tear_lx + tear_w//2, tear_ly + tear_len + tear_w//2)], fill=tear_color)
    
    # Right tear line and drops
    tear_rx = cx + eye_offset_x
    tear_ry = cy - eye_offset_y
    # Draw black outline (slightly wider)
    draw.line([(tear_rx, tear_ry), (tear_rx, tear_ry + tear_len)], fill=(0, 0, 0), width=tear_w + 6)
    draw.ellipse([(tear_rx - (tear_w+6)//2, tear_ry + tear_len - (tear_w+6)//2), (tear_rx + (tear_w+6)//2, tear_ry + tear_len + (tear_w+6)//2)], fill=(0, 0, 0))
    # Draw main blue tear
    draw.line([(tear_rx, tear_ry), (tear_rx, tear_ry + tear_len)], fill=tear_color, width=tear_w)
    draw.ellipse([(tear_rx - tear_w//2, tear_ry + tear_len - tear_w//2), (tear_rx + tear_w//2, tear_ry + tear_len + tear_w//2)], fill=tear_color)



def draw_broken_heart_emoji(draw, cx, cy, size):
    r = size // 2
    # Outlines
    o = 6
    draw.ellipse([(cx - r - o, cy - r//2 - r//4 - o), (cx - o, cy - r//2 + r//4 + o)], fill=(0,0,0))
    draw.ellipse([(cx - o, cy - r//2 - r//4 - o), (cx + r + o, cy - r//2 + r//4 + o)], fill=(0,0,0))
    draw.polygon([(cx - r - o, cy), (cx + r + o, cy), (cx, cy + r + o)], fill=(0,0,0))
    
    # Red heart lobes
    draw.ellipse([(cx - r, cy - r//2 - r//4), (cx, cy - r//2 + r//4)], fill=(230, 20, 20))
    draw.ellipse([(cx, cy - r//2 - r//4), (cx + r, cy - r//2 + r//4)], fill=(230, 20, 20))
    draw.polygon([(cx - r, cy), (cx + r, cy), (cx, cy + r)], fill=(230, 20, 20))
    
    # Crack in the middle
    crack_pts = [
        (cx, cy - r//2),
        (cx - r//6, cy - r//6),
        (cx + r//6, cy + r//12),
        (cx - r//10, cy + r//3),
        (cx, cy + r)
    ]
    draw.line(crack_pts, fill=(0, 0, 0), width=6)


def create_thumbnail(title: str, topic: str = "", output_path: str = "thumbnail.jpg", video_path: str = None, is_short: bool = False) -> str:
    """
    Generate a highly engaging, clickbait YouTube thumbnail matching Tawhidul official style:
    - 3-panel diagonal slice face collage with yellow divider lines
    - Cold cyan/dramatic color grade & high saturation
    - Neon green text with thick black outline + crying emoji 😭
    """
    if is_short:
        width, height = 2160, 2160
    else:
        width, height = 1280, 720

    if not PIL_AVAILABLE:
        _create_placeholder(output_path, width, height)
        return output_path

    img = None
    draw = None

    # ── 1. Create Background (Stitched 3-Frame Sliced Collage) ──────────
    if video_path and os.path.exists(video_path):
        try:
            # Estimate video duration dynamically
            duration = _get_video_duration_ffmpeg(video_path)
            
            # Extract frames at relative timestamps to ensure compatibility
            im1 = _extract_frame_ffmpeg(video_path, duration * 0.15)
            im2 = _extract_frame_ffmpeg(video_path, duration * 0.45)
            im3 = _extract_frame_ffmpeg(video_path, duration * 0.75)
            
            if im1 and im2 and im3:
                img = Image.new("RGB", (width, height))
                
                if is_short:
                    row_h = height // 3
                    im1_cropped = resize_and_crop(im1, (width, row_h))
                    im2_cropped = resize_and_crop(im2, (width, row_h))
                    im3_cropped = resize_and_crop(im3, (width, row_h))
                    
                    img.paste(im1_cropped, (0, 0))
                    img.paste(im2_cropped, (0, row_h))
                    img.paste(im3_cropped, (0, row_h * 2))
                    
                    draw = ImageDraw.Draw(img)
                    draw.line([(0, row_h), (width, row_h)], fill=(255, 220, 0), width=10)
                    draw.line([(0, row_h * 2), (width, row_h * 2)], fill=(255, 220, 0), width=10)
                else:
                    # Widescreen: 3 diagonal panels sliced using PIL masking
                    im1_full = resize_and_crop(im1, (width, height))
                    im2_full = resize_and_crop(im2, (width, height))
                    im3_full = resize_and_crop(im3, (width, height))
                    
                    # Define slanted line boundaries (X coordinates at top and bottom)
                    x1_top = int(width * 0.234) # ~300
                    x1_bot = int(width * 0.400) # ~512
                    x2_top = int(width * 0.766) # ~980
                    x2_bot = int(width * 0.600) # ~768
                    
                    # Panel 1: Left area
                    mask1 = Image.new("L", (width, height), 0)
                    d1 = ImageDraw.Draw(mask1)
                    d1.polygon([(0, 0), (x1_top, 0), (x1_bot, height), (0, height)], fill=255)
                    img.paste(im1_full, (0, 0), mask=mask1)
                    
                    # Panel 2: Middle area
                    mask2 = Image.new("L", (width, height), 0)
                    d2 = ImageDraw.Draw(mask2)
                    d2.polygon([(x1_top, 0), (x2_top, 0), (x2_bot, height), (x1_bot, height)], fill=255)
                    img.paste(im2_full, (0, 0), mask=mask2)
                    
                    # Panel 3: Right area
                    mask3 = Image.new("L", (width, height), 0)
                    d3 = ImageDraw.Draw(mask3)
                    d3.polygon([(x2_top, 0), (width, 0), (width, height), (x2_bot, height)], fill=255)
                    img.paste(im3_full, (0, 0), mask=mask3)
                    
                    # Apply dramatic cinematic color grade (High contrast, warm grading, vivid saturation)
                    sat_enhancer = ImageEnhance.Color(img)
                    img = sat_enhancer.enhance(1.6)
                    con_enhancer = ImageEnhance.Contrast(img)
                    img = con_enhancer.enhance(1.35)
                    
                    draw = ImageDraw.Draw(img)
                    
                    # Draw angled/slanted yellow divider lines exactly along the boundaries
                    divider_width = 12
                    draw.line([(x1_top, 0), (x1_bot, height)], fill=(255, 230, 0), width=divider_width)
                    draw.line([(x2_top, 0), (x2_bot, height)], fill=(255, 230, 0), width=divider_width)
            else:
                im_single = _extract_frame_ffmpeg(video_path, 10.0)
                if im_single:
                    img = resize_and_crop(im_single, (width, height))
                    sat_enhancer = ImageEnhance.Color(img)
                    img = sat_enhancer.enhance(1.4)
                    draw = ImageDraw.Draw(img)
                    
        except Exception as e:
            print(f"[Warning] Failed to extract multi-frame collage: {e}")
            img = None

    # Fallback gradient
    if img is None:
        img = Image.new("RGB", (width, height), color=(10, 20, 35))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            r = int(5 + (20 - 5) * y / height)
            g = int(25 + (60 - 25) * y / height)
            b = int(45 + (100 - 45) * y / height)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
    else:
        if draw is None:
            draw = ImageDraw.Draw(img)

    # ── 2. High Contrast Clickbait Bengali Title with Emoji at Bottom ─────────
    fp = get_best_font_path("bangla")
    try:
        title_font = ImageFont.truetype(fp, 90 if not is_short else 80)
    except Exception:
        title_font = ImageFont.load_default()
 
    # Clean and prepare title (keep alphanumeric and Bengali)
    display_title_str = re.sub(r'[^\w\s\u0980-\u09FF\-\|\,\.\!]', '', title.strip())
    if not display_title_str:
        display_title_str = title.strip()
 
    # Pre-shape Bengali text for correct rendering
    display_title_str = shape_bengali(display_title_str)
 
    has_bengali = bool(re.search(r'[\u0980-\u09FF]', display_title_str))
    wrap_width = 18 if has_bengali else 22
    wrapped_lines = textwrap.wrap(display_title_str, width=wrap_width)
    
    line_height = 100
    total_text_height = len(wrapped_lines) * line_height
    
    if is_short:
        y_text = height - 500 - total_text_height if height == 2160 else (height - 250 - total_text_height if height == 1080 else height - 450 - total_text_height)
    else:
        y_text = height - total_text_height - 35

    last_line_info = None
    for idx, line in enumerate(wrapped_lines[:2]):
        try:
            line_bbox = draw.textbbox((0, 0), line, font=title_font)
            line_w = line_bbox[2] - line_bbox[0]
        except Exception:
            line_w = len(line) * 42
            
        x_text = (width - line_w) // 2
        
        # Draw high-contrast rounded rectangle background banner box for 100% readability
        try:
            line_bbox_real = draw.textbbox((x_text, y_text), line, font=title_font)
            padding_x = 24
            padding_y = 12
            draw.rounded_rectangle(
                [line_bbox_real[0] - padding_x, line_bbox_real[1] - padding_y, line_bbox_real[2] + padding_x, line_bbox_real[3] + padding_y],
                radius=15,
                fill=(180, 0, 0, 220) if idx == 0 else (0, 0, 0, 220)
            )
        except Exception:
            pass
            
        # Draw beautiful high-contrast text overlay (Yellow for line 1, White for line 2)
        text_color = (255, 235, 0) if idx == 0 else (255, 255, 255)
        draw.text(
            (x_text, y_text),
            line,
            font=title_font,
            fill=text_color,
            stroke_width=8,
            stroke_fill=(0, 0, 0)
        )
        
        # Keep track of the last line position to draw the crying emoji
        last_line_info = (x_text, y_text, line_w, idx)
        y_text += line_height

    # ── 3. Draw Crying Emoji and Broken Heart Emoji for Clickbait Natok Style ────────
    if last_line_info:
        lx, ly, lw, line_idx = last_line_info
        emoji_size = 90 if not is_short else 80
        
        # 3a. Draw crying emoji on the right of the second line
        emoji_cx = lx + lw + emoji_size // 2 + 25
        emoji_cy = ly + emoji_size // 2
        if emoji_cx + emoji_size // 2 < width:
            try:
                draw_crying_emoji(draw, emoji_cx, emoji_cy, emoji_size)
            except Exception as e:
                print(f"[Warning] Failed to draw crying emoji: {e}")
                
        # 3b. Draw broken heart emoji on the left of the first line of text
        # If there are 2 lines, first line was drawn at ly - line_height
        y_first_line = ly - line_height if line_idx > 0 else ly
        heart_cx = lx - emoji_size // 2 - 25
        heart_cy = y_first_line + emoji_size // 2
        if heart_cx - emoji_size // 2 > 0:
            try:
                draw_broken_heart_emoji(draw, heart_cx, heart_cy, emoji_size)
            except Exception as e:
                print(f"[Warning] Failed to draw broken heart: {e}")

    img.save(output_path, "JPEG", quality=98)
    return output_path


def _create_placeholder(path: str, width: int, height: int):
    """Write a minimal valid JPEG placeholder (Pillow not available)."""
    tiny_jpeg = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD7, 0xFF, 0xD9,
    ])
    with open(path, 'wb') as f:
        f.write(tiny_jpeg)
