#!/usr/bin/env python3

import argparse
import os
from datetime import datetime


def make_output_path( input_path: str ) -> str:
    in_dir = os.path.dirname( input_path )
    base = os.path.basename( input_path )
    name, _ext = os.path.splitext( base )

    timestamp = datetime.now().strftime( "%Y%m%d_%H%M%S" )

    out_name = f"{name}_e_{timestamp}.txt"
    return os.path.join( in_dir, out_name )


def process_file( input_path: str ) -> str:
    output_path = make_output_path( input_path )

    removed = 0
    kept_lines = []

    with open( input_path, "r", encoding="utf-8", errors="replace", newline="" ) as f:
        for line in f:
            if line.lstrip().startswith( "// val unk:" ):
                removed += 1
                continue
            if line.lstrip().startswith( "// child unk:" ):
                removed += 1
                continue

            kept_lines.append( line )

    with open( output_path, "w", encoding="utf-8", newline="" ) as f:
        f.writelines( kept_lines )

    print( f"Input   : {input_path}" )
    print( f"Output  : {output_path}" )
    print( f"Removed : {removed} lines" )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove lines whose trimmed version starts with '// val unk:' and write a timestamped copy."
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="/mnt/data/viewkick_patterns.txt",
        help="Path to the input file (default: /mnt/data/viewkick_patterns.txt)"
    )

    args = parser.parse_args()

    input_path = os.path.abspath( args.file )

    if not os.path.isfile( input_path ):
        raise FileNotFoundError( f"Input file not found: {input_path}" )

    process_file( input_path )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
