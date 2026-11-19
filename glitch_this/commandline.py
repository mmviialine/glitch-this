#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from time import time
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

from glitch_this import ImageGlitcher


def read_version() -> str:
    with open(version_filepath, 'r') as version_file:
        content = version_file.read()
    return content.strip()


def write_version(version: str):
    with open(version_filepath, 'w') as version_file:
        version_file.write(version + '\n')


def is_expired(filepath: str) -> bool:
    # Check if the file has been created 2 weeks prior
    file_creation = datetime.fromtimestamp(os.stat(filepath).st_mtime)
    now = datetime.now()
    return (now - file_creation).days > 14


def is_latest(version: str) -> bool:
    # Check pypi for the latest version number
    from urllib import request
    import json
    if os.path.isfile(version_filepath) and not is_expired(version_filepath):
        # If a version log already exists and it's not more than 14 days old
        latest_version = read_version()
    else:
        # Either version log does not exist or is outdated
        try:
            contents = request.urlopen(
                'https://pypi.org/pypi/glitch-this/json').read()
        except:
            # Connection issue
            # Silenty return True, update check failed
            return True
        data = json.loads(contents)
        latest_version = data['info']['version']
        write_version(latest_version)

    print(f'Current version: {version} | Latest version: {latest_version}')
    return version == latest_version


def get_help(glitch_min: float, glitch_max: float) -> Dict:
    help_text = dict()
    help_text['path'] = 'Relative or Absolute string path to source image'
    help_text['level'] = f'Number between {glitch_min} and {
        glitch_max}, inclusive, representing amount of glitchiness'
    help_text['color'] = 'Include if you want to add color offset'
    help_text['scan'] = 'Include if you want to add scan lines effect\nDefaults to False'
    help_text['vertical'] = 'Include if you want vertical cuts instead of horizontal ones\nDefaults to False'
    help_text['color_blocks'] = 'Include to apply a retro pixel-art glitch (pixelation + blocky band displacement)\nDefaults to False'
    help_text['seed'] = 'Set a random seed for generating similar images across runs'
    help_text['gif'] = 'Include if you want output to be a GIF'
    help_text['frames'] = 'Number of frames to include in output GIF, default - 23'
    help_text['step'] = 'Glitch every step\'th frame of output GIF, default - 1 (every frame)'
    help_text['increment'] = 'Increment glitch_amount by given value after glitching every frame of output GIF\nA negative value fades the glitch out and ends the GIF once it reaches no glitch'
    help_text['cycle'] = f'Include if glitch_amount should be cycled back to {
        glitch_min} or {glitch_max} if it over/underflows'
    help_text['duration'] = 'How long to display each frame (in centiseconds), default - 200'
    help_text['relative_duration'] = 'Multiply given value to input GIF\'s original duration and use that as duration'
    help_text['loop'] = 'How many times the glitched GIF should loop, default - 0 (infinite loop)'
    help_text['inputgif'] = 'Include if input image is GIF'
    help_text['force'] = 'Forcefully overwrite output file\nDefaults to False (a new name is used if it already exists)'
    help_text['out'] = 'Explcitly supply full/relative path to output file'
    help_text["output_frames"] = "Output individual frames of the glitched GIF as separate images"
    help_text['concat'] = ('Concatenate the given images/GIFs, in the given order, into one animation\n'
                           'Usage: glitch_this -cc first.gif second.png third.jpg [-o out.gif]')
    help_text['orange'] = 'Include to draw the white bold word "orange" at the center of every frame'

    return help_text


def format_number(value: float) -> str:
    # 5.0 -> '5', 2.5 -> '2.5'
    return f'{value:g}'


def build_change_description(args) -> str:
    # Describe the used effects in the output filename,
    # e.g. glitched_cat_level5_color_scan.png
    parts = [f'level{format_number(args.glitch_level)}']
    if args.color:
        parts.append('color')
    if args.scan_lines:
        parts.append('scan')
    if args.vertical:
        parts.append('vertical')
    if args.color_blocks:
        parts.append('pixel')
    if args.orange:
        parts.append('orange')
    if args.seed is not None:
        parts.append(f'seed{format_number(args.seed)}')
    if args.increment:
        parts.append(f'inc{format_number(args.increment)}')
    if args.cycle:
        parts.append('cycle')
    if args.gif or args.input_gif:
        parts.append('gif')
    if args.output_frames:
        parts.append(f'{args.frames}frames')
    return '_'.join(parts)


def frame_files_exist(out_path: str, filename: str, extension: str) -> bool:
    # Check whether any "<filename>_<digits>.<extension>" already exists
    directory = out_path or '.'
    if not os.path.isdir(directory):
        return False
    pattern = re.compile(
        rf'^{re.escape(filename)}_\d+\.{re.escape(extension)}$', re.IGNORECASE)
    return any(pattern.match(name) for name in os.listdir(directory))


def make_unique_filename(out_path: str, filename: str, extension: str,
                         output_frames: bool) -> str:
    # Append _2, _3, ... until the name does not clash with an existing file
    def exists(name: str) -> bool:
        if output_frames:
            return frame_files_exist(out_path, name, extension)
        return os.path.exists(os.path.join(out_path, f'{name}.{extension}'))

    if not exists(filename):
        return filename
    index = 2
    while exists(f'{filename}_{index}'):
        index += 1
    return f'{filename}_{index}'


def load_bold_font(size: int):
    # Look for a bold system font, fall back to Pillow's default font
    font_names = [
        'arialbd.ttf',
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'),
                     'Fonts', 'arialbd.ttf'),
        'DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        'LiberationSans-Bold.ttf',
    ]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def add_orange_text(image: Image.Image) -> Image.Image:
    # Draw the word "orange" in white bold letters at the center of the frame
    frame = image.copy()
    if frame.mode not in ('RGB', 'RGBA'):
        frame = frame.convert('RGBA')
    draw = ImageDraw.Draw(frame)

    max_width = int(frame.width * 0.9)
    size = max(12, int(min(frame.width, frame.height) * 0.18))
    font = load_bold_font(size)
    bbox = draw.textbbox((0, 0), 'orange', font=font)
    while bbox[2] - bbox[0] > max_width and size > 10:
        size -= 2
        font = load_bold_font(size)
        bbox = draw.textbbox((0, 0), 'orange', font=font)

    x = (frame.width - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (frame.height - (bbox[3] - bbox[1])) / 2 - bbox[1]
    fill = (255, 255, 255, 255) if frame.mode == 'RGBA' else (255, 255, 255)
    draw.text((x, y), 'orange', font=font, fill=fill)
    return frame


def fit_frame(frame: Image.Image, size: Tuple[int, int]) -> Image.Image:
    # Scale the frame to fit inside size, keeping its aspect ratio,
    # and center it on a black canvas (letterboxing)
    if frame.size == size:
        return frame
    target_width, target_height = size
    scale = min(target_width / frame.width, target_height / frame.height)
    new_size = (max(1, round(frame.width * scale)),
                max(1, round(frame.height * scale)))
    resized = frame.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, (0, 0, 0))
    canvas.paste(resized, ((target_width - new_size[0]) // 2,
                           (target_height - new_size[1]) // 2))
    return canvas


def collect_concat_frames(paths: List[str], fallback_duration: int) -> Tuple[List[Image.Image], List[int]]:
    # Load every input in the given order, flattening GIFs into their frames
    frames = []
    durations = []
    target_size = None
    for path in paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(f'No image found at given path: {path}')
        with Image.open(path) as img:
            if target_size is None:
                # Every following input is fitted to the first input's size
                target_size = img.size
            for index in range(getattr(img, 'n_frames', 1)):
                img.seek(index)
                frame = img.convert('RGB')
                if frame.size != target_size:
                    frame = fit_frame(frame, target_size)
                duration = img.info.get('duration') or fallback_duration
                frames.append(frame)
                durations.append(int(duration))
    return frames, durations


def save_concat_video(frames: List[Image.Image], durations: List[int], out_path: str):
    # Encode frames to a video using ffmpeg (constant frame rate, 25 fps)
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise Exception('Writing video files requires ffmpeg, which was not found\n'
                        'Install ffmpeg or use a .gif/.webp output instead')
    fps = 25
    width, height = frames[0].size
    command = [
        ffmpeg, '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24',
        '-s', f'{width}x{height}', '-r', str(fps), '-i', '-',
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', out_path
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for frame, duration in zip(frames, durations):
            # Hold each frame for its duration at the chosen frame rate
            repeats = max(1, round(duration / 1000 * fps))
            data = frame.tobytes()
            for _ in range(repeats):
                process.stdin.write(data)
    finally:
        process.stdin.close()
        exit_code = process.wait()
    if exit_code != 0:
        raise Exception(f'ffmpeg could not write "{out_path}"')


def save_concat_animation(frames: List[Image.Image], durations: List[int],
                          out_path: str, loop: int):
    extension = os.path.splitext(out_path)[1].lower()
    if extension == '.webp':
        frames[0].save(out_path, format='WEBP', save_all=True,
                       append_images=frames[1:], duration=durations,
                       loop=loop, quality=90, method=4)
    else:
        frames[0].save(out_path, format='GIF', save_all=True,
                       append_images=frames[1:], duration=durations,
                       loop=loop, optimize=False)


def concat_inputs(args):
    # Join the given images/GIFs, in the given order, into one animation
    out_path = args.outfile or 'combined.gif'
    out_dir, out_file = os.path.split(out_path)
    if out_dir != '' and not os.path.isdir(out_dir):
        raise Exception(f'Given outfile path, {out_dir}, does not exist')

    out_base, out_ext = os.path.splitext(out_file)
    if not out_ext:
        out_ext = '.gif'

    video_extensions = ('.mp4', '.mov', '.avi')
    if out_ext.lower() in video_extensions and not shutil.which('ffmpeg'):
        raise Exception('Writing video files requires ffmpeg, which was not found\n'
                        'Install ffmpeg or use a .gif/.webp output instead')

    if not args.force:
        out_base = make_unique_filename(
            out_dir, out_base, out_ext.lstrip('.'), False)
    full_path = os.path.join(out_dir, f'{out_base}{out_ext}')

    # Still images are shown for -d centiseconds, GIF frames keep their timing
    frames, durations = collect_concat_frames(
        args.concat, args.duration * 10)
    if args.orange:
        frames = [add_orange_text(frame) for frame in frames]
    if out_ext.lower() in video_extensions:
        save_concat_video(frames, durations, full_path)
    else:
        save_concat_animation(frames, durations, full_path, args.loop)

    print(f'Combined {len(args.concat)} input(s) into "{full_path}"')
    print(f'Frames = {len(frames)}, Size = {frames[0].width}x{frames[0].height}')


def orange_only(args):
    # No glitch level was given, so just draw the orange text on the input
    frames, durations = collect_concat_frames(
        [args.src_img_path], args.duration * 10)
    frames = [add_orange_text(frame) for frame in frames]
    animated = len(frames) > 1 or args.gif

    if args.outfile:
        out_dir, out_file = os.path.split(args.outfile)
        out_base, out_ext = os.path.splitext(out_file)
        if not out_ext:
            out_ext = '.gif' if animated else '.png'
    else:
        out_dir, src_file = os.path.split(args.src_img_path)
        out_base, out_ext = os.path.splitext(src_file)
        out_base = f'orange_{out_base}'
        out_ext = '.gif' if animated else out_ext

    if out_dir != '' and not os.path.isdir(out_dir):
        raise Exception(f'Given outfile path, {out_dir}, does not exist')

    if not args.force:
        out_base = make_unique_filename(
            out_dir, out_base, out_ext.lstrip('.'), False)
    full_path = os.path.join(out_dir, f'{out_base}{out_ext}')

    video_extensions = ('.mp4', '.mov', '.avi')
    if out_ext.lower() in video_extensions:
        save_concat_video(frames, durations, full_path)
    elif animated:
        save_concat_animation(frames, durations, full_path, args.loop)
    else:
        frames[0].save(full_path)

    print(f'Added "orange" text, saved in "{full_path}"')
    print(f'Frames = {len(frames)}, Size = {frames[0].width}x{frames[0].height}')


def main():
    glitch_min, glitch_max = 0.1, 10.0
    current_version = ImageGlitcher.__version__
    help_text = get_help(glitch_min, glitch_max)
    # Add commandline arguments parser
    argparser = argparse.ArgumentParser(description='glitch_this: Glitchify images and GIFs, with highly customizable options!\n\n'
                                        '* Website: https://github.com/TotallyNotChase/glitch-this \n'
                                        f'* Version: {current_version}\n'
                                        '* Changelog: https://github.com/TotallyNotChase/glitch-this/blob/master/CHANGELOG.md',
                                        formatter_class=argparse.RawTextHelpFormatter)
    argparser.add_argument('--version', action='version',
                           version=f'glitch_this {current_version}')
    argparser.add_argument('src_img_path', metavar='Image_Path', type=str, nargs='?',
                           help=help_text['path'])
    argparser.add_argument('glitch_level', metavar='Glitch_Level', type=str, nargs='?',
                           help=help_text['level'])
    argparser.add_argument('keyword', metavar='Keyword', type=str, nargs='?',
                           help='Optional keyword, pass "orange" to draw the text')
    argparser.add_argument('-cc', '--concat', dest='concat', nargs='+', metavar='Path',
                           help=help_text['concat'])
    argparser.add_argument('-c', '--color', dest='color', action='store_true',
                           help=help_text['color'])
    argparser.add_argument('-s', '--scan', dest='scan_lines', action='store_true',
                           help=help_text['scan'])
    argparser.add_argument('-l', '--vertical', dest='vertical', action='store_true',
                           help=help_text['vertical'])
    argparser.add_argument('-z', '--color-blocks', dest='color_blocks', action='store_true',
                           help=help_text['color_blocks'])
    argparser.add_argument('-orange', '--orange', dest='orange', action='store_true',
                           help=help_text['orange'])
    argparser.add_argument('-g', '--gif', dest='gif', action='store_true',
                           help=help_text['gif'])
    argparser.add_argument('-ig', '--inputgif', dest='input_gif', action='store_true',
                           help=help_text['inputgif'])
    argparser.add_argument('-f', '--force', dest='force', action='store_true',
                           help=help_text['force'])
    argparser.add_argument('-sd', '--seed', dest='seed', metavar='Seed', type=float, default=None,
                           help=help_text['seed'])
    argparser.add_argument('-fr', '--frames', dest='frames', metavar='Frames', type=int, default=23,
                           help=help_text['frames'])
    argparser.add_argument('-st', '--step', dest='step', metavar='Step', type=int, default=1,
                           help=help_text['step'])
    argparser.add_argument('-i', '-in', '--increment', dest='increment', metavar='Increment', type=float, default=0.0,
                           help=help_text['increment'])
    argparser.add_argument('-cy', '--cycle', dest='cycle', action='store_true',
                           help=help_text['cycle'])
    argparser.add_argument('-d', '--duration', dest='duration', metavar='Duration', type=int, default=200,
                           help=help_text['duration'])
    argparser.add_argument('-rd', '--relative_duration', dest='rel_duration', metavar='Relative_Duration', type=float,
                           help=help_text['relative_duration'])
    argparser.add_argument('-lp', '--loop', dest='loop', metavar='Loop_Count', type=int, default=0,
                           help=help_text['loop'])
    argparser.add_argument('-o', '--outfile', dest='outfile', metavar='Outfile_path', type=str,
                           help=help_text['out'])
    argparser.add_argument("-of", "--output-frames", dest="output_frames",
                           action="store_true", help=help_text["output_frames"])
    args = argparser.parse_args()

    # Sanity check inputs
    if not args.duration > 0:
        raise ValueError('Duration must be greater than 0')
    if not args.loop >= 0:
        raise ValueError('Loop must be greater than or equal to 0')
    if not args.frames > 0:
        raise ValueError('Frames must be greater than 0')

    if args.concat:
        # Concatenation mode only joins the given files, no glitching is done
        concat_inputs(args)
        return

    if args.glitch_level is not None:
        try:
            args.glitch_level = float(args.glitch_level)
        except ValueError:
            # A keyword can be given in place of the glitch level,
            # e.g. "image.png orange"
            if args.keyword is None:
                args.keyword, args.glitch_level = args.glitch_level, None
            else:
                # e.g. "image.png orange 5"
                try:
                    args.glitch_level, args.keyword = float(args.keyword), args.glitch_level
                except ValueError:
                    argparser.error(f'Unknown keyword: {args.glitch_level}')

    if args.keyword:
        if args.keyword.lower() == 'orange':
            args.orange = True
        else:
            argparser.error(f'Unknown keyword: {args.keyword}')

    if args.src_img_path is None:
        argparser.error('Image_Path is required unless -cc/--concat is used')

    if not os.path.isfile(args.src_img_path):
        raise FileNotFoundError('No image found at given path')

    if args.orange and args.glitch_level is None:
        # The glitch level is optional here, only the text is added
        orange_only(args)
        return

    if args.glitch_level is None:
        argparser.error('Glitch_Level is required unless -cc/--concat is used, '
                        'or orange is given')

    if args.output_frames and not args.gif:
        raise ValueError("Cannot output frames without GIF output enabled")

    # Set up full_path, for output saving location
    out_path, out_file = os.path.split(Path(args.src_img_path))
    out_filename, out_fileex = out_file.rsplit('.', 1)
    # Output file extension should be '.gif' if output file is going to be a gif
    if args.gif:
        out_fileex = "gif"
    elif args.output_frames:
        out_fileex = "png"
    else:
        out_fileex = out_fileex

    if args.outfile:
        # If output file path is already given
        # Overwrite the previous values
        out_path, out_file = os.path.split(Path(args.outfile))
        if out_path != "" and not os.path.exists(out_path):
            raise Exception("Given outfile path, " +
                            out_path + ", does not exist")
        # The extension in user provided outfile path is ignored
        out_filename = out_file.rsplit(".", 1)[0]
    else:
        # Include the used effects in the name so different runs
        # are easy to tell apart, e.g. glitched_cat_level5_color_scan
        out_filename = f'glitched_{out_filename}_{build_change_description(args)}'

    # Never overwrite existing output unless asked to, keep both files instead
    if not args.force:
        unique_filename = make_unique_filename(
            out_path, out_filename, out_fileex, args.output_frames)
        if unique_filename != out_filename:
            print(f'"{out_filename}.{out_fileex}" already exists, '
                  f'saving as "{unique_filename}.{out_fileex}" instead')
            out_filename = unique_filename

    # Now create the full path
    full_path = os.path.join(out_path, f"{out_filename}.{out_fileex}")

    # Actual work begins here
    glitcher = ImageGlitcher()
    global version_filepath
    version_filepath = os.path.join(glitcher.lib_path, 'version.info')
    t0 = time()
    if not args.input_gif:
        # Get glitched image or GIF (from image)
        glitch_img = glitcher.glitch_image(args.src_img_path, args.glitch_level,
                                           glitch_change=args.increment,
                                           cycle=args.cycle,
                                           scan_lines=args.scan_lines,
                                           color_offset=args.color,
                                           seed=args.seed,
                                           gif=args.gif,
                                           frames=args.frames,
                                           step=args.step,
                                                                    vertical=args.vertical,
                                                                    color_blocks=args.color_blocks)
    else:
        # Get glitched image or GIF (from GIF)
        glitch_img, src_duration, args.frames = glitcher.glitch_gif(args.src_img_path, args.glitch_level,
                                                                    glitch_change=args.increment,
                                                                    cycle=args.cycle,
                                                                    scan_lines=args.scan_lines,
                                                                    color_offset=args.color,
                                                                    seed=args.seed,
                                                                    step=args.step,
                                           vertical=args.vertical,
                                           color_blocks=args.color_blocks)
        # Set args.gif to true if it isn't already in this case
        args.gif = True
        # Set args.duration to src_duration * relative duration, if one was given
        args.duration = args.duration if not args.rel_duration else int(
            args.rel_duration * src_duration)
    t1 = time()
    # End of glitching
    if args.orange:
        # Draw the word "orange" at the center of every output frame
        if isinstance(glitch_img, list):
            glitch_img = [add_orange_text(frame) for frame in glitch_img]
        else:
            glitch_img = add_orange_text(glitch_img)
    t2 = time()
    # Save the image
    if not args.gif:
        glitch_img.save(full_path, compress_level=3)
        t3 = time()
        print('Glitched Image saved in "{}"'.format(full_path))
    elif not args.output_frames:
        glitch_img[0].save(
            full_path,
            format="GIF",
            append_images=glitch_img[1:],
            save_all=True,
            duration=args.duration,
            loop=args.loop,
            compress_level=3,
        )
        t3 = time()
        print(
            f'Glitched GIF saved in "{full_path}"\nFrames = {
                len(glitch_img)}, Duration = {args.duration}, Loop = {args.loop}'
        )
    else:
        for i, frame in enumerate(glitch_img):
            frame_path = os.path.join(
                out_path, (f"{out_filename}_{i}.{out_fileex}"))
            frame.save(frame_path, compress_level=3)
        t3 = time()
        print(f'Glitched frames saved in "{out_filename}_*.png"')
    print(f"Time taken to glitch: {t1 - t0}")
    print(f"Time taken to save: {t3 - t2}")
    print(f"Total Time taken: {t3 - t0}")

    # Let the user know if new version is available
    if not is_latest(current_version):
        print('A new version of "glitch-this" is available. Please consider upgrading via `pip3 install --upgrade glitch-this`')


if __name__ == '__main__':
    main()
