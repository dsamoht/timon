import os
import re
from collections import defaultdict
from .config import Config

def input_validation(name):
    """Checks if the experiment ID contains illegal characters."""
    if not name:
        return False
    # Avoid characters that break shell commands or file paths
    for char in name:
        if char in [r"?", "\\", r"/", r".", r",", r":", r";", r" "]:
            return False
    return True

def convert_realpaths_to_wildcards(paths):
    """
    Convert a list of file paths into a single wildcard pattern.
    If only one file, return it directly.
    """
    if len(paths) == 1:
        return paths[0]

    dirs = [os.path.dirname(p) for p in paths]
    basenames = [os.path.basename(p) for p in paths]

    if len(set(dirs)) > 1:
        # fallback: cannot wildcard across directories, join with comma
        return ",".join(paths)

    dir_prefix = dirs[0]
    # Find common prefix
    common_prefix = os.path.commonprefix(basenames)
    # Find common suffix
    reversed_basenames = [b[::-1] for b in basenames]
    common_suffix_reversed = os.path.commonprefix(reversed_basenames)
    common_suffix = common_suffix_reversed[::-1]

    # Construct wildcard for variable middle part
    wildcard = common_prefix + "*" + common_suffix
    return os.path.join(dir_prefix, wildcard)

def detect_samples_files():
    """
    Recursively detect fastq files and group them by sample name.
    Returns a dictionary of {sample_name: path_string (or wildcard)}.
    """
    if not os.path.exists(Config.IMPORT_FOLDER):
        return {}

    fastq_pattern = re.compile(r'\.f(ast)?q(\.gz)?$', re.IGNORECASE)

    # Patterns for obvious technical split suffixes
    split_patterns = [
        re.compile(r'(_part\d+)$', re.IGNORECASE),
        re.compile(r'(_run\d+)$', re.IGNORECASE),
        re.compile(r'(_rep\d+)$', re.IGNORECASE),
        re.compile(r'(_bf[a-z0-9]+_[a-z0-9]+_\d+)$', re.IGNORECASE),  # Nanopore-like
        re.compile(r'(_[Rr]?[12])$'),  # Illumina _R1/_R2 etc.
        re.compile(r'(?<=\D)_(\d+)$'),  # trailing _1, _2 after non-digit prefix
    ]

    samples_map = defaultdict(list)

    for root, _, files in os.walk(Config.IMPORT_FOLDER):
        for f in files:
            if not fastq_pattern.search(f):
                continue
            
            basename = re.sub(fastq_pattern, '', f)
            cleaned = basename
            # Apply all split suffix cleanups to guess the sample name
            for pat in split_patterns:
                cleaned = pat.sub('', cleaned)
            # Remove any leftover trailing dots/underscores/hyphens
            cleaned = re.sub(r'[\.\-_]+$', '', cleaned)
            
            full_path = os.path.join(root, f)
            samples_map[cleaned].append(full_path)
    
    # Convert lists to wildcards or single paths
    final_files = {}
    for s, paths in samples_map.items():
        paths.sort()
        final_files[s] = convert_realpaths_to_wildcards(paths)
        
    return final_files
