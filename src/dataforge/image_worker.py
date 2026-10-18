"""Private disposable raster worker. Input is constructed internally, never uploaded SVG."""
import sys


def main():
    import resvg_py

    from dataforge.graph_images import MAX_SVG_BYTES

    svg = sys.stdin.buffer.read(MAX_SVG_BYTES + 1)
    if len(svg) > MAX_SVG_BYTES:
        raise ValueError('SVG exceeds input budget')
    sys.stdout.buffer.write(resvg_py.svg_to_bytes(svg_string=svg.decode('utf-8')))


if __name__ == '__main__':
    main()
